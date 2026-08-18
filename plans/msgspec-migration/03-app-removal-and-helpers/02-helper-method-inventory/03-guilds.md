# Helper Removal — `hikari/guilds.py`

Removal recipe for the **45 helper methods** in `hikari/guilds.py` — the single largest cluster
(29 `rest.*` + 14 `cache.*` call-site lines, plus 2 non-rest/cache `self.app.*` sites, dossier 04 §0).
Split across `GuildWidget` (1), `Member` (1), `PartialGuild` (22), and `Guild` (21, mostly cache
getters).

See [`00-README.md`](00-README.md) for the shared legend,
[`../03-new-rest-methods-and-free-functions.md`](../03-new-rest-methods-and-free-functions.md) for the
`fetch_roles`/`get_my_member`/guild-scoped-getter targets, and
[`../01-app-field-removal.md`](../01-app-field-removal.md) §5.1 for the shard-id divergence.

## 1. Objective

Delete `guilds.py`'s `app`-delegating helpers; map each to its `rest.*`/`cache.*` replacement;
re-home the four ownership-filtered cache getters, the client-side `Member.fetch_roles` filter, the
`get_my_member` own-user composition, and the `shard_id` shard-count read. Serves constraint (a) / D9.

## 2. Current state (dossier 04 §3.9, source-anchored)

`app` fields: `PartialGuild` (`guilds.py:1664`), `Member` (`guilds.py:1150`); `Guild`
(`guilds.py:1664`+) extends `PartialGuild`. `GuildWidget` carries its own `app`.

### 2.1 `GuildWidget` and `Member`

| Line | Class | Method | async | Delegates to | Extra logic |
|---:|---|---|:--:|---|---|
| 332 | `GuildWidget` | `fetch_channel` | yes | `rest.fetch_channel(self.channel_id)` | `None` guard + `assert` |
| 868 | `Member` | `fetch_roles` | yes | `rest.fetch_roles(self.guild_id)` | **`compose`** — client-side filter by `role_ids` |

Verified `Member.fetch_roles` body (`guilds.py:888-889`):
```python
fetched_roles = await self.app.rest.fetch_roles(self.guild_id)
return [role for role in fetched_roles if role.id in self.role_ids]
```
Discord has no "member roles" endpoint — the filter is unavoidably client-side.

### 2.2 `PartialGuild` (22 methods)

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

### 2.3 `Guild` (21 methods — 15 cache getters + 6 rest)

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

## 4. Step-by-step migration

1. Remove `app` fields on `PartialGuild` (`guilds.py:1664`), `Member` (`guilds.py:1150`),
   `GuildWidget` per [`../01-app-field-removal.md`](../01-app-field-removal.md).
2. Delete the 19 pure `PartialGuild` rest helpers + `fetch_owner` (§3.1); rewrite docs/examples.
3. Inline the None-guard on the six channel fetchers (§3.2); apply narrowing policy to the `assert`
   forms and `delete_channel`.
4. Convert the 10 simple cache getters to caller-side `cache.*` with `{}`/`None` degradation (§3.3).
5. Re-home the 4 ownership-filtered getters to guild-scoped free functions (§3.4).
6. Re-home `get_my_member` to a client-level helper (§3.5) and `shard_id` to the client/free-function
   layer (§3.6), normalizing the shard-id style.
7. Re-home `Member.fetch_roles` to `fetch_member_roles(rest, member)` (§3.7).
8. Catalog all 45 removed public methods in `../../11-rollout/03-breaking-changes-and-changelog.md`.

## 5. Affected files & symbols

| Path | Anchor | Change |
|---|---|---|
| `hikari/guilds.py` | 1150, 1664 | remove `app` fields (`Member`, `PartialGuild`/`Guild`) |
| `hikari/guilds.py` | 332 | `GuildWidget.fetch_channel` |
| `hikari/guilds.py` | 868 | re-home `Member.fetch_roles` |
| `hikari/guilds.py` | 1683–2797 | remove `PartialGuild` 22 helpers (incl. `shard_id`) |
| `hikari/guilds.py` | 3090–3637 | remove `Guild` 21 getters/fetchers |
| `hikari/snowflakes.py` | 135 | `calculate_shard_id` now called from client layer with int |
| `hikari/impl/entity_factory.py` | guild deserialize | drop `app=self._app` |

## 6. Risks / gotchas

- **Highest blast radius of any module** — 45 documented methods, including the heavily-used
  `guild.get_member(...)`, `guild.get_channel(...)`, `guild.create_text_channel(...)`. Every doc
  example using these breaks.
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

1. `grep -n "self\.app" hikari/guilds.py` → 0 after the pass.
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
