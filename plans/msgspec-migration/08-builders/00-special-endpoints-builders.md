# Special-endpoints builders (outbound serialization)

Scope: the 40 concrete builder classes in `hikari/impl/special_endpoints.py`
(44 interfaces in `hikari/api/special_endpoints.py`) plus the 7
`entity_factory.serialize_*` methods they compose. These objects serialize **to**
Discord and are **never JSON-decoded**. This file applies decision **D11**: keep the
builders as-is (mutable, dict-emitting) in the first pass; msgspec only replaces the
encoder underneath. From dossier 06.

---

## 1. Objective

- Serve constraint (c) with an explicit **exemption**: builders are mutable fluent state
  machines and **must not be frozen** — see §3.
- Keep the outbound serialization pipeline unchanged while `orjson.dumps` is swapped for
  `msgspec.json.encode` (the JSON-layer swap lives in
  [`../01-foundations/04-json-data-binding.md`](../01-foundations/04-json-data-binding.md)).
- Preserve the tri-state `UNDEFINED`/`None`/value PATCH semantics that Discord edits
  depend on, and the `X | int` outbound escape hatches when enums go strict.
- Constraint (a) is already satisfied here: builders hold no `app`.

---

## 2. Current state

### 2.1 Builders assemble dicts by hand; they never serialize themselves

Every `build()` returns a plain `dict` (via `data_binding.JSONObjectBuilder`, a `dict`
subclass) out of primitives + `int`-subclasses. The attrs class is just a mutable holder
with a fluent `set_*`/`add_*` API (dossier 06 §0/§1.2). Example
(`AutocompleteChoiceBuilder`, `special_endpoints.py:852-877`):

```python
_name: str = attrs.field(alias="name")
_value: int | str | float = attrs.field(alias="value")
@property
def name(self) -> str: return self._name
def set_name(self, name: str, /) -> Self:
    self._name = name          # mutation — incompatible with frozen
    return self
def build(self) -> typing.MutableMapping[str, typing.Any]:
    return {"name": self._name, "value": self._value}
```

40 concrete builders (grep `class .*Builder(` in impl), 44 interfaces in api (extra
interfaces are pure-ABC parents: `InteractionResponseBuilder`, `ComponentBuilder`,
`ButtonBuilder`, `SelectMenuBuilder`, `AutoModActionBuilder`, `AutoModTriggerBuilder`).
Full class table with line anchors: dossier 06 §1.1. **No `GuildBuilder` exists** — guild
creation is inline in `RESTClientImpl.create_guild` (dossier 06 §1.1).

### 2.2 Four `build()` contracts (dossier 06 §2)

| Contract | Signature | Users |
|---|---|---|
| A | `build() -> MutableMapping` | autocomplete choice, onboarding, select option, poll, all auto-mod builders |
| B | `build(entity_factory, /) -> MutableMapping` | command builders (serialize `CommandOption`s) |
| C | `build(entity_factory, /) -> tuple[MutableMapping, Sequence[Resource]]` | interaction responses |
| D | `build() -> tuple[MutableMapping, Sequence[Resource]]` | components (v2 media components return the wrapped `files.Resource`) |

The `entity_factory` arg is a **call parameter**, not stored state; no builder captures
`app` (dossier 06 §0.3). Command builders' `create(rest, application, …)`
(`special_endpoints.py:1663/1699`) already take `rest` explicitly — they match the
constraint-(a) target model.

### 2.3 Builders are inherently mutable and CANNOT be frozen (dossier 06 §0.2/§10.1)

- 100+ `set_*`/`add_*`/`clear_*` methods do `self._x = …; return self`.
- `__attrs_post_init__` writes derived fields, e.g.
  `self._emoji_id, self._emoji_name = _build_emoji(self._emoji)`
  (`special_endpoints.py:1757-1758/1928-1929/899-900`); `set_emoji` recomputes the pair on
  every call (`:1786-1789`).
- **`build()` itself mutates.** `InteractionMessageBuilder._build_components`
  (`:1349-1366`) OR-s `MessageFlag.IS_COMPONENTS_V2` into `self._flags` when a v2 component
  is present — `build()` is not side-effect-free and calling it twice can matter. The same
  logic is duplicated in `RESTClientImpl._build_message_payload` (`rest.py:1512-1530`).
- `MessageActionRowBuilder`/`ModalActionRowBuilder` keep a `_stored_type` guard that
  mutates on `add_component`.

### 2.4 The `UNDEFINED` filter lives in `JSONObjectBuilder.put*`, not the encoder

`put`/`put_array`/`put_snowflake`/`put_snowflake_array`
(`data_binding.py:275/320/357/381`) early-return on `value is undefined.UNDEFINED`, so
undefined keys never enter the dict (dossier 06 §4). `InteractionMessageBuilder.build`
(`:1376-1408`) hand-distinguishes the tri-state per field: truthy list → serialize;
`is None` → emit explicit JSON `null` (clears on edit); `is UNDEFINED` → omit the key. This
is load-bearing for Discord edit semantics.

### 2.5 All special value types subclass `int` (the enc_hook crux — dossier 06 §8)

`Snowflake(int)` (`snowflakes.py:51`), `Color(int)` (`colors.py:75`), every enum
`class X(int, enums.Enum)`, every `Flag` (metaclass injects `int`, `enums.py:479`). Today
`orjson` int-ifies them natively; the built dicts encode correctly. The 7 `serialize_*`
methods already pre-lower most values: `str(int(perm))` for permissions
(`entity_factory.py:1120`), `int(color)` and `timestamp.isoformat()` in `serialize_embed`
(`:1898/:1895`) — but `serialize_forum_tag` (`:1481`) puts a **raw `Snowflake`** as a
value, relying on the encoder to int-ify it.

### 2.6 `with_copy` on builders is a user-convenience concern

`@attrs_extensions.with_copy` is applied to many builders for "copy a half-configured
builder" DX, and `ChannelRepositioner._request_call` carries `SKIP_DEEP_COPY` so the bound
REST callable isn't deep-copied (`special_endpoints.py:237`). This is separate from the
cache's copy-removal (constraint c targets frozen *entities*, not builders — dossier 06
§10.5).

---

## 3. Target design (D11: minimal first pass)

### 3.1 Keep builders mutable; do NOT convert to frozen Structs

Recommendation (dossier 06 §10.1, CONVENTIONS §9): **keep the 40 builders on mutable
`attrs`** (or, if a later cleanup wants uniformity, mutable `msgspec.Struct` with
`frozen=False`). Do not freeze them. The `orjson → msgspec` encode swap does **not** require
touching them at all, because they emit plain dicts that `msgspec.json.encode` serializes
natively.

Why not frozen Structs now:
- The private-underscore field + `alias=` + property getter + `set_*` mutator facade does
  not map onto Struct fields (Structs expose fields directly). Reproducing the public API
  on a Struct is real hand-work across 40 classes.
- `build()`-time mutation (`IS_COMPONENTS_V2`) and `__attrs_post_init__` derived-field
  writes would need `object.__setattr__` hacks under frozen.

### 3.2 The encode swap is the only mandatory change (single point)

`data_binding.py:106-123` becomes (detail in
[`../01-foundations/04-json-data-binding.md`](../01-foundations/04-json-data-binding.md)):

```python
import msgspec
_encoder = msgspec.json.Encoder(enc_hook=_enc_hook)   # enc_hook only if §3.3 requires it
def default_json_dumps(obj: JSONArray | JSONObject) -> bytes:
    return _encoder.encode(obj)
default_json_loads = msgspec.json.decode
```

Builders keep working unchanged; `RESTClientImpl._dumps` continues to default to
`default_json_dumps`.

### 3.3 `enc_hook` only if msgspec won't int-ify the custom enums

msgspec natively encodes `int` subclasses by their integer value, and every hikari enum
member *is* an `int` subclass — but hikari enums use a **custom metaclass**, not stdlib
`enum`, so this must be verified against the target msgspec version (dossier 06 §8). Two
outcomes:

- If msgspec int-ifies them natively → **no enc_hook needed** for the builder path.
- If not → register a global `enc_hook`: `Snowflake/Color → int`, `enums.Enum/Flag →
  int(x)`, and `datetime → .isoformat()` as a safety net (though builders pre-stringify
  datetimes already).

Note the enum port to **stdlib** enums (decision D2) resolves this cleanly regardless:
stdlib `IntEnum`/`int, Enum` members encode as ints with first-class msgspec support. So
after the enums migration the enc_hook is needed (if at all) only for `Snowflake`/`Color`
int-subclasses — for which the builders already stringify snowflakes via `put_snowflake`
(`str(int(v))`) and `serialize_*` stringify perms, leaving `serialize_forum_tag`'s raw
`Snowflake` value as the one audit target.

### 3.4 Preserve `UNDEFINED` filtering verbatim — do NOT adopt `omit_defaults`

Because the sentinel is filtered at dict-build time (`JSONObjectBuilder.put*`) and never
reaches the encoder, there is no need to map `undefined.UNDEFINED → msgspec.UNSET` for the
builder subsystem. `UNSET`/`omit_defaults` only matter if a builder were ever encoded as a
Struct directly — which D11 defers. Keep the tri-state hand-distinguishing in
`InteractionMessageBuilder.build` untouched.

### 3.5 Preserve `OPT_NON_STR_KEYS` parity and the `X | int` escape hatches

- `OPT_NON_STR_KEYS` is driven by localization maps keyed by `Locale`
  (`special_endpoints.py:1496/1590/1610/1660`). msgspec encodes non-`str` dict keys
  (str/int/enum) by default, so this is free **iff** `Locale` encodes as its `str` base —
  guaranteed once `Locale` is a stdlib `str, Enum` (D2). See dossier 01 §8.2.
- Many builder fields are deliberately typed `… | int` (`flags: int | MessageFlag`,
  `style: int | ButtonStyle`, `type: ComponentType | int`) to let callers send
  not-yet-modeled values. Strict enums (constraint b) apply to **decode** typing; these
  **outbound** escape hatches must be preserved (dossier 06 §10.4) — do not strip the `int`
  arm from builder input types. `cast_variants_array` (`data_binding.py:411`) and
  `CommandBuilder.build`'s `Permissions | int` tolerance (`:1597-1598`) stay.

### 3.6 Optional later pass (deferred): frozen Struct + `enc_hook` + `UNSET`

If the maintainer later wants direct Struct encoding, each builder becomes a frozen/mutable
Struct whose `set_*` facade is re-expressed, with `T | msgspec.UnsetType = UNSET` fields
auto-omitted on encode. This is a large orthogonal change to the public builder API and is
**not** part of this migration (CONVENTIONS §9). Documented here only so the end-state is on
record.

---

## 4. Step-by-step migration

1. **Do nothing to the 40 builders** in the first pass — keep them mutable attrs. Add a
   comment/marker that they are the explicit constraint-(c) exemption.
2. **Swap the encoder** in `data_binding.py:106-123` to msgspec (owned by 04-json-data-binding).
3. **Verify int-enum encoding** empirically against the target msgspec version; add the
   global `enc_hook` only if native int-ification fails (§3.3).
4. **Audit `serialize_forum_tag`** (`entity_factory.py:1481`) — the one place a raw
   `Snowflake` is a dict *value*; ensure the encoder int-ifies it (or lower it to
   `str(int(...))` / plain `int`).
5. **Confirm `OPT_NON_STR_KEYS` parity** for localization maps after the `Locale` enum port
   (grep outbound dict-literals for enum/int keys).
6. **Preserve `X | int` outbound types** — do not narrow builder input signatures during
   the strict-enum pass.
7. **Mirror any component/embed serialization change** into the non-builder twin
   `RESTClientImpl._build_message_payload` (`rest.py:1430-1596`), which duplicates the
   embed/component/attachment/v2-flag/allowed-mentions logic.
8. **Re-provide `with_copy`/`SKIP_DEEP_COPY`** semantics only if a later pass moves builders
   off attrs (esp. `ChannelRepositioner._request_call`) — not needed while they stay attrs.

---

## 5. Affected files & symbols

| File | Anchor(s) | Change |
|---|---|---|
| `hikari/internal/data_binding.py` | `:106-123` | encoder/decoder swap (single point) |
| `hikari/internal/data_binding.py` | `:275/320/357/381`, `:411` | `put*` UNDEFINED filter + `cast_variants_array` — **unchanged** |
| `hikari/impl/special_endpoints.py` | 40 builders (dossier 06 §1.1) | **unchanged** (mutable, exempt from frozen) |
| `hikari/impl/special_endpoints.py` | `:1349-1366` | `_build_components` flag mutation — unchanged |
| `hikari/impl/entity_factory.py` | `:853/1120/1481/1879/2078/2850/3237` | 7 `serialize_*`; audit `serialize_forum_tag` raw Snowflake |
| `hikari/impl/rest.py` | `:1430-1596` | `_build_message_payload` twin — mirror any serialize change |
| `hikari/snowflakes.py:51`, `hikari/colors.py:75` | | int-subclass encode audit (enc_hook only if needed) |

Serialize-method deep-dive: [`../05-entity-factory/03-serialize-methods.md`](../05-entity-factory/03-serialize-methods.md).

---

## 6. Risks / gotchas

- **Do not freeze builders.** Freezing breaks the entire fluent `set_*`/`add_*` pattern and
  the `build()`-time flag mutation. This is the one subsystem where "everything frozen" is
  waived.
- **`build()` side effects.** `InteractionMessageBuilder.build` mutates `self._flags`;
  callers that build twice, or introspect flags after building, observe the change. Keep
  behavior identical — do not "purify" it during the swap.
- **int-subclass encode gap.** If msgspec rejects the custom-metaclass enum instances (or,
  post-port, `Snowflake`/`Color`), encode raises `TypeError`. The enc_hook is the fallback;
  verify before the swap (dossier 06 §8/§10.3).
- **`serialize_forum_tag` raw Snowflake value** — the one path that leaks an int-subclass as
  a dict value; msgspec strict typing could bite where orjson/stdlib-json tolerate it.
- **`OPT_NON_STR_KEYS` regression** — if `Locale` is not encoded via its `str` base, the
  localization maps raise on encode. Tie the verification to the enum port.
- **Losing the `X | int` outbound escape hatch** would break users sending not-yet-modeled
  Discord values — a real regression; guard against over-eager strict-enum narrowing of
  builder inputs.
- **`_build_message_payload` drift** — the twin logic in `rest.py` must stay in lockstep
  with `InteractionMessageBuilder`; a serialize change applied to one but not the other
  produces inconsistent wire output between the REST and interaction paths.

---

## 7. Verification

- **Golden-dict equality:** for each builder, assert `build()` produces byte-identical JSON
  under `msgspec.json.encode` as it did under `orjson.dumps` for a representative fixture
  (snowflakes stringified, enums as ints, undefined keys absent, `None` present where the
  edit-clear semantics require).
- **Tri-state test:** `InteractionMessageBuilder` with `attachments=UNDEFINED` omits the
  key; `attachments=None` emits `"attachments": null`; `attachments=[...]` serializes.
- **Flag mutation test:** building an `InteractionMessageBuilder` containing a v2 component
  sets `IS_COMPONENTS_V2` in the emitted `flags` (and in `_build_message_payload`).
- **Encode-hook probe:** empirically confirm `msgspec.json.encode` on a dict containing a
  `Snowflake`/`Color`/enum member either succeeds natively or is covered by the enc_hook.
- **Localization keys:** encode a command builder with a `name_localizations` map keyed by
  `Locale` members; assert no `TypeError` and correct string keys.
- **Twin parity:** a message with the same content/embeds/components produces the same body
  through `create_message` (`_build_message_payload`) and through
  `InteractionMessageBuilder.build`.

---

## 8. Open questions / decisions

Cross-linked to [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md):

1. **D11 — keep builders as-is (recommended).** Confirm the first pass leaves the 40
   builders mutable attrs, deferring any Struct conversion. Alternative (frozen/mutable
   Struct + `enc_hook` + `UNSET`) is documented (§3.6) but not scheduled.
2. **enc_hook necessity** — resolve empirically whether msgspec int-ifies the (pre-port)
   custom enums and (post-port) `Snowflake`/`Color`; if native, drop the enc_hook for the
   builder path entirely. Tie to
   [`../01-foundations/02-custom-scalar-types-and-hooks.md`](../01-foundations/02-custom-scalar-types-and-hooks.md).
3. **`X | int` outbound policy** — confirm the outbound escape hatches survive the
   strict-enum pass; coordinate with
   [`../02-enums/03-strict-enum-field-inventory.md`](../02-enums/03-strict-enum-field-inventory.md)
   (method-parameter unions are orthogonal to decode strictness).
