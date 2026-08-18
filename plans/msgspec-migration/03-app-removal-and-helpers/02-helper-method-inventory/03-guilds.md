# Helper Removal — `hikari/guilds.py`

Removal recipe for the **55 app-delegating helper methods** in `hikari/guilds.py` — the single
largest cluster. The `self\.app`-only grep found **45** (29 `rest.*` + 14 `cache.*` call-site lines,
plus 2 non-rest/cache `self.app.*` sites, dossier 04 §0); that was a floor. `Member` delegates 10 of
its helpers through `self.user.app.(rest|cache)` (the wrapped user's app, `guilds.py:641/658/673/862/
925/954/981/1011/1041/1120`), which the `self.app` grep never saw. Counting both patterns, the true
split is `GuildWidget` (1), `Member` (11), `PartialGuild` (22), and `Guild` (21, mostly cache
getters) = **55** (45 `self.app` + 10 `self.user.app`). See §2.1 for the full `Member` table.

See [`00-README.md`](00-README.md) for the shared legend,
[`../03-new-rest-methods-and-free-functions.md`](../03-new-rest-methods-and-free-functions.md) for the
`fetch_roles`/`get_my_member`/guild-scoped-getter targets, and
[`../01-app-field-removal.md`](../01-app-field-removal.md) §5.1 for the shard-id divergence.

## 1. Objective

Delete `guilds.py`'s `app`-delegating helpers; map each to its `rest.*`/`cache.*` replacement;
re-home the four ownership-filtered cache getters, the client-side `Member.fetch_roles` filter, the
`get_my_member` own-user composition, and the `shard_id` shard-count read. Serves constraint (a) / D9.

## 2. Current state (dossier 04 §3.9, source-anchored)

`app` fields: `PartialGuild` (`guilds.py:1664`), `PartialRole` (`guilds.py:1150`); `Guild`
(`guilds.py:1664`+) extends `PartialGuild`. `GuildWidget` carries its own `app` (`guilds.py:321`).
`Member` has **no** `app` field — `Member.app` (`guilds.py:514-518`) is a **property** returning
`self.user.app`, so its 10 non-`fetch_roles` helpers delegate through `self.user.app.(rest|cache)`
rather than `self.app`; removing `User.app` (`02-users.md`) removes it.

### 2.1 `GuildWidget` (1)

| Line | Class | Method | async | Delegates to | Extra logic |
|---:|---|---|:--:|---|---|
| 332 | `GuildWidget` | `fetch_channel` | yes | `rest.fetch_channel(self.channel_id)` | `None` guard + `assert` |

### 2.2 `Member` (11 app-delegating helpers)

`Member` is **not** a single-helper class. The original `self\.app` grep found only `fetch_roles`
(`guilds.py:888`, which uses `self.app.rest.fetch_roles`); the other **10** helpers reach the client
through the **wrapped user's** app — `self.user.app.(rest|cache)` (`Member.app` is itself a property
returning `self.user.app`, `guilds.py:514-518`). A `self\.app` grep never sees those, so they were
undercounted as 1. The complete set is 11:

| Line | Method | async | Delegates to | Extra logic |
|---:|---|:--:|---|---|
| 641 | `get_guild` | no | `self.user.app.cache.get_guild(self.guild_id)` | `guard` (CacheAware → `None`) |
| 658 | `get_presence` | no | `self.user.app.cache.get_presence(self.guild_id, self.user.id)` | `guard` (→ `None`) |
| 673 | `get_roles` | no | `self.user.app.cache.get_role(role_id)` per `role_id` | `guard` (→ `[]`) + **`compose`** (per-`role_ids` cache walk) |
| 862 | `fetch_self` | yes | `self.user.app.rest.fetch_member(self.guild_id, self.user.id)` | pure |
| 888 | `fetch_roles` | yes | `self.app.rest.fetch_roles(self.guild_id)` | **`compose`** — client-side filter by `role_ids` |
| 925 | `ban` | yes | `self.user.app.rest.ban_user(self.guild_id, self.user.id, …)` | pure |
| 954 | `unban` | yes | `self.user.app.rest.unban_user(self.guild_id, self.user.id, reason=)` | pure |
| 981 | `kick` | yes | `self.user.app.rest.kick_user(self.guild_id, self.user.id, reason=)` | pure |
| 1011 | `add_role` | yes | `self.user.app.rest.add_role_to_member(self.guild_id, self.user.id, role, reason=)` | pure |
| 1041 | `remove_role` | yes | `self.user.app.rest.remove_role_from_member(self.guild_id, self.user.id, role, reason=)` | pure |
| 1120 | `edit` | yes | `self.user.app.rest.edit_member(self.guild_id, self.user.id, …)` | pure |

`get_top_role` (`guilds.py:675`) and `fetch_dm_channel` (`guilds.py:865`) are **not** counted here:
the former composes over `self.get_roles()` (no direct app access), the latter delegates to
`self.user.fetch_dm_channel()` (re-homed under `02-users.md`).

Verified `Member.fetch_roles` body (`guilds.py:888-889`):
```python
fetched_roles = await self.app.rest.fetch_roles(self.guild_id)
return [role for role in fetched_roles if role.id in self.role_ids]
```
Discord has no "member roles" endpoint — the filter is unavoidably client-side.

### 2.3 `PartialGuild` (22 methods)

| Line | Method | async | Delegates to | Extra logic |
|---:|---|:--:|---|---|
| 1683 | `shard_id` (property) | no | `self.app.shard_count` + `snowflakes.calculate_shard_id(shard_count, self.id)` | `guard` (ShardAware); **passes int** |
| 1748 | `ban` | yes | `rest.ban_user(self.id, user, …)` | pure |
| 1787 | `unban` | yes | `rest.unban_user(self.id, user, reason=)` | pure |
| 1821 | `kick` | yes | `rest.kick_user(self.id, user, reason=)` | pure |
| 1855 | `edit` | yes | `rest.edit_guild(self.id, …)` | pure |
| 1971 | `set_incident_actions` | yes | `rest.set_guild_incident_actions(self.id, …)` | pure |
| 2028 | `fetch_emojis` | yes | `rest.fetch_guild_emojis(self.id)` | pure |
| 2050 | `fetch_emoji` | yes | `rest.fetch_emoji(self.id, emoji)` | pure |
| 2078 | `fetch_stickers` | yes | `rest.fetch_guild_stickers(self.id)` | pure |
| 2102 | `fetch_sticker` | yes | `rest.fetch_guild_sticker(self.id, sticker)` | pure |
| 2132 | `create_sticker` | yes | `rest.create_sticker(self.id, …)` | pure |
| 2187 | `edit_sticker` | yes | `rest.edit_sticker(self.id, sticker, …)` | pure |
| 2239 | `delete_sticker` | yes | `rest.delete_sticker(self.id, sticker, reason=)` | pure |
| 2273 | `create_category` | yes | `rest.create_guild_category(self.id, name, …)` | pure |
| 2322 | `create_text_channel` | yes | `rest.create_guild_text_channel(self.id, name, …)` | pure |
| 2395 | `create_news_channel` | yes | `rest.create_guild_news_channel(self.id, name, …)` | pure |
| 2468 | `create_forum_channel` | yes | `rest.create_guild_forum_channel(self.id, name, …)` | pure |
| 2573 | `create_voice_channel` | yes | `rest.create_guild_voice_channel(self.id, name, …)` | pure |
| 2654 | `create_stage_channel` | yes | `rest.create_guild_stage_channel(self.id, name, …)` | pure |
| 2731 | `delete_channel` | yes | `rest.delete_channel(channel)` | `assert isinstance(..., GuildChannel)` |
| 2773 | `fetch_self` | yes | `rest.fetch_guild(self.id)` | pure |
| 2797 | `fetch_roles` | yes | `rest.fetch_roles(self.id)` | pure |

### 2.4 `Guild` (21 methods — 15 cache getters + 6 rest)

| Line | Method | async | Delegates to | Extra logic |
|---:|---|:--:|---|---|
| 3090 | `get_members` | no | `cache.get_members_view_for_guild(self.id)` | `guard` (→`{}`) |
| 3103 | `get_presences` | no | `cache.get_presences_view_for_guild(self.id)` | `guard` |
| 3117 | `get_channels` | no | `cache.get_guild_channels_view_for_guild(self.id)` | `guard` |
| 3131 | `get_voice_states` | no | `cache.get_voice_states_view_for_guild(self.id)` | `guard` |
| 3145 | `get_emojis` | no | `cache.get_emojis_view_for_guild(self.id)` | `guard` |
| 3158 | `get_stickers` | no | `cache.get_stickers_view_for_guild(self.id)` | `guard` |
| 3171 | `get_roles` | no | `cache.get_roles_view_for_guild(self.id)` | `guard` |
| 3331 | `get_channel` | no | `cache.get_guild_channel(channel)` | `guard` + **ownership filter** (`guild_id == self.id`) |
| 3355 | `get_member` | no | `cache.get_member(self.id, user)` | `guard` |
| 3373 | `get_my_member` | no | `self.app.get_me()` → `self.get_member(me.id)` | `guard` + **`get_me()` (non-rest/cache)** |
| 3390 | `get_presence` | no | `cache.get_presence(self.id, user)` | `guard` |
| 3408 | `get_voice_state` | no | `cache.get_voice_state(self.id, user)` | `guard` |
| 3426 | `get_emoji` | no | `cache.get_emoji(emoji)` | `guard` + ownership filter |
| 3449 | `get_sticker` | no | `cache.get_sticker(sticker)` | `guard` + ownership filter |
| 3472 | `get_role` | no | `cache.get_role(role)` | `guard` + ownership filter |
| 3494 | `fetch_owner` | yes | `rest.fetch_member(self.id, self.owner_id)` | pure |
| 3516 | `fetch_widget_channel` | yes | `rest.fetch_channel(self.widget_channel_id)` | `None` guard + `assert` |
| 3547 | `fetch_afk_channel` | yes | `rest.fetch_channel(self.afk_channel_id)` | `None` guard + `assert` |
| 3576 | `fetch_system_channel` | yes | `rest.fetch_channel(self.system_channel_id)` | `None` guard + `assert` |
| 3606 | `fetch_rules_channel` | yes | `rest.fetch_channel(self.rules_channel_id)` | `None` guard + `assert` |
| 3637 | `fetch_public_updates_channel` | yes | `rest.fetch_channel(self.public_updates_channel_id)` | `None` guard + `assert` |

## 3. Target design — replacements

### 3.1 Pure `PartialGuild` rest helpers → direct `rest.*` (Strategy 1)

19 of `PartialGuild`'s 22 helpers are pure single-call delegations. The caller substitutes `self.id`
with `guild.id`:

| Removed helper | Caller now writes |
|---|---|
| `guild.ban(user, ...)` | `await rest.ban_user(guild.id, user, ...)` |
| `guild.unban(user, reason=...)` | `await rest.unban_user(guild.id, user, reason=...)` |
| `guild.kick(user, reason=...)` | `await rest.kick_user(guild.id, user, reason=...)` |
| `guild.edit(...)` | `await rest.edit_guild(guild.id, ...)` |
| `guild.set_incident_actions(...)` | `await rest.set_guild_incident_actions(guild.id, ...)` |
| `guild.fetch_emojis()` / `fetch_emoji(e)` | `await rest.fetch_guild_emojis(guild.id)` / `rest.fetch_emoji(guild.id, e)` |
| `guild.fetch_stickers()` / `fetch_sticker(s)` | `await rest.fetch_guild_stickers(guild.id)` / `rest.fetch_guild_sticker(guild.id, s)` |
| `guild.create_sticker/edit_sticker/delete_sticker(...)` | `await rest.create_sticker/edit_sticker/delete_sticker(guild.id, ...)` |
| `guild.create_{category,text,news,forum,voice,stage}_channel(...)` | `await rest.create_guild_{category,text_channel,news_channel,forum_channel,voice_channel,stage_channel}(guild.id, ...)` |
| `guild.fetch_self()` | `await rest.fetch_guild(guild.id)` |
| `guild.fetch_roles()` | `await rest.fetch_roles(guild.id)` |
| `guild.fetch_owner()` | `await rest.fetch_member(guild.id, guild.owner_id)` |

`delete_channel` (`guilds.py:2731`) is `assert`-narrowed (returns `GuildChannel`); apply the cluster
narrowing policy ([`00-README.md`](00-README.md) §9) — `typing.cast` or a typed wrapper.

### 3.2 `None`-guarded channel fetchers → direct `rest.*` with the None check inline

`GuildWidget.fetch_channel` (`guilds.py:332`) and the five `Guild.fetch_*_channel` helpers
(`guilds.py:3516/3547/3576/3606/3637`) return `None` when the id field is `None`, then `assert` the
channel type. Callers inline the None check:

```python
# before: await guild.fetch_afk_channel()  -> GuildVoiceChannel | None
# after:
afk = (
    await rest.fetch_channel(guild.afk_channel_id)
    if guild.afk_channel_id is not None
    else None
)
```

### 3.3 Simple cache getters → direct `cache.*` with `{}`/`None` degradation (Strategy 3)

The seven view getters (`get_members`…`get_roles`) and `get_member`/`get_presence`/`get_voice_state`
gate on `isinstance(self.app, traits.CacheAware)` and return an empty view / `None` when there is no
cache. Preserve that:

```python
# before: guild.get_members()  -> Mapping[...], {} if no cache
# after:
members = cache.get_members_view_for_guild(guild.id) if cache is not None else {}
# before: guild.get_member(user)  -> Member | None
# after:
member = cache.get_member(guild.id, user) if cache is not None else None
```

### 3.4 Ownership-filtered getters → guild-scoped free functions (no-1:1)

`Guild.get_channel` (`guilds.py:3331`), `get_emoji` (`:3426`), `get_sticker` (`:3449`), `get_role`
(`:3472`) do a raw cache hit **then verify** `obj.guild_id == self.id` (the object may be cached but
belong to another guild). A bare `cache.get_*` drops that check. Target: the guild-scoped free
functions in
[`../03-new-rest-methods-and-free-functions.md`](../03-new-rest-methods-and-free-functions.md) §8.1:

```python
# before: guild.get_channel(cid)
# after:  get_guild_channel_scoped(cache, guild.id, cid)   # returns None if not in this guild
# analogous: get_guild_emoji_scoped / get_guild_sticker_scoped / get_guild_role_scoped
```

### 3.5 `get_my_member` — client-level (own-user + cache, no-1:1)

`Guild.get_my_member` (`guilds.py:3373`) needs `self.app.get_me()` (the ShardAware own-user, a
non-rest/non-cache client fact) then `self.get_member(me.id)`. It cannot be a pure struct method —
it inherently needs the client. Target: a client/free-function helper `get_my_member(app, guild_id)`
(see [`../03-new-rest-methods-and-free-functions.md`](../03-new-rest-methods-and-free-functions.md)
§8.2). This is one of the 2 non-rest/cache `self.app.*` sites (dossier 04 §6: `guilds.py:3384`
`me = self.app.get_me()`).

### 3.6 `shard_id` — client-level (shard count, no-1:1)

`PartialGuild.shard_id` (`guilds.py:1683`) reads `self.app.shard_count` (dossier 04 §6,
`guilds.py:1692`) and computes `calculate_shard_id(shard_count, self.id)`. It **passes an int** — the
opposite style from `channels.GuildChannel.shard_id` which passes the app object (see
[`../01-app-field-removal.md`](../01-app-field-removal.md) §5.1). Move to the client/free-function
layer:

```python
# before: guild.shard_id  (property)
# after:  snowflakes.calculate_shard_id(bot.shard_count, guild.id)
```

### 3.7 `Member.fetch_roles` — client-side filter (no-1:1)

`Member.fetch_roles` (`guilds.py:868`) fetches all guild roles then filters by `self.role_ids`. Target:
free function `fetch_member_roles(rest, member)` (no Discord endpoint) — see
[`../03-new-rest-methods-and-free-functions.md`](../03-new-rest-methods-and-free-functions.md) §3:

```python
async def fetch_member_roles(rest, member):
    fetched = await rest.fetch_roles(member.guild_id)
    return [r for r in fetched if r.id in member.role_ids]
```

### 3.8 `Member` action helpers + cache getters → 1:1 `rest.*` / `cache.*`

The six `Member` action helpers (§2.2) are pure single-call delegations through `self.user.app.rest`;
each maps 1:1 to a `rest.*` call, substituting `member.guild_id` / `member.user.id`. The
`self.user.app` indirection (via `Member.app` → `self.user.app`, `guilds.py:514-518`) collapses to the
plain `rest` handle — the migration is identical to §3.1 for `PartialGuild`, only the delegation path
differs:

| Removed helper | Caller now writes |
|---|---|
| `member.ban(...)` | `await rest.ban_user(member.guild_id, member.user.id, ...)` |
| `member.unban(reason=...)` | `await rest.unban_user(member.guild_id, member.user.id, reason=...)` |
| `member.kick(reason=...)` | `await rest.kick_user(member.guild_id, member.user.id, reason=...)` |
| `member.add_role(role, reason=...)` | `await rest.add_role_to_member(member.guild_id, member.user.id, role, reason=...)` |
| `member.remove_role(role, reason=...)` | `await rest.remove_role_from_member(member.guild_id, member.user.id, role, reason=...)` |
| `member.edit(...)` | `await rest.edit_member(member.guild_id, member.user.id, ...)` |
| `member.fetch_self()` | `await rest.fetch_member(member.guild_id, member.user.id)` |

The three cache getters gate on `isinstance(self.user.app, traits.CacheAware)` and degrade to
`None`/`[]`; preserve that per Strategy 3 (§3.3):

```python
# before: member.get_guild()  -> Guild | None
member_guild = cache.get_guild(member.guild_id) if cache is not None else None
# before: member.get_presence()  -> MemberPresence | None
member_presence = (
    cache.get_presence(member.guild_id, member.user.id) if cache is not None else None
)
# before: member.get_roles()  -> Sequence[Role], [] if no cache (per-role_ids cache walk)
member_roles = (
    [r for rid in member.role_ids if (r := cache.get_role(rid)) is not None]
    if cache is not None
    else []
)
```

`member.fetch_roles()` is the no-1:1 client-side filter re-homed in §3.7. `member.get_top_role()`
composes over `get_roles()` (sort by `position`); it re-homes as a free function over the same
cache-walked roles, not an app call.

## 4. Step-by-step migration

1. Remove `app` fields on `PartialGuild` (`guilds.py:1664`), `PartialRole` (`guilds.py:1150`),
   `GuildWidget` (`guilds.py:321`) per [`../01-app-field-removal.md`](../01-app-field-removal.md); the
   `Member.app` property (`guilds.py:514-518`) drops with `User.app` (`02-users.md`).
2. Delete the 19 pure `PartialGuild` rest helpers + `fetch_owner` (§3.1); rewrite docs/examples.
3. Inline the None-guard on the six channel fetchers (§3.2); apply narrowing policy to the `assert`
   forms and `delete_channel`.
4. Convert the 10 simple cache getters to caller-side `cache.*` with `{}`/`None` degradation (§3.3).
5. Re-home the 4 ownership-filtered getters to guild-scoped free functions (§3.4).
6. Re-home `get_my_member` to a client-level helper (§3.5) and `shard_id` to the client/free-function
   layer (§3.6), normalizing the shard-id style.
7. Re-home `Member.fetch_roles` to `fetch_member_roles(rest, member)` (§3.7); convert the 6 `Member`
   action helpers to 1:1 `rest.*` and the 3 `Member` cache getters to `cache.*` degradation (§3.8).
8. Catalog all 55 removed public methods (45 `self.app` + 10 `self.user.app` on `Member`) in
   `../../11-rollout/03-breaking-changes-and-changelog.md`.

## 5. Affected files & symbols

| Path | Anchor | Change |
|---|---|---|
| `hikari/guilds.py` | 321, 1150, 1664 | remove `app` fields (`GuildWidget`, `PartialRole`, `PartialGuild`/`Guild`); `Member.app` property (514) drops with `User.app` |
| `hikari/guilds.py` | 332 | `GuildWidget.fetch_channel` |
| `hikari/guilds.py` | 630–1120 | re-home `Member`'s 11 helpers: `fetch_roles` (888), 6 action rest helpers (925/954/981/1011/1041/1120), `fetch_self` (862), 3 cache getters (641/658/673) |
| `hikari/guilds.py` | 1683–2797 | remove `PartialGuild` 22 helpers (incl. `shard_id`) |
| `hikari/guilds.py` | 3090–3637 | remove `Guild` 21 getters/fetchers |
| `hikari/snowflakes.py` | 135 | `calculate_shard_id` now called from client layer with int |
| `hikari/impl/entity_factory.py` | guild deserialize | drop `app=self._app` |

## 6. Risks / gotchas

- **Highest blast radius of any module** — 55 documented methods (45 `self.app` + 10
  `self.user.app` on `Member`), including the heavily-used `guild.get_member(...)`,
  `guild.get_channel(...)`, `guild.create_text_channel(...)`, `member.ban(...)`, `member.edit(...)`.
  Every doc example using these breaks.
- **`Member` delegates through `self.user.app`, not `self.app`** — 10 of its 11 helpers reach the
  client via the wrapped user's app (`Member.app` is a property, `guilds.py:514-518`). A `self\.app`
  grep silently misses them; use the `self\.(user\.)?app\.(rest|cache)` regex (§7) or the count reads
  45 instead of the true 55.
- **Ownership-filter silently changes semantics if replaced by a bare `cache.get_*`** — an object
  cached under another guild would wrongly be returned. §3.4 free functions must keep the
  `guild_id == self.id` check.
- **`get_my_member` and `shard_id` cannot be struct methods** — they need client facts
  (own-user/shard-count). They must land at the client/free-function layer, not silently disappear.
- **Two shard-id styles** — `guilds.py:1692` passes an int; `channels.py:995` passes the app object.
  Normalize both (`../01-app-field-removal.md` §5.1).
- **`Member.fetch_roles` is not replaceable by any single rest call** — do not point users at
  `rest.fetch_roles` alone (that returns *all* guild roles).

## 7. Verification

1. `grep -nE "self\.(user\.)?app\.(rest|cache)" hikari/guilds.py` → 0 after the pass. The broadened
   regex is mandatory here: a bare `self\.app` grep misses `Member`'s 10 `self.user.app.(rest|cache)`
   sites (`guilds.py:641/658/673/862/925/954/981/1011/1041/1120`).
2. `fetch_member_roles(rest, member)` returns only roles whose id ∈ `member.role_ids`.
3. Guild-scoped getters return `None` for an id cached under a different guild.
4. Simple cache getters return `{}`/`None` (not raise) with no cache.
5. `get_my_member` client helper returns `None` when there is no own-user / no cache.

## 8. Open questions

- Assert-narrowing policy for the 6 channel fetchers + `delete_channel`
  (`../../00-overview/05-decisions-log.md`).
- Final home + signature of `get_my_member`, `shard_id`, and the guild-scoped getters —
  `../03-new-rest-methods-and-free-functions.md` §8.
- Shard-id style normalization — `../01-app-field-removal.md` §5.1.
