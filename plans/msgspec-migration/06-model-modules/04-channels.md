# Channels

Purpose: migrate `hikari/channels.py` — the deepest polymorphic hierarchy in the library
(`PartialChannel` fanning out through 6 abstract bases into ~12 concrete channel/thread types) plus
`ChannelFollow`, `PermissionOverwrite`, `ForumTag`, `ThreadMember`, `ThreadMetadata`. This module is
the archetype for the tagged-union work (decode routes on the `type` int) and carries the second
`app` field declaration set (2 fields, ~16 `self.app` helpers). It depends on scalars, users,
emojis, and permissions landing first (`00-README.md` §3).

--------------------------------------------------------------------------------------------------

## 1. Objective

- Turn `PartialChannel` and its subclasses into a **tagged union keyed on `type`** so
  `deserialize_channel` becomes a union decode (`../05-entity-factory/01-polymorphism-and-tagged-unions.md`).
- Freeze all channel Structs app-less; remove the 2 `app` field declarations (`ChannelFollow.app`,
  `PartialChannel.app`) and re-home the ~16 `self.app` helpers
  (`../03-app-removal-and-helpers/02-helper-method-inventory/01-channels.md`).
- Port the 6 channel enums to stdlib; strict-type the `type` and quality/layout/sort fields.
- Handle the sharp cases: `PermissionOverwrite`/`ForumTag` converters, the `ForumTag._emoji` alias,
  the two `shard_id` styles, and the diamond MRO of the guild-channel bases.

Decode classification: the concrete channels are **P** (tagged union) then partly **T** (forum/media
channels have nested tags, sibling-typed emoji, timedelta fields with "old channel omits this"
defaults). `PermissionOverwrite`/`ForumTag`/`ThreadMember`/`ThreadMetadata` are **T** (converters,
`_emoji` sibling typing, timedelta/datetime).

--------------------------------------------------------------------------------------------------

## 2. Current state (file:line anchors)

### 2.1 Enums
`ChannelType(int, enums.Enum)` `:92-136` (GUILD_TEXT=0, DM=1, GUILD_VOICE=2, GROUP_DM=3,
GUILD_CATEGORY=4, GUILD_NEWS=5, GUILD_NEWS_THREAD=10, GUILD_PUBLIC_THREAD=11, GUILD_PRIVATE_THREAD=12,
GUILD_STAGE=13, GUILD_FORUM=15, GUILD_MEDIA=16); `ChannelFlag(enums.Flag)` `:138`;
`VideoQualityMode(int, enums.Enum)` `:184`; `PermissionOverwriteType(int, enums.Enum)` `:294`;
`ForumSortOrderType(int, enums.Enum)` `:1452`; `ForumLayoutType(int, enums.Enum)` `:1463`.

### 2.2 The hierarchy (all `@attrs.define(unsafe_hash=True, kw_only=True, weakref_slot=False)` unless noted)
```
PartialChannel(Unique)                          :353   app, id(hash), name|None, type   -> mention/__str__/delete(app)
├─ TextableChannel(PartialChannel)              :424   ABSTRACT; 8 app helpers (fetch_history/fetch_message/send/
│                                                       trigger_typing/fetch_pins/pin_message/unpin_message/delete_messages)
├─ PrivateChannel(PartialChannel)               :857   ABSTRACT
│  ├─ DMChannel(PrivateChannel, TextableChannel):870   shard_id -> Literal[0] (:877)
│  └─ GroupDMChannel(PrivateChannel)            :887   make_icon_url (no app)
└─ GuildChannel(PartialChannel)                 :966   ABSTRACT; guild_id, application_id, parent_id;
   │                                                    shard_id -> int|None via self.app (:988-997);
   │                                                    get_guild/fetch_guild/edit (app)
   ├─ PermissibleGuildChannel(GuildChannel)     :1170  ABSTRACT; edit_overwrite/remove_overwrite (app)
   │  ├─ GuildCategory                          :1299
   │  ├─ GuildTextChannel(…, TextableGuildChannel):1314
   │  ├─ GuildNewsChannel(…, TextableGuildChannel):1356
   │  ├─ GuildVoiceChannel(…, TextableGuildChannel):1386
   │  ├─ GuildStageChannel(…, TextableGuildChannel):1419
   │  ├─ GuildForumChannel                      :1521  nested available_tags, default_reaction_emoji, timedeltas
   │  └─ GuildMediaChannel                      :1816  LEGACY `hash=True` spelling (dossier 03 §2)
   ├─ TextableGuildChannel(GuildChannel, TextableChannel):1291 ABSTRACT
   └─ GuildThreadChannel(TextableGuildChannel)  :1673  ABSTRACT; is_archived/auto_archive_duration/
      │                                                 archive_timestamp/is_locked/thread_created_at props
      ├─ GuildNewsThread                        :1776
      ├─ GuildPublicThread                      :1783
      └─ GuildPrivateThread                     :1803  is_invitable
```

### 2.3 Non-channel wire models
- `ChannelFollow` `:196` — `app`, `channel_id`, `webhook_id`; helpers `fetch_channel` (`:214`, app),
  `fetch_webhook` (`:243`, app), `get_channel` (`:270`, cache).
- `PermissionOverwrite(Unique)` `:305-349` — `@attrs_extensions.with_copy`; `id`
  (`converter=Snowflake`), `type` (`converter=PermissionOverwriteType`, `| int`), `allow`/`deny`
  (`converter=Permissions`, `default=Permissions.NONE`); `unset` property. User-constructable +
  `serialize_permission_overwrite` (`entity_factory.py:1120`).
- `ForumTag(Unique)` `:1476-1517` — `id` (`converter=Snowflake, factory=Snowflake.min`), `name`,
  `moderated: bool = False`, `_emoji: str|int|Emoji|None` (`alias="emoji", default=None`); resolving
  properties `unicode_emoji` (`:1503-1509`), `emoji_id` (`:1511-1517`). Serialized + deserialized
  (emoji-id XOR emoji-name, `entity_factory.py:1425-1431`).
- `ThreadMember` `:1606` and `ThreadMetadata` `:1632` — `@attrs.define(kw_only=True,
  weakref_slot=False)` value objects (not `Unique`); timedelta/datetime fields.

App declarations: `ChannelFollow.app` `:203`, `PartialChannel.app` `:361` (inherited by the whole
tree). Factory app-injection sites for channels: `entity_factory.py:1103,1133,1146,1172,1221,1259,
1305,1338,1378,1452,1560,1607,1650,1719` (dossier 05 §7).

--------------------------------------------------------------------------------------------------

## 3. Target design

### 3.1 Enums → stdlib
`ChannelType`/`VideoQualityMode`/`PermissionOverwriteType`/`ForumSortOrderType`/`ForumLayoutType`
→ `int, enum.Enum` + `_missing_`; `ChannelFlag` → `IntFlag` + set-API mixin
(`../02-enums/`). Drop `| int` on `type` (2 sites), `PermissionOverwriteType | int`, quality/layout/
sort fields (`../02-enums/03-strict-enum-field-inventory.md`).

### 3.2 Tagged union on `type`

`PartialChannel` is the tag base; each concrete channel pins its `type` as the tag literal:

```python
class PartialChannel(snowflakes.Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    id: snowflakes.Snowflake
    name: str | None = None
    type: ChannelType           # NO app; strict enum
    # mention / __str__ verbatim; delete() re-homed to rest

# concrete members carry a fixed type via the tagged-union tag (../05-entity-factory/01):
#   GuildTextChannel  -> tag ChannelType.GUILD_TEXT (0)
#   DMChannel         -> tag DM (1)          GuildVoiceChannel -> GUILD_VOICE (2)
#   GroupDMChannel    -> tag GROUP_DM (3)    GuildCategory     -> GUILD_CATEGORY (4)
#   GuildNewsChannel  -> GUILD_NEWS (5)      GuildNewsThread   -> GUILD_NEWS_THREAD (10)
#   GuildPublicThread -> 11  GuildPrivateThread -> 12  GuildStageChannel -> 13
#   GuildForumChannel -> 15  GuildMediaChannel  -> 16
```

`deserialize_channel` (`entity_factory.py:1761`) becomes a union decode. Discord's `type` is the
discriminator; msgspec tagged unions **raise on unknown tag**, matching today's
`UnrecognisedEntityError` (`:1782`) — behavior preserved. The three context sub-mappings
(`_dm_channel_type_mapping`, `_guild_channel_type_mapping`, `_thread_channel_type_mapping`) become
**narrower unions** for callers that only accept a subset (e.g. thread endpoints). Details and the
tag-field mechanics live in `../05-entity-factory/01-polymorphism-and-tagged-unions.md`.

### 3.3 Abstract-base MRO and the diamond

The 6 abstract bases (`TextableChannel`, `PrivateChannel`, `GuildChannel`, `PermissibleGuildChannel`,
`TextableGuildChannel`, `GuildThreadChannel`) exist to share **fields + methods**. The tricky ones are
diamonds: `GuildTextChannel(PermissibleGuildChannel, TextableGuildChannel)` where both bases derive
from `GuildChannel → PartialChannel`. msgspec Structs support inheritance but multiple **Struct** base
classes with a shared ancestor need verification (field-order and MRO). Options, in
`../05-entity-factory/01-polymorphism-and-tagged-unions.md`:
1. Keep the abstract bases as **Struct bases** (they carry fields like `guild_id`) and verify msgspec
   accepts the diamond; `kw_only=True` removes field-ordering constraints (conventions §2).
2. Flatten: give each concrete channel its full field set directly and demote the abstract bases to
   **non-Struct mixins** providing only methods (no fields). This sidesteps the diamond entirely at
   the cost of field duplication.
Recommend attempting (1); fall back to (2) if msgspec rejects the multi-Struct diamond. `kw_only`
means the "required-after-optional" trap does not bite either way.

### 3.4 PermissionOverwrite — converters → construction/hook

```python
class PermissionOverwrite(snowflakes.Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    id: snowflakes.Snowflake
    type: PermissionOverwriteType                      # was `| int`; strict
    allow: permissions.Permissions = permissions.Permissions.NONE
    deny: permissions.Permissions = permissions.Permissions.NONE
    @property
    def unset(self) -> permissions.Permissions: return ~(self.allow | self.deny)
```

- msgspec has no `converter=`; the `Snowflake`/`PermissionOverwriteType`/`Permissions` coercion moves
  to the global `dec_hook` (decode) and to explicit construction/`enc_hook` for the user-built +
  serialize path. Note the `default=Permissions.NONE` currently runs through the converter — under
  msgspec the default is already a `Permissions`, so no coercion needed for the default.
- `serialize_permission_overwrite` stays a hand-built dict (D11) or moves to `enc_hook`.

### 3.5 ForumTag — the `_emoji` alias (keep storage + properties)

`_emoji` does real computation (splits the raw emoji into `unicode_emoji` XOR `emoji_id`), so per the
leading-underscore rule (conventions §2) **keep `_emoji` storage + the two properties**:

```python
class ForumTag(snowflakes.Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    id: snowflakes.Snowflake = snowflakes.Snowflake.min()   # default 0 on create (was factory)
    name: str
    moderated: bool = False
    _emoji: str | int | emojis.Emoji | None = None          # ctor kwarg is `_emoji=` (see note)
    @property
    def unicode_emoji(self) -> emojis.UnicodeEmoji | None: ...   # verbatim
    @property
    def emoji_id(self) -> snowflakes.Snowflake | None: ...       # verbatim
```

- msgspec has no init-alias: the constructor kwarg is the attribute name, so `_emoji` forces
  callers/factory to pass `_emoji=` (not `emoji=`). Two choices (conventions §2): (i) keep `_emoji`
  and update the few construction sites, or (ii) add a `classmethod` constructor accepting `emoji=`.
  **VERIFY** msgspec accepts a leading-underscore field name with `field(name="emoji")` for the wire
  key (dossier 03 §6.1) before relying on (i).
- Decode is **T**: Discord sends `emoji_id` XOR `emoji_name` (`entity_factory.py:1425-1431`) — a
  sibling-typed value resolved in the residual factory into `_emoji`, then the properties split it.
- `serialize_forum_tag` (`entity_factory.py:1481`) emits `emoji_id`/`emoji_name` from `_emoji`.

### 3.6 app removal — the ~16 helpers and the two shard_id styles

| Helper cluster | Location | Re-home |
|---|---|---|
| `PartialChannel.delete` | `:395` | `rest.delete_channel(channel.id)` |
| `ChannelFollow.fetch_channel`/`fetch_webhook` | `:214`/`:243` | `rest.fetch_channel`/`rest.fetch_webhook` |
| `ChannelFollow.get_channel` | `:270` | `cache.get_guild_channel(follow.channel_id)` (cache getter) |
| `TextableChannel.*` (8) | `:424-855` | `rest.*` (`fetch_messages`, `fetch_message`, `create_message`, `trigger_typing`, `fetch_pins`, `pin_message`, `unpin_message`, `delete_messages`) |
| `GuildChannel.get_guild`/`fetch_guild`/`edit` | `:999`/`:1012`/`:1036` | `cache.get_guild` / `rest.fetch_guild` / `rest.edit_channel` |
| `PermissibleGuildChannel.edit_overwrite`/`remove_overwrite` | `:1203`/`:1263` | `edit_overwrite` infers `target_type` — **no 1:1 rest equivalent** → new rest method / free function (dossier 04; `../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md`) |

- **Two `shard_id` styles (conventions §8 gotcha):** `DMChannel.shard_id` is the constant
  `Literal[0]` (`:877`, no app) and stays a plain property; `GuildChannel.shard_id` (`:988-997`) calls
  `snowflakes.calculate_shard_id(self.app, self.guild_id)` — with `app` gone it becomes a free-function
  call `calculate_shard_id(shard_count_or_app, channel.guild_id)` at the call site (the helper already
  exists, `snowflakes.py:135-152`). Drop the `GuildChannel.shard_id` property or reduce it to a
  `guild_id`-only computation that no longer needs shard count.
- `GuildMediaChannel` uses the legacy `hash=True` class flag (`:1815`) — normalize to the standard
  `frozen=True, eq=False` like its siblings.

--------------------------------------------------------------------------------------------------

## 4. Step-by-step migration

1. Port the 6 enums to stdlib (`../02-enums/`); drop `| int` on channel enum fields.
2. Convert `PartialChannel` → frozen Struct base; drop `app`; strict `type`.
3. Establish the tagged union (with `../05-entity-factory/01`): assign each concrete channel its
   `type` tag; verify the abstract-base diamond (§3.3) or flatten to mixins.
4. Convert the concrete channels, normalizing `GuildMediaChannel`'s legacy flag; keep all non-app
   properties (`GuildThreadChannel` archive/lock props, `is_invitable`, `make_icon_url`).
5. Convert `ChannelFollow`/`PermissionOverwrite`/`ForumTag`/`ThreadMember`/`ThreadMetadata`; move
   converters to hooks/construction; keep `ForumTag._emoji` storage + properties.
6. Extract the ~16 `self.app` helpers per §3.6; `edit_overwrite` → new rest method; `shard_id`
   (guild) → free function at call sites.
7. Update the 14 channel factory sites to stop injecting `app`; route forum/media nested tags and
   sibling-typed emoji through the residual transform.

--------------------------------------------------------------------------------------------------

## 5. Affected files & symbols

| Path / anchor | Change |
|---|---|
| `hikari/channels.py:92-1463` (enums) | 6 enums → stdlib; strict fields |
| `hikari/channels.py:353-1816` (hierarchy) | frozen app-less Structs; tagged union on `type`; MRO/diamond decision |
| `hikari/channels.py:196-283` (`ChannelFollow`) | drop `app`; 3 helpers re-homed |
| `hikari/channels.py:305-349` (`PermissionOverwrite`) | converters → hooks; strict `type`; keep `serialize_*` |
| `hikari/channels.py:1476-1517` (`ForumTag`) | `_emoji` alias handling; sibling-typed decode; `Snowflake.min` default |
| `hikari/channels.py:1606-1671` (`ThreadMember`/`ThreadMetadata`) | frozen value Structs; timedelta/datetime |
| `hikari/impl/entity_factory.py:1103-1782` | drop `app`; `deserialize_channel` → union; forum/media transforms |
| `../03-app-removal-and-helpers/02-helper-method-inventory/01-channels.md` | ~16 helper re-homing |
| `../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md` | `edit_overwrite` target_type inference |

--------------------------------------------------------------------------------------------------

## 6. Risks / gotchas

1. **Multi-Struct diamond MRO** (`GuildTextChannel(PermissibleGuildChannel, TextableGuildChannel)`) —
   msgspec may reject two Struct bases sharing an ancestor. Fallback: mixin-flatten (§3.3). This is
   the biggest structural risk in the module.
2. **Tagged-union soft-skip vs raise:** channels currently **raise** on unknown type (`:1782`), which
   matches msgspec tagged-union behavior — but confirm no caller relied on the sub-mapping soft path.
3. **`ForumTag._emoji` init kwarg** becomes `_emoji=` under msgspec (no init alias); construction sites
   and the serialize path must be updated, or add a classmethod. VERIFY leading-`_` field + `field(name=)`.
4. **`shard_id` split** — dropping the app-dependent `GuildChannel.shard_id` is a public API change;
   callers must call `calculate_shard_id` themselves (breaking-changes catalog).
5. **Converters ran on defaults** (`allow`/`deny=Permissions.NONE`) — under msgspec the default is the
   final type; ensure no code depended on the converter normalizing a raw default.
6. **Forum/media "old channel omits this"** timedelta fields with `payload.get(...) or 0` defaults are
   transforms; native timedelta decode is unusable (Discord sends bare numbers, dossier 09 §2.4).
7. **`GuildMediaChannel` legacy flag** and the inconsistent `hash=True` spelling — normalize.

--------------------------------------------------------------------------------------------------

## 7. Verification

- Decode a `GUILD_TEXT` (0), a `DM` (1), a `GUILD_PUBLIC_THREAD` (11), and a `GUILD_MEDIA` (16)
  payload through the union → the correct concrete Struct each time; an unknown `type` (e.g. 99)
  raises (matching `UnrecognisedEntityError`).
- `PermissionOverwrite` round-trips: decode with string `allow`/`deny` → `Permissions`; `unset`
  computes; `serialize_permission_overwrite` emits string bitmasks.
- `ForumTag` decode with `emoji_id` → `emoji_id` property set, `unicode_emoji` None; with `emoji_name`
  → the reverse; frozen; default `id == 0`.
- Identity: two channels with equal `id` compare/hash equal; frozen (attribute set raises).
- Grep: no `self.app` in `channels.py`; the ~16 helpers resolve via `rest.*`/`cache.*`/free functions.

--------------------------------------------------------------------------------------------------

## 8. Open questions / decisions

Cross-link `../00-overview/05-decisions-log.md`:

- **Multi-Struct diamond vs mixin-flatten** for the guild-channel bases — settle in
  `../05-entity-factory/01-polymorphism-and-tagged-unions.md`.
- **`ForumTag._emoji`** keep-underscore-and-update-callers vs add-classmethod (VERIFY leading-`_`
  field name with `field(name="emoji")`).
- **D9 / new-rest:** `PermissibleGuildChannel.edit_overwrite` (target_type inference) becomes a new
  rest method / free function.
- **`shard_id` breaking change** — document caller migration to `calculate_shard_id`.
- **eq=False + Unique VERIFY** (conventions §2).
