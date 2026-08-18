# Presences and activities

Purpose: migrate `hikari/presences.py` — 3 enums and 9 value/wire models split across the
inbound/outbound divide: `RichActivity` (received) vs `Activity` (the set-presence builder), plus the
`ActivityTimestamps`/`ActivityParty`/`ActivityAssets`/`ActivitySecret` pieces, `ClientStatus`, and
`MemberPresence`. The standout hazards are **unix-epoch timestamps** (JSON numbers, not RFC3339), the
`[current, max]` party-size tuple, the `_application_id` context-injected alias, per-platform `Status`
defaulting, and the polymorphic `emoji`.

--------------------------------------------------------------------------------------------------

## 1. Objective

- Freeze all presence Structs; drop `MemberPresence.app` (`presences.py:423`) and re-home its 2 live
  helpers (`fetch_user`, `fetch_member`) to `rest.*`
  (`../03-app-removal-and-helpers/02-helper-method-inventory/05-templates-presences-commands.md`) — this
  is **not** a dead-`app` module (conventions §8).
- Port the 3 enums to stdlib (`ActivityType` → `int, enum.Enum`; `ActivityFlag` → `IntFlag`;
  `Status` → `str, enum.Enum`) and drop the `Status | str` tolerance on `visible_status`/`ClientStatus`.
- Route the unix-epoch datetimes (`created_at`, `timestamps.start/end`) through
  `time.unix_epoch_to_datetime` — **not** msgspec native RFC3339 decode.
- Preserve the `[current, max]` party-size tuple unpack, the `ActivityAssets` `_application_id`
  context injection, per-platform `Status.OFFLINE` defaulting, and the `Activity`-vs-`RichActivity`
  outbound/inbound split.

Decode classification: `MemberPresence`, `RichActivity`, `ActivityTimestamps`, `ActivityParty`,
`ActivityAssets` are **T** (epoch datetimes, tuple split, context injection, polymorphic emoji,
`guild_id`/`user_id` threading). `ActivitySecret` is **D**; `ClientStatus` is near-**D** (per-platform
default). `Activity` is the **outbound builder** (D11-adjacent — user-constructed, serialized TO Discord).

--------------------------------------------------------------------------------------------------

## 2. Current state (file:line anchors)

### 2.1 Enums
`ActivityType(int, enums.Enum)` `presences.py:61`; `ActivityFlag(enums.Flag)` `presences.py:284`
(9 bits, INSTANCE…EMBEDDED); `Status(str, enums.Enum)` `presences.py:387` (online/idle/dnd/offline).

### 2.2 Value objects
- `ActivityTimestamps` `presences.py:95` — `start`/`end: datetime | None` (**unix-epoch numbers**,
  `entity_factory.py:4157-4161`). Not `Unique`.
- `ActivityParty` `presences.py:107` — `id: str | None` (hash), `current_size`/`max_size: int | None`.
  Built from the `[current, max]` array unpacked positionally (`entity_factory.py:4175-4180`).
- `ActivityAssets` `presences.py:123` — `_application_id: Snowflake | None` (`alias="application_id"`)
  `:128`, `large_image`/`large_text`/`small_image`/`small_text`. `_make_asset_url` `:142` uses
  `self._application_id`. The `_application_id` is **not in the assets payload** — the factory injects it
  from the parent activity (`entity_factory.py:4190`).
- `ActivitySecret` `presences.py:270` — `join`/`spectate`/`match: str | None`.

### 2.3 Activities
- `Activity` `presences.py:321` (**outbound builder**) — `name`, `state`, `url`,
  `type: ActivityType | int = attrs.field(converter=ActivityType, default=PLAYING)` `:340`; `__str__`.
- `RichActivity(Activity)` `presences.py:349` (**inbound**) — `created_at` (**unix epoch**,
  `entity_factory.py:4216`), `timestamps`, `application_id`, `details`, `emoji: Emoji | None`, `party`,
  `assets`, `secrets`, `is_instance`, `flags: ActivityFlag | None`, `buttons: Sequence[str]`.

### 2.4 ClientStatus and MemberPresence
- `ClientStatus` `presences.py:405` — `desktop`/`mobile`/`web: Status | str`. Each defaults to
  `Status.OFFLINE` when the wire omits the platform (`entity_factory.py:4232-4247`).
- `MemberPresence` `presences.py:420` — `app` `:423`, `user_id` (hash) `:428`, `guild_id` (hash) `:431`,
  `visible_status: Status | str` `:434`, `activities: Sequence[RichActivity]` `:437`,
  `client_status: ClientStatus` `:444`. Helpers `fetch_user` `:447` (`self.app.rest.fetch_user`),
  `fetch_member` `:469` (`self.app.rest.fetch_member`).
- Factory: `deserialize_member_presence` `entity_factory.py:4146` (the whole manual traversal:
  epoch timestamps `:4157`, party tuple `:4175`, assets `_application_id` inject `:4190`, polymorphic
  emoji `:4207`, per-platform status `:4232`, `buttons or []` `:4227`, `guild_id` context `:4252`).

--------------------------------------------------------------------------------------------------

## 3. Target design

### 3.1 Enums → stdlib
`ActivityType` → `int, enum.Enum` + `_missing_`; `Status` → `str, enum.Enum` + `_missing_`;
`ActivityFlag` → `IntFlag` + set-API mixin. Drop `ActivityType | int` and the `Status | str` unions on
`visible_status`/`ClientStatus.*` (`../02-enums/03-strict-enum-field-inventory.md`).

### 3.2 Unix-epoch datetimes (the headline gotcha, dossier 09 §2.4)
`created_at`, `timestamps.start`, `timestamps.end` are JSON **numbers** (unix millis), not RFC3339
strings — msgspec native `datetime` decode errors on them. They must bypass native decode via a
per-field hook (`Annotated[datetime, "unix_millis"]`) or an `int`/`float` field converted in the
residual factory, keeping `time.unix_epoch_to_datetime` (incl. its `datetime.max/min` clamping,
`time.py:138-167`). See `../01-foundations/02-custom-scalar-types-and-hooks.md`.

### 3.3 Value objects
```python
class ActivityTimestamps(msgspec.Struct, frozen=True, kw_only=True):
    start: Annotated[datetime.datetime, "unix_millis"] | None = None   # T: epoch number
    end:   Annotated[datetime.datetime, "unix_millis"] | None = None

class ActivityParty(msgspec.Struct, frozen=True, kw_only=True):
    id: str | None = None
    current_size: int | None = None      # T: from size[0]
    max_size: int | None = None          # T: from size[1]

class ActivityAssets(msgspec.Struct, frozen=True, kw_only=True):
    application_id: snowflakes.Snowflake | None = None   # renamed from _application_id; T (context-injected)
    large_image: str | None = None
    large_text: str | None = None
    small_image: str | None = None
    small_text: str | None = None
    # _make_asset_url / make_large_image_url / make_small_image_url: verbatim, reading self.application_id

class ActivitySecret(msgspec.Struct, frozen=True, kw_only=True):   # D
    join: str | None = None
    spectate: str | None = None
    match: str | None = None
```
- **`_application_id` alias → `application_id` plain field (conventions §2 / dossier 03 §6.1 option 1).**
  The attrs `alias="application_id"` already makes the constructor kwarg `application_id`, so renaming the
  attribute drops the underscore with **zero** call-site churn; update `_make_asset_url` to read
  `self.application_id`. It stays **T**: the value is threaded from the parent activity, not present in the
  assets JSON.
- The `[current, max]` **party tuple** cannot be split declaratively — `size` decodes as
  `tuple[int, int] | None` on a wire Struct, and the residual factory unpacks it into
  `current_size`/`max_size` (dossier 05 §3f/§6; `../05-entity-factory/02-hard-cases-and-transforms.md`).
- These value objects are not `Unique`; accept msgspec's default all-field `eq` (immutable scalar records).

### 3.4 Activity (outbound) vs RichActivity (inbound)
```python
class Activity(msgspec.Struct, frozen=True, kw_only=True):     # outbound builder
    name: str
    state: str | None = None
    url: str | None = None
    type: ActivityType = ActivityType.PLAYING     # converter dropped (see gotcha)
    def __str__(self) -> str: return self.name

class RichActivity(Activity, frozen=True, kw_only=True):        # inbound (T)
    created_at: Annotated[datetime.datetime, "unix_millis"]     # epoch number
    timestamps: ActivityTimestamps | None = None
    application_id: snowflakes.Snowflake | None = None
    details: str | None = None
    emoji: emojis.CustomEmoji | emojis.UnicodeEmoji | None = None   # polymorphic by key presence
    party: ActivityParty | None = None
    assets: ActivityAssets | None = None
    secrets: ActivitySecret | None = None
    is_instance: bool | None = None                # field(name="instance")
    flags: ActivityFlag | None = None
    buttons: typing.Sequence[str] = ()             # `or []` default
```
- **`Activity` is the outbound builder** (dossier 03 §4.2): it is constructed by the user and serialized
  into the set-presence payload; only `RichActivity` is decoded. Keeping `Activity` frozen is fine — but
  the attrs `converter=ActivityType` on `type` has **no msgspec equivalent**. msgspec `__init__` does not
  run converters, so `Activity(type=0)` would store a bare `0`. Preserve the caller ergonomics via the
  method-parameter lenience path (conventions §3, orthogonal to decode) or a classmethod/`__post_init__`
  normalisation; document that `type` should be an `ActivityType`. On encode use `int(type)`.
- **Polymorphic `emoji`** — a reaction/status emoji is a `CustomEmoji` when it has an `id`, else a
  `UnicodeEmoji` (`deserialize_emoji`, `entity_factory.py:4207` → key-presence dispatch, dossier 05 §6).
  This is discriminated by **presence of `id`**, not a tag field, so it stays a residual dispatch
  (`03-emojis-and-files-resources.md`, `../05-entity-factory/02-hard-cases-and-transforms.md`).

### 3.5 ClientStatus, MemberPresence
```python
class ClientStatus(msgspec.Struct, frozen=True, kw_only=True):   # near-D
    desktop: Status = Status.OFFLINE     # per-platform default when key absent (declarative default)
    mobile:  Status = Status.OFFLINE
    web:     Status = Status.OFFLINE

class MemberPresence(msgspec.Struct, frozen=True, kw_only=True, eq=False):
    user_id: snowflakes.Snowflake        # from payload["user"]["id"] (T context)
    guild_id: snowflakes.Snowflake       # T: gateway-injected
    visible_status: Status               # field(name="status"); was `| str`
    activities: typing.Sequence[RichActivity] = ()
    client_status: ClientStatus
    # NO app; fetch_user / fetch_member removed
```
- `ClientStatus`' per-platform "default OFFLINE when key absent" becomes a declarative field default —
  msgspec produces the default on an absent key, matching `entity_factory.py:4232-4247` exactly.
- `MemberPresence` identity is by `(user_id, guild_id)` today (both `hash=True`, and it is **not**
  `Unique`). Under `eq=False` the Struct falls back to object identity; hand-write `__eq__`/`__hash__`
  over `(user_id, guild_id)` to preserve cache/dict semantics, or accept object identity (flag it).
- `user_id` is `payload["user"]["id"]` (a nested-object field) and `guild_id` is gateway-injected — both
  **T** context threads; `MemberPresence` is not declaratively decodable as-is.

### 3.6 MemberPresence helper re-homing (2 live helpers)
| Helper | Location | Re-home |
|---|---|---|
| `MemberPresence.fetch_user` | `presences.py:447` | `rest.fetch_user(presence.user_id)` |
| `MemberPresence.fetch_member` | `presences.py:469` | `rest.fetch_member(presence.guild_id, presence.user_id)` |

Both have 1:1 rest equivalents — straight delete + caller uses `rest.*`
(`../03-app-removal-and-helpers/02-helper-method-inventory/05-templates-presences-commands.md`).

--------------------------------------------------------------------------------------------------

## 4. Step-by-step migration

1. Port the 3 enums to stdlib; drop `ActivityType | int` and `Status | str` unions.
2. Convert the 4 value objects to frozen Structs; rename `_application_id`→`application_id`; set up the
   unix-epoch hook for `ActivityTimestamps`; keep the party-tuple split as a residual transform.
3. Convert `Activity`/`RichActivity`; drop the `type` converter (document the input-lenience path); wire
   the `created_at` epoch hook, polymorphic `emoji`, `is_instance` rename, and `buttons` default.
4. Convert `ClientStatus` (per-platform `Status.OFFLINE` defaults) and `MemberPresence`; drop `app`;
   add the `(user_id, guild_id)` identity; keep `visible_status` rename.
5. Re-home `fetch_user`/`fetch_member` to `rest.*`; delete the `self.app.rest.*` bodies.
6. Keep `deserialize_member_presence` as the residual transform (epoch conversions, party unpack, assets
   `application_id` injection, per-platform status, `guild_id`/`user_id` threading); stop injecting `app`.

--------------------------------------------------------------------------------------------------

## 5. Affected files & symbols

| Path / anchor | Change |
|---|---|
| `hikari/presences.py:61,284,387` (enums) | 3 enums → stdlib; strict fields |
| `hikari/presences.py:95-117` (`ActivityTimestamps`/`ActivityParty`) | frozen Structs; epoch hook; tuple-split **T** |
| `hikari/presences.py:123-171` (`ActivityAssets`) | frozen; `_application_id`→`application_id` (context **T**); `_make_asset_url` update |
| `hikari/presences.py:270-281` (`ActivitySecret`) | frozen Struct (**D**) |
| `hikari/presences.py:321-383` (`Activity`/`RichActivity`) | frozen; drop `type` converter; epoch `created_at`; polymorphic `emoji`; defaults |
| `hikari/presences.py:405-445` (`ClientStatus`/`MemberPresence`) | frozen; per-platform defaults; drop `app`; `(user_id,guild_id)` identity |
| `hikari/impl/entity_factory.py:4146-4256` | residual transform: epoch, party unpack, assets inject, per-platform status, context threading; drop `app` |
| `../03-app-removal-and-helpers/02-helper-method-inventory/05-templates-presences-commands.md` | `fetch_user`/`fetch_member` |
| `../05-entity-factory/02-hard-cases-and-transforms.md` | epoch datetimes, party tuple, context injection, polymorphic emoji |
| `03-emojis-and-files-resources.md`, `02-users.md`, `05-guilds-members-roles.md` | emoji/user/member reference types |

--------------------------------------------------------------------------------------------------

## 6. Risks / gotchas

1. **Unix-epoch datetimes** (`created_at`, `timestamps.start/end`) are JSON **numbers** — routing them
   through msgspec native RFC3339 decode fails. They need the epoch hook + `time.unix_epoch_to_datetime`
   (with the max/min clamping). Highest-risk item.
2. **`[current, max]` party tuple** — `size` is a 2-element array; splitting into `current_size`/`max_size`
   is a residual transform, not a declarative field.
3. **`_application_id` is context-injected**, not in the assets JSON — keep it a **T** field threaded from
   the parent activity; the rename to `application_id` is safe (attrs alias already exposes that kwarg).
4. **`Activity.type` converter loss** — msgspec `__init__` runs no converter; `Activity(type=0)` stores a
   bare int. Preserve caller ergonomics via input-lenience/classmethod, not a decode-time hook.
5. **Polymorphic `emoji`** discriminated by `id` presence — a residual dispatch, not a tagged union.
6. **`MemberPresence`/`ActivityParty` identity** — `(user_id, guild_id)` and `id` respectively; `eq=False`
   would drop to object identity. Preserve with hand-written dunders or accept the change (flag).
7. **`app` is live here** — presences is NOT a dead-`app` module; the 2 helpers must be re-homed.

--------------------------------------------------------------------------------------------------

## 7. Verification

- Decode an activity with `timestamps`/`created_at` epoch millis → tz-aware datetimes equal to
  `time.unix_epoch_to_datetime(...)`; out-of-range epoch clamps to `datetime.max/min`.
- Decode an activity `party.size == [2, 5]` → `current_size == 2`, `max_size == 5`; missing `size` →
  both `None`.
- Decode assets → `application_id` equals the parent activity's `application_id`; `make_large_image_url`
  resolves.
- Decode a custom-status activity with a custom emoji (`id` present) → `emoji` is `CustomEmoji`; unicode
  → `UnicodeEmoji`.
- Decode a presence whose `client_status` omits `mobile` → `client_status.mobile == Status.OFFLINE`.
- Strict enums: unknown `Status` string / `ActivityType` int → pseudo-member.
- Grep: no `self.app` in `presences.py`; `fetch_user`/`fetch_member` resolve to `rest.*`.

--------------------------------------------------------------------------------------------------

## 8. Open questions / decisions

Cross-link `../00-overview/05-decisions-log.md`:
- **Unix-epoch field hook mechanism** (`Annotated[datetime, "unix_millis"]` vs int-field-then-transform) —
  settle in `../01-foundations/02-custom-scalar-types-and-hooks.md`; must replicate the max/min clamping.
- **`Activity.type` converter replacement** — input-lenience (recommended) vs classmethod/`__post_init__`
  normalisation for the outbound builder.
- **`MemberPresence`/`ActivityParty` identity** under frozen `eq=False` — hand-written `(user_id,guild_id)`
  / `id` dunders vs object identity.
- **D5:** no tri-state `UNDEFINED` fields in presences; `is_instance`/`flags` use `None`.
