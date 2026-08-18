# Helper Removal — `hikari/messages.py`

Removal recipe for the 9 helper methods on `PartialMessage` (inherited by `Message`) that reference
`self.app` (9 `rest.*` call-site lines + 1 `cache.*` call-site line, dossier 04 §0). Seven are pure
delegations, two are cache-backed mention getters, and `respond`/`remove_reaction`/
`remove_all_reactions` carry small compose/branch logic.

See [`00-README.md`](00-README.md) for the shared legend and
[`../03-new-rest-methods-and-free-functions.md`](../03-new-rest-methods-and-free-functions.md) for the
mention-getter and `respond` targets.

## 1. Objective

Delete `PartialMessage`'s `app`-delegating helpers and give callers the exact replacement, preserving
`respond`'s `reply` coercion and the mention getters' cache-degradation semantics. Serves constraint
(a) / D9.

## 2. Current state (dossier 04 §3.8, source-anchored)

`PartialMessage` (`messages.py:408`) declares the `app` field; `Message` (`messages.py:599`) inherits
it. All 9 helpers hang off `PartialMessage`.

| Line | Method | async | Delegates to | Extra logic |
|---:|---|:--:|---|---|
| 816 | `get_member_mentions` | no | `cache.get_member(guild_id, user_id)` via `_map_cache_maybe_discover` | `guard` + UNDEFINED handling + closure over `app`,`guild_id` |
| 850 | `get_role_mentions` | no | `cache.get_role(...)` via `_map_cache_maybe_discover` | `guard` + UNDEFINED handling |
| 901 | `fetch_channel` | yes | `rest.fetch_channel(self.channel_id)` | pure |
| 928 | `edit` | yes | `rest.edit_message(message=self.id, channel=self.channel_id, …)` | pure |
| 1102 | `respond` | yes | `rest.create_message(channel=self.channel_id, …)` | `compose` (reply coercion) |
| 1298 | `delete` | yes | `rest.delete_message(self.channel_id, self.id)` | pure |
| 1317 | `add_reaction` | yes | `rest.add_reaction(channel=self.channel_id, message=self.id, …)` | pure |
| 1390 | `remove_reaction` | yes | `rest.delete_my_reaction(...)` **or** `rest.delete_reaction(..., user=)` | branch on `user` UNDEFINED |
| 1472 | `remove_all_reactions` | yes | `rest.delete_all_reactions(...)` **or** `rest.delete_all_reactions_for_emoji(...)` | branch on `emoji` UNDEFINED |

## 3. Target design — replacements

### 3.1 Pure → direct `rest.*` (Strategy 1)

| Removed helper | Caller now writes |
|---|---|
| `message.fetch_channel()` | `await rest.fetch_channel(message.channel_id)` |
| `message.edit(...)` | `await rest.edit_message(message.channel_id, message.id, ...)` |
| `message.delete()` | `await rest.delete_message(message.channel_id, message.id)` |
| `message.add_reaction(emoji, emoji_id=...)` | `await rest.add_reaction(message.channel_id, message.id, emoji, emoji_id=...)` |

### 3.2 `respond` — compose (`reply` coercion)

`PartialMessage.respond` (`messages.py:1102`) forwards to `rest.create_message` but coerces the
`reply` argument: `reply is True` → reply to `self`; `reply is False` → `undefined.UNDEFINED`; any
other value passes through (dossier 04 §3.8, §7.2). Because the coercion is tiny and the only piece of
`self` it needs is `self` itself (as the reply target) plus `self.channel_id`, the caller can inline
it, or use the thin wrapper documented in
[`../03-new-rest-methods-and-free-functions.md`](../03-new-rest-methods-and-free-functions.md) §7:

```python
# before: await message.respond("hi", reply=True)
# after (inline coercion):
await rest.create_message(message.channel_id, "hi", reply=message)
# before: await message.respond("hi", reply=False) / reply=UNDEFINED
# after:
await rest.create_message(message.channel_id, "hi")  # no reply
```

The `reply=True/False` boolean sugar is the only behavior lost; document it in the breaking-changes
catalog so users know `reply=True` becomes `reply=message`.

### 3.3 `remove_reaction` / `remove_all_reactions` — two-call branch

Both issue one of two rest calls depending on whether an argument is `UNDEFINED` (dossier 04 §3.8):

- `remove_reaction` (`messages.py:1390`): `rest.delete_my_reaction(...)` when `user` is UNDEFINED,
  else `rest.delete_reaction(..., user=user)`.
- `remove_all_reactions` (`messages.py:1472`): `rest.delete_all_reactions(...)` when `emoji` is
  UNDEFINED, else `rest.delete_all_reactions_for_emoji(...)`.

These are thin dispatchers, not new capability. Callers pick the correct rest method directly, or use
the reaction-dispatcher wrapper in
[`../03-new-rest-methods-and-free-functions.md`](../03-new-rest-methods-and-free-functions.md) §7:

```python
# before: await message.remove_reaction(emoji)               # my reaction
# after:  await rest.delete_my_reaction(message.channel_id, message.id, emoji)
# before: await message.remove_reaction(emoji, user=someone)  # someone else's
# after:  await rest.delete_reaction(message.channel_id, message.id, someone, emoji)
```

### 3.4 Mention getters — cache + `_map_cache_maybe_discover` closure (Strategy 3, no-1:1)

`get_member_mentions` (`messages.py:816`) and `get_role_mentions` (`messages.py:850`) map the message's
mention ids through the cache. Verified body of `get_member_mentions` (`messages.py:838-848`):

```python
if self.user_mentions is undefined.UNDEFINED:
    return undefined.UNDEFINED
if isinstance(self.app, traits.CacheAware) and self.guild_id is not None:
    app = self.app
    guild_id = self.guild_id
    return _map_cache_maybe_discover(
        self.user_mentions, lambda user_id: app.cache.get_member(guild_id, user_id)
    )
return {}
```

Three behaviors must be preserved by any replacement:
1. **Tri-state UNDEFINED passthrough** — returns `UNDEFINED` when `user_mentions`/`role_mentions` is
   UNDEFINED (partial-update payload omitted the key).
2. **Cache degradation** — returns `{}` when there is no cache or no `guild_id`.
3. **The closure captures `app`+`guild_id`.** Under app removal the closure must thread `cache` and
   `guild_id` explicitly, not `self.app` (dossier 04 §8.8).

Target: free functions taking `cache` (see
[`../03-new-rest-methods-and-free-functions.md`](../03-new-rest-methods-and-free-functions.md) §8.3):

```python
def get_member_mentions(cache, message):
    if message.user_mentions is undefined.UNDEFINED:
        return undefined.UNDEFINED
    if cache is not None and message.guild_id is not None:
        return _map_cache_maybe_discover(
            message.user_mentions,
            lambda uid: cache.get_member(message.guild_id, uid),
        )
    return {}
```

`_map_cache_maybe_discover` itself is a module-level helper and stays; only its closure's capture
changes from `app`→`cache`.

## 4. Step-by-step migration

1. Delete the `app` field from `PartialMessage` (`messages.py:408`) per
   [`../01-app-field-removal.md`](../01-app-field-removal.md).
2. Delete the 4 pure helpers (§3.1); rewrite docstrings/examples to `rest.*`.
3. Replace `respond`'s call sites with inline reply coercion or the thin wrapper (§3.2); catalog the
   `reply=True/False` sugar loss.
4. Replace `remove_reaction`/`remove_all_reactions` call sites with the correct rest method (§3.3).
5. Re-home the two mention getters as `cache`-taking free functions preserving UNDEFINED/`{}`
   semantics (§3.4); update `_map_cache_maybe_discover`'s closure capture.
6. Add removed public methods to `../../11-rollout/03-breaking-changes-and-changelog.md`.

## 5. Affected files & symbols

| Path | Anchor | Change |
|---|---|---|
| `hikari/messages.py` | 408 | remove `app` field (`PartialMessage`) |
| `hikari/messages.py` | 816, 850 | re-home mention getters to `cache` free functions |
| `hikari/messages.py` | 901, 928, 1298, 1317 | remove pure helpers |
| `hikari/messages.py` | 1102 | remove `respond` (inline reply coercion / wrapper) |
| `hikari/messages.py` | 1390, 1472 | remove two-call reaction dispatchers |
| `hikari/messages.py` | `_map_cache_maybe_discover` | change closure capture `app`→`cache` |
| `hikari/impl/entity_factory.py` | message deserialize | drop `app=self._app` (`../01-app-field-removal.md`) |

## 6. Risks / gotchas

- **`respond(reply=True)` is a widely-used ergonomic.** Its loss (replaced by `reply=message`) is a
  visible break — flag prominently in the changelog.
- **UNDEFINED semantics on decoded `PartialMessage`.** `user_mentions`/`role_mentions` are role-(ii)
  UNDEFINED fields (partial payload omitted vs. `None`); the mention getters depend on the tri-state
  and it must round-trip through the msgspec field default (see
  `../../01-foundations/03-undefined-and-unset.md`).
- **Closure capture** — the mention getters currently close over `self.app`; the free-function
  rewrite must close over `cache` (dossier 04 §8.8), or unknown-mention ids silently vanish.
- Cache getters must return `{}` (not raise) when there is no cache.

## 7. Verification

1. `grep -n "self\.app" hikari/messages.py` → 0 after the pass.
2. Unit test the mention free functions: (a) UNDEFINED in → UNDEFINED out; (b) no cache → `{}`;
   (c) with cache → maps known ids, drops uncached ids.
3. Test that `rest.create_message(channel_id, ..., reply=message)` reproduces `respond(reply=True)`
   behavior (message reference set).
4. Test both branches of the reaction dispatchers resolve to the correct rest method.

## 8. Open questions

- Keep a thin `respond`-style wrapper (app-free) vs. inline coercion at call sites —
  `../03-new-rest-methods-and-free-functions.md` §7 and `../../00-overview/05-decisions-log.md`.
- Where the mention free functions live (module-level in `messages.py` vs. a `cache` helper module) —
  `../03-new-rest-methods-and-free-functions.md` §8.3.
