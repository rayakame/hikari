# Monetization, stage instances, voices, templates, sessions

Purpose: migrate five small model modules bundled by size — `hikari/monetization.py`,
`hikari/stage_instances.py`, `hikari/voices.py`, `hikari/templates.py`, `hikari/sessions.py`. Together
they span the cleanest declarative cases in the whole migration (`VoiceRegion`, `SKU`/`Entitlement`),
three dead-`app` fields, one live-`app` module (templates, 4 helpers), two non-`Unique` identity
oddities, and the `sessions._created_at` factory-default field.

--------------------------------------------------------------------------------------------------

## 1. Objective

- Freeze all Structs across the five modules; drop the **dead** `app` fields (`StageInstance.app`
  `stage_instances.py:56`, `VoiceState.app` `voices.py:47`) with no helper re-homing, and drop
  `Template.app` (`templates.py:151`) while re-homing its **4 live** helpers.
- Keep the enums as hikari's custom `Enum`/`Flag` (adopt #2770 strict typing; unknown values become
  `is_unknown` pseudo-members via the shared `dec_hook`, `../02-enums/00-strategy-and-forward-compat.md`)
  and drop the `SKUType | int` / `EntitlementType | int` and the guild-enum `| int` unions inherited by
  `TemplateGuild`.
- Handle the two non-`Unique` identity oddities (`StageInstance` hashes by channel+guild; `VoiceState`
  hashes by `session_id`), the `TemplateGuild` array→Mapping re-keyings, and the `sessions._created_at`
  factory-default field.

Decode classification: `VoiceRegion`, `SKU`, `Entitlement` are **D** (flat scalars, nullable datetimes,
enums — the cleanest in the codebase, dossier 05 §9). `VoiceState` is **T** (context-injected
`guild_id`/`member`, `is_streaming` rename+default). `Template`/`TemplateGuild` are **T** (re-keyings,
nested source guild, timedelta). `StageInstance` is near-**D**. `SessionStartLimit`/`GatewayBotInfo` are
**T**/near-**D** (timedelta, factory `_created_at`).

--------------------------------------------------------------------------------------------------

## 2. monetization (`hikari/monetization.py`)

### 2.1 Current state
Enums `SKUType(int, enums.Enum)` `:39`, `SKUFlags(enums.Flag)` `:56`, `EntitlementType(int, enums.Enum)`
`:79`, `EntitlementOwnerType(int, enums.Enum)` `:108`. Models `SKU(snowflakes.Unique)` `:119` and
`Entitlement(snowflakes.Unique)` `:146`, both declared **plain** `@attrs.define(kw_only=True)` — **no
`unsafe_hash`** (dossier 03 §8). No `app` field.
- `SKU`: `id` (hash), `type: SKUType | int` `:129`, `application_id`, `name`, `slug`, `flags: SKUFlags`.
- `Entitlement`: `id` (hash), `sku_id`, `application_id`, `user_id: Snowflake | None`,
  `type: EntitlementType | int` `:161`, `is_deleted`, `is_consumed`, `starts_at: datetime | None`,
  `ends_at: datetime | None`, `guild_id: Snowflake | None`, `subscription_id: Snowflake | None`.

### 2.2 Target design
```python
class SKU(snowflakes.Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    id: snowflakes.Snowflake
    type: SKUType                       # was `| int`
    application_id: snowflakes.Snowflake
    name: str
    slug: str
    flags: SKUFlags

class Entitlement(snowflakes.Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    id: snowflakes.Snowflake
    sku_id: snowflakes.Snowflake
    application_id: snowflakes.Snowflake
    user_id: snowflakes.Snowflake | None = None
    type: EntitlementType               # was `| int`
    is_deleted: bool                    # field(name="deleted")
    is_consumed: bool                   # field(name="consumed")
    starts_at: datetime.datetime | None = None
    ends_at: datetime.datetime | None = None
    guild_id: snowflakes.Snowflake | None = None
    subscription_id: snowflakes.Snowflake | None = None
```
- **Identity fix (behaviour note).** Because the attrs classes have neither `unsafe_hash` nor per-field
  `hash=True`, attrs today generates an **all-field `__eq__`** and sets `__hash__ = None` (unhashable),
  overriding the `Unique` id-only dunders — an inconsistency with every other `Unique` entity. The
  msgspec `eq=False` + `Unique` base makes them **id-only and hashable**, matching the rest of the
  library. Arguably a fix; flag as an intentional behaviour change (`../00-overview/05-decisions-log.md`).
- Nullable RFC3339 `starts_at`/`ends_at` decode natively. **D** apart from the `is_*`/`type` renames.

--------------------------------------------------------------------------------------------------

## 3. stage_instances (`hikari/stage_instances.py`)

### 3.1 Current state
Enum `StageInstancePrivacyLevel(int, enums.Enum)` `:39`. `StageInstance(snowflakes.Unique)` `:50`,
`@attrs.define(unsafe_hash=True)`. **Identity oddity:** `id` is `eq=False, hash=False` `:53`, while
`channel_id` `:61` and `guild_id` `:64` are `hash=True` — so today it hashes by **(channel_id, guild_id)**,
not `id`. Fields: `app` `:56` (**dead**), `topic`, `privacy_level`, `discoverable_disabled`,
`scheduled_event_id: SnowflakeishOr[ScheduledEvent] | None`. No `self.app` helper (dead-`app` module).

### 3.2 Target design
```python
class StageInstance(snowflakes.Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    id: snowflakes.Snowflake
    channel_id: snowflakes.Snowflake
    guild_id: snowflakes.Snowflake
    topic: str
    privacy_level: StageInstancePrivacyLevel
    discoverable_disabled: bool
    scheduled_event_id: snowflakes.Snowflake | None = None
    # NO app
```
- **Identity decision.** Porting to the `Unique` `eq=False` base changes identity from
  `(channel_id, guild_id)` to `id`. For a stage instance the `id` is the natural key, so this is a
  reasonable normalisation, but it **is** a behaviour change — flag it. If channel+guild identity must be
  preserved, hand-write `__eq__`/`__hash__` over `(channel_id, guild_id)` instead.
- near-**D**: flat scalars + one enum + nullable id.

--------------------------------------------------------------------------------------------------

## 4. voices (`hikari/voices.py`)

### 4.1 Current state
`VoiceState` `:44` (`@attrs.define(unsafe_hash=True)`, **not** `Unique`; identity by `session_id`
(`hash=True` `:97`)) — `app` `:47` (**dead**), `channel_id: Snowflake | None`, `guild_id`, 6 `is_*` bools,
`user_id`, `member: Member | None`, `session_id`, `requested_to_speak_at: datetime | None`. No `self.app`
helper. `VoiceRegion` `:109` (`unsafe_hash=True`, not `Unique`; identity by `id: str`) — `id` (str, hash),
`name`, `is_optimal_location`, `is_deprecated`, `is_custom`; `__str__` → `id`.
- Factory: `deserialize_voice_state` (context kwargs `guild_id`/`member`; `is_streaming =
  payload.get("self_stream", False)`, dossier 05 §4).

### 4.2 Target design
```python
class VoiceRegion(msgspec.Struct, frozen=True, kw_only=True):          # D — the cleanest model (dossier 05 §9)
    id: str
    name: str
    is_optimal_location: bool = msgspec.field(name="optimal")
    is_deprecated: bool = msgspec.field(name="deprecated")
    is_custom: bool = msgspec.field(name="custom")
    def __str__(self) -> str: return self.id

class VoiceState(msgspec.Struct, frozen=True, kw_only=True):           # T
    channel_id: snowflakes.Snowflake | None = None
    guild_id: snowflakes.Snowflake        # T: context-injected
    is_guild_deafened: bool = msgspec.field(name="deaf")
    is_guild_muted: bool = msgspec.field(name="mute")
    is_self_deafened: bool = msgspec.field(name="self_deaf")
    is_self_muted: bool = msgspec.field(name="self_mute")
    is_streaming: bool = msgspec.field(name="self_stream", default=False)   # rename + default
    is_suppressed: bool = msgspec.field(name="suppress")
    is_video_enabled: bool = msgspec.field(name="self_video")
    user_id: snowflakes.Snowflake
    member: guilds.Member | None = None   # T: context-injected
    session_id: str
    requested_to_speak_at: datetime.datetime | None = None
    # NO app
```
- **Identity (non-`Unique`).** `VoiceState` hashes by `session_id`, `VoiceRegion` by `id` (str). Neither
  is `Unique`; preserve via hand-written `__eq__`/`__hash__` (over `session_id` / `id`) or accept
  msgspec's default all-field `eq` (fine for `VoiceRegion`; for `VoiceState` the all-field variant would
  break on the nested `member`). Recommend a small `session_id`/`id`-keyed dunder pair; flag it.
- `VoiceState` is **T** only for the `guild_id`/`member` context injection (dossier 05 §4); the `is_*`
  renames and the `self_stream` default are declarative.

--------------------------------------------------------------------------------------------------

## 5. templates (`hikari/templates.py`)

### 5.1 Current state
`TemplateRole(guilds.PartialRole)` `:49` — `permissions: Permissions`, `color: Color`, `is_hoisted`,
`is_mentionable`. `TemplateGuild(guilds.PartialGuild)` `:76` — `description`,
`verification_level: GuildVerificationLevel | int`, `default_message_notifications:
GuildMessageNotificationsLevel | int`, `explicit_content_filter: GuildExplicitContentFilterLevel | int`,
`preferred_locale: str`, `afk_timeout: timedelta`, `roles: Mapping[Snowflake, TemplateRole]`,
`channels: Mapping[Snowflake, GuildChannel]`, `afk_channel_id`, `system_channel_id`,
`system_channel_flags: GuildSystemChannelFlag`. `Template` `:148` — `app` `:151` (**live**), `code`
(hash), `name`, `description`, `usage_count`, `creator: User`, `created_at`, `updated_at`,
`source_guild: TemplateGuild`, `is_unsynced`; **4 live helpers**: `fetch_self` `:183`, `edit` `:205`,
`delete` `:241`, `sync` `:260` (all `self.app.rest.*`), plus `__str__` → `https://discord.new/{code}`.
- Factory: `deserialize_template` `entity_factory.py:4378` — inline `TemplateRole` build with
  unique-placeholder ids `:4391`, array→Mapping re-key of `roles` `:4389` and `channels` `:4402`,
  `guild_id` from `source_guild_id` (not on the guild object) `:4381`.

### 5.2 Target design
```python
class TemplateRole(guilds.PartialRole, frozen=True, kw_only=True, eq=False):     # near-D; PartialRole drops app upstream
    permissions: permissions.Permissions      # str-bitmask hook
    color: colors.Color                        # int hook
    is_hoisted: bool = msgspec.field(name="hoist")
    is_mentionable: bool = msgspec.field(name="mentionable")

class TemplateGuild(guilds.PartialGuild, frozen=True, kw_only=True, eq=False):   # T
    description: str | None
    verification_level: guilds.GuildVerificationLevel        # strict
    default_message_notifications: guilds.GuildMessageNotificationsLevel
    explicit_content_filter: guilds.GuildExplicitContentFilterLevel
    preferred_locale: str
    afk_timeout: datetime.timedelta            # seconds hook
    roles: typing.Mapping[snowflakes.Snowflake, TemplateRole]      # T: array→Mapping
    channels: typing.Mapping[snowflakes.Snowflake, channels.GuildChannel]  # T: array→Mapping
    afk_channel_id: snowflakes.Snowflake | None
    system_channel_id: snowflakes.Snowflake | None
    system_channel_flags: guilds.GuildSystemChannelFlag

class Template(msgspec.Struct, frozen=True, kw_only=True, eq=False):
    code: str
    name: str
    description: str | None
    usage_count: int
    creator: users.User
    created_at: datetime.datetime
    updated_at: datetime.datetime
    source_guild: TemplateGuild
    is_unsynced: bool
    def __str__(self) -> str: return f"https://discord.new/{self.code}"
    # NO app; fetch_self/edit/delete/sync removed
```
- `TemplateRole`/`TemplateGuild` subclass the app-less `PartialRole`/`PartialGuild`
  (`05-guilds-members-roles.md`); drop the guild-enum `| int` unions.
- **`Template` identity by `code`** (the sole `hash=True`, not `Unique`) — `eq=False` drops to object
  identity; hand-write `__eq__`/`__hash__` over `code` (mirrors invites, `12-invites.md`).
- **T** on `TemplateGuild`: the `roles`/`channels` array→Mapping re-keyings and the placeholder-id inline
  role build stay in the residual factory (`entity_factory.py:4389-4406`;
  `../05-entity-factory/02-hard-cases-and-transforms.md`). `afk_timeout` needs the seconds hook.
- **4 live helpers** re-home (each has a 1:1 rest method — straight delete + `rest.*`
  (`../03-app-removal-and-helpers/02-helper-method-inventory/05-templates-presences-commands.md`)):

| Helper | Location | Re-home |
|---|---|---|
| `Template.fetch_self` | `:183` | `rest.fetch_template(t.code)` |
| `Template.edit` | `:205` | `rest.edit_template(t.source_guild, t, name=…, description=…)` |
| `Template.delete` | `:241` | `rest.delete_template(t.source_guild, t)` |
| `Template.sync` | `:260` | `rest.sync_guild_template(t.source_guild.id, t.code)` |

--------------------------------------------------------------------------------------------------

## 6. sessions (`hikari/sessions.py`)

### 6.1 Current state
`SessionStartLimit` `:40` — `total`, `remaining`, `reset_after: timedelta`, `max_concurrency`,
`_created_at: datetime = attrs.field(factory=time.local_datetime, init=False)` `:66`; properties
`used` `:68`, `reset_at` (`_created_at + reset_after`) `:73`. `GatewayBotInfo` `:81` — `url`,
`shard_count`, `session_start_limit: SessionStartLimit`. No `app`.

### 6.2 Target design
```python
class SessionStartLimit(msgspec.Struct, frozen=True, kw_only=True):
    total: int
    remaining: int
    reset_after: datetime.timedelta        # millis hook (per-field)
    max_concurrency: int
    _created_at: datetime.datetime = msgspec.field(default_factory=time.local_datetime)
    @property
    def used(self) -> int: return self.total - self.remaining
    @property
    def reset_at(self) -> datetime.datetime: return self._created_at + self.reset_after

class GatewayBotInfo(msgspec.Struct, frozen=True, kw_only=True):   # near-D
    url: str
    shard_count: int
    session_start_limit: SessionStartLimit
```
- **`_created_at` factory field.** The wire never sends `_created_at`; it is stamped at construction via
  `time.local_datetime` (`sessions.py:66`). msgspec has no `init=False`, but a
  `msgspec.field(default_factory=time.local_datetime)` runs the factory when the key is absent — the
  decoder never sees `_created_at`, so the factory fires on every decode, reproducing the behaviour.
  **VERIFY** msgspec accepts a leading-underscore field name; if not, rename to a plain field (there is
  no public `created_at` property today, so a rename is low-risk) or expose it via a property.
- `reset_after` is a bare number (milliseconds) on the wire — not ISO8601 duration; use the per-field
  timedelta hook (`../01-foundations/02-custom-scalar-types-and-hooks.md`).

--------------------------------------------------------------------------------------------------

## 7. Step-by-step migration (all five modules)

1. Adopt #2770's strict custom enums (keep custom `Enum`/`Flag`); drop `SKUType | int`,
   `EntitlementType | int`, and the `TemplateGuild` guild-enum `| int` unions.
2. monetization: convert `SKU`/`Entitlement` to frozen `Unique`/`eq=False` Structs (id-only identity —
   the behaviour fix); add `is_deleted`/`is_consumed`/`type` renames.
3. stage_instances: convert `StageInstance`; drop the **dead** `app`; settle the id-vs-(channel,guild)
   identity decision.
4. voices: convert `VoiceRegion` (D) and `VoiceState` (drop **dead** `app`, `is_*` renames, `self_stream`
   default, `guild_id`/`member` context injection); settle `session_id`/`id` identity.
5. templates: convert `TemplateRole`/`TemplateGuild` (subclassing app-less `PartialRole`/`PartialGuild`;
   re-keyings **T**; `afk_timeout` hook); convert `Template` (drop `app`, `code`-keyed identity, re-home
   the 4 helpers).
6. sessions: convert `SessionStartLimit` (`_created_at` `default_factory`; `reset_after` hook) and
   `GatewayBotInfo`.
7. Update the corresponding factory sites (`deserialize_entitlement` `entity_factory.py:4686`,
   `deserialize_voice_state` `:4545`, `deserialize_voice_region` `:4589`, `deserialize_stage_instance`
   `:1745`, `deserialize_template` `:4378`, `deserialize_gateway_bot_info` `:2028`) to stop injecting
   `app` where present.

--------------------------------------------------------------------------------------------------

## 8. Affected files & symbols

| Path / anchor | Change |
|---|---|
| `hikari/monetization.py:39-185` | 4 enums stay custom (#2770 strict typing); `SKU`/`Entitlement` frozen `Unique`/`eq=False` (id-only fix); renames |
| `hikari/stage_instances.py:39-80` | enum stays custom (#2770 strict typing); `StageInstance` frozen; drop dead `app`; identity decision |
| `hikari/voices.py:44-135` | `VoiceState` (drop dead `app`, `is_*` renames, context inject) + `VoiceRegion` (D); identity |
| `hikari/templates.py:49-287` | `TemplateRole`/`TemplateGuild` (re-keyings **T**, hooks); `Template` drop `app`, `code` identity, re-home 4 helpers |
| `hikari/sessions.py:40-92` | `SessionStartLimit` (`_created_at` factory, `reset_after` hook) + `GatewayBotInfo` |
| `hikari/impl/entity_factory.py:1745,2028,4378-4409,4545,4589,4686` | drop `app`; template re-keyings; voice context injection |
| `../03-app-removal-and-helpers/01-app-field-removal.md` | 2 dead (`StageInstance`, `VoiceState`) + 1 live (`Template`) app fields |
| `../03-app-removal-and-helpers/02-helper-method-inventory/05-templates-presences-commands.md` | the 4 `Template` helpers |
| `../05-entity-factory/02-hard-cases-and-transforms.md` | template re-keyings, voice/member context injection |
| `05-guilds-members-roles.md`, `02-users.md`, `04-channels.md`, `17-scheduled-events.md` | referenced base/entity types |

--------------------------------------------------------------------------------------------------

## 9. Risks / gotchas

1. **monetization identity change.** `SKU`/`Entitlement` currently get attrs all-field `eq` + unhashable
   (no `unsafe_hash`), diverging from the id-only norm. The msgspec `Unique`/`eq=False` base makes them
   id-only + hashable — arguably a fix, but a **behaviour change**; flag it.
2. **stage_instances identity change.** Currently hashes by `(channel_id, guild_id)` (id excluded); the
   `Unique` base switches it to `id`. Decide which key is intended and preserve deliberately.
3. **Non-`Unique` identities** in voices (`session_id`, `id`), templates (`code`), sessions (value
   objects) — `eq=False` drops to object identity; hand-write dunders where a stable key matters (esp.
   `VoiceState.session_id`, since all-field `eq` would recurse into the nested `member`).
4. **`_created_at` factory field** — map to `default_factory=time.local_datetime`; VERIFY leading-`_`
   field-name acceptance or rename.
5. **Template re-keyings + placeholder ids** — `roles`/`channels` array→Mapping and the placeholder-id
   inline role build stay residual transforms; `guild_id` comes from `source_guild_id`, not the guild
   object.
6. **Timedelta units differ** — `afk_timeout` (seconds), `reset_after` (millis); each needs the correct
   per-field hook, not msgspec native timedelta.
7. **Template is live-`app`** — its 4 helpers must be re-homed; stage_instances/voices are dead-`app`
   (drop cleanly).

--------------------------------------------------------------------------------------------------

## 10. Verification

- monetization: decode an `SKU`/`Entitlement` → id-only identity, hashable as a cache key; nullable
  `starts_at`/`ends_at` present-or-`None`; `deleted`→`is_deleted` maps.
- stage_instances: decode → identity per the chosen key; nullable `scheduled_event_id`.
- voices: decode a `VoiceRegion` (pure declarative, no hooks beyond renames); decode a `VoiceState`
  missing `self_stream` → `is_streaming is False`; `guild_id`/`member` threaded from context; identity by
  `session_id`.
- templates: decode a `Template` → `roles`/`channels` are snowflake-keyed mappings; `afk_timeout` a
  `timedelta`; identity by `code`; the 4 helpers resolve via `rest.*`.
- sessions: decode a `GatewayBotInfo` → `_created_at` stamped via `time.local_datetime`;
  `reset_at == _created_at + reset_after`; `used == total - remaining`.
- Strict enums: unknown `SKUType`/`EntitlementType`/guild-level int → pseudo-member.
- Grep: no `self.app` in stage_instances/voices/templates; no `app=` construction for these entities.

--------------------------------------------------------------------------------------------------

## 11. Open questions / decisions

Cross-link `../00-overview/05-decisions-log.md`:
- **monetization id-only identity** (behaviour change from attrs all-field `eq`/unhashable) — confirm the
  fix is intended.
- **stage_instances identity** — `id` (via `Unique`) vs the current `(channel_id, guild_id)`.
- **Non-`Unique` identity dunders** — `VoiceState.session_id`, `VoiceRegion.id`, `Template.code`
  (mirrors invites) — hand-written vs default `eq`.
- **`_created_at`** — `default_factory` field; VERIFY leading-`_` name or rename.
- **Per-field timedelta hooks** (`afk_timeout` seconds, `reset_after` millis) —
  `../01-foundations/02-custom-scalar-types-and-hooks.md`.
- **D9:** the 4 `Template` helpers re-home to `rest.*`; stage_instances/voices dead-`app` drop cleanly.
