# Entity factory: polymorphism and tagged unions

Maps every one of the factory's polymorphic dispatch tables onto a msgspec strategy: tagged unions
where the shape fits, and an explicit `msgspec.Raw` peek prepass where it does not. Also specifies
how to preserve today's split raise-vs-soft-skip behavior on unknown discriminators.

Parent: [`00-architecture-and-decode-strategy.md`](./00-architecture-and-decode-strategy.md).
Siblings: [`02-hard-cases-and-transforms.md`](./02-hard-cases-and-transforms.md),
[`03-serialize-methods.md`](./03-serialize-methods.md).

---

## 1. Objective

Replace the 19 hand-built dispatch dictionaries (dossier 05 §2) with msgspec **tagged unions**
(`Union[A, B, …]` where each arm carries a `Literal` discriminator, decoded via `tag_field`/`tag`)
wherever the discriminator is a field on the object; keep an explicit prepass only for the families
that tagged unions structurally cannot express. This serves constraint (b) — the discriminator
dispatch is separate from scalar-enum tolerance (D2) — and preserves the two distinct unknown-tag
behaviors the codebase relies on today.

---

## 2. Current state: the dispatch tables

`EntityFactoryImpl.__init__` (`hikari/impl/entity_factory.py:485`) builds 18 instance tables onto
`__slots__` (`464-483`); a 19th is module-level. Confirmed anchors in this checkout:

| # | Table | Anchor | Discriminator | Unknown-tag behavior |
|---|---|---|---|---|
| 1 | `_audit_log_entry_converters` | `487` | change `key` (str) | per-key converter; skip unknown key |
| 2 | `_audit_log_event_mapping` | `529` | `action_type` (int) | options deserializer by action |
| 3 | `_auto_mod_action_mapping` | `544` | `type` | dispatch (`4784`) |
| 4 | `_auto_mod_trigger_mapping` | `549` | `trigger_type` | dispatch (`4839`) |
| 5 | `_command_mapping` | `556` | command `type` | dispatch (`2822`) |
| 6 | `_action_row_component_type_mapping` | `561` | component `type` | **soft-skip** (`3564-3566`) |
| 7 | `_top_level_components_mapping` | `571` | component `type` | soft-skip |
| 8 | `_container_component_mapping` | `583` | component `type` | soft-skip |
| 9 | `_section_component_mapping` | `592` | component `type` | soft-skip (`3587-3589`) |
| 10 | `_section_accessory_mapping` | `596` | accessory `type` | **raise** (`3577-3581`) |
| 11 | `_modal_component_type_mapping` | `603` | component `type` | soft-skip (`3413`) |
| 12 | `_dm_channel_type_mapping` | `606` | channel `type` | raise (`1779`) |
| 13 | `_guild_channel_type_mapping` | `610` | channel `type` | raise |
| 14 | `_thread_channel_type_mapping` | `619` | channel `type` | raise |
| 15 | `_interaction_type_mapping` | `624` | `type` | raise (`3190`) |
| 16 | `_interaction_metadata_mapping` | `632` | `type` | dispatch (recurses) |
| 17 | `_scheduled_event_type_mapping` | `639` | `entity_type` | dispatch (`4349`) |
| 18 | `_webhook_type_mapping` | `644` | `type` | dispatch (`4674`) |
| 19 | `_interaction_option_type_mapping` | `81` (module) | option `type` | sibling-typed value — NOT a class union |

Two more polymorphic sites are not table-driven:
- **emoji** (`deserialize_emoji`, `2015`) dispatches by **presence of `id`**, not a type field:
  `if payload.get("id") is not None: custom else unicode`.
- **sticker** dispatches by key/context in the caller, not a self-contained tag.

---

## 3. Target design: tagged unions

msgspec decodes a tagged union by reading a discriminator field and selecting the matching Struct.
Each arm declares its literal tag; the union is a plain `Union` (or `typing.Union`) of the arms.
Two encodings apply to hikari:

### 3.1 Integer discriminators via `tag_field` + `tag`

Discord's `type`/`entity_type`/`trigger_type` are **ints**. msgspec supports an integer tag value:

```python
class GuildTextChannel(
    channel_models.PermissibleGuildChannel,
    msgspec.Struct, frozen=True, kw_only=True, eq=False,
    tag_field="type", tag=int(ChannelType.GUILD_TEXT),      # 0
):
    ...

class GuildVoiceChannel(
    channel_models.PermissibleGuildChannel,
    msgspec.Struct, frozen=True, kw_only=True, eq=False,
    tag_field="type", tag=int(ChannelType.GUILD_VOICE),     # 2
):
    ...

# The union used at the decode site:
GuildChannelU = typing.Union[GuildTextChannel, GuildVoiceChannel, GuildCategory, ...]
_guild_channel_decoder = msgspec.json.Decoder(GuildChannelU, dec_hook=dec_hook)
```

Notes / gotchas:
- `tag` must be a `Literal`-compatible constant; use `int(ChannelType.X)` so the tag is the raw wire
  int, not the enum member. The `type` field is then **consumed by the tag machinery** — do not also
  declare a `type: ChannelType` field on the arm (msgspec reserves `tag_field`).
- If callers still need `channel.type` as a `ChannelType`, expose it as a class-level constant /
  property on each arm (the value is fixed per concrete class anyway).
- All arms of one union must share the same `tag_field` string and be the same tag type (all int).
- **Verified (dossier 13 §14):** msgspec 0.21.1 accepts an `int` tag value and dispatches on a numeric
  discriminator — `tag=0`/`tag=2` with `tag_field="type"` was tested end-to-end (decode dispatches to
  the matching arm, encode injects the int). This is settled, not an open probe; native int tags are
  used for every int-discriminated family. See
  [`../12-appendices/01-open-questions-and-verifications.md`](../12-appendices/01-open-questions-and-verifications.md) §5 and
  [`../01-foundations/05-decode-boundary-and-decoders.md`](../01-foundations/05-decode-boundary-and-decoders.md).

### 3.2 Families that map cleanly to tagged unions

| Family | Arms | Tag field | Today's unknown-tag | Union raises on unknown? |
|---|---|---|---|---|
| Guild channels | 15 concrete channel classes | `type` | raise (`1779`) | yes — **matches** |
| DM / thread channels | (subsets of the 15) | `type` | raise | yes — matches |
| Interactions | command / component / autocomplete / modal | `type` | raise (`3190`) | yes — matches |
| Interaction metadata | 3 variants (recurses) | `type` | dispatch | yes (acceptable) |
| Scheduled events | external / stage / voice | `entity_type` | dispatch (`4349`) | yes (acceptable) |
| Auto-mod actions | block / alert / timeout | `type` | dispatch (`4784`) | yes (acceptable) |
| Auto-mod triggers | keyword / spam / preset / mention-spam / member-profile | `trigger_type` | dispatch (`4839`) | yes (acceptable) |
| Webhooks | incoming / channel-follower / application | `type` | dispatch (`4674`) | yes (acceptable) |
| Commands | slash / context-menu | `type` | dispatch (`2822`) | yes (acceptable) |

For the "raise" families the tagged-union default (raise `msgspec.ValidationError` on unknown tag) is
behavior-preserving — layer 2 catches `ValidationError` and re-raises `errors.UnrecognisedEntityError`
to keep the public exception type.

### 3.3 Components (the mixed family)

Components are the hard sub-case: 7 top-level types, container/section/action-row nest further, and a
**section has a polymorphic `accessory`**. The dispatch is spread over 6 tables (#6-11 above). All
components share the same `type` field, so one big `ComponentU` tagged union with per-type arms is the
natural shape — **but** the unknown-tag behavior differs by context:

- Inside an action row / container / section child list, an unknown component type is **soft-skipped**
  (`_LOGGER.debug` + `continue`, `3564-3566` / `3587-3589`).
- A section with an **unknown accessory raises** (`3577-3581`).

A single tagged union cannot do "skip on unknown here, raise on unknown there." This forces the Raw
peek prepass for the component *lists* (§4) while the section *accessory* stays a strict union (raise).

---

## 4. Families that do NOT fit tagged unions

Four cases are structurally incompatible with `tag_field`/`tag`. Each needs an explicit
`msgspec.Raw` peek-then-dispatch prepass in layer 2.

### 4.1 Emoji by key-presence (`deserialize_emoji`, `2015`)

The discriminator is **presence of the `id` key**, not a `type` field:

```python
def deserialize_emoji(self, payload) -> UnicodeEmoji | CustomEmoji:
    if payload.get("id") is not None:
        return self.deserialize_custom_emoji(payload)
    return self.deserialize_unicode_emoji(payload)
```

msgspec has no "tag by field presence." Keep an explicit prepass that peeks `id` on a
`dict[str, msgspec.Raw]` (or the decoded dict) and routes to the `CustomEmoji` vs `UnicodeEmoji`
decoder. `UnicodeEmoji` is additionally a bare `str` on the wire in some contexts (forum-tag /
reaction emoji), compounding the mismatch — see
[`02-hard-cases-and-transforms.md`](./02-hard-cases-and-transforms.md) §4.

### 4.2 Section accessory (tag reused across contexts)

`_section_accessory_mapping` (`596`) reuses `ComponentType` values that also appear as top-level and
in-row component types. A shared `ComponentU` union would let a section accessory decode as a
non-accessory component. Keep a **narrow** accessory-only union (button / thumbnail) and dispatch it
explicitly from `_deserialize_section_component` (`3574`), preserving the **raise** on unknown
accessory (`3577-3581`).

### 4.3 Audit-log options (tag is the entry's `action_type`, not a field of the options object)

`_audit_log_event_mapping` (`529`) selects the options deserializer by the **entry's**
`action_type` — a sibling field one level up, not a discriminator on the options object itself.
Tagged unions can only dispatch on a field of the object being decoded. Keep an explicit prepass in
`deserialize_audit_log_entry` (`975`) that reads `action_type`, then decodes the options blob
(`msgspec.Raw`) with the matching decoder. The separate `_audit_log_entry_converters` table (`487`,
40+ change-value converters keyed by change `key`) is a value-typing problem, not class polymorphism
— see [`02-hard-cases-and-transforms.md`](./02-hard-cases-and-transforms.md) §4.

### 4.4 Command-option value (sibling-dependent scalar typing)

`_interaction_option_type_mapping` (`81`) is not class polymorphism at all — it re-types the scalar
`value` field based on the sibling `type` (USER/CHANNEL/ROLE/MENTIONABLE/ATTACHMENT → `Snowflake`;
`_deserialize_interaction_command_option`, `2853`). Covered in
[`02-hard-cases-and-transforms.md`](./02-hard-cases-and-transforms.md) §4; listed here only to close
out table #19.

---

## 5. The `msgspec.Raw` peek prepass (preserving soft-skip)

For the soft-skip families (components in rows/containers/sections, audit entries), the target keeps
a small prepass that peeks the discriminator without fully decoding, then routes each element,
silently dropping unknowns. Sketch:

```python
# One reusable peek struct: decode ONLY the discriminator, leave the body as Raw.
class _Tagged(msgspec.Struct, frozen=True):
    type: int
    _raw: msgspec.Raw = msgspec.field(name="")     # not used; see note

_component_decoders: dict[ComponentType, msgspec.json.Decoder] = { ... }

def _deserialize_component_list(raws: list[msgspec.Raw]) -> list[PartialComponent]:
    out: list[PartialComponent] = []
    for raw in raws:
        ctype = ComponentType(_peek_type_decoder.decode(raw).type)   # peek only "type"
        decoder = _component_decoders.get(ctype)
        if decoder is None:
            _LOGGER.debug("Unknown component type %s", ctype)          # preserve soft-skip
            continue
        out.append(decoder.decode(raw))
    return out
```

Key points:
- **Peek is cheap:** decode a tiny `struct { type: int }` from the `Raw` slice, then decode the full
  arm once the type is known. Two decodes of the same bytes, but only for the outer element, not the
  whole tree.
- The **list field on the parent wire Struct is typed `list[msgspec.Raw]`** so msgspec defers the
  per-element decode to the prepass. The parent is otherwise declarative.
- **Raise families do NOT use the prepass** — they use a plain tagged union and let
  `ValidationError` propagate (re-wrapped as `UnrecognisedEntityError`). The prepass exists solely to
  keep the `_LOGGER.debug` + `continue` semantics.
- `deserialize_audit_log` (`1037`) additionally wraps whole-entry decode in try/except and skips
  entries/rules/threads/webhooks that raise `UnrecognisedEntityError` (`1044-1099`) — that outer
  tolerance stays in layer 2 regardless of the inner union/prepass choice.

---

## 6. Step-by-step migration

1. **Adopt native int tags** (§3.1) — dossier 13 §14 already verified `tag=0`/`tag=2` integer dispatch
   on msgspec 0.21.1, so every int-discriminated family uses a native tagged union; the Raw peek
   prepass (§5) is reserved for the non-tag-fittable families, not an int-tag fallback.
2. **Add `Literal`/`tag` discriminators** to each concrete Struct arm, per family, using
   `int(EnumMember)` as the tag. Do not also declare the `type` field on the arm.
3. **Assemble the unions** (`GuildChannelU`, `InteractionU`, `AutoModActionU`, `AutoModTriggerU`,
   `WebhookU`, `CommandU`, `ScheduledEventU`, `InteractionMetadataU`) and their module-level
   `Decoder`s.
4. **Build the accessory-only union** (§4.2) and wire it into `_deserialize_section_component`.
5. **Build the Raw peek prepass** (§5) for component lists (tables #6-9, #11) and the audit-log
   entry/options dispatch (#1-2).
6. **Keep the emoji key-presence prepass** (§4.1) and the sticker key/context dispatch as explicit
   layer-2 code.
7. **Re-wrap exceptions:** where a tagged union raises `msgspec.ValidationError` on an unknown tag,
   catch it at the `deserialize_*` boundary and raise `errors.UnrecognisedEntityError` so the public
   contract (and `deserialize_audit_log`'s try/except) is unchanged.
8. **Delete the 18 instance tables** and `EntityFactoryImpl.__slots__` entries as each family is
   converted; the module-level `_interaction_option_type_mapping` moves to the value-typing transform.

---

## 7. Affected files and symbols

| Path | Anchor | Change |
|---|---|---|
| `hikari/impl/entity_factory.py` | `464-483` | drop 18 dispatch-table slots |
| `hikari/impl/entity_factory.py` | `487-651` | delete table construction in `__init__` |
| `hikari/impl/entity_factory.py` | `deserialize_channel` `1761` | tagged union + re-wrap raise |
| `hikari/impl/entity_factory.py` | `deserialize_interaction` `3182` | tagged union + re-wrap raise |
| `hikari/impl/entity_factory.py` | `_deserialize_section_component` `3574` | accessory union (raise) + child prepass (skip) |
| `hikari/impl/entity_factory.py` | `_deserialize_action_row_component` `3556` | Raw peek prepass (skip) |
| `hikari/impl/entity_factory.py` | `deserialize_emoji` `2015` | key-presence prepass |
| `hikari/impl/entity_factory.py` | `deserialize_audit_log_entry` `975` / `deserialize_audit_log` `1037` | action_type prepass + outer try/except |
| `hikari/channels.py`, `hikari/interactions/*`, `hikari/components.py`, `hikari/scheduled_events.py`, `hikari/auto_mod.py`, `hikari/webhooks.py`, `hikari/commands.py` | model modules | add `tag_field`/`tag` to arms (see [`../06-model-modules/`](../06-model-modules/)) |

---

## 8. Risks and gotchas

- **Int-tag support is verified.** dossier 13 §14 tested `tag=0`/`tag=2` integer dispatch end-to-end
  on msgspec 0.21.1 (`tag_field="type"`, decode dispatches, encode injects the int), so the native
  tagged-union plan holds for every int-discriminated family. The Raw peek prepass is needed only for
  the genuinely non-tag-fittable families (emoji key-presence, section accessory, audit-log sibling
  `action_type`, soft-skip component lists), not as an int-tag contingency.
- **`type` field consumption.** Once a field is used as `tag_field`, it is no longer a normal field —
  code reading `entity.type` must get it from a class constant/property, not a Struct field.
- **Tag-value drift.** The tag literal must equal the raw wire int; if an enum member's value changes,
  the tag must track it. Deriving tags via `int(EnumMember)` keeps them in lockstep.
- **Mixed soft/hard failure within components.** A single union cannot express both; the section
  accessory (raise) and the child lists (skip) must be split into a strict union + a prepass.
- **Exception-type compatibility.** Downstream code (and `deserialize_audit_log`) catches
  `errors.UnrecognisedEntityError`, not `msgspec.ValidationError`; the re-wrap is mandatory.

---

## 9. Verification

1. **Per-arm decode.** For each union, decode a real payload of every arm and assert the concrete
   type and fields match the current output.
2. **Unknown tag = raise.** Feed an unknown `type` to channels/interactions/section-accessory; assert
   `errors.UnrecognisedEntityError` is raised (not `ValidationError`).
3. **Unknown tag = skip.** Feed an action row / container / modal / section-child list containing an
   unknown component type; assert the unknown element is dropped and the rest survive, and that a
   debug log line is emitted.
4. **Audit-log tolerance.** Feed an audit log with an entry that raises; assert the surrounding
   entries/rules/threads/webhooks still decode (`1044-1099` semantics).
5. **Emoji dispatch.** Assert `{"id": null, "name": "😀"}` → `UnicodeEmoji` and `{"id": "123", …}` →
   `CustomEmoji`.

---

## 10. Open questions and decisions

Consolidated in the master gate
[`../12-appendices/01-open-questions-and-verifications.md`](../12-appendices/01-open-questions-and-verifications.md);
the polymorphism items map onto it as follows:

- **Int tags:** **resolved / verified** — dossier 13 §14 tested `tag=0`/`tag=2` integer dispatch on
  msgspec 0.21.1 end-to-end (`tag_field="type"`, decode dispatches, encode injects the int). Not an
  open probe; native int tags are used for every int-discriminated family, and the Raw peek prepass
  (§4-5) is reserved for the non-tag-fittable families only.
- **Soft-skip vs raise:** consolidated probe **V9** (+ decision **Q8**) — confirmed split: raise
  families use native unions (+ re-wrap), soft-skip families use the Raw peek prepass. Confirm no
  downstream code depends on the *order* of soft-skipped elements being preserved (it is, since the
  prepass iterates in wire order).
- **Accessory union scope:** open confirmation, folded into the per-union reconciliation (V9/Q8) —
  confirm the accessory-only union (button/thumbnail) matches Discord's current accessory type set;
  new accessory types must raise, matching `3577-3581`.
