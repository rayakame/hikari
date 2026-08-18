# Helper Removal — `hikari/channels.py`

Removal recipe for the 18 helper methods in `hikari/channels.py` that delegate to `self.app`
(16 `rest.*` call-site lines + 2 `cache.*` call-site lines, dossier 04 §0). All are removed under
constraint (a); callers switch to `rest.*` / `cache.*` directly, except `edit_overwrite` (compose)
which re-homes to a free function.

See [`00-README.md`](00-README.md) for the shared legend and strategy definitions,
[`../00-strategy.md`](../00-strategy.md) for the philosophy, and
[`../03-new-rest-methods-and-free-functions.md`](../03-new-rest-methods-and-free-functions.md) for the
compose case.

## 1. Objective

Delete `channels.py`'s `app`-delegating sugar and give callers the exact `rest.*`/`cache.*` call to
use in each case. Serves constraint (a) / D9.

## 2. Current state (dossier 04 §3.4, source-anchored)

Classes carrying these helpers: `ChannelFollow` (`channels.py:203`), `PartialChannel`
(`channels.py:361`) and its subclasses `TextableChannel`, `GuildChannel`,
`PermissibleGuildChannel`. The `app` field is inherited from `PartialChannel`
(`channels.py:361`); `ChannelFollow` carries its own `app` (`channels.py:203`).

| Line | Class | Method | async | Delegates to | Extra logic |
|---:|---|---|:--:|---|---|
| 214 | `ChannelFollow` | `fetch_channel` | yes | `rest.fetch_channel(self.channel_id)` | `assert` |
| 243 | `ChannelFollow` | `fetch_webhook` | yes | `rest.fetch_webhook(self.webhook_id)` | `assert` |
| 270 | `ChannelFollow` | `get_channel` | no | `cache.get_guild_channel(self.channel_id)` | `guard` + `assert` |
| 395 | `PartialChannel` | `delete` | yes | `rest.delete_channel(self.id)` | pure |
| 431 | `TextableChannel` | `fetch_history` | no | `rest.fetch_messages(self.id, …)` | pure (returns `LazyIterator`) |
| 485 | `TextableChannel` | `fetch_message` | yes | `rest.fetch_message(self.id, message)` | pure |
| 516 | `TextableChannel` | `send` (huge sig) | yes | `rest.create_message(channel=self.id, …)` | pure (id substitution) |
| 703 | `TextableChannel` | `trigger_typing` | no | `rest.trigger_typing(self.id)` | pure |
| 729 | `TextableChannel` | `fetch_pins` | no | `rest.fetch_pins(self.id)` | pure |
| 754 | `TextableChannel` | `pin_message` | yes | `rest.pin_message(self.id, message)` | pure |
| 780 | `TextableChannel` | `unpin_message` | yes | `rest.unpin_message(self.id, message)` | pure |
| 806 | `TextableChannel` | `delete_messages` | yes | `rest.delete_messages(self.id, messages, *other)` | pure |
| 989 | `GuildChannel` | `shard_id` (property) | no | `snowflakes.calculate_shard_id(self.app, self.guild_id)` | `guard` (ShardAware); **passes `self.app` object** |
| 999 | `GuildChannel` | `get_guild` | no | `cache.get_guild(self.guild_id)` | `guard` |
| 1012 | `GuildChannel` | `fetch_guild` | yes | `rest.fetch_guild(self.guild_id)` | pure |
| 1036 | `GuildChannel` | `edit` (huge sig) | yes | `rest.edit_channel(self.id, …)` | pure |
| 1203 | `PermissibleGuildChannel` | `edit_overwrite` | yes | `rest.edit_permission_overwrite(self.id, …)` ×2 branches | `compose`/`arg-default` |
| 1263 | `PermissibleGuildChannel` | `remove_overwrite` | yes | `rest.delete_permission_overwrite(self.id, target)` | pure |

`fetch_dm_channel`-style DM helpers do not live here; `send` on a channel is a straight
`create_message` (dossier 04 §3.4). The 2 `cache.*` sites are `ChannelFollow.get_channel`
(`channels.py:270`) and `GuildChannel.get_guild` (`channels.py:999`).

## 3. Target design — replacements

### 3.1 Pure / assert / arg-default → direct `rest.*` (Strategy 1)

Delete the method; the caller reproduces it from public struct data. Every `self.<id>` the helper
injected (`self.id`, `self.channel_id`, `self.webhook_id`, `self.guild_id`) survives as a plain field.

| Removed helper | Caller now writes |
|---|---|
| `channel.delete()` | `await rest.delete_channel(channel.id)` |
| `channel.fetch_history(...)` | `rest.fetch_messages(channel.id, ...)` |
| `channel.fetch_message(m)` | `await rest.fetch_message(channel.id, m)` |
| `channel.send(...)` | `await rest.create_message(channel.id, ...)` |
| `channel.trigger_typing()` | `rest.trigger_typing(channel.id)` |
| `channel.fetch_pins()` | `rest.fetch_pins(channel.id)` |
| `channel.pin_message(m)` | `await rest.pin_message(channel.id, m)` |
| `channel.unpin_message(m)` | `await rest.unpin_message(channel.id, m)` |
| `channel.delete_messages(ms, *more)` | `await rest.delete_messages(channel.id, ms, *more)` |
| `channel.fetch_guild()` | `await rest.fetch_guild(channel.guild_id)` |
| `channel.edit(...)` | `await rest.edit_channel(channel.id, ...)` |
| `channel.remove_overwrite(t)` | `await rest.delete_permission_overwrite(channel.id, t)` |
| `follow.fetch_channel()` | `await rest.fetch_channel(follow.channel_id)` |
| `follow.fetch_webhook()` | `await rest.fetch_webhook(follow.webhook_id)` |

### 3.2 The `assert isinstance(...)` narrowing loss

`ChannelFollow.fetch_channel` (`channels.py:214`) and `.fetch_webhook` (`channels.py:243`) do
`assert isinstance(result, ...)` before returning, giving the caller a narrower static type than
`rest.fetch_channel`/`rest.fetch_webhook` (which return the union of all channel/webhook subtypes).
Dropping the helper drops the narrowing. Options (decide once, apply cluster-wide — see
[`00-README.md`](00-README.md) §9):
- push `typing.cast("GuildChannel", await rest.fetch_channel(...))` onto callers (zero runtime cost);
- or keep a thin, app-free typed convenience wrapper at module or `rest` level.

Recommendation: push `typing.cast` onto callers; the `assert` was a caller convenience, and `rest`
already returns the correct runtime type.

### 3.3 Cache getters → direct `cache.*` with degradation preserved (Strategy 3)

`GuildChannel.get_guild` (`channels.py:999`) and `ChannelFollow.get_channel` (`channels.py:270`)
today gate on `isinstance(self.app, traits.CacheAware)` and return `None` when there is no cache.
That degradation must survive:

```python
# before: channel.get_guild()  -> Guild | None, None if app not CacheAware
# after (caller holds an optional cache):
guild = cache.get_guild(channel.guild_id) if cache is not None else None
```

`ChannelFollow.get_channel` additionally `assert`s the result is a `GuildChannel`; same
narrowing-loss note as §3.2.

### 3.4 `shard_id` — client-level, cannot be a struct method (special case)

`GuildChannel.shard_id` (`channels.py:989`) calls
`snowflakes.calculate_shard_id(self.app, self.guild_id)` — it **passes the whole app object** into
`calculate_shard_id` (which reads `.shard_count`). This is one of the two divergent shard-id styles
(`../01-app-field-removal.md` §5.1): `guilds.PartialGuild.shard_id` passes `self.app.shard_count`
(an int) instead. `calculate_shard_id` (`snowflakes.py:135`) accepts `traits.ShardAware | int`, so
both compile today.

Under app removal `shard_id` cannot remain a struct property (it needs the shard count, a client
fact). Replacement: a client/free-function-level call. Normalize both styles to pass the int:

```python
# before: channel.shard_id  (property)
# after:  snowflakes.calculate_shard_id(bot.shard_count, channel.guild_id)
```

### 3.5 `edit_overwrite` — compose (target_type inference)

`PermissibleGuildChannel.edit_overwrite` (`channels.py:1203`) is not a pure delegation: when
`target_type` is `UNDEFINED` it asserts the `target` is not a bare `int` and infers the overwrite
type from the runtime type of `target` (`channels.py:1253-1261`), then issues one of two
`rest.edit_permission_overwrite` calls. This logic is orphaned by removal. Target design lives in
[`../03-new-rest-methods-and-free-functions.md`](../03-new-rest-methods-and-free-functions.md) §6
(free function with `target_type` inference, or require an explicit `target_type` at the call site).
Do not lose the `TypeError`/assert path — callers passing a bare id with no `target_type` must still
get a clear error.

## 4. Step-by-step migration

1. Delete the `app` field from `PartialChannel` (`channels.py:361`) and `ChannelFollow`
   (`channels.py:203`) per [`../01-app-field-removal.md`](../01-app-field-removal.md).
2. Delete the 14 pure/assert/arg-default helpers (§3.1); update docstrings/examples to the `rest.*`
   form.
3. Convert the 2 cache getters (`get_guild`, `ChannelFollow.get_channel`) to caller-side `cache.*`
   with the `None`-degradation preserved (§3.3).
4. Move `shard_id` off the struct to the client/free-function layer, normalizing to the int style
   (§3.4); coordinate with `../01-app-field-removal.md` §5.1.
5. Re-home `edit_overwrite` to the free function specified in
   [`../03-new-rest-methods-and-free-functions.md`](../03-new-rest-methods-and-free-functions.md) §6.
6. Decide the `assert`-narrowing policy (§3.2) once and apply it to `ChannelFollow.fetch_channel`,
   `.fetch_webhook`, `.get_channel`.
7. Add every removed public method to the breaking-changes catalog
   (`../../11-rollout/03-breaking-changes-and-changelog.md`).

## 5. Affected files & symbols

| Path | Anchor | Change |
|---|---|---|
| `hikari/channels.py` | 203, 361 | remove `app` field (`ChannelFollow`, `PartialChannel`) |
| `hikari/channels.py` | 214, 243, 270 | remove `ChannelFollow.fetch_channel/fetch_webhook/get_channel` |
| `hikari/channels.py` | 395–806 | remove `PartialChannel.delete`, `TextableChannel.*` (8) |
| `hikari/channels.py` | 989, 999, 1012, 1036 | remove `GuildChannel.shard_id/get_guild/fetch_guild/edit` |
| `hikari/channels.py` | 1203, 1263 | remove `PermissibleGuildChannel.edit_overwrite/remove_overwrite` |
| `hikari/impl/entity_factory.py` | 63 `app=self._app` sites | drop `app=` on channel deserialize (`../01-app-field-removal.md`) |
| docs / examples | — | rewrite `channel.send(...)` etc. |

## 6. Risks / gotchas

- **`send`/`edit` are enormous signatures.** Removing them means callers must reproduce the full
  kwargs surface against `rest.create_message` / `rest.edit_channel`; both already accept the same
  kwargs, so it is a mechanical `channel.send(x=...)` → `rest.create_message(channel.id, x=...)`.
  The public break is large — `channel.send(...)` appears throughout user code and docs.
- **`fetch_history` returns a `LazyIterator`, not a coroutine** — it is a sync method
  (`channels.py:431`). The replacement `rest.fetch_messages(channel.id, ...)` is likewise sync-returns-iterator; do not `await` it in the migration examples.
- **Two shard-id styles** (`channels.py:989` passes the app object; `guilds.py:1692` passes the int).
  A mechanical pass must handle both — see `../01-app-field-removal.md` §5.1.
- **Narrowing loss** on the three `assert` helpers (§3.2).
- Cache getters must not raise when there is no cache — preserve `None` (§3.3).

## 7. Verification

1. `grep -n "self\.app" hikari/channels.py` → 0 hits after the pass.
2. Type-check a sample caller migrated from `channel.send(...)` to `rest.create_message(...)` — kwargs
   line up.
3. Unit test: `edit_overwrite` free function still raises on a bare-int target with no `target_type`
   (preserves `channels.py:1253` assert semantics).
4. Cache getter free-function/inline replacement returns `None` (not raises) when handed no cache.

## 8. Open questions

- Assert-narrowing policy (keep typed wrapper vs. push `typing.cast`) — `../../00-overview/05-decisions-log.md`.
- Final home of `shard_id` (client method vs. free function) — coordinate with
  `../01-app-field-removal.md` §5.1 and the decisions log.
- `edit_overwrite` target shape — `../03-new-rest-methods-and-free-functions.md` §6.
