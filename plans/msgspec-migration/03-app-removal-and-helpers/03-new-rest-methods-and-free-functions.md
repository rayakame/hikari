# New REST Methods and Free Functions

The subset of removed helpers whose logic does **more** than a thin `rest.*` forward and therefore
cannot collapse to a single direct call. For each, this file proposes a concrete replacement — a free
function taking `rest`/`cache` explicitly, or a new `rest.*` convenience method — with a signature.
This is Strategy 2 from [`00-strategy.md`](./00-strategy.md) §4.

Scope note: **no removed helper wraps a *missing* endpoint** (dossier 10 §7, §9). Every underlying
`rest.*` method already exists. What follows is about *preserving composed behaviour and DX*, not
about adding capability. Zero new HTTP endpoints are mandatory.

---

## 1. Objective

Give the `compose` and `token` helpers (taxonomy in [`00-strategy.md`](./00-strategy.md) §3) a landing
pad before they are deleted, so callers do not lose:
- client-side filtering (`Member.fetch_roles`),
- multi-step flows (`PartialUser.send`: cache→create DM→message),
- guard/branch logic (webhook `use_token` resolution; reaction dispatchers; `respond`'s `reply` coercion),
- runtime-type inference (`edit_overwrite`'s `target_type`),
- ownership-scoped cache lookups (`Guild.get_*`),
- own-user resolution (`Guild.get_my_member`).

This serves **constraint (a)** without regressing behaviour, and it must land *before* the
corresponding helpers are removed (sequencing in [`00-strategy.md`](./00-strategy.md) §6).

---

## 2. The cluster (source-anchored)

| Helper | File:line | Why no 1:1 rest call | Proposed replacement |
|---|---|---|---|
| `Member.fetch_roles` | `guilds.py:868` | fetch all guild roles, filter by `self.role_ids` (no Discord "member roles" endpoint) | free fn `fetch_member_roles(rest, member)` |
| `PartialUser.send` | `users.py:429` (body `:588-614`) | cache DM lookup → `create_dm_channel` → `create_message` | new `rest.send_dm(user, ...)` **or** free fn |
| `ExecutableWebhook.execute` / `fetch_message` / `edit_message` / `delete_message` | `webhooks.py:99/242/276/440` | mandatory `self.token` gate (`ValueError` if `None`) | free fns, or `rest` token param |
| `IncomingWebhook.delete` / `edit` / `fetch_self` | `webhooks.py:611/645/743` | `use_token` tri-state resolution | free fn `resolve_webhook_token(...)` + direct call |
| `PermissibleGuildChannel.edit_overwrite` | `channels.py:1203` | `target_type` inferred from `target`'s runtime type | free fn / require explicit `target_type` |
| `PartialMessage.respond` | `messages.py:1102` | `reply` bool → `self`/`UNDEFINED` coercion | free fn / caller passes `reply=message` |
| `PartialMessage.remove_reaction` | `messages.py:1390` | branch: `delete_my_reaction` vs `delete_reaction` | inline branch, or tiny sugar |
| `PartialMessage.remove_all_reactions` | `messages.py:1472` | branch: `delete_all_reactions` vs `delete_all_reactions_for_emoji` | inline branch, or tiny sugar |
| `PartialMessage.get_member_mentions` / `get_role_mentions` | `messages.py:816/850` | map mention ids through cache | free fn taking `cache` |
| `Guild.get_channel` / `get_emoji` / `get_sticker` / `get_role` | `guilds.py:3331/3426/3449/3472` | cache hit **+** `obj.guild_id == self.id` ownership filter | free fn `get_guild_scoped_*(cache, guild_id, id)` |
| `Guild.get_my_member` | `guilds.py:3373` | needs `app.get_me()` (own-user) + cache | **client-level** free fn `get_my_member(app, guild_id)` — cannot be a struct method |
| Interaction `build_*_response` | see §9 | `ResponseType` selection + app-free builder factory | app-free builder factory (D10-interactions) |

---

## 3. `Member.fetch_roles` → `fetch_member_roles(rest, member)`

Current body (`guilds.py:888-889`):

```python
fetched_roles = await self.app.rest.fetch_roles(self.guild_id)
return [role for role in fetched_roles if role.id in self.role_ids]
```

Discord has no per-member roles endpoint; the filter is client-side. Proposed free function (module:
`hikari/guilds.py` or a `hikari/internal`/helpers home — maintainer choice):

```python
async def fetch_member_roles(
    rest: rest_api.RESTClient, member: Member, /
) -> typing.Sequence[Role]:
    """Fetch an up-to-date view of a member's roles from the API."""
    fetched = await rest.fetch_roles(member.guild_id)
    return [role for role in fetched if role.id in member.role_ids]
```

Rationale: keeps the client-side filter in the library rather than forcing every caller to re-derive
it. A free function (not a new `rest.*` method) is right here — the logic is member-specific, not a
general REST capability.

---

## 4. `PartialUser.send` → `rest.send_dm(user, ...)` (recommended new convenience method)

Current body (`users.py:589-614`) — genuinely compound, no single endpoint:

```python
channel_id = None
if isinstance(self.app, traits.CacheAware):
    channel_id = self.app.cache.get_dm_channel_id(self.id)   # cache fast-path (read)
if channel_id is None:
    channel_id = (await self.fetch_dm_channel()).id          # create_dm_channel (also caches it)
return await self.app.rest.create_message(channel=channel_id, content=content, ...)  # full kwargs
```

`create_dm_channel` already writes `set_dm_channel_id` into cache (`impl/rest.py:2452-2453`); only the
cache *read* fast-path lives in the helper (dossier 10 §7.2). This is the **strongest candidate for a
new `rest.*` convenience method** — it is the highest-traffic compound helper and the DX loss is the
sharpest.

Proposed signature (mirrors `create_message`, adds the DM resolution):

```python
async def send_dm(
    self,
    user: snowflakes.SnowflakeishOr[users.PartialUser],
    content: undefined.UndefinedOr[typing.Any] = undefined.UNDEFINED,
    *,
    # ... the full create_message kwarg surface (attachment(s), component(s), embed(s),
    #     nonce, tts, reply, reply_must_exist, mentions_everyone, user/role mentions,
    #     mentions_reply, flags) ...
) -> messages.Message:
    """Resolve (or open) the DM channel with `user` and send a message to it."""
    channel_id = self._cache.get_dm_channel_id(int(user)) if self._cache else None
    if channel_id is None:
        channel_id = (await self.create_dm_channel(user)).id
    return await self.create_message(channel_id, content, ...)
```

Notes:
- Lives on `RESTClientImpl`, which already holds `self._cache` (used at `impl/rest.py:1064-1065,
  2452-2453`) — so the cache fast-path is preserved without any `app`.
- If the maintainer prefers **no** REST-surface growth, ship it as a free function
  `send_dm(rest, cache, user, ...)` instead; behaviour identical. Recommendation: the `rest.send_dm`
  method, because `user.send(...)` is one of the two or three most-used helpers in existing code
  (dossier 10 §8.1) and a method reads most naturally.

---

## 5. Webhook token resolution (`token` helpers)

The `IncomingWebhook` action helpers wrap a `use_token` tri-state resolution before forwarding
(dossier 04 §3.3; verified `webhooks.py:633-643` for `delete`, `:701-713` for `edit`):

```python
token: undefined.UndefinedOr[str] = undefined.UNDEFINED
if use_token:
    if self.token is None:
        raise ValueError("This webhook's token is unknown, so cannot be used")
    token = self.token
elif use_token is undefined.UNDEFINED and self.token:
    token = self.token
await self.app.rest.delete_webhook(self.id, token=token)
```

The `ExecutableWebhook` mixin helpers (`execute`, `fetch_message`, `edit_message`, `delete_message`,
`webhooks.py:99/242/276/440`) instead hard-require `self.token` and raise if it is `None`
(dossier 10 §7.2, `webhooks.py:217-219` pattern).

Two clean homes:

**Option A — a small free function for the tri-state, direct call for the rest:**

```python
def resolve_webhook_token(
    webhook: PartialWebhook, use_token: undefined.UndefinedOr[bool]
) -> undefined.UndefinedOr[str]:
    """Resolve the `use_token` tri-state into a token argument (or raise)."""
    if use_token:
        if webhook.token is None:
            raise ValueError("This webhook's token is unknown, so cannot be used")
        return webhook.token
    if use_token is undefined.UNDEFINED and webhook.token:
        return webhook.token
    return undefined.UNDEFINED

# caller:
token = resolve_webhook_token(webhook, use_token)
await rest.delete_webhook(webhook.id, token=token)
```

For the token-mandatory `ExecutableWebhook` helpers, the guard is one line the caller inlines
(`if webhook.token is None: raise ValueError(...)`), then a direct
`rest.execute_webhook(webhook.webhook_id, webhook.token, ...)`.

**Option B — push token handling into the REST layer** by letting `execute_webhook`/`edit_webhook`/…
accept a `PartialWebhook` and internally resolve `webhook.token`. Heavier (touches the REST signatures)
and mixes data-resolution into transport; **not recommended**. Prefer Option A.

---

## 6. `edit_overwrite` → free function with `target_type` inference (or explicit arg)

Current body (`channels.py:1253-1261`):

```python
if target_type is undefined.UNDEFINED:
    assert not isinstance(target, int), (
        "Cannot determine the type of the target to update. Try specifying 'target_type' manually."
    )
    return await self.app.rest.edit_permission_overwrite(self.id, target, allow=..., deny=..., reason=...)
return await self.app.rest.edit_permission_overwrite(
    self.id, typing.cast("int", target), target_type=target_type, allow=..., deny=..., reason=...
)
```

The inference: when `target_type` is omitted, `rest.edit_permission_overwrite` can itself infer the
type from a non-int `target` (a `PartialUser`/`PartialRole`/`PermissionOverwrite`); when `target` is a
bare int the type is unknowable, so the helper raises. Two options:

**Option A — require the caller to pass `target_type`** when `target` is a raw id, and call
`rest.edit_permission_overwrite(channel.id, target, target_type=..., ...)` directly. The inference
already exists inside `edit_permission_overwrite` for non-int targets, so callers passing an object
lose nothing.

**Option B — free function** that preserves the exact inference + assertion:

```python
async def edit_permission_overwrite_for(
    rest: rest_api.RESTClient,
    channel: snowflakes.SnowflakeishOr[PermissibleGuildChannel],
    target: snowflakes.Snowflakeish | users.PartialUser | guilds.PartialRole | PermissionOverwrite,
    *,
    target_type: undefined.UndefinedOr[PermissionOverwriteType] = undefined.UNDEFINED,
    allow: undefined.UndefinedOr[permissions.Permissions] = undefined.UNDEFINED,
    deny: undefined.UndefinedOr[permissions.Permissions] = undefined.UNDEFINED,
    reason: undefined.UndefinedOr[str] = undefined.UNDEFINED,
) -> None: ...
```

Recommendation: **Option A** — the inference lives in the REST method already; the only thing the
helper added was raising early on a bare-int target, which is a one-line caller guard. Note the strict-
enum move also drops the `| int` on `target_type` (dossier 08 §8 relatives; the parameter union is a
separate input-lenience decision, CONVENTIONS §3).

---

## 7. Reaction dispatchers and `respond` (`compose`, thin)

These are branch-only; the underlying endpoints all exist (dossier 10 §7.2). They do not need a free
function — the branch inlines at the call site — but a tiny sugar method is cheap if DX matters.

- `Message.remove_reaction` (`messages.py:1390`) — `rest.delete_my_reaction(...)` when no `user`,
  else `rest.delete_reaction(..., user=user)`.
- `Message.remove_all_reactions` (`messages.py:1472`) — `rest.delete_all_reactions(...)` when no
  `emoji`, else `rest.delete_all_reactions_for_emoji(...)`.
- `Message.respond` (`messages.py:1102`) — coerces `reply is True → self`, `reply is False → UNDEFINED`,
  then `rest.create_message(self.channel_id, ...)`. After removal the caller passes `reply=message`
  explicitly to `rest.create_message(message.channel_id, ...)`.

Recommendation: inline at call sites; optionally provide `rest.remove_all_reactions(channel, message,
emoji=UNDEFINED)` sugar if user feedback shows the branch is a common footgun.

---

## 8. Cache getters with ownership filters and own-user

### 8.1 Guild-scoped getters → `get_guild_scoped_*(cache, guild_id, id)`

`Guild.get_channel`/`get_emoji`/`get_sticker`/`get_role` (`guilds.py:3331/3426/3449/3472`) do a raw
cache hit **plus** an ownership check `obj.guild_id == self.id` (dossier 04 §3.9). A bare
`cache.get_*` drops the ownership filter. Proposed free functions preserving both the filter and the
"no cache → `None`" degradation (dossier 04 §8.6):

```python
def get_guild_channel_scoped(
    cache: cache_api.Cache, guild_id: snowflakes.Snowflake, channel: snowflakes.SnowflakeishOr[...]
) -> channels.PermissibleGuildChannel | None:
    obj = cache.get_guild_channel(channel)
    return obj if obj is not None and obj.guild_id == guild_id else None
# analogous get_guild_emoji_scoped / get_guild_sticker_scoped / get_guild_role_scoped
```

The plain guild getters without an ownership filter (`get_members`, `get_presences`, `get_channels`,
`get_voice_states`, `get_emojis`, `get_stickers`, `get_roles`, `get_member`, `get_presence`,
`get_voice_state`, `guilds.py:3090-3171/3355/3390/3408`) are pure Strategy 3 —
`cache.get_*_view_for_guild(guild.id)` / `cache.get_member(guild.id, user)` at the call site, no
wrapper needed. Cross-link [`../04-frozen-and-cache/02-cache-app-and-views.md`](../04-frozen-and-cache/02-cache-app-and-views.md).

### 8.2 `Guild.get_my_member` is inherently client-level

`Guild.get_my_member` (`guilds.py:3373`) does `me = self.app.get_me()` then `self.get_member(me.id)`
(dossier 04 §3.9, §6). `get_me()` is neither `rest` nor `cache` — it reads the ShardAware app's cached
own-user (dossier 04 §6, `guilds.py:3384`). It therefore **cannot be a pure struct method** and cannot
be a `cache`-only free function. Proposed client-level free function:

```python
def get_my_member(app: traits.ShardAware, guild_id: snowflakes.Snowflake) -> guilds.Member | None:
    me = app.get_me()
    if me is None or not isinstance(app, traits.CacheAware):
        return None
    return app.cache.get_member(guild_id, me.id)
```

This is the one case where the replacement genuinely needs the `app` (own-user is app-state), so it
lives at the client layer, not on the entity. Document as a behaviour-preserving relocation, not a
drop.

### 8.3 Message mention getters → free fns taking `cache`

`get_member_mentions`/`get_role_mentions` (`messages.py:816/850`) map mention ids through the cache via
`_map_cache_maybe_discover`, closing over `app`+`guild_id` (`messages.py:842-846`; dossier 04 §8.8).
Rewrite as free functions threading `cache`:

```python
def get_member_mentions(
    cache: cache_api.Cache, message: messages.PartialMessage
) -> undefined.UndefinedOr[typing.Mapping[snowflakes.Snowflake, guilds.Member]]:
    if message.user_mentions is undefined.UNDEFINED:
        return undefined.UNDEFINED
    if message.guild_id is None:
        return {}
    return _map_cache_maybe_discover(
        message.user_mentions, lambda uid: cache.get_member(message.guild_id, uid)
    )
```

Preserve the exact tri-state: `UNDEFINED` in → `UNDEFINED` out; DM (no `guild_id`) → `{}`; no cache →
`{}` (the caller simply does not call it, or a stateless variant returns `{}`).

---

## 9. Interaction response builders (app-free factories)

`build_response` / `build_deferred_response` / `build_modal_response` /
`AutocompleteInteraction.build_response` select a `ResponseType` and call `rest.interaction_*_builder`
(dossier 04 §4, dossier 08 §7.4). **These builders do not need `app`** — `rest.interaction_message_builder`
etc. (`impl/rest.py:4664-4683`) are one-line constructors that capture no `app`, and the builder
classes (`impl/special_endpoints.py`) take the `entity_factory` as a `build()` argument, not at
construction (dossier 08 §7.4). So the sugar can be **preserved app-free**:
- Reimplement `build_response()` as a direct constructor call / module-level factory, or
- Retain the methods under D10-interactions option 2 where interactions keep an app-injecting construction path.

This is the one place "remove all app helpers" is too blunt — distinguish **action** helpers (need a
client, must go) from **builder-factory** helpers (app-free, can stay). Full treatment in
[`04-events-and-interactions-app-decision.md`](./04-events-and-interactions-app-decision.md) and
[`../06-model-modules/11-interactions.md`](../06-model-modules/11-interactions.md).

---

## 10. Step-by-step migration

1. **Land `fetch_member_roles`** (free fn) — smallest, self-contained.
2. **Decide `rest.send_dm` vs free fn** and land it (§4). Highest DX payoff.
3. **Land `resolve_webhook_token`** and inline the token-mandatory guards (§5, Option A).
4. **Land the guild-scoped cache free fns + `get_my_member` + mention free fns** (§8).
5. **Decide `edit_overwrite` Option A/B** (§6) — recommend A (caller passes `target_type` for raw ids).
6. Only after the above exist, **delete the corresponding helpers** (Strategy 2 rows in
   [`02-helper-method-inventory/`](./02-helper-method-inventory/00-README.md)).
7. **Interaction builders** land per the resolved D10-interactions option (§9).

---

## 11. Affected files & symbols

| Path | Anchor | Replacement |
|---|---|---|
| `hikari/guilds.py` | 868 (`Member.fetch_roles`) | free fn `fetch_member_roles(rest, member)` |
| `hikari/guilds.py` | 3331/3426/3449/3472 | `get_guild_scoped_*` free fns |
| `hikari/guilds.py` | 3373 (`get_my_member`) | client-level `get_my_member(app, guild_id)` |
| `hikari/users.py` | 429 / 588-614 | `rest.send_dm(user, ...)` (recommended) |
| `hikari/webhooks.py` | 99/242/276/440/611/645/743 | `resolve_webhook_token` + direct call |
| `hikari/channels.py` | 1203 | Option A (explicit `target_type`) or `edit_permission_overwrite_for` |
| `hikari/messages.py` | 816/850 | mention free fns taking `cache` |
| `hikari/messages.py` | 1102/1390/1472 | inline branch (optional `rest` sugar) |
| `hikari/interactions/*` | build_* methods | app-free builder factory (D10-interactions) |
| `hikari/impl/rest.py` | 2452-2453, 1064-1065 | `send_dm` reuses existing cache write / `_cache` handle |

---

## 12. Risks / gotchas

- **Preserve graceful degradation.** Cache-backed free fns must return `{}`/`None` when there is no
  cache, never raise (dossier 04 §8.6). The old helpers degraded silently and callers rely on it.
- **`get_my_member` cannot be cache-only** — it needs the app's own-user; keep it at the client layer
  (§8.2). Do not silently drop it.
- **`send_dm` must keep the cache read fast-path** to avoid a spurious `create_dm_channel` round-trip on
  every send (§4). Reuse `RESTClientImpl._cache`.
- **Do not push webhook token logic into REST signatures** (§5 Option B) — it couples transport to data
  resolution; keep it a free function.
- **The strict-enum move** removes `| int` from `edit_overwrite`'s `target_type` annotation; the
  *input-lenience* union decision is separate (CONVENTIONS §3; recommend keeping input lenience).

---

## 13. Verification

- Behaviour parity tests: for each free fn / new method, assert it produces the identical `rest.*`
  call sequence the old helper did (mock `rest`/`cache`, compare call args).
- `fetch_member_roles` returns exactly the roles whose `id in member.role_ids` from a mocked
  `rest.fetch_roles`.
- `send_dm` hits `cache.get_dm_channel_id` first and only calls `create_dm_channel` on a cache miss.
- `resolve_webhook_token` raises `ValueError` iff `use_token is True and webhook.token is None`; returns
  the token when `use_token` is truthy or (UNDEFINED and token present); else `UNDEFINED`.
- Guild-scoped getters return `None` when the cached object's `guild_id` differs (ownership filter).

---

## 14. Open questions / decisions

- **`rest.send_dm` as a public REST method** vs a free function — recommend the method (DX). Confirm in
  [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md) /
  [`../09-rest-and-gateway/00-rest-client.md`](../09-rest-and-gateway/00-rest-client.md).
- **Optional reaction/`remove_all` sugar** — ship or inline? Default: inline.
- **`edit_overwrite` Option A vs B** — recommend A.
- **Interaction builder retention** — tied to D10-interactions; see
  [`04-events-and-interactions-app-decision.md`](./04-events-and-interactions-app-decision.md).
