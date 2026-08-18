# Commands

Purpose: migrate `hikari/commands.py` — the `PartialCommand`→`SlashCommand`/`ContextMenuCommand`
application-command hierarchy plus `CommandOption`, `CommandChoice`, `CommandPermission`, and
`GuildCommandPermissions`, with 3 enums. Notable: `PartialCommand.app` is the **outlier app field
without `SKIP_DEEP_COPY`** (dossier 03 §7.2), the command hierarchy is a `type`-discriminated union,
and `CommandPermission` is a user-built model carrying attrs `converter=`s.

--------------------------------------------------------------------------------------------------

## 1. Objective

- Freeze the 7 classes (`frozen=True, kw_only=True`); id-only identity from `snowflakes.Unique` on the
  command hierarchy.
- Remove the live `PartialCommand.app` field (`commands.py:220`) and its **5** `self.app.*` helpers;
  re-home per `../03-app-removal-and-helpers/02-helper-method-inventory/05-templates-presences-commands.md`.
- Port `CommandType`/`OptionType`/`CommandPermissionType` to stdlib int enums; strict-type every enum
  field.
- Model `PartialCommand`→`SlashCommand`/`ContextMenuCommand` as a `type`-tagged union (raises on
  unknown, `entity_factory.py:2825-2827`).
- Preserve localization enum-keyed maps, the recursive `CommandOption.options`, and the
  `CommandPermission` coercion previously done by `converter=`.

Decode classification: `CommandChoice`/`GuildCommandPermissions` **D**; `CommandOption` **D** (native
recursion + `int | float` unions); the command hierarchy **P**; `CommandPermission` **D/B** (user-built
+ serialized).

--------------------------------------------------------------------------------------------------

## 2. Current state (file:line anchors)

### 2.1 Enums
| Enum | Anchor | Target |
|---|---|---|
| `CommandType` | `commands.py:56-66` (SLASH/USER/MESSAGE) | int enum + `_missing_` |
| `OptionType` | `commands.py:69-111` (SUB_COMMAND..ATTACHMENT) | int enum |
| `CommandPermissionType` | `commands.py:466-477` (ROLE/USER/CHANNEL) | int enum |

### 2.2 Value objects
- `CommandChoice` — `commands.py:113-127`; `name`, `name_localizations: Mapping[Locale | str, str]`
  (`factory=dict`), `value: str | int | float`. **D.**
- `CommandOption` — `commands.py:130-212`; `type: OptionType | int`, `name`, `description`,
  `is_required` (default False), `choices: Sequence[CommandChoice] | None`, **`options:
  Sequence[CommandOption] | None`** (recursive self-reference), `channel_types: Sequence[ChannelType |
  int] | None`, `autocomplete`, `min_value`/`max_value: int | float | None`, `name_localizations`/
  `description_localizations` (`factory=dict`), `min_length`/`max_length`. **D.**
- `CommandPermission` — `commands.py:479-497`; `id: Snowflake` (`converter=snowflakes.Snowflake`,
  `:484`), `type: CommandPermissionType | int` (`converter=CommandPermissionType`, `:493`),
  `has_access`. **User-built** (a caller may pass raw int/str). Serialized via
  `serialize_command_permission` (`entity_factory.py:2850`).
- `GuildCommandPermissions` — `commands.py:500-523`; `id`, `application_id`, `command_id`, `guild_id`,
  `permissions: Sequence[CommandPermission]`. **D.**

### 2.3 Command hierarchy
- `PartialCommand(snowflakes.Unique)` — `commands.py:215-437`; **`app` field at `:220` with
  `eq=False, hash=False` but NO `SKIP_DEEP_COPY` metadata** (outlier). `id` (`hash=True`), `type:
  CommandType` (`hash=True` — part of identity), `application_id`, `name`, `default_member_permissions:
  Permissions`, `is_nsfw`, `guild_id`, `version`, `name_localizations: Mapping[Locale | str, str]`,
  `integration_types: Sequence[ApplicationIntegrationType]`, `context_types:
  Sequence[ApplicationContextType]`. **5 helpers:** `fetch_self` (`:269`), `edit` (`:295`), `delete`
  (`:346`), `fetch_guild_permissions` (`:367`), `set_guild_permissions` (`:400`) — all `self.app.rest`.
- `SlashCommand(PartialCommand)` — `commands.py:439-457`; `description`,
  `description_localizations`, `options: Sequence[CommandOption] | None`.
- `ContextMenuCommand(PartialCommand)` — `commands.py:460-463`; no extra fields.

Factory: `SlashCommand` `app=self._app` at `entity_factory.py:2747`, `ContextMenuCommand` at `:2799`;
dispatch table `_command_mapping` (`:437-441`), raises `UnrecognisedEntityError` on unknown type
(`:2825-2827`). Serialize: `serialize_command_option` (`:3237`), `serialize_command_permission`
(`:2850`).

--------------------------------------------------------------------------------------------------

## 3. Target design

### 3.1 Enums → stdlib int enums (`../02-enums/02-int-and-str-enums-migration.md`).
Strict-type: `CommandOption.type`→`OptionType`, `CommandOption.channel_types`→`Sequence[ChannelType]`,
`CommandPermission.type`→`CommandPermissionType`. `integration_types`/`context_types` already strict.

### 3.2 Value objects
```python
class CommandChoice(msgspec.Struct, frozen=True, kw_only=True):
    name: str
    value: str | int | float
    name_localizations: typing.Mapping[locales.Locale, str] = msgspec.field(default_factory=dict)

class CommandOption(msgspec.Struct, frozen=True, kw_only=True):
    type: OptionType                                   # strict
    name: str
    description: str
    is_required: bool = False
    choices: typing.Sequence[CommandChoice] | None = None
    options: typing.Sequence["CommandOption"] | None = None      # recursive; msgspec-native
    channel_types: typing.Sequence[channels.ChannelType] | None = None
    autocomplete: bool = False
    min_value: int | float | None = None               # msgspec disambiguates int vs float by token
    max_value: int | float | None = None
    name_localizations: typing.Mapping[locales.Locale, str] = msgspec.field(default_factory=dict)
    description_localizations: typing.Mapping[locales.Locale, str] = msgspec.field(default_factory=dict)
    min_length: int | None = None
    max_length: int | None = None
```
The recursive `options` field decodes natively (msgspec supports self-referential Structs). `min_value`/
`max_value`/`CommandChoice.value` are `int | float` unions — msgspec picks `int` for an integer JSON
token and `float` otherwise; document that a whole-number FLOAT option value decodes as `int` (put
`int` first, matching current behavior). The docstring "sibling-typed by option type" is informational;
no sibling-dependent decode is needed here — the genuinely sibling-typed value lives on
`CommandInteractionOption.value` (`11-interactions.md` §3.3).

### 3.3 `CommandPermission` — converters → typed fields
```python
class CommandPermission(msgspec.Struct, frozen=True, kw_only=True):
    id: snowflakes.Snowflake                # was converter=Snowflake; scalar hook handles wire str/int
    type: CommandPermissionType             # was converter=CommandPermissionType; strict enum
    has_access: bool
```
msgspec has no `converter=`; on decode the Snowflake hook + strict enum give the same coercion. On
**user construction**, callers previously passed a raw `int`/`str` and attrs coerced it — decide
whether to keep that lenience via a classmethod constructor or require the exact types (recommend
requiring exact types for the frozen Struct, with input lenience preserved only at the REST parameter
layer, conventions §3). `serialize_command_permission` reads these fields as-is
(`../05-entity-factory/03-serialize-methods.md`).

### 3.4 Command hierarchy → tagged union (app-less)
```python
class PartialCommand(snowflakes.Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False,
                     tag_field="type"):
    id: snowflakes.Snowflake
    type: CommandType
    # NO app field.
    application_id: snowflakes.Snowflake
    name: str
    default_member_permissions: permissions.Permissions
    is_nsfw: bool
    guild_id: snowflakes.Snowflake | None
    version: snowflakes.Snowflake
    name_localizations: typing.Mapping[locales.Locale, str]
    integration_types: typing.Sequence[applications.ApplicationIntegrationType]
    context_types: typing.Sequence[applications.ApplicationContextType]

class SlashCommand(PartialCommand, frozen=True, kw_only=True, eq=False, tag=int(CommandType.SLASH)):
    description: str
    description_localizations: typing.Mapping[locales.Locale, str]
    options: typing.Sequence[CommandOption] | None

class ContextMenuCommand(PartialCommand, frozen=True, kw_only=True, eq=False,
                         tag=int(CommandType.USER)):   # USER & MESSAGE share this class; see §6
    ...
```
Dispatch on `type` via a tagged union that **raises** on unknown (matches
`entity_factory.py:2825-2827`), `../05-entity-factory/01-polymorphism-and-tagged-unions.md`. The 5
`self.app.*` helpers are removed; callers use `rest.fetch_application_command(...)` etc. with the
command's `application_id`/`id`/`guild_id` (all plain fields).

--------------------------------------------------------------------------------------------------

## 4. Step-by-step migration

1. Port the 3 enums to stdlib int enums.
2. Convert `CommandChoice`/`CommandOption` (recursive, localization maps, strict enums) to frozen
   Structs.
3. Convert `CommandPermission`/`GuildCommandPermissions`; drop `converter=`, rely on the Snowflake hook
   + strict enum; decide user-construction lenience (§3.3).
4. Convert `PartialCommand`: drop the outlier `app` field, add `tag_field="type"`, strict-type,
   localization map; extract the 5 helpers.
5. Convert `SlashCommand`/`ContextMenuCommand` as tagged members; resolve the USER/MESSAGE tag mapping
   (§6).
6. Slim the factory: drop `SlashCommand`/`ContextMenuCommand` app injection; keep the tagged-union
   dispatch (raise on unknown); update `serialize_command_option`/`serialize_command_permission` to
   read the Struct fields.

--------------------------------------------------------------------------------------------------

## 5. Affected files & symbols

| Path / anchor | Change |
|---|---|
| `hikari/commands.py:56-111,466-477` | 3 enums → stdlib |
| `hikari/commands.py:113-212` | `CommandChoice`/`CommandOption` → frozen Structs; recursion; localization; strict enums |
| `hikari/commands.py:215-437` | `PartialCommand` → frozen Struct; drop outlier `app`; `tag_field`; extract 5 helpers |
| `hikari/commands.py:439-463` | `SlashCommand`/`ContextMenuCommand` → tagged members |
| `hikari/commands.py:479-523` | `CommandPermission`(drop converters)/`GuildCommandPermissions` → Structs |
| `hikari/impl/entity_factory.py:437-441,2747,2799,2825` | `_command_mapping` tagged dispatch; drop app injection |
| `hikari/impl/entity_factory.py:2850,3237` | `serialize_command_permission`/`serialize_command_option` read Struct fields |
| `../03-app-removal-and-helpers/02-helper-method-inventory/05-templates-presences-commands.md` | 5 helper re-homings |

--------------------------------------------------------------------------------------------------

## 6. Risks / gotchas

1. **`app` outlier without `SKIP_DEEP_COPY`** (`commands.py:220`) — under the old copy machinery the
   command `app` was deep-copied (a latent inconsistency); removing the field makes it moot. Note it so
   the reviewer does not treat the missing metadata as intentional.
2. **`CommandType` USER vs MESSAGE → one class** — both `USER=2` and `MESSAGE=3` deserialize to
   `ContextMenuCommand` (only SLASH maps to `SlashCommand`). A tag can only map to one class, so a
   single `tag=` cannot cover two enum values. Either give `ContextMenuCommand` a custom tag matcher /
   two tags, or keep a thin hand dispatch for the command union (recommend the latter; note in
   `../05-entity-factory/01-polymorphism-and-tagged-unions.md`).
3. **Identity narrows from `(id, type)` to `id`** — attrs put `type` in the hash (`:226`); under
   `eq=False` + inherited `Unique` dunders, identity is id-only. Command ids are globally unique, so
   this is a no-op in practice but is a behavior note.
4. **`int | float` union ordering** — a whole-number FLOAT `value`/`min_value`/`max_value` decodes as
   `int`; keep `int` first to match current behavior, or coerce in a transform if float-ness must be
   preserved.
5. **`CommandPermission` user-construction** — dropping `converter=` removes the raw-int/str lenience
   at construction; keep it only at the REST-parameter boundary (conventions §3).
6. **Localization maps** — `Mapping[Locale, str]` keyed on a str-enum with `default_factory=dict`;
   unknown locales become str-enum pseudo-members (`../02-enums/`).

--------------------------------------------------------------------------------------------------

## 7. Verification

- Decode a `SlashCommand` → `type` `CommandType.SLASH`, `options` a sequence of `CommandOption` with a
  nested recursive `options`; `default_member_permissions` a `Permissions`.
- Decode a USER and a MESSAGE command → both `ContextMenuCommand` with the correct `type`.
- Decode an unknown command `type` → `UnrecognisedEntityError`.
- Construct a `CommandPermission(id=..., type=CommandPermissionType.ROLE, has_access=True)` and
  round-trip through `serialize_command_permission`.
- Grep proves no `self.app` remains in `commands.py`; the 5 helpers resolve via `rest.*`.

--------------------------------------------------------------------------------------------------

## 8. Open questions / decisions

Cross-link `../00-overview/05-decisions-log.md`:

- **Command union USER/MESSAGE→one class** — tagged union cannot map two tags to one class cleanly;
  keep a thin hand dispatch (recommended) — settle in
  `../05-entity-factory/01-polymorphism-and-tagged-unions.md`.
- **`CommandPermission` construction lenience** — drop `converter=` coercion at construction (keep at
  REST layer) vs add a coercing classmethod.
- **`int | float` value ordering** — confirm `int`-first matches expectations for FLOAT options.
- **eq=False + `Unique`** — identity narrows to id-only (VERIFY, conventions §2).
