# Entity factory: the serialize methods

The 7 outbound `serialize_*` methods (model → JSON dict; the reverse of `deserialize_*`) and their
interplay with the `special_endpoints` builders and the `msgspec.json` encode path. These are the
factory's only outbound surface and are largely independent of the (much larger) decode rewrite.

Parent: [`00-architecture-and-decode-strategy.md`](./00-architecture-and-decode-strategy.md).
Related: [`../08-builders/00-special-endpoints-builders.md`](../08-builders/00-special-endpoints-builders.md)
(D11), [`../01-foundations/04-json-data-binding.md`](../01-foundations/04-json-data-binding.md) (the
encode swap and int-subclass gap).

---

## 1. Objective

Keep the 7 hand-written `serialize_*` methods working through the orjson→msgspec encode swap, and
audit them (plus the builders that call them) for the **int-subclass encode gap** — the empirically
verified fact (D4) that `msgspec.json.encode` **cannot encode `int`/`str` subclasses natively**
(`Snowflake`, `Color`, hikari enums), unlike orjson. This is an outbound-only slice: it does not
touch the decode boundary, tagged unions, or the transform layer.

---

## 2. Current state

### 2.1 The 7 methods

Confirmed anchors (impl `hikari/impl/entity_factory.py`, interface `hikari/api/entity_factory.py`):

| Method | api | impl | Returns | Undefined/None handling | Notes (dossier 06 §5) |
|---|---|---|---|---|---|
| `serialize_application_connection_metadata_record` | `244` | `853` | `dict` | none (all required) | `int(record.type)` — explicit enum→int cast |
| `serialize_permission_overwrite` | `394` | `1120` | `dict` | none | `str(int(allow/deny))` — `Permissions` Flag → str; `type` left as int-enum |
| `serialize_forum_tag` | `646` | `1481` | `dict` | none | `"id": tag.id` — leaves a **raw `Snowflake`** (int-subclass) as a value |
| `serialize_embed` | `937` | `1879` | **`tuple[dict, list[Resource]]`** | manual `if x is not None` per field | `# noqa: C901, PLR0912, PLR0915`; `timestamp.isoformat()`, `int(color)`, collects file uploads |
| `serialize_welcome_channel` | `1088` | `2078` | `dict` | manual `if … is not None` | `str(channel_id)`, `str(emoji_id)` |
| `serialize_command_permission` | `1439` | `2850` | `dict` | none | `str(permission.id)`, `type` left int-enum |
| `serialize_command_option` | `1544` | `3237` | `dict` | manual `if … is not None` per optional | **recursive** (`options`), leaves `type`/`channel_types` as int-enums |

### 2.2 How they build dicts

Unlike the request-param path, these methods **hand-roll plain dicts with `if x is not None`** — they
do **not** use `data_binding.JSONObjectBuilder` (dossier 06 §5). They mix two encoding conventions:

- **Explicit lowering** for values that must be strings on the wire: `str(int(perms))`,
  `str(channel_id)`, `str(permission.id)`, `embed.timestamp.isoformat()`, `int(embed.color)`.
- **Raw int-subclass pass-through** for enums (`"type": overwrite.type`) and, in `serialize_forum_tag`,
  a raw `Snowflake` id — relying on the encoder to int-serialize them. orjson does this natively;
  **msgspec does not** (§4).

`serialize_embed` is the outlier: it returns `(payload, uploads)` and walks each sub-resource
(`footer.icon`/`image`/`thumbnail`/`author.icon`), appending non-`WebResource` resources to `uploads`
and setting the payload URL to `resource.url` (`hikari/impl/entity_factory.py:1900-1944`). It also
raises `TypeError` on a `None` field name/value as a UX guard (`1959-1965`). This conditional,
upload-collecting logic will **not** collapse into a pure `msgspec.json.encode(struct)` call.

### 2.3 Who calls them (interplay with builders)

The serialize methods are invoked from the outbound builders and their non-builder twin (dossier 06
§9), which pass `entity_factory` into `build()`:

| Caller | Anchor | Calls |
|---|---|---|
| `SlashCommandBuilder.build` | `hikari/impl/special_endpoints.py:1659` | `serialize_command_option` per option |
| `InteractionMessageBuilder.build` | `hikari/impl/special_endpoints.py:1392-1400` | `serialize_embed`; appends uploads to the file list |
| `RESTClientImpl._build_message_payload` | `hikari/impl/rest.py:1430-1596` | `serialize_embed` (the non-builder twin of the message builder) |

Builders are mutable, `entity_factory`-parameterized, and hold no `app` (constraint (a) already
satisfied for them). They are **not** frozen wire Structs — see D11 and
[`../08-builders/00-special-endpoints-builders.md`](../08-builders/00-special-endpoints-builders.md).

---

## 3. Target design

Recommendation (aligned with D6/D11): **keep the 7 methods as hand-written dict builders in the first
pass**; the orjson→msgspec swap is at the encode call (`data_binding.default_json_dumps`), not in
these methods. Optionally, later, replace the *flat* ones with `msgspec.to_builtins(struct,
enc_hook=…)` once the corresponding models are Structs — but the two complex ones stay hand-written.

| Method | First-pass | Later (optional) |
|---|---|---|
| `serialize_application_connection_metadata_record` | keep | `to_builtins` (flat) |
| `serialize_permission_overwrite` | keep | `to_builtins` (flat) |
| `serialize_forum_tag` | keep (fix id lowering, §4) | `to_builtins` (flat) |
| `serialize_welcome_channel` | keep | `to_builtins` (flat, but has optionals) |
| `serialize_command_permission` | keep | `to_builtins` (flat) |
| `serialize_embed` | **keep** (uploads + conditionals) | stays hand-written |
| `serialize_command_option` | **keep** (recursive + optionals) | stays hand-written |

### 3.1 The encode swap (context)

The single swap point is `hikari/internal/data_binding.py:107-123` (D6):

```python
import msgspec
_encoder = msgspec.json.Encoder(enc_hook=_enc_hook)     # enc_hook mandatory — see §4
def default_json_dumps(obj: object) -> bytes:
    return _encoder.encode(obj)
default_json_loads = msgspec.json.decode
```

msgspec's native non-string dict-key handling matches orjson's `OPT_NON_STR_KEYS`
(`data_binding.py:111`) — verify parity for the `name_localizations` maps (keys are `Locale`, a
str-enum) before the swap.

---

## 4. The int-subclass encode gap (the load-bearing risk)

D4 records the empirically verified fact: **`msgspec.json.encode` cannot encode `int`/`str`
subclasses natively** (the docs claim otherwise). Every place the serialize methods (or the builders)
leave a raw `Snowflake`, `Color`, or hikari enum in the output dict is a `TypeError` waiting at
encode time. orjson tolerated all of these because it does `isinstance(o, int)`.

Known raw-int-subclass leaks in the serialize methods:

- `serialize_forum_tag` (`1481`) — `"id": tag.id` leaves a raw `Snowflake` (dossier 06 §5).
- Any `"type": <enum>` left as a raw enum member (`serialize_permission_overwrite`,
  `serialize_command_permission`, `serialize_command_option`'s `type`/`channel_types`).

Two mutually reinforcing fixes (do both):

1. **Register the global `enc_hook`** on the module `Encoder` so any residual int-subclass lowers:

   ```python
   def _enc_hook(obj: object) -> object:
       if isinstance(obj, snowflakes.Snowflake):   return str(int(obj))   # Discord wants a string
       if isinstance(obj, permissions.Permissions): return str(int(obj))
       if isinstance(obj, colors.Color):           return int(obj)        # Discord wants an int
       if isinstance(obj, enums.Enum):             return obj.value       # or int(obj)/str(obj)
       if isinstance(obj, datetime.datetime):      return obj.isoformat()
       raise NotImplementedError(f"no enc hook for {type(obj)!r}")
   ```

   Note: after the enum port (D2) to stdlib enums, `enum.Enum`/`IntEnum`/`IntFlag` members **are**
   natively encodable by msgspec — so the `enums.Enum` branch is only needed while the custom-metaclass
   enums remain, or as a safety net. `Snowflake`/`Color` remain int-subclasses and **always** need the
   hook (or explicit lowering). Full hook reference:
   [`../01-foundations/02-custom-scalar-types-and-hooks.md`](../01-foundations/02-custom-scalar-types-and-hooks.md).

2. **Lower explicitly in the serialize methods** so they never emit an int-subclass — e.g.
   `serialize_forum_tag` emits `"id": str(int(tag.id))`. This makes the methods encoder-agnostic
   (works under stdlib-json too) and removes reliance on the hook firing. Preferred for the 7
   methods; the hook is the backstop for the builders and any missed site.

The two conventions must agree on `Snowflake` → **string** and `Color` → **int** (Discord's wire
forms; dossier 09 §1.2, §3.2).

---

## 5. Step-by-step migration

1. **Swap the encoder** in `data_binding.py:107-123` to `msgspec.json.Encoder(enc_hook=_enc_hook)`
   with `default_json_loads = msgspec.json.decode` (D6). Cross-linked to
   [`../01-foundations/04-json-data-binding.md`](../01-foundations/04-json-data-binding.md).
2. **Audit the 7 serialize methods** for raw int-subclass values in their output dicts; add explicit
   lowering (§4 fix 2). Priority: `serialize_forum_tag` (`"id"`), all `"type"` enum fields.
3. **Audit the builder dicts** (`special_endpoints.py`) and the non-builder twin
   (`rest.py:1430-1596`) for the same leaks — especially `default_member_permissions`
   (`Permissions`), button `style`/`type` (int-enums), `accent_color` (`Color`). D11 keeps builders
   as-is otherwise.
4. **Preserve UNDEFINED filtering.** The builders' `JSONObjectBuilder.put*` already skip `UNDEFINED`
   (`data_binding.py:299,346,373,402`); do **not** replace with `omit_defaults` — the sentinel never
   reaches the encoder (dossier 06 §10.2). The serialize methods use `if x is not None`, unaffected.
5. **Keep the two complex methods hand-written** (`serialize_embed`, `serialize_command_option`); do
   not attempt `to_builtins` on them.
6. **Verify non-string key parity** (`OPT_NON_STR_KEYS` → msgspec native) for `name_localizations`
   and any other enum/int-keyed outbound maps.
7. **(Optional, later)** convert the 5 flat methods to `msgspec.to_builtins(struct, enc_hook=…)` once
   their source models are frozen Structs.

---

## 6. Affected files and symbols

| Path | Anchor | Change |
|---|---|---|
| `hikari/impl/entity_factory.py` | `853,1120,1481,2078,2850` | explicit int-subclass lowering (flat methods) |
| `hikari/impl/entity_factory.py` | `1879` `serialize_embed` | keep hand-written; verify `int(color)`/`isoformat`/uploads |
| `hikari/impl/entity_factory.py` | `3237` `serialize_command_option` | keep hand-written; lower `type`/`channel_types` |
| `hikari/internal/data_binding.py` | `107-123` | orjson→msgspec encode/decode swap + `enc_hook` |
| `hikari/impl/special_endpoints.py` | `1659`, `1392-1400` | builders call serialize methods; audit leaks |
| `hikari/impl/rest.py` | `1430-1596` | `_build_message_payload` twin; mirror embed/serialize changes |

---

## 7. Risks and gotchas

- **Silent orjson tolerance is gone.** Any int-subclass that reached orjson encoded fine; the same
  value TypeErrors under msgspec. The audit (§5.2-5.3) must be exhaustive — grep every serialize/
  builder output for `Snowflake`/`Color`/enum values not explicitly lowered.
- **Two twins must stay in sync.** `InteractionMessageBuilder.build` and
  `RESTClientImpl._build_message_payload` duplicate the embed/serialize logic (dossier 06 §9); a fix
  in one must be mirrored in the other.
- **`serialize_embed` uploads.** The `(payload, uploads)` contract and the `WebResource` check
  (`1900-1944`) are load-bearing for multipart upload; a naive `encode(struct)` would drop the file
  collection.
- **enum→wire form.** After the D2 port, encode `IntFlag`/`IntEnum` members natively; but confirm the
  wire form matches (permissions as **string**, most enums as **int**) — the `enc_hook` for
  `Permissions` (str) overrides the native int encoding.
- **`OPT_NON_STR_KEYS` parity.** A regression here silently breaks any enum/int-keyed outbound map.

---

## 8. Verification

1. **Encode round-trip.** For each serialize method, build a model, serialize, `msgspec.json.encode`,
   and assert the bytes match the current orjson output (modulo key order) on a fixtures corpus.
2. **Int-subclass probe.** Unit-test `msgspec.json.encode` on a dict containing a raw `Snowflake`,
   `Color`, and enum member — assert the `enc_hook` lowers each (and that an unlowered one raises, to
   catch regressions).
3. **Embed uploads.** Assert `serialize_embed` still returns the right `uploads` list for local-file
   vs web resources, and raises `TypeError` on `None` field name/value.
4. **Builder parity.** Build a message/command/interaction response through the builders and assert
   the wire bytes are byte-equivalent (or field-equivalent) pre/post swap.
5. **Non-string keys.** Assert `name_localizations` (Locale-keyed) encodes identically under msgspec.

---

## 9. Open questions and decisions

These are local serialize-path decisions, not global VERIFY probes; the two maintainer confirmations
below are tracked in the consolidated gate
[`../12-appendices/01-open-questions-and-verifications.md`](../12-appendices/01-open-questions-and-verifications.md)
(see SD "serialize-method fate" / SD "enc_hook vs explicit lowering"):

- **Serialize-method fate (resolved default):** the first pass keeps all 7 `serialize_*` methods
  hand-written; only the 5 flat ones are later candidates for `to_builtins`. Open confirmation: does
  the maintainer want the optional later conversion at all, or keep them hand-written permanently?
- **enc_hook vs explicit lowering (resolved default):** do both — explicit lowering in the 7 methods
  (encoder-agnostic) plus the global `enc_hook` as the builder backstop. Open confirmation: no builder
  relies on emitting a raw int-subclass that the hook would then double-convert.
- **D11 (builders):** builders stay mutable and as-is in the first pass; builder→Struct conversion is
  deferred. See [`../08-builders/00-special-endpoints-builders.md`](../08-builders/00-special-endpoints-builders.md).
