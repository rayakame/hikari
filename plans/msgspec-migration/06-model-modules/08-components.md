# Components

Purpose: migrate `hikari/components.py` — 17 message/modal component classes plus 5 enums and the type
unions that drive polymorphic decode. This is the most polymorphism-dense model module: top-level
components, action-row children, container children, and section accessories each form a discriminated
set keyed on Discord's `type` int, decoded with **mixed soft-skip / hard-raise** semantics
(dossier 05 §4/§6.2).

--------------------------------------------------------------------------------------------------

## 1. Objective

- Freeze the 17 classes (`frozen=True, kw_only=True`); they are value objects (not `Unique`).
- Keep the 5 enums as hikari's custom int enums (adopt #2770); strict-type every enum field
  (drop `| int`), decoded via the shared `dec_hook`.
- Model the four polymorphic sets as msgspec **tagged unions** keyed on `type`
  (`../05-entity-factory/01-polymorphism-and-tagged-unions.md`), preserving the exact soft-skip vs
  raise behavior per context.
- Resolve `MediaResource(files.Resource)` via the shared Resource decision
  (`03-emojis-and-files-resources.md`).
- Handle `ActionRowComponent` (Generic + currently positional, one of only 2 non-`kw_only` model
  classes, dossier 03 §2).
- No `app` field, no helper methods in this module.

Decode classification: **P** throughout, with **T** where a `MediaResource` wraps a URL via
`files.ensure_resource` and where containers/sections nest further polymorphic children.

--------------------------------------------------------------------------------------------------

## 2. Current state (file:line anchors)

### 2.1 Enums
| Enum | Anchor | Members |
|---|---|---|
| `ComponentType` | `components.py:77-181` | `ACTION_ROW=1 .. SEPARATOR=14, CONTAINER=17` (gaps 15/16) |
| `ButtonStyle` | `components.py:184-218` | `PRIMARY=1 .. PREMIUM=6` |
| `TextInputStyle` | `components.py:221-229` | `SHORT=1`, `PARAGRAPH=2` |
| `SpacingType` | `components.py:232-243` | `SMALL=1`, `LARGE=2` |
| `MediaLoadingType` | `components.py:246-260` | `UNKNOWN=0 .. LOADED_NOT_FOUND=3` |

### 2.2 Base + polymorphic members
- `PartialComponent` — `components.py:263-271`; `type: ComponentType | int` (`:267`), `id: int`
  (`:270`, a component id, not a Snowflake). Base of all components.
- `ActionRowComponent(PartialComponent, typing.Generic[AllowedComponentsT])` — `components.py:277-297`;
  **`@attrs.define(weakref_slot=False)` — positional, NOT kw_only.** `components` field +
  `__getitem__`/`__iter__`/`__len__` (Sequence-like). `AllowedComponentsT` bound to `PartialComponent`.
- `ButtonComponent` — `components.py:300-329`; `unsafe_hash`, `hash=True` on **`custom_id`** (identity
  by custom_id). `style: ButtonStyle | int`, `label`, `emoji`, `custom_id`, `url`, `is_disabled`.
- `SelectMenuOption` — `components.py:332-349`; `label`, `value`, `description`, `emoji`, `is_default`.
- `SelectMenuComponent` — `components.py:352-377`; `unsafe_hash`, `hash=True` on `custom_id`;
  `placeholder`, `min_values`, `max_values`, `is_disabled`.
- `TextSelectMenuComponent(SelectMenuComponent)` — `components.py:380-385`; `options`.
- `ChannelSelectMenuComponent(SelectMenuComponent)` — `components.py:388-393`; `channel_types:
  Sequence[int | channels.ChannelType]`.
- `TextInputComponent` — `components.py:396-404`; `custom_id`, `value` (modal submit).
- `MediaResource(files.Resource[files.AsyncReader])` — `components.py:407-474`; `resource`,
  `proxy_resource`, `width`/`height`/`content_type`/`loading_state` (all `UndefinedNoneOr`),
  computed `url`/`filename`/`proxy_url`/`proxy_filename` properties, `stream`. **Resource mixin.**
- `SectionComponent` — `components.py:477-485`; `components: Sequence[SectionComponentTypesT]`,
  `accessory: SectionAccessoryTypesT`.
- `ThumbnailComponent` — `components.py:488-499`; `media: MediaResource`, `description`, `is_spoiler`.
- `TextDisplayComponent` — `components.py:502-507`; `content`.
- `MediaGalleryComponent` — `components.py:510-515`; `items`.
- `MediaGalleryItem` — `components.py:518-529`; `media`, `description`, `is_spoiler`.
- `SeparatorComponent` — `components.py:532-540`; `spacing: SpacingType`, `divider`.
- `FileComponent` — `components.py:543-551`; `file: MediaResource`, `is_spoiler`.
- `ContainerComponent` — `components.py:554-565`; `accent_color: Color | None`, `is_spoiler`,
  `components: Sequence[ContainerTypesT]`.

### 2.3 Type unions (drive dispatch)
- `TopLevelComponentTypesT` — `components.py:568-588` (ActionRow, TextDisplay, Section, MediaGallery,
  Separator, File, Container).
- `ContainerTypesT` — `components.py:590-608` (same minus Container).
- `SectionComponentTypesT = TextDisplayComponent` — `components.py:610`.
- `SectionAccessoryTypesT = ButtonComponent | ThumbnailComponent` — `components.py:618`.

### 2.4 Factory dispatch (mixed soft-skip / raise)
| Method | Anchor | Unknown-type behavior |
|---|---|---|
| `_deserialize_top_level_components` | `entity_factory.py:3430` | **soft-skip** (`_LOGGER.debug`, `:3441`) |
| `_deserialize_action_row_component` | `entity_factory.py:3556` | **soft-skip** (`:3565`) |
| `_deserialize_section_component` | `entity_factory.py:3574` | accessory **RAISES** `UnrecognisedEntityError` (`:3578-3580`); section child **soft-skip** (`:3588`) |
| `_deserialize_container_component` | `entity_factory.py:3645` | **soft-skip** (`:3658`) |
| `_deserialize_modal_components` | `entity_factory.py:3396` | **soft-skip** (`:3405`/`:3414`) |

Dispatch tables: `_top_level_components_mapping` (`entity_factory.py:452-463`),
`_container_component_mapping` (`:464-472`), `_section_component_mapping` (`:473-476`),
`_section_accessory_mapping` (`:477-483`), `_action_row_component_type_mapping` (`:442-451`),
`_modal_component_type_mapping` (`:484-486`).

--------------------------------------------------------------------------------------------------

## 3. Target design

### 3.1 Enums — strict custom int enums (adopt #2770; `../02-enums/00-strategy-and-forward-compat.md`), each decoded via the shared `dec_hook` with an `is_unknown` pseudo-member on a miss.

### 3.2 Base + tags
```python
class PartialComponent(msgspec.Struct, frozen=True, kw_only=True):
    type: ComponentType        # strict (drop `| int`); doubles as the union tag discriminator
    id: int

class ButtonComponent(PartialComponent, frozen=True, kw_only=True, tag_field="type",
                      tag=int(ComponentType.BUTTON)):        # tag = 2
    style: ButtonStyle         # strict
    label: str | None
    emoji: emojis.Emoji | None
    custom_id: str | None
    url: str | None
    is_disabled: bool
```
Every concrete component becomes a tagged member (`tag_field="type"`, `tag=<int value>`), so a
`msgspec.json.Decoder(SomeUnion)` dispatches on the wire `type`. `PartialComponent.type` remains a real
field carrying the enum; the tag and the field coincide (verify msgspec allows the tag field to also
be read back as the enum — otherwise expose `type` as a `ClassVar`/property and keep the tag internal).

### 3.3 `ActionRowComponent` (Generic, kw_only-ify)
```python
class ActionRowComponent(PartialComponent, typing.Generic[AllowedComponentsT],
                         frozen=True, kw_only=True, tag=int(ComponentType.ACTION_ROW)):   # tag = 1
    components: typing.Sequence[AllowedComponentsT]
    # __getitem__ / __iter__ / __len__ port verbatim
```
Convert it from positional to `kw_only=True` (conventions §2 mandates kw_only on the hierarchy;
positional here was incidental). msgspec supports Generic Structs; confirm the `AllowedComponentsT`
bound resolves under the frozen base. The two aliases `MessageActionRowComponent =
ActionRowComponent[MessageComponentTypesT]` and `ModalActionRowComponent =
ActionRowComponent[ModalComponentTypesT]` (`components.py:712-715`) are unchanged.

### 3.4 `MediaResource` (Resource mixin + tri-state)
```python
class MediaResource(files.Resource[files.AsyncReader], msgspec.Struct, frozen=True, kw_only=True):
    resource: files.Resource[files.AsyncReader]
    proxy_resource: files.Resource[files.AsyncReader] | None = None
    width: undefined.UndefinedNoneOr[int] = undefined.UNDEFINED
    height: undefined.UndefinedNoneOr[int] = undefined.UNDEFINED
    content_type: undefined.UndefinedNoneOr[str] = undefined.UNDEFINED
    loading_state: undefined.UndefinedNoneOr[MediaLoadingType] = undefined.UNDEFINED   # strict
    # url/filename/proxy_url/proxy_filename properties + stream verbatim
```
Same Resource-mixin resolution as `Attachment`/`EmbedResource` (`03-emojis-and-files-resources.md`).
`MediaResource` is built by wrapping a URL via `files.ensure_resource` (**T**), not decoded straight.

### 3.5 Tagged unions and soft-skip
- `SectionAccessoryTypesT = Union[ButtonComponent, ThumbnailComponent]` maps to a plain msgspec tagged
  union that **raises on unknown tag** — matching the current accessory RAISE (`entity_factory.py:3578`).
- `TopLevelComponentTypesT`, `ContainerTypesT`, action-row children, section children, and modal
  children currently **soft-skip** unknown types. A bare `list[Union[...]]` decode raises on an
  unknown tag, so preserve soft-skip via a `msgspec.Raw` peek-then-dispatch prepass that filters out
  unknown `type` values before decoding each member (dossier 05 §6.2, conventions §3). This prepass
  lives in the residual factory / decode layer, detailed in
  `../05-entity-factory/01-polymorphism-and-tagged-unions.md`.

--------------------------------------------------------------------------------------------------

## 4. Step-by-step migration

1. Adopt #2770 for the 5 enums — keep them custom int enums, strict-type the fields.
2. Resolve the `files.Resource` mixin (`03-emojis-and-files-resources.md`); convert `MediaResource`.
3. Convert `PartialComponent` → frozen Struct with strict `type`; add `tag_field="type"` + per-class
   `tag=` on every concrete component.
4. Convert `ActionRowComponent` to `kw_only=True` frozen Generic Struct; keep the Sequence dunders.
5. Convert the remaining components + `SelectMenuOption`/`MediaGalleryItem` to frozen Structs; strict
   `ButtonComponent.style`, `ChannelSelectMenuComponent.channel_types`, `MediaResource.loading_state`.
6. Define the four msgspec tagged unions; wire the accessory union to raise and the top-level/
   action-row/container/modal unions to the soft-skip prepass.
7. Slim the six `_deserialize_*_component(s)` methods to the union decoders + prepass, preserving the
   exact soft-skip/raise matrix (§2.4).

--------------------------------------------------------------------------------------------------

## 5. Affected files & symbols

| Path / anchor | Change |
|---|---|
| `hikari/components.py:77-260` | 5 enums stay custom; adopt #2770 (strict fields, `is_unknown`) |
| `hikari/components.py:263-271` | `PartialComponent` → frozen Struct, strict `type`, `tag_field` base |
| `hikari/components.py:277-297` | `ActionRowComponent` → `kw_only` frozen Generic Struct |
| `hikari/components.py:300-565` | 14 component classes + `SelectMenuOption`/`MediaGalleryItem` → frozen Structs, tags, strict enums |
| `hikari/components.py:407-474` | `MediaResource` → frozen Struct (Resource mixin, tri-state fields) |
| `hikari/impl/entity_factory.py:442-486` | 6 dispatch tables (top-level/container/section/accessory/action-row/modal) |
| `hikari/impl/entity_factory.py:3396-3670` | 6 `_deserialize_*_component(s)` → tagged unions + soft-skip prepass |
| `../05-entity-factory/01-polymorphism-and-tagged-unions.md` | union design + soft-skip prepass |

--------------------------------------------------------------------------------------------------

## 6. Risks / gotchas

1. **Soft-skip vs raise asymmetry** — section accessory raises on unknown type; every other component
   context soft-skips. A single uniform tagged-union decode would raise everywhere, changing behavior
   for forward-compat (new Discord component types would break existing messages). The Raw-peek
   prepass is mandatory for the soft-skip contexts.
2. **`ActionRowComponent` Generic + positional** — must become `kw_only`; verify msgspec Generic
   Struct + frozen + the `AllowedComponentsT` bound; verify the Sequence dunders coexist with slots.
3. **Tag field doubles as data field** — `type` is both the union discriminator and a public field.
   Confirm msgspec `tag_field="type"` still surfaces `type` as a readable enum member; if not, make
   `type` a `ClassVar`/property returning the tag.
4. **Identity change** — `ButtonComponent`/`SelectMenuComponent` hash by `custom_id` today
   (`unsafe_hash` + `hash=True` on `custom_id`); under frozen `eq=False`/default this changes. Since
   components are rarely used as dict keys, recommend `eq=False` (object identity) with a changelog
   note, or accept msgspec default all-field eq where fields are hashable (buttons hold no list/dict).
5. **`MediaResource` mixin + tri-state** — combines the Resource hazard with four `UndefinedNoneOr`
   fields (role (ii), D5).
6. **`id: int` is not a Snowflake** — the component `id` is a plain int (component index), not a
   snowflake; do not route it through the Snowflake hook.

--------------------------------------------------------------------------------------------------

## 7. Verification

- Decode a message `components` array with a top-level unknown `type` → the unknown component is
  skipped, the rest decode (soft-skip preserved).
- Decode a `SectionComponent` with an unknown accessory `type` → `UnrecognisedEntityError` (raise
  preserved).
- Decode a `ButtonComponent` → `style` a `ButtonStyle`, `type` `ComponentType.BUTTON`.
- Decode a `ChannelSelectMenuComponent` → `channel_types` a sequence of `ChannelType`.
- `ActionRowComponent[...]` supports `row[0]`, `len(row)`, `iter(row)`; frozen (field set raises).
- `MediaResource(...).url` equals the wrapped resource URL; `loading_state` absent → `UNDEFINED`.

--------------------------------------------------------------------------------------------------

## 8. Open questions / decisions

Cross-link `../00-overview/05-decisions-log.md`:

- **D2 / soft-skip:** the Raw-peek prepass to keep soft-skip semantics for top-level/action-row/
  container/modal components while the accessory union raises — settled in
  `../05-entity-factory/01-polymorphism-and-tagged-unions.md`.
- **Tag-field-as-data-field** — VERIFY msgspec exposes `type` after `tag_field="type"`.
- **Component identity** — `eq=False` vs default all-field eq for `ButtonComponent`/
  `SelectMenuComponent` (was custom_id-hash).
- **Resource mixin** — resolved in `03-emojis-and-files-resources.md`.
