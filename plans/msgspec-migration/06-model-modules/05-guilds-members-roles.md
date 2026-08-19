# Guilds, members, roles

Purpose: migrate `hikari/guilds.py` — the largest model module (22 `@attrs.define` classes, 13
enums, ~2000-line `PartialGuild`/`Guild` hierarchy) and the top of the reference graph. It carries 3
`app` field declarations, ~55 app-delegating helper methods (the most of any module — 45 `self.app`
plus 10 `self.user.app` on `Member`; the `self\.app`-only grep's 45 was a floor), the
`Member(users.User, eq=False)` identity-delegation hazard, the `Role` color/colors sibling typing,
and the bespoke lazy `GatewayGuild` deserialization. It migrates last in this cluster (`00-README.md`
§3) because it depends on scalars, users, emojis, channels, permissions, and (forward) presences,
voices, stickers.

--------------------------------------------------------------------------------------------------

## 1. Objective

- Freeze all 22 guild Structs app-less; remove the 3 `app` fields (`GuildWidget.app`,
  `PartialRole.app`, `PartialGuild.app`) and re-home ~55 app-delegating helpers (45 `self.app` + 10
  `self.user.app` on `Member`) — a large share are
  cache getters with ownership/scope filters that have **no 1:1 rest equivalent**
  (`../03-app-removal-and-helpers/02-helper-method-inventory/03-guilds.md`,
  `../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md`).
- Keep the 13 enums as hikari's custom enums (adopt #2770); strict-type the many `Enum | int` /
  `Enum | str` guild fields, decoded via the shared `dec_hook`.
- Preserve `Member`'s identity-by-wrapped-user under `eq=False`, and its ~30 delegating properties.
- Preserve `Role`'s `color`/`colors` (+`colour`/`colours`) sibling typing and the `@everyone` mention.
- Keep the lazy `GatewayGuild` deserialization contract (or explicitly redesign it) —
  `../05-entity-factory/02-hard-cases-and-transforms.md`.

Decode classification: `PartialGuild`→`Guild`→`GatewayGuild`/`RESTGuild` are **T** (array→Mapping
re-keying of roles/emojis/stickers, flattened fields, lazy gateway definition, context injection of
`guild_id` into children). `Member` is **T** (context-injected `guild_id`/`user`, `role_ids`
@everyone append). `Role` is **T** (sibling `color`/`colors`, flattened `tags`). `PartialRole`,
`IntegrationAccount`, `GuildBan`, `BulkBanResponse`, `WelcomeChannel`, `GuildIncidents` are near-**D**.

--------------------------------------------------------------------------------------------------

## 2. Current state (file:line anchors)

### 2.1 Enums (13)
`GuildExplicitContentFilterLevel` `:89`, `GuildOnboardingMode` `:103`, `GuildOnboardingPromptType`
`:114`, `GuildFeature(str, enums.Enum)` `:125`, `GuildMessageNotificationsLevel` `:221`,
`GuildMFALevel` `:232`, `GuildPremiumTier` `:243`, `GuildSystemChannelFlag(enums.Flag)` `:260`,
`GuildVerificationLevel` `:280`, `GuildNSFWLevel` `:300`, `GuildMemberFlags(enums.Flag)` `:369`,
`IntegrationType(str, enums.Enum)` `:1319`, `IntegrationExpireBehaviour` `:1336`.

### 2.2 Members and roles
- `Member(users.User)` — `guilds.py:422-…`; `@attrs.define(eq=False, kw_only=True, weakref_slot=False)`.
  Fields: `guild_id: Snowflake` (`:426`), `is_deaf`/`is_mute`/`is_pending: UndefinedOr[bool]`
  (`:429-446`, tri-state), `joined_at: datetime | None` (`:448`), `nickname: str | None` (`:455`),
  `premium_since: datetime | None` (`:461`), `raw_communication_disabled_until: datetime | None`
  (`:467`), `role_ids: Sequence[Snowflake]` (`:478`), `user: users.User` (`:487`),
  `guild_avatar_decoration`/`guild_avatar_hash`/`guild_banner_hash`, `guild_flags: GuildMemberFlags`.
  ~30 **delegating properties** to `self.user`: `app` (`:514-518`, property, not a field),
  `primary_guild`, `avatar_decoration`, `avatar_hash`, `banner_hash`, `accent_color`, `discriminator`
  (`:568`), `flags` (`:590`), `id` (`:595`, returns `self.user.id`), `is_bot`/`is_system`, `mention`,
  `username`/`global_name`, plus **11 app-delegating helpers**: cache getters `get_guild`/
  `get_presence`/`get_roles` (`:641`/`:658`/`:673`) and derived `get_top_role` (`:675`),
  `fetch_self`/`fetch_roles` (`:862`/`:888`), and the 6 action helpers `ban`/`unban`/`kick`/
  `add_role`/`remove_role`/`edit` (`:925`/`:954`/`:981`/`:1011`/`:1041`/`:1120`). All but `fetch_roles`
  delegate through `self.user.app.(rest|cache)` (`fetch_dm_channel` at `:865` forwards to
  `self.user`), so a `self\.app` grep undercounts them.
- `PartialRole(snowflakes.Unique)` — `guilds.py:1146-1168`; `app` field (`:1150-1152`), `id`, `name`;
  `mention` (`:1161`), `__str__`.
- `Role(PartialRole)` — `guilds.py:1171-1315`; `color: Color` (`:1175`), `colors: ColorGradient`
  (`:1181`), `guild_id`, `is_hoisted`, `icon_hash`, `unicode_emoji: UnicodeEmoji | None`,
  `is_managed`, `is_mentionable`, `permissions: Permissions`, `position`, `bot_id`,
  `integration_id`, `is_premium_subscriber_role`, `subscription_listing_id`,
  `is_available_for_purchase`, `is_guild_linked_role`; `colour`/`colours` alias properties
  (`:1249-1257`), `mention` (@everyone special, `:1259-1270`), `make_icon_url` (`:1272-1315`, no app).

### 2.3 Guild hierarchy and value objects
- `GuildWidget` `:317` (`app`), `GuildIncidents` `:388`, `IntegrationAccount` `:1347`,
  `PartialApplication` `:1364`, `IntegrationApplication` `:1436`, `PartialIntegration` `:1445`,
  `Integration` `:1466`, `WelcomeChannel` `:1523` (**non-`kw_only`**, dossier 03 §2.1),
  `WelcomeScreen` `:1546`, `GuildOnboarding` `:1558`, `GuildOnboardingPromptOption(Unique)` `:1579`,
  `GuildOnboardingPrompt(Unique)` `:1603`, `GuildBan` `:1633`, `BulkBanResponse` `:1645`.
- `PartialGuild(snowflakes.Unique)` `:1660` — `app` field (`:1664`); base for the whole guild tree;
  ~30 cache/rest helpers (`get_channel`/`get_member`/`get_role`/`get_my_member`/`fetch_*`, dossier 04).
- `GuildPreview(PartialGuild)` `:2820`, `Guild(PartialGuild)` `:2943` — the bulk of the ~55 helpers
  (`get_members`/`get_channels`/`get_roles`/`get_emojis`/`get_stickers` map getters at `:3090-3171`,
  `get_channel`/`get_member`/`get_role`/`get_my_member` scalar getters at `:3331-3494`,
  `fetch_owner`/`fetch_*_channel` at `:3494-3660`).
- `RESTGuild(Guild)` `:3670`, `GatewayGuild(Guild)` `:3709` — adds `is_large: bool | None`,
  `joined_at: datetime | None`, `member_count: int | None` (gateway-only fields).

App declarations: `GuildWidget.app` `:321`, `PartialRole.app` `:1150`, `PartialGuild.app` `:1664`.
Lazy gateway: `deserialize_gateway_guild` returns `_GatewayGuildDefinition`
(`entity_factory.py:140-335`, interface ABC `api/entity_factory.py:63`) storing the raw payload and
deserializing channels/members/roles/emojis on demand with `guild_id=self.id` injected.

--------------------------------------------------------------------------------------------------

## 3. Target design

### 3.1 Enums — strict custom (adopt #2770)
The 11 int enums stay custom `int, enums.Enum`; `GuildFeature`/`IntegrationType` stay custom
`str, enums.Enum` (open-ended — new features/types appear); `GuildSystemChannelFlag`/`GuildMemberFlags`
stay the custom `enums.Flag`. #2770 mints an `is_unknown` pseudo-member on unknown values (int, str, or
flag bit) and drops the raw-type unions; each field decodes through the shared `dec_hook`
(`../02-enums/00-strategy-and-forward-compat.md`). Drop `| int`/`| str` on all guild enum fields
(`../02-enums/03-strict-enum-field-inventory.md`) — this module contributes the largest share of the
~150 tolerance unions (verification/notification/premium/nsfw/mfa levels, features, member flags).

### 3.2 Member → frozen Struct subclassing User, eq=False

```python
class Member(users.User, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    guild_id: snowflakes.Snowflake
    is_deaf: undefined.UndefinedOr[bool] = undefined.UNDEFINED    # tri-state (D5)
    is_mute: undefined.UndefinedOr[bool] = undefined.UNDEFINED
    is_pending: undefined.UndefinedOr[bool] = undefined.UNDEFINED
    joined_at: datetime.datetime | None
    nickname: str | None
    premium_since: datetime.datetime | None
    raw_communication_disabled_until: datetime.datetime | None
    role_ids: typing.Sequence[snowflakes.Snowflake]              # @everyone appended in factory (T)
    user: users.User
    guild_avatar_decoration: users.AvatarDecoration | None
    guild_avatar_hash: str | None
    guild_banner_hash: str | None
    guild_flags: GuildMemberFlags                               # was `| int`; strict
    # id / username / discriminator / flags / is_bot / ... : delegating @property to self.user (verbatim)
```

- **Identity delegation (the hazard, dossier 03 §5):** `Member` subclasses `User` with `eq=False`, so
  it inherits `User`'s `Unique`-based `__eq__`/`__hash__` (by `self.id`), and `Member.id` is a
  property returning `self.user.id` (`guilds.py:595`). This double-indirection (Member is a `User`
  **and** wraps a `user`) must survive: keep `eq=False` and the `id` property. **VERIFY** the
  `eq=False`+inherited-`Unique` result holds through **two** inheritance levels (User→Member), an
  extension of the conventions §2 experiment.
- `Member.app` (`:514-518`) is a **property** returning `self.user.app`, not a field — it vanishes when
  `User.app` is removed. All ~30 delegating properties port verbatim except `app`.
- The tri-state `is_deaf`/`is_mute`/`is_pending` get `default=undefined.UNDEFINED` (D5).
- `role_ids` gets the `guild_id` appended (the @everyone role) in the residual factory
  (`entity_factory.py:2153-2156`) — a **T** computed field.
- Member helper re-homing (11 app-delegating helpers: cache getters + client-side filters + 6 action
  helpers). Note: 10 of these delegate through **`self.user.app.(rest|cache)`** (the wrapped user's
  app; `Member.app` is a property, `guilds.py:514-518`), not `self.app` — only `fetch_roles` uses
  `self.app.rest`. Full inventory + recipes in
  `../03-app-removal-and-helpers/02-helper-method-inventory/03-guilds.md` §2.2/§3.8.

| Helper | Location | Re-home |
|---|---|---|
| `Member.get_roles`/`get_top_role` | `:673`/`:675` | per-`role_ids` `cache.get_role` walk (Strategy 3, `[]` degradation); `get_top_role` sorts the result by `position` |
| `Member.get_guild`/`get_presence` | `:641`/`:658` | `cache.get_guild(guild_id)`/`cache.get_presence(guild_id, user.id)` (Strategy 3, `None`) |
| `Member.fetch_roles` | `:888` | **client-side role filter — no 1:1 rest** → new rest method/free fn (dossier 04) |
| `Member.fetch_self`/`fetch_dm_channel` | `:862`/`:865` | `rest.fetch_member(guild_id, user.id)` / `self.user.fetch_dm_channel()` (re-homed in `02-users.md`) |
| `Member.ban`/`unban`/`kick` | `:925`/`:954`/`:981` | `rest.ban_user`/`rest.unban_user`/`rest.kick_user(guild_id, user.id, …)` (1:1) |
| `Member.add_role`/`remove_role` | `:1011`/`:1041` | `rest.add_role_to_member`/`rest.remove_role_from_member(guild_id, user.id, role, reason=)` (1:1) |
| `Member.edit` | `:1120` | `rest.edit_member(guild_id, user.id, …)` (1:1) |

### 3.3 Role → frozen Struct, sibling color/colors

```python
class PartialRole(snowflakes.Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    id: snowflakes.Snowflake        # NO app
    name: str
    @property
    def mention(self): return f"<@&{self.id}>"

class Role(PartialRole, frozen=True, kw_only=True, eq=False):
    color: colors.Color             # flat int on wire
    colors: colors.ColorGradient    # `colors` object on wire, OR built from flat `color` (T)
    guild_id: snowflakes.Snowflake
    is_hoisted: bool                # field(name="hoist")
    icon_hash: str | None           # field(name="icon")
    unicode_emoji: emojis.UnicodeEmoji | None
    is_managed: bool                # field(name="managed")
    is_mentionable: bool            # field(name="mentionable")
    permissions: permissions.Permissions
    position: int
    bot_id: snowflakes.Snowflake | None
    integration_id: snowflakes.Snowflake | None
    is_premium_subscriber_role: bool
    subscription_listing_id: snowflakes.Snowflake | None
    is_available_for_purchase: bool
    is_guild_linked_role: bool
    @property
    def colour(self): return self.color
    @property
    def colours(self): return self.colors
    @property
    def mention(self):  # @everyone special-case verbatim (guilds.py:1259-1270)
        return "@everyone" if self.guild_id == self.id else super().mention
```

- **Sibling typing (T, dossier 05 §3j):** `colors` is decoded from the `colors` object when present,
  else `ColorGradient.of(payload["color"])` from the flat int (`entity_factory.py:2216-2223`). Cannot
  be declarative — a residual transform builds `colors`. `color` itself is the flat int via the
  `Color` hook. `bot_id`/`integration_id`/`is_premium_subscriber_role`/etc. are hoisted out of the
  flattened `tags` object (`entity_factory.py:2199-2213`) — also **T**.
- `unicode_emoji` uses the `UnicodeEmoji` scalar hook.

### 3.4 Guild hierarchy → frozen Structs (app-less)

`PartialGuild`/`GuildPreview`/`Guild`/`RESTGuild`/`GatewayGuild` become frozen Structs; drop the
`PartialGuild.app` field. The guild-tree helpers (~44; `Member`'s 11 re-home separately in §3.2)
split into:
- **cache map getters** (`get_members`/`get_channels`/`get_roles`/`get_emojis`/`get_stickers`,
  `:3090-3171`) → `cache.get_*_view_for_guild(guild.id)`;
- **cache scalar getters** (`get_channel`/`get_member`/`get_role`, `:3331-3494`) → `cache.get_*`;
- **`Guild.get_my_member`** (`:3373`) — ownership-filtered cache getter, **no 1:1 rest** → new
  cache/free helper (dossier 04, conventions §8);
- **rest fetchers** (`fetch_owner`/`fetch_*_channel`/`fetch_emojis`/`fetch_roles`, `:2028-3660`) →
  `rest.*`.
Enumerated in `../03-app-removal-and-helpers/02-helper-method-inventory/03-guilds.md`.

Array→Mapping re-keying (`roles`/`emojis`/`stickers` → `Mapping[Snowflake, T]`) and `guild_id`
context injection into children are residual transforms (dossier 05 §§3f, 6.4) —
`../05-entity-factory/02-hard-cases-and-transforms.md`.

### 3.5 GatewayGuild lazy definition — preserve or redesign

`deserialize_gateway_guild` returns the lazy `_GatewayGuildDefinition` (interface ABC
`GatewayGuildDefinition`, `api/entity_factory.py:63`) so a large `GUILD_CREATE` is not deserialized
eagerly (channels/members/roles decoded on demand with `guild_id` injected). This has **no
declarative msgspec equivalent** and is antithetical to decode-everything-now. Recommendation
(settle in `../05-entity-factory/02-hard-cases-and-transforms.md` /
`../00-overview/05-decisions-log.md`): **preserve the lazy contract** — the lazy object holds
`msgspec.Raw` slices of the payload and decodes each collection on first access via the residual
factory, keeping the memory/CPU profile. The `GatewayGuild` Struct itself (with `is_large`/`joined_at`/
`member_count`) is frozen and built once the definition is realized. Eager decode is the simpler
fallback but regresses large-guild startup (dossier 05 §4 guild, §9 interface ripples).

### 3.6 WelcomeChannel — the non-kw_only exception

`WelcomeChannel` (`:1523`) is one of only 2 non-`kw_only` model classes (dossier 03 §2). Under the
mandatory `kw_only=True` Struct config (conventions §2) it becomes kw-only; verify no positional
construction site depends on the old ordering (grep the factory + tests).

--------------------------------------------------------------------------------------------------

## 4. Step-by-step migration

1. Adopt #2770 for the 13 enums — keep them custom, drop `| int`/`| str` on guild fields (`../02-enums/`).
2. Convert `PartialRole`/`Role` → frozen Structs; drop `PartialRole.app`; wire `color` (hook),
   `colors` (sibling **T**), flattened `tags` (**T**), `unicode_emoji` (hook); keep alias props and
   `@everyone` mention.
3. Convert `Member` → frozen Struct(User, eq=False); drop the `app` property; set tri-state defaults;
   keep the ~30 delegating properties; re-home its 11 app-delegating helpers — 6 action helpers +
   `fetch_self` to 1:1 `rest.*`, 3 cache getters to `cache.*`, `fetch_roles` to the client-side filter
   (§3.2); `role_ids` @everyone append stays a factory transform.
4. Convert `PartialGuild`→`GuildPreview`→`Guild`→`RESTGuild`/`GatewayGuild`; drop `PartialGuild.app`;
   re-home the ~44 guild-tree helpers (§3.4); make `WelcomeChannel` kw-only.
5. Preserve the lazy `GatewayGuild` definition using `msgspec.Raw` slices (§3.5) or accept eager decode.
6. Convert the remaining value objects (`GuildWidget` drop `app`, `GuildIncidents`,
   `IntegrationAccount`, `Integration*`, `WelcomeScreen`, `GuildOnboarding*`, `GuildBan`,
   `BulkBanResponse`).
7. Update all guild factory sites to stop injecting `app`; route re-keying/flatten/context-injection
   through the residual transform.

--------------------------------------------------------------------------------------------------

## 5. Affected files & symbols

| Path / anchor | Change |
|---|---|
| `hikari/guilds.py:89-1336` (enums) | 13 enums stay custom; adopt #2770 (strict fields, `is_unknown`) |
| `hikari/guilds.py:422-1120` (`Member`) | frozen Struct(User, eq=False); drop `app` property; tri-state; delegating props; re-home 11 helpers (6 action + `fetch_self` → `rest.*`, 3 cache getters → `cache.*`, `fetch_roles` client-side) — 10 delegate via `self.user.app` |
| `hikari/guilds.py:1146-1315` (`PartialRole`/`Role`) | frozen; drop `app`; color/colors sibling typing; flattened tags |
| `hikari/guilds.py:1660-3760` (guild tree) | frozen app-less; ~44 guild-tree helpers re-homed; lazy `GatewayGuild` |
| `hikari/guilds.py:317-1645` (value objects) | frozen Structs; `GuildWidget` drop `app`; `WelcomeChannel` kw-only |
| `hikari/impl/entity_factory.py:51-100,140-335,2140-2463` | drop `app`; `_GuildFields`, re-keying, `guild_id` injection, lazy def, `role_ids` @everyone, Role color/colors |
| `../03-app-removal-and-helpers/02-helper-method-inventory/03-guilds.md` | ~55 helper re-homing (45 `self.app` + 10 `self.user.app` on `Member`) |
| `../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md` | `Member.fetch_roles`, `Guild.get_my_member` |
| `../05-entity-factory/02-hard-cases-and-transforms.md` | re-keying, flatten, context injection, lazy guild |

--------------------------------------------------------------------------------------------------

## 6. Risks / gotchas

1. **Member identity through two levels.** `Member(User, eq=False)` must inherit `User`'s
   `Unique`-based identity, itself under `eq=False`, with `Member.id → self.user.id`. If msgspec sets
   `__hash__=None` under `eq=False` at either level, members become unhashable — a cache-breaking
   regression. This is the module's highest-risk item; VERIFY explicitly.
2. **Lazy GatewayGuild.** Naive eager msgspec decode of `GUILD_CREATE` regresses memory/CPU on large
   guilds (the whole reason the lazy definition exists). Preserve it with `msgspec.Raw` slices.
3. **Role color/colors sibling typing** and the **flattened `tags`** cannot be declarative — both are
   residual transforms; forgetting either yields wrong `colors`/`bot_id`/`is_premium_subscriber_role`.
4. **`role_ids` @everyone append** is a value not present in the payload (`entity_factory.py:2154`) —
   must stay a computed transform, not a declarative list.
5. **`WelcomeChannel` positional construction** — becoming kw-only may break internal/test callers.
6. **Massive helper surface (~55).** Many are cache getters with scope/ownership filters
   (`get_my_member`, `Member.fetch_roles`) that have no 1:1 rest method; these need new
   free-functions/rest-methods, not a mechanical delete (dossier 04, conventions §8).
7. **`Member.app` is a property, not a field** — its removal is coupled to `User.app` removal
   (`02-users.md`), not a field deletion here. Consequently `Member`'s 10 non-`fetch_roles` helpers
   delegate through `self.user.app.(rest|cache)`, which a `self\.app` grep misses — count them
   explicitly (11 helpers, not 1) or the module sizes at 45 instead of 55.

--------------------------------------------------------------------------------------------------

## 7. Verification

- **Member identity VERIFY:** construct two `Member` with the same `user.id` (differing other fields)
  → equal and equal-hash; frozen; hashable (works as a cache/dict key). Repeat with the wrapped user
  swapped for an equal-id user.
- Decode a guild role with a `colors` object → `Role.colors` is that gradient; with only flat `color`
  → `colors == ColorGradient.of(color)`; `colour`/`colours` aliases resolve; `@everyone` role
  (`guild_id == id`) mentions `"@everyone"`.
- Decode a member payload missing `deaf`/`mute` → those are `undefined.UNDEFINED`; `role_ids` includes
  `guild_id` (the @everyone role); tri-state distinct from `None`/`False`.
- **Lazy gateway:** deserialize a `GUILD_CREATE`; assert channels/members are not decoded until their
  accessor is called (retain the lazy contract test).
- Strict enums: unknown `verification_level`/`premium_tier` int → enum `is_unknown` pseudo-member;
  unknown `GuildFeature` string → `is_unknown` pseudo-member (forward-compat).
- Grep: `grep -nE "self\.(user\.)?app\.(rest|cache)" hikari/guilds.py` → 0 (the broadened regex is
  mandatory — a bare `self\.app` grep misses `Member`'s 10 `self.user.app` sites); the ~55 helpers
  resolve via `rest.*`/`cache.*`/new helpers.

--------------------------------------------------------------------------------------------------

## 8. Open questions / decisions

Cross-link `../00-overview/05-decisions-log.md`:

- **Member eq=False through two inheritance levels** (User→Member) — extend the conventions §2 VERIFY.
- **Lazy `GatewayGuild`:** preserve via `msgspec.Raw` slices (recommended) vs eager decode — settle in
  `../05-entity-factory/02-hard-cases-and-transforms.md`.
- **D9 / new-rest & cache helpers:** `Member.fetch_roles` (client-side role filter), `Guild.get_my_member`
  (ownership-filtered cache getter), guild-scoped cache getters — enumerate signatures in
  `../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md`.
- **D5:** Member tri-state (`is_deaf`/`is_mute`/`is_pending`) keeps `undefined.UNDEFINED` defaults.
- **`WelcomeChannel` kw-only** conversion — confirm no positional caller.
