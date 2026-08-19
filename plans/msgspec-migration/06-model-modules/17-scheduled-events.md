# Scheduled events

Purpose: migrate `hikari/scheduled_events.py` — 3 enums, the abstract `ScheduledEvent` base, its 3
concrete subtypes (`ScheduledStageEvent`, `ScheduledVoiceEvent`, `ScheduledExternalEvent`) dispatched
polymorphically by `entity_type`, and `ScheduledEventUser`. The base carries a **dead** `app` field
(no `self.app` helpers), and the external subtype flattens `location` up out of `entity_metadata`.

--------------------------------------------------------------------------------------------------

## 1. Objective

- Freeze the 5 Structs; drop the **dead** `ScheduledEvent.app` field (`scheduled_events.py:102`,
  inherited by all 3 subtypes) with no helper re-homing (confirmed: **no `self.app` in
  `scheduled_events.py`** — a dead-`app` module, conventions §8,
  `../03-app-removal-and-helpers/01-app-field-removal.md`).
- Keep the 3 enums as hikari's custom `Enum` (adopt #2770 strict typing); the fields are already strict
  (no `| int` unions here).
- Express the `ScheduledEvent` → 3-subtype polymorphism as a msgspec tagged union on `entity_type`,
  preserving the current **raise-on-unknown-type** semantics (`entity_factory.py:4354`).
- Preserve the `ScheduledExternalEvent.location` grandchild flatten and the differing `end_time`
  nullability.

Decode classification: `ScheduledExternalEvent` is **T** (`location` lifted from
`entity_metadata.location`, nested `creator`). `ScheduledStageEvent`/`ScheduledVoiceEvent` are near-**D**
(a `channel_id` + nested `creator` + tagged dispatch). `ScheduledEventUser` is **T** (context-injected
`guild_id`/`user` into `member`, renamed `event_id`).

--------------------------------------------------------------------------------------------------

## 2. Current state (file:line anchors)

### 2.1 Enums
`EventPrivacyLevel(int, enums.Enum)` `scheduled_events.py:55` (GUILD_ONLY=2);
`ScheduledEventType(int, enums.Enum)` `:62` (STAGE_INSTANCE=1, VOICE=2, EXTERNAL=3);
`ScheduledEventStatus(int, enums.Enum)` `:75` (SCHEDULED/ACTIVE/COMPLETED/CANCELED, with the alias
`CANCELLED = CANCELED` `:90`).

### 2.2 Models
- `ScheduledEvent(snowflakes.Unique)` (abstract base) `scheduled_events.py:96` — `app` `:102` (**dead**),
  `id` (hash), `guild_id`, `name`, `description`, `start_time: datetime`, `end_time: datetime | None`,
  `privacy_level`, `status`, `entity_type: ScheduledEventType`, `creator: User | None`,
  `user_count: int | None`, `image_hash`; `make_image_url` `:153` (no `app`).
- `ScheduledExternalEvent(ScheduledEvent)` `:206` — `location: str` `:209` (from
  `payload["entity_metadata"]["location"]`, `entity_factory.py:4284`), `end_time: datetime`
  (non-null override) `:217`.
- `ScheduledStageEvent(ScheduledEvent)` `:223` — `channel_id: Snowflake` `:226`.
- `ScheduledVoiceEvent(ScheduledEvent)` `:232` — `channel_id: Snowflake` `:235`.
- `ScheduledEventUser` `:241` — `event_id: Snowflake` (from `guild_scheduled_event_id`,
  `entity_factory.py:4370`), `user: User` (hash), `member: Member | None`.

### 2.3 Factory
- `deserialize_scheduled_external_event` `entity_factory.py:4263` (`location` flatten `:4284`, required
  `end_time` `:4277`), `deserialize_scheduled_stage_event` `:4288`, `deserialize_scheduled_voice_event`
  `:4317` (nullable `end_time` `:4296`/`:4324`).
- `deserialize_scheduled_event` `:4346` routes on `ScheduledEventType` via `_scheduled_event_type_mapping`
  (built `:520-524`), raising `UnrecognisedEntityError` on unknown `:4354`.
- `deserialize_scheduled_event_user` `:4357` — context-injected `guild_id`/`user` into `member` `:4367`.

--------------------------------------------------------------------------------------------------

## 3. Target design

### 3.1 Enums → strict custom (adopt #2770)
The 3 enums stay `int, enums.Enum` (hikari's custom `Enum`, unchanged,
`../02-enums/00-strategy-and-forward-compat.md`); PR #2770's `_EnumMeta.__call__` mints an `is_unknown`
pseudo-member on unrecognised values and decode routes through the shared `dec_hook`.
`ScheduledEventStatus.CANCELLED = CANCELED` remains an alias member of the custom enum (aliases already
work). Fields are already strict-typed — no `| int` unions to drop.

### 3.2 Tagged-union polymorphism on `entity_type`
`entity_type` (1/2/3) is a clean per-object discriminator mapping 1:1 to the 3 subtypes — a tagged union
(`../05-entity-factory/01-polymorphism-and-tagged-unions.md`):
```python
class ScheduledEvent(
    snowflakes.Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False,
    tag_field="entity_type",
):
    id: snowflakes.Snowflake
    guild_id: snowflakes.Snowflake
    name: str
    description: str | None
    start_time: datetime.datetime = msgspec.field(name="scheduled_start_time")
    end_time: datetime.datetime | None = msgspec.field(name="scheduled_end_time", default=None)
    privacy_level: EventPrivacyLevel
    status: ScheduledEventStatus
    creator: users.User | None = None
    user_count: int | None = None
    image_hash: str | None = msgspec.field(name="image", default=None)
    # NO app; make_image_url verbatim (routes.*)

class ScheduledStageEvent(ScheduledEvent, frozen=True, kw_only=True, eq=False, tag=1):
    channel_id: snowflakes.Snowflake

class ScheduledVoiceEvent(ScheduledEvent, frozen=True, kw_only=True, eq=False, tag=2):
    channel_id: snowflakes.Snowflake

class ScheduledExternalEvent(ScheduledEvent, frozen=True, kw_only=True, eq=False, tag=3):
    location: str            # T: flattened from entity_metadata.location
    end_time: datetime.datetime = msgspec.field(name="scheduled_end_time")  # required override

AnyScheduledEvent = typing.Union[ScheduledStageEvent, ScheduledVoiceEvent, ScheduledExternalEvent]
```
- The old `entity_type` field becomes the tag discriminator; msgspec **raises** on unknown tag — matching
  today's `UnrecognisedEntityError` (`entity_factory.py:4354`). Expose a read-only `entity_type` property
  if API parity requires the enum value.
- Renamed timestamp keys (`scheduled_start_time`/`scheduled_end_time`) and `image`→`image_hash` are
  declarative via `msgspec.field(name=…)`; the timestamps are RFC3339 (native datetime decode).
- **`ScheduledExternalEvent.location`** is a grandchild flatten (`entity_metadata.location`,
  `entity_factory.py:4284`) — msgspec cannot pull a grandchild up declaratively, so this stays a residual
  transform (dossier 05 §3h; `../05-entity-factory/02-hard-cases-and-transforms.md`). The differing
  `end_time` nullability (required on external, optional on stage/voice) is handled by the per-subtype
  override.
- Interim fallback: keep `deserialize_scheduled_event` as a `msgspec.Raw` peek on `entity_type`
  dispatching to the concrete decoders until the tagged union lands.

### 3.3 ScheduledEventUser (T)
```python
class ScheduledEventUser(msgspec.Struct, frozen=True, kw_only=True):
    event_id: snowflakes.Snowflake = msgspec.field(name="guild_scheduled_event_id")
    user: users.User
    member: guilds.Member | None = None    # T: guild_id/user context-injected
```
`member` is built with the parent `guild_id` and the sibling `user` threaded in
(`entity_factory.py:4367`) — a context injection that stays in the residual factory. Identity today is by
`user` (the sole `hash=True` field, `scheduled_events.py:247`); it is not `Unique`, so preserve `user`-keyed
identity with hand-written dunders or accept msgspec's default all-field `eq` (flag it).

--------------------------------------------------------------------------------------------------

## 4. Step-by-step migration

1. Adopt #2770's strict custom enums (keep custom `Enum`, keep the `CANCELLED` alias).
2. Convert `ScheduledEvent` to a frozen Struct base with `tag_field="entity_type"`; drop the **dead**
   `app` field; add the `scheduled_start_time`/`scheduled_end_time`/`image` renames; keep `make_image_url`.
3. Convert the 3 subtypes to tagged Structs (`tag=1/2/3`); keep `channel_id` on stage/voice; keep the
   `location` flatten and required `end_time` override on external.
4. Convert `ScheduledEventUser`; rename `event_id`; keep the `guild_id`/`user` context injection for
   `member`; settle `user`-keyed identity.
5. Update the 3 concrete decoders + `deserialize_scheduled_event`/`deserialize_scheduled_event_user`
   (`entity_factory.py:4263-4371`) to stop injecting `app` and to feed the tagged union / `Raw` dispatch.

--------------------------------------------------------------------------------------------------

## 5. Affected files & symbols

| Path / anchor | Change |
|---|---|
| `hikari/scheduled_events.py:55-91` (enums) | 3 enums stay custom (#2770 strict typing); keep `CANCELLED` alias |
| `hikari/scheduled_events.py:96-201` (`ScheduledEvent`) | frozen Struct base, `tag_field="entity_type"`; drop dead `app`; timestamp/image renames |
| `hikari/scheduled_events.py:206-236` (3 subtypes) | tags 1/2/3; `location` flatten **T**; `end_time` override; `channel_id` |
| `hikari/scheduled_events.py:241-251` (`ScheduledEventUser`) | frozen; `event_id` rename; `member` context injection **T** |
| `hikari/impl/entity_factory.py:4263-4371,520-524` | drop `app`; feed tagged union / `Raw` dispatch; keep `location` flatten + `member` context |
| `../05-entity-factory/01-polymorphism-and-tagged-unions.md` | scheduled-event tagged union, raise-on-unknown |
| `../05-entity-factory/02-hard-cases-and-transforms.md` | `location` flatten, `member` context injection |
| `../03-app-removal-and-helpers/01-app-field-removal.md` | the dead `app` field |
| `02-users.md`, `05-guilds-members-roles.md` | `User`/`Member` reference types |

--------------------------------------------------------------------------------------------------

## 6. Risks / gotchas

1. **`location` grandchild flatten** — `entity_metadata.location` cannot be pulled up declaratively; it
   stays a residual transform on the external subtype only.
2. **Differing `end_time` nullability** — required on external, optional on stage/voice; the per-subtype
   override must set the right shape (a subclass re-declaring an inherited field with a different type is
   allowed in msgspec, but confirm the base's optional default does not leak).
3. **Tag field vs stored `entity_type`** — moving `entity_type` to the tag may change how it reads back;
   add a property for parity if needed.
4. **`ScheduledEventUser` identity** — by `user` today; `eq=False`/all-field `eq` both change it; decide
   and preserve.
5. **Raise-on-unknown preserved** — tagged unions raise on unknown tag, matching
   `entity_factory.py:4354`.

--------------------------------------------------------------------------------------------------

## 7. Verification

- Decode each of stage/voice/external → correct concrete class; unknown `entity_type` → decode error
  (parity with `UnrecognisedEntityError`).
- External event: `location` equals `entity_metadata.location`; `end_time` is a required non-null datetime.
- Stage/voice: `channel_id` present; `end_time` nullable.
- `ScheduledEventUser`: `event_id` maps from `guild_scheduled_event_id`; `member` carries the parent
  `guild_id`; absent member → `None`.
- Strict enums: unknown `status`/`privacy_level` int → pseudo-member; `CANCELLED is CANCELED`.
- Grep: no `self.app` and no `app=` construction remains for scheduled-event entities.

--------------------------------------------------------------------------------------------------

## 8. Open questions / decisions

Cross-link `../00-overview/05-decisions-log.md`:
- **Tagged union vs retained hand dispatch** on `entity_type` — recommend the tagged union
  (`../05-entity-factory/01-polymorphism-and-tagged-unions.md`); interim `Raw` peek bridges.
- **`entity_type` property parity** once it is the tag.
- **`ScheduledEventUser` identity** (`user`-keyed) under frozen — hand-written dunders vs all-field `eq`.
- **`location` flatten** and **`member` context injection** live in
  `../05-entity-factory/02-hard-cases-and-transforms.md`.
