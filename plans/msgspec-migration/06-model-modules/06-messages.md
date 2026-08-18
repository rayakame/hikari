# Messages

Purpose: migrate `hikari/messages.py` — the `PartialMessage` (tri-state) / `Message` (full) hierarchy
plus the value objects `Attachment`, `Reaction`, `ReactionCountDetails`, `MessageActivity`,
`MessageReference`, `MessageApplication`, `MessageSnapshot`, `PinnedMessage`. This is the crown-jewel
module of the migration: nearly every hard-case category (dossier 05 §6) is present here, and
`deserialize_message`/`deserialize_partial_message` are the two heaviest factory methods
(`entity_factory.py:4032`/`3888`, both `# noqa: C901, PLR0912, PLR0915`).

--------------------------------------------------------------------------------------------------

## 1. Objective

- Freeze the message hierarchy (`frozen=True, kw_only=True, eq=False`), id-only identity from
  `snowflakes.Unique` for `PartialMessage`/`Message`/`Attachment`.
- Remove `PartialMessage.app` (1 live declaration, `messages.py:599`) + the **9** `self.app.*` helper
  methods, and drop the **dead** `MessageReference.app` (`messages.py:408`). Re-home the helpers per
  `../03-app-removal-and-helpers/02-helper-method-inventory/02-messages.md`.
- Port 5 enums to stdlib (`MessageType`, `MessageReferenceType`, `MessageActivityType`, `ReactionType`
  → `int, enum.Enum`; `MessageFlag` → `enum.IntFlag`), strict-type every enum field.
- Preserve the tri-state (`UndefinedOr`) contract on `PartialMessage` (~24 fields) under D5.
- Keep the residual factory transforms for re-keyed mentions, recursive `referenced_message`,
  `sticker_items` fallback, polymorphic `interaction_metadata`/`components`, and the
  `message_snapshot` flatten.

Decode classification: mostly **T**. `Attachment`/`MessageActivity`/`MessageReference`/
`MessageApplication`/`ReactionCountDetails` are **D**; `Reaction` is **T** (`burst_colors` hex hook);
`MessageSnapshot`/`PinnedMessage`/`PartialMessage`/`Message` are **T** (see §3.5).

--------------------------------------------------------------------------------------------------

## 2. Current state (file:line anchors)

### 2.1 Enums
| Enum | Anchor | Kind | Target |
|---|---|---|---|
| `MessageType` | `messages.py:73-186` (37 members, non-contiguous, gaps at 13/30/33-35/40-43/45) | `int, enums.Enum` | `int, enum.Enum` + `_missing_` |
| `MessageReferenceType` | `messages.py:189-197` | `int, enums.Enum` | `int, enum.Enum` |
| `MessageFlag` | `messages.py:200-244` (bitfield `1<<0..1<<15`, gaps) | `enums.Flag` | `enum.IntFlag` + set-API mixin |
| `MessageActivityType` | `messages.py:247-264` | `int, enums.Enum` | `int, enum.Enum` |
| `ReactionType` | `messages.py:331-339` | `int, enums.Enum` | `int, enum.Enum` |

### 2.2 Value objects (not `Unique`)
- `ReactionCountDetails` — `messages.py:342-351`; `burst`/`normal` ints. **D**.
- `Reaction` — `messages.py:354-384`; `@attrs.define(unsafe_hash=True…)` but the sole `hash=True`
  field is **`emoji`** (`:365`), not an id — identity is by emoji. `burst_colors:
  Sequence[colors_.Color]` (`:374`) decoded from **hex strings** (`Color.from_hex_code`, dossier 05
  §3i, `entity_factory.py:3726`). `burst_colours` alias property (`:377-380`). **T + custom identity.**
- `MessageActivity` — `messages.py:387-397`; `type: MessageActivityType | int` (`:392`), `party_id`.
- `MessageReference` — `messages.py:399-456`; carries **dead** `app` (`:408`, `SKIP_DEEP_COPY`),
  `type: MessageReferenceType | int` (`:413`, default `DEFAULT`), nullable `id`/`guild_id`,
  `channel_id`; `message_link`/`channel_link` properties use only `id`/`guild_id`/`channel_id`
  (**no `self.app`**).
- `MessageApplication` — `messages.py:458-514`; extends `guilds.PartialApplication`
  (`05-guilds-members-roles.md`), adds `cover_image_hash` + `make_cover_image_url` (no `app`).

### 2.3 `Attachment` (mixin hazard)
- `Attachment(snowflakes.Unique, files.WebResource)` — `messages.py:267-328`. Multiple inheritance:
  the abstract `url`/`filename` properties of `files.WebResource` are satisfied by attrs **fields**
  (`:281`/`:284`). Fields: `id` (`hash=True`), `url`, `filename`, `title`, `description`, `media_type`,
  `size`, `proxy_url`, `height`, `width`, `is_ephemeral`, `duration`, `waveform`; `__str__`→`filename`.
  Shared hazard with `components.MediaResource`/`embeds.EmbedResource` — see
  `03-emojis-and-files-resources.md` and the files plan.

### 2.4 `MessageSnapshot` / `PinnedMessage` (eq=False, repr=True)
- `MessageSnapshot` — `messages.py:528-569`; `@attrs.define(kw_only=True, repr=True, eq=False…)`;
  no id, no app. `user_mentions: Mapping[Snowflake, User]` (re-keyed), `role_mention_ids`, `stickers`,
  `components`, `type: MessageType | int`. `user_mentions_ids` property (`:566`).
- `PinnedMessage` — `messages.py:572-582`; `pinned_at`, `message: Message` (nested).

### 2.5 `PartialMessage` (tri-state) and `Message` (full)
- `PartialMessage(snowflakes.Unique)` — `messages.py:584-1521`;
  `@attrs.define(kw_only=True, repr=True, eq=False…)`. `app` field (`:599`, `SKIP_DEEP_COPY`), `id`
  (`hash=True`), `channel_id`, `guild_id`, then **~24 `UndefinedOr`/`UndefinedNoneOr`** decoded
  tri-state fields (`author`, `member`, `content`, `timestamp`, `edited_timestamp`, `is_tts`,
  `user_mentions`, `role_mention_ids`, `channel_mentions`, `mentions_everyone`, `attachments`,
  `embeds`, `poll`, `reactions`, `is_pinned`, `webhook_id`, `type`, `activity`, `application`,
  `message_reference`, `flags`, `stickers`, `nonce`, `referenced_message`, `application_id`,
  `components`), plus two **non**-tri-state fields `message_snapshots: Sequence[MessageSnapshot]`
  (`:764`) and `interaction_metadata: PartialInteractionMetadata | None` (`:779`). Properties
  `channel_mention_ids` (`:784`), `user_mentions_ids` (`:801`); helpers `get_member_mentions`
  (`:816`), `get_role_mentions` (`:850`), `make_link` (`:880`).
- `Message(PartialMessage)` — `messages.py:1524-1624`; `@attrs.define(unsafe_hash=True…)`. Redeclares
  the fields as **full** non-tri-state types (`author: User`, `content: str | None`, `timestamp:
  datetime`, `flags: MessageFlag`, `type: MessageType | int`, …), all `None`/`[]` defaults populated
  by the factory, and adds `thread: GuildThreadChannel | None` (`:1619`).

### 2.6 The 9 `self.app.*` helpers on `PartialMessage`
`fetch_channel` (`:901`, rest), `edit` (`:928`, rest), `respond` (`:1102`, rest), `delete` (`:1298`,
rest), `add_reaction` (`:1317`, rest), `remove_reaction` (`:1390`, rest), `remove_all_reactions`
(`:1472`, rest), `get_member_mentions` (`:816`, cache), `get_role_mentions` (`:850`, cache). All
enumerated with re-homing targets in
`../03-app-removal-and-helpers/02-helper-method-inventory/02-messages.md`.

Factory sites (dossier 05 §7): `MessageReference` `app=self._app` at `entity_factory.py:3739`,
`Message` at `:3997`, `PartialMessage` at `:4106`.

--------------------------------------------------------------------------------------------------

## 3. Target design

### 3.1 Enums (see `../02-enums/`)
```python
class MessageType(int, enum.Enum):        # 37 members verbatim; _missing_ = classmethod(_int_enum_missing)
    DEFAULT = 0; ...; POLL_RESULT = 46
class MessageReferenceType(int, enum.Enum): DEFAULT = 0; FORWARD = 1
class MessageActivityType(int, enum.Enum):  NONE = 0; JOIN = 1; SPECTATE = 2; LISTEN = 3; JOIN_REQUEST = 5
class ReactionType(int, enum.Enum):         NORMAL = 0; BURST = 1
class MessageFlag(_FlagMixin, enum.IntFlag): NONE = 0; CROSSPOSTED = 1 << 0; ...; IS_COMPONENTS_V2 = 1 << 15
```

### 3.2 Value objects
```python
class ReactionCountDetails(msgspec.Struct, frozen=True, kw_only=True):   # D, default eq ok
    burst: int
    normal: int

class Reaction(msgspec.Struct, frozen=True, kw_only=True, eq=False):     # T; see §3.6 identity
    count: int
    count_details: ReactionCountDetails
    emoji: emojis.UnicodeEmoji | emojis.CustomEmoji
    is_me: bool
    is_me_burst: bool
    burst_colors: typing.Sequence[colors.Color]           # hex-string wire -> Color.from_hex_code hook
    @property
    def burst_colours(self) -> typing.Sequence[colors.Color]: return self.burst_colors

class MessageActivity(msgspec.Struct, frozen=True, kw_only=True):
    type: MessageActivityType                              # was `| int` -> strict (b)
    party_id: str | None

class MessageReference(msgspec.Struct, frozen=True, kw_only=True):        # D; NO app field
    type: MessageReferenceType = MessageReferenceType.DEFAULT
    id: snowflakes.Snowflake | None
    channel_id: snowflakes.Snowflake
    guild_id: snowflakes.Snowflake | None
    # message_link / channel_link properties port verbatim (no app)
```

### 3.3 `Attachment` (mixin)
`Attachment` keeps `snowflakes.Unique` (id identity) but the `files.WebResource` mixin must be
resolved: either (a) keep `WebResource` as a plain non-Struct behavioural mixin whose abstract
`url`/`filename` are satisfied by the Struct's own slotted fields, or (b) split the data fields off
into the Struct and expose the reader behaviour via composition. This is the same decision taken for
`components.MediaResource` and `embeds.EmbedResource`; resolve it once in
`03-emojis-and-files-resources.md` and apply here. Fields port 1:1; `__str__`→`filename`.

### 3.4 `MessageSnapshot` / `PinnedMessage`
```python
class MessageSnapshot(msgspec.Struct, frozen=True, kw_only=True):     # T, not Unique
    type: MessageType                                                 # strict
    content: str | None
    embeds: typing.Sequence[embeds.Embed]
    attachments: typing.Sequence[Attachment]
    timestamp: undefined.UndefinedOr[datetime.datetime] = undefined.UNDEFINED
    edited_timestamp: datetime.datetime | None = None
    flags: undefined.UndefinedOr[MessageFlag] = undefined.UNDEFINED
    stickers: typing.Sequence[stickers.PartialSticker]
    user_mentions: typing.Mapping[snowflakes.Snowflake, users.User]   # re-keyed (T)
    role_mention_ids: typing.Sequence[snowflakes.Snowflake]
    components: typing.Sequence[component_models.TopLevelComponentTypesT]

class PinnedMessage(msgspec.Struct, frozen=True, kw_only=True):
    pinned_at: datetime.datetime
    message: Message
```

### 3.5 `PartialMessage` / `Message`
```python
class PartialMessage(snowflakes.Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    id: snowflakes.Snowflake
    channel_id: snowflakes.Snowflake
    guild_id: snowflakes.Snowflake | None = None
    # NO app field.
    author: undefined.UndefinedOr[users.User] = undefined.UNDEFINED
    member: undefined.UndefinedNoneOr[guilds.Member] = undefined.UNDEFINED
    content: undefined.UndefinedNoneOr[str] = undefined.UNDEFINED
    # ... the remaining ~21 tri-state fields, each default=undefined.UNDEFINED ...
    message_snapshots: typing.Sequence[MessageSnapshot] = ()          # NOT tri-state
    interaction_metadata: base_interactions.PartialInteractionMetadata | None = None   # NOT tri-state
    # channel_mention_ids / user_mentions_ids properties + make_link port verbatim

class Message(PartialMessage, frozen=True, kw_only=True, eq=False):
    author: users.User
    content: str | None
    timestamp: datetime.datetime
    flags: MessageFlag
    type: MessageType                                                 # strict (drop `| int`)
    # ... all fields redeclared as full types, defaults supplied by factory ...
    thread: channels.GuildThreadChannel | None = None
```

The ~24 tri-state fields carry role (ii) `UNDEFINED` (D5, `../01-foundations/03-undefined-and-unset.md`)
— this and `PartialUserImpl` (`02-users.md`) are the two canonical decoded-entity `UNDEFINED` cases.
Strict-enum fields drop their `| int` arm: `PartialMessage.type` becomes `UndefinedOr[MessageType]`,
`Message.type`/`MessageSnapshot.type` become `MessageType`.

### 3.6 `Reaction` identity change (gotcha)
Today `Reaction` hashes/compares by **`emoji`** only (attrs `unsafe_hash` + `hash=True` on `emoji`).
It is not `Unique` and holds an unhashable `burst_colors` list, so msgspec default all-field `eq`
would raise on hash. Options: (1) `eq=False` (object identity — loses emoji-equality, low risk since
reactions are rarely compared), or (2) hand-write `__eq__`/`__hash__` over `emoji` to preserve
current semantics. Recommend (1) with a changelog note, unless a caller relies on emoji-equality —
raise in `../00-overview/05-decisions-log.md`.

### 3.7 Residual transforms (the hard cases)
| Field / behavior | Anchor | Category |
|---|---|---|
| `user_mentions` array→`{u.id: u}` | `entity_factory.py:3928`/`3858` | re-keying (05 §3f) |
| `channel_mentions` array→`{c.id: c}` | `entity_factory.py:3930` | re-keying |
| `role_mention_ids` list of `Snowflake` | `entity_factory.py:3929`/`3862` | computed |
| `referenced_message` recursion (partial↔full) | `deserialize_message`/`_partial_message` | recursion (05 §3e) |
| `sticker_items` → `stickers` fallback → `[]` | `entity_factory.py:3844-3850` | conditional key |
| `interaction_metadata` polymorphic dispatch | `entity_factory.py:3933-3934`/`3813-3821` | polymorphism, **raises** on unknown |
| `components` polymorphic dispatch | `_deserialize_top_level_components:3430` | polymorphism, soft-skip |
| `message_snapshot` flatten `payload["message"]` | `entity_factory.py:3825` | flatten (05 §3h) |
| `burst_colors` hex→`Color.from_hex_code` | `entity_factory.py:3726` | computed/hook |

`interaction_metadata` and `components` are tagged unions handled in
`../05-entity-factory/01-polymorphism-and-tagged-unions.md`; the array-re-keying, flatten and
sticker fallback are transforms in `../05-entity-factory/02-hard-cases-and-transforms.md`.

--------------------------------------------------------------------------------------------------

## 4. Step-by-step migration

1. Port the 5 enums (`../02-enums/01-flags-migration.md` for `MessageFlag`;
   `../02-enums/02-int-and-str-enums-migration.md` for the four int enums).
2. Convert the leaf value objects (`ReactionCountDetails`, `MessageActivity`, `MessageReference`,
   `MessageApplication`) to frozen Structs; drop the **dead** `MessageReference.app` field and its
   `entity_factory.py:3739` injection.
3. Resolve the `Attachment` / `files.WebResource` mixin per `03-emojis-and-files-resources.md`;
   convert `Attachment` to a frozen `Unique` Struct.
4. Convert `Reaction` (`eq=False`, `burst_colors` hex hook) — decide identity per §3.6.
5. Convert `MessageSnapshot`/`PinnedMessage` (frozen, `eq=False` retained for snapshot).
6. Convert `PartialMessage`: drop the `app` field, keep `id`/`channel_id`, set the ~24 tri-state
   fields to `default=undefined.UNDEFINED`, keep `message_snapshots`/`interaction_metadata` as
   non-tri-state. Move `get_member_mentions`/`get_role_mentions` (cache) and the 7 rest helpers out
   per the helper-inventory file; keep `channel_mention_ids`/`user_mentions_ids`/`make_link`.
7. Convert `Message` (full types, add `thread`), confirm 2-level frozen/eq=False inheritance from
   `PartialMessage`.
8. Slim `deserialize_message`/`deserialize_partial_message`/`deserialize_message_snapshot` to keep the
   transforms (§3.7) but stop injecting `app=self._app` (`entity_factory.py:3997`/`4106`).

--------------------------------------------------------------------------------------------------

## 5. Affected files & symbols

| Path / anchor | Change |
|---|---|
| `hikari/messages.py:73-339` | 5 enums → stdlib |
| `hikari/messages.py:267-328` | `Attachment` → frozen `Unique` Struct + WebResource mixin resolution |
| `hikari/messages.py:342-514` | `ReactionCountDetails`/`Reaction`/`MessageActivity`/`MessageReference`/`MessageApplication` → Structs; drop dead `MessageReference.app` |
| `hikari/messages.py:528-582` | `MessageSnapshot`/`PinnedMessage` → frozen Structs |
| `hikari/messages.py:584-1521` | `PartialMessage` → frozen Struct; drop `app`; 24 tri-state defaults; extract 9 helpers |
| `hikari/messages.py:1524-1624` | `Message` → frozen Struct; full types; `thread` |
| `hikari/impl/entity_factory.py:3726` | `burst_colors` `Color.from_hex_code` hook |
| `hikari/impl/entity_factory.py:3813-3878` | `_deserialize_interaction_metadata` + `deserialize_message_snapshot` transforms; drop app |
| `hikari/impl/entity_factory.py:3888-4130` | `deserialize_partial_message`/`deserialize_message`: drop `app`, keep transforms |
| `../03-app-removal-and-helpers/02-helper-method-inventory/02-messages.md` | 9 helper re-homings |

--------------------------------------------------------------------------------------------------

## 6. Risks / gotchas

1. **Tri-state vs full split** — the same field is `UndefinedOr[...]` on `PartialMessage` and a full
   type on `Message`; msgspec permits the subclass redeclaration, but the defaults differ
   (`UNDEFINED` vs factory-supplied). Both must be kept; the two `deserialize_*` methods stay distinct.
2. **`Reaction` identity change** (§3.6) — the only value object here with a non-id custom hash; the
   `burst_colors` list makes default hashing impossible.
3. **`Attachment` mixin** — Struct + `files.WebResource` ABC with slotted fields satisfying abstract
   properties is a known sharp edge (`reportIncompatibleVariableOverride` note, `pyproject.toml:180`).
   Do not convert independently of the shared Resource decision.
4. **`referenced_message` recursion** — a `PartialMessage` field of type `PartialMessage | None`
   (self-referential); msgspec supports recursive Structs, but the partial↔full distinction is
   factory-driven, not type-driven — keep it in the transform.
5. **`interaction_metadata` raises on unknown type** (`entity_factory.py:3820`) while `components`
   soft-skip — preserve the asymmetric semantics (dossier 05 §6.2,
   `../05-entity-factory/01-polymorphism-and-tagged-unions.md`).
6. **`get_member_mentions`/`get_role_mentions`** depend on `self.app.cache` + `self.guild_id`; they
   become free functions taking `cache` (dossier 04 mention getters cluster,
   `../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md`).
7. **`MessageReference.app` is dead** — confirm nothing external reads `message_reference.app` before
   dropping (dossier 03 §7 lists it among unused app carriers; not one of the 10 dead *modules*, but
   this specific field is dead because `PartialMessage.app` is the live one).

--------------------------------------------------------------------------------------------------

## 7. Verification

- Decode a `MESSAGE_UPDATE` partial payload omitting `content`/`embeds` → those fields are
  `undefined.UNDEFINED`; `id`/`channel_id` present; frozen (attribute set raises).
- Decode a full `Message` → `flags` a `MessageFlag`, `type` a `MessageType`, `user_mentions` a
  `Mapping[Snowflake, User]`, `referenced_message` a `Message`/`None`.
- Decode a message with `message_snapshots` → snapshot `type` a `MessageType`, `sticker_items`
  populated; a snapshot missing `sticker_items` but with legacy `stickers` uses the fallback; neither
  present → `[]`.
- Decode a message with an unknown `interaction_metadata.type` → `UnrecognisedEntityError`; with an
  unknown component type → the component is skipped, decode succeeds.
- `burst_colors` from `["#ff0000"]` → `[Color(0xFF0000)]`.
- Grep proves no `self.app` remains in `messages.py`; the 9 helpers resolve via `rest.*`/free
  functions in caller tests.

--------------------------------------------------------------------------------------------------

## 8. Open questions / decisions

Cross-link `../00-overview/05-decisions-log.md`:

- **D5:** `PartialMessage` ~24-field tri-state — keep `undefined.UNDEFINED` defaults (VERIFY msgspec
  accepts `T | UndefinedType` with a non-UNSET default).
- **Reaction identity** (§3.6) — `eq=False` (object identity, recommended) vs hand-written
  emoji-equality. Behavior change either way; needs a changelog entry.
- **`Attachment`/WebResource mixin** — resolved once in `03-emojis-and-files-resources.md`; this
  module consumes that decision.
- **D9 / cache getters:** `get_member_mentions`/`get_role_mentions` become free functions over
  `cache` — confirm signatures in `../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md`.
