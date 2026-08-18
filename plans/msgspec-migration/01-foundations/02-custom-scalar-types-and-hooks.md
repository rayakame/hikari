# Custom Scalar Types and Hooks

The single global `dec_hook`/`enc_hook` pair that teaches msgspec hikari's non-native scalars
(`Snowflake`, `Color`, `Permissions`, `UnicodeEmoji`) plus the datetime/timedelta special cases.
Locks decision D4. Fields must be typed as the exact custom type for the hook to fire.

## 1. Objective

- Give msgspec a way to decode/encode the four custom scalars it cannot handle natively, and the two
  time forms Discord sends in non-native shapes (unix-epoch numbers, per-field-unit durations).
- Establish **one** module-level `dec_hook` (routes by annotation `type`) and **one** `enc_hook`
  (routes by `type(obj)`), bound to reusable `msgspec.json.Decoder`/`Encoder` instances
  (see [`05-decode-boundary-and-decoders.md`](05-decode-boundary-and-decoders.md)).
- Serves the declarative-decode end-state (D1): scalars decode straight into typed struct fields.

## 2. Current state (file:line)

Wire forms and today's hand-coded (de)serialization (dossier 09 §0, §1–§5, §7):

| Type | Def | Wire form | Decode today | Encode today |
|------|-----|-----------|--------------|--------------|
| `Snowflake(int)` | `snowflakes.py:50-100` | JSON **string** of digits | `Snowflake(payload["id"])` — 241 sites in entity_factory | `put_snowflake` → `str(int(v))` (`data_binding.py:357-379`) |
| `Color(int)` | `colors.py:75-181` (validating `__init__` `:174-180`) | JSON **int** `0..0xFFFFFF`; burst = hex str; role gradient = object | `Color(payload["color"])`; `Color.from_hex_code` (`entity_factory.py:3726`); `ColorGradient.of` | `Color` is an int → emitted as int |
| `Permissions(Flag)` | `permissions.py:32-336` | JSON **string** bitmask | `Permissions(int(payload["permissions"]))` — 6 int-wrapped + 4 raw sites | `str(int(perms))` |
| `Locale(str, Enum)` | `locales.py:32-131` | JSON **string** | `Locale(payload[...])`; map keys `{Locale(k): v}` | is a `str` → emitted directly |
| `UnicodeEmoji(str)` | `emojis.py:105-227` | JSON **string** | `UnicodeEmoji(raw)` (`entity_factory.py:1431,1449,1698,1716`) | is a `str` → emitted directly |
| `datetime` (RFC3339) | — | JSON **string** RFC3339 (`Z`/offset, µs) | `time.iso8601_datetime_string_to_datetime` (~45 sites) | `.isoformat()` (10 sites) |
| `datetime` (unix epoch) | `time.py:138-167` | JSON **number** (s or ms) | `time.unix_epoch_to_datetime(...)` (7 sites, some `is_millis=False`) | n/a |
| `timedelta` | — | JSON **number**, per-field unit (s or days) | `timedelta(seconds=...)` / `timedelta(days=...)`; helpers `entity_factory.py:96,105-106,113-114` | `timespan_to_int` etc. |

Empirically-verified msgspec facts that shape the design (dossier 13 §8, §11, §10):

- A field typed as an `int`/`str` subclass **without a hook** fails to decode: `ValidationError:
  Expected 'Snowflake', got 'int'` (and `got 'str'`). msgspec does not auto-coerce base→subclass, and
  `strict=False` does **not** change custom-type resolution.
- `dec_hook(type, obj)` receives the **raw JSON scalar as-is** (`123` for a number, `'123'` for a
  string), so `Snowflake(obj)` handles both wire shapes because `int("123") == int(123)`.
- **Int-subclass encode gap (orjson-parity break):** msgspec **cannot** encode `int`/`str`
  subclasses natively — `encode({"channel_id": Snowflake(5)})` → `TypeError: Encoding objects of type
  Snowflake is unsupported`. orjson serialized them fine. `int(Snowflake(5))` returns a plain `int`.
- msgspec decodes RFC3339 **natively** into `datetime` (C fast path) — this is what makes ciso8601
  redundant for entity timestamps (dossier 13 §13).
- msgspec native `datetime` decode expects a JSON **string**; a JSON **number** (unix epoch) errors.
- msgspec native `timedelta` decode expects an **ISO8601 duration** (`PT30S`); Discord never sends
  those, so it is unusable for hikari.

## 3. Target design

### 3.1 The global hooks (refined from dossier 09 §10)

```python
# hikari/internal/msgspec_hooks.py  (new module; imported by data_binding + decoder registry)
from __future__ import annotations
import datetime as _dt
import typing
import msgspec
from hikari import snowflakes, colors, permissions, emojis

# ---- DECODE ----------------------------------------------------------------
def dec_hook(type_: type, obj: typing.Any) -> typing.Any:
    # `obj` is the primitive msgspec already parsed from JSON:
    #   Snowflake  -> str  | Color -> int | Permissions -> str | UnicodeEmoji -> str
    if type_ is snowflakes.Snowflake:
        return snowflakes.Snowflake(obj)              # int("123") == 123; handles str+int
    if type_ is colors.Color:
        return colors.Color(obj)                      # keeps the 0..0xFFFFFF __init__ guard
    if type_ is permissions.Permissions:
        return permissions.Permissions(int(obj))      # tolerant: unknown bits preserved
    if type_ is emojis.UnicodeEmoji:
        return emojis.UnicodeEmoji(obj)
    raise NotImplementedError(f"no dec hook for {type_!r}")

# ---- ENCODE (only when Structs/dicts carrying these types are encoded) ------
def enc_hook(obj: typing.Any) -> typing.Any:
    if isinstance(obj, snowflakes.Snowflake):
        return str(int(obj))                          # Discord wants a string
    if isinstance(obj, permissions.Permissions):
        return str(int(obj))
    if isinstance(obj, colors.Color):
        return int(obj)                               # Discord wants an int
    if isinstance(obj, emojis.UnicodeEmoji):
        return str(obj)
    if isinstance(obj, _dt.datetime):
        return obj.isoformat()
    raise NotImplementedError(f"no enc hook for {type(obj)!r}")
```

Notes:

- **Fields must be typed as the exact custom type** (`id: snowflakes.Snowflake`, not `id: int`) or
  the `dec_hook` never fires — a bare `int`/`str` field decodes natively and skips the hook.
- `Locale` is **not** in the hooks — it becomes a stdlib `str` enum handled by `_missing_` (decision
  D2), so msgspec decodes/encodes it natively. See
  [`../02-enums/02-int-and-str-enums-migration.md`](../02-enums/02-int-and-str-enums-migration.md)
  and [`../06-model-modules/01-scalars-snowflakes-colors-permissions-locales.md`](../06-model-modules/01-scalars-snowflakes-colors-permissions-locales.md).
- `dec_hook` fires **per value** — snowflake-dense payloads pay one Python call per snowflake field.
  Still expected to beat today's `orjson.loads` + Python `entity_factory` construction, but measure
  ([`../11-rollout/02-performance-benchmarking.md`](../11-rollout/02-performance-benchmarking.md)).

### 3.2 Snowflake: decode vs the encode gap

`Snowflake` decodes cleanly via the `dec_hook`. The **encode** side has two viable strategies
(decision D4 open item Q-SCALAR-1):

1. **Keep the hand-built builders** (`JSONObjectBuilder.put_snowflake` etc.) that already lower
   snowflakes to strings before encode — recommended for the first pass, because request bodies are
   built by those builders, not by encoding Structs (dossier 01 §8.3,
   [`04-json-data-binding.md`](04-json-data-binding.md)). The int-subclass encode gap then never
   bites, because `str(int(v))` produces a plain `str`.
2. **Register the global `enc_hook`** (`str(int(v))`) on the shared `Encoder` — needed only if/when
   Structs are encoded directly to request bodies (a later, orthogonal change).

Either way, **audit** for raw `Snowflake`/`Color`/`Permissions` int-subclasses reaching
`msgspec.json.encode` (they raise `TypeError`) — see [`04-json-data-binding.md`](04-json-data-binding.md) §"encode-gap audit".

### 3.3 Color: three wire forms

- Plain `color` (int) → `Color` via the global `dec_hook` (preserves `__init__` range validation; a
  plain-`int` field would silently accept garbage).
- `burst_colors` (hex **strings**, `entity_factory.py:3726`) → field-specific hook
  `Color.from_hex_code` (the global hook expects int). Type as `Color` with an `Annotated` marker
  (§3.5) or transform in the residual factory.
- Role color **gradient** (object) → `ColorGradient` becomes a frozen Struct
  (`colors.py:596-677`, currently attrs) whose `primary/secondary/tertiary` fields are `Color` and
  route through the global hook. See [`../06-model-modules/01-scalars-snowflakes-colors-permissions-locales.md`](../06-model-modules/01-scalars-snowflakes-colors-permissions-locales.md).

### 3.4 Permissions: stay tolerant regardless of global strictness

Wire is a **string** bitmask; the hook does `Permissions(int(obj))`. Discord adds permission bits
regularly (max defined bit is `1<<52`, approaching `2**53-1` — the reason Discord sends them as
strings), so `Permissions` must stay tolerant of unknown bits even under constraint (b) strict enums.
Once `Permissions` is ported to stdlib `enum.IntFlag` (decision D2), unknown bits are preserved
natively (KEEP boundary, 3.11+); the hook still bridges the **string→int** wire mismatch. Do **not**
validate against `all_permissions()` — a new Discord bit would crash decode.

### 3.5 datetime: the RFC3339 vs unix-epoch split

Two disjoint field populations:

```python
# RFC3339 entity timestamps -> NATIVE msgspec decode, no hook:
joined_at: datetime.datetime
premium_since: datetime.datetime | None = None
# Optionally require tz-aware:
created_at_field: typing.Annotated[datetime.datetime, msgspec.Meta(tz=True)]

# unix-epoch numbers (activity/voice) -> NOT native; number-on-wire:
# type the field as int/float and convert in the residual factory, OR a per-field Annotated hook.
start: typing.Annotated[datetime.datetime, "unix_millis"]   # inspected in a field-aware hook
```

- RFC3339 fields (~45 sites) decode natively — msgspec handles `Z`, offsets, and 6-digit µs (dossier
  13 §13). This is where ciso8601 becomes redundant. **VERIFY** (before dropping ciso8601): msgspec
  matches ciso8601/`time.iso8601_datetime_string_to_datetime` on Discord's exact variants — trailing
  `Z`, `+00:00`, and >6 fractional digits (msgspec truncates to ns). Owner: this file, tracked in
  [`../12-appendices/01-open-questions-and-verifications.md`](../12-appendices/01-open-questions-and-verifications.md).
- Unix-epoch fields (7 sites, `time.py:138-167`, some `is_millis=False`) are JSON **numbers** — they
  must **bypass** native datetime decode. Keep `time.unix_epoch_to_datetime` including its
  `datetime.max`/`min` clamping (catches `OSError`/`ValueError`); a bare native decode has no
  equivalent. Route via a residual-factory transform or an `Annotated` marker inspected in a
  field-aware hook (§3.6).
- Snowflake `created_at` is a **computed property** (`snowflakes.py:114-116`) — unaffected.
- Encode: msgspec emits RFC3339 for `datetime` natively; keeping the hand builders keeps `.isoformat()`
  (10 sites). No change forced.

### 3.6 timedelta: per-field unit, never native

Discord sends durations as **bare numbers** whose unit varies per field (seconds vs days), so msgspec
native `timedelta` (ISO8601 duration) is unusable. A single global `dec_hook` branch is impossible
(the unit is not in the value). Two mechanisms:

```python
import typing, datetime, msgspec

# Annotated marker inspected by a field-aware decode path (residual factory or a wrapping hook):
afk_timeout:  typing.Annotated[datetime.timedelta, "seconds"]   # entity_factory.py:199
rate_limit_per_user: typing.Annotated[datetime.timedelta, "seconds"]  # :1273,1466
delete_member_days:  typing.Annotated[datetime.timedelta, "days"]     # :946
```

- Preferred first-pass: keep the per-field conversion helpers (`_deserialize_seconds_timedelta`
  `entity_factory.py:96`, `_deserialize_day_timedelta` `:105-106`, `_deserialize_max_age`
  `:113-114`) in the residual factory — msgspec decodes the raw number into an `int` field, the
  factory wraps it. Zero hook complexity.
- End-state option: type as `Annotated[timedelta, unit]`, decode the number into an int, and convert
  in a `__post_init__`/`force_setattr` or a field-aware hook that reads the `Annotated` metadata.
  Only worthwhile once declarative decode is pervasive.

### 3.7 UnicodeEmoji and the files.Resource wrinkle

`UnicodeEmoji(str)` decodes via the global hook (`UnicodeEmoji(obj)`), encodes as `str` natively.
The hazard is multiple inheritance: `UnicodeEmoji(str, Emoji)` and `CustomEmoji(Unique, Emoji)` where
`Emoji` is a `files.WebResource` — a Struct plus a non-Struct mixin. `files.Resource` is **never**
JSON-decoded (upload-only, dossier 09 §8), so no dec_hook is needed for it, but the emoji Structs must
keep their `WebResource` behavior. Detailed in
[`../06-model-modules/03-emojis-and-files-resources.md`](../06-model-modules/03-emojis-and-files-resources.md).

## 4. Step-by-step migration

1. Create `hikari/internal/msgspec_hooks.py` with `dec_hook`/`enc_hook` (§3.1).
2. Ensure every custom-scalar field is annotated as the **exact** type (`Snowflake`, `Color`,
   `Permissions`, `UnicodeEmoji`) — audited per module in [`../06-model-modules/`](../06-model-modules/00-README.md).
3. Bind `dec_hook` to the module-level typed `Decoder`s (see 05); decide whether to also bind
   `enc_hook` (only if Structs are encoded directly — otherwise leave request encoding to the builders).
4. Split datetime fields into RFC3339 (native) vs unix-epoch (int field + `unix_epoch_to_datetime`
   transform); keep `time.unix_epoch_to_datetime`.
5. Mark timedelta fields with `Annotated[timedelta, unit]`; keep the `_deserialize_*_timedelta`
   helpers for the first pass.
6. Convert `ColorGradient` to a frozen Struct; wire `burst_colors` to `Color.from_hex_code`.
7. Run the ciso8601-parity VERIFY (§3.5); if it passes end-to-end, schedule the ciso8601 drop with
   [`00-dependencies-and-tooling.md`](00-dependencies-and-tooling.md).

## 5. Affected files and symbols

| Path | Anchor | Change |
|------|--------|--------|
| `hikari/internal/msgspec_hooks.py` | new | global `dec_hook`/`enc_hook` |
| `hikari/snowflakes.py` | `:50-100` | field typing target; no code change to the type |
| `hikari/colors.py` | `:75-181`, `:596-677` | `Color` field typing; `ColorGradient`→Struct |
| `hikari/permissions.py` | `:32-336` | → stdlib `IntFlag` (D2); string-wire hook |
| `hikari/emojis.py` | `:105-227` | `UnicodeEmoji` field typing; MI wrinkle |
| `hikari/internal/time.py` | `:138-167` | keep `unix_epoch_to_datetime`; ciso8601 (`:86-103`) revisit |
| `hikari/impl/entity_factory.py` | `:96,105-114,199,946,1273,1466,3726` | timedelta/burst-color transforms move to residual layer |

## 6. Risks and gotchas

1. **Int-subclass encode gap.** Any `Snowflake`/`Color`/`Permissions` reaching `msgspec.json.encode`
   without lowering raises `TypeError`. Mitigate via the builders (already stringify) or the
   `enc_hook`. Audit owned by [`04-json-data-binding.md`](04-json-data-binding.md).
2. **Hook only fires on exact type.** Mis-annotating a field as `int`/`str` silently skips the hook
   and (for Color) drops the range guard. Field-typing audit is load-bearing.
3. **datetime edge cases.** ciso8601 cannot be dropped until the parity VERIFY passes; a naive-stamp
   endpoint (no offset) would need `Meta(tz=...)` handling — audit that Discord always sends offsets.
4. **timedelta unit ambiguity.** A global hook cannot infer seconds-vs-days; per-field marking is
   mandatory. Getting it wrong silently scales a duration by 86400.
5. **`Color.__init__` raises** on out-of-range — the hook preserves the guard; a plain-int field does
   not.
6. **Per-value hook cost.** Snowflake-dense payloads pay a Python call per field; benchmark against
   the orjson+factory baseline before claiming a win.

## 7. Verification

- Round-trip probes per scalar: `Decoder(Struct, dec_hook=dec_hook).decode(b'{"id":"123"}')` yields
  `Snowflake(123)`; a JSON int `123` yields the same. `Color(0x1000000)` (out of range) raises via the
  hook. `Permissions` decodes an unknown high bit losslessly.
- ciso8601-parity table: feed the same Discord stamps to `time.iso8601_datetime_string_to_datetime`
  and to a msgspec `datetime` decode; assert equality across `Z`, `+00:00`, and 6-µs cases.
- unix-epoch: assert `unix_epoch_to_datetime` clamping still applies to out-of-range activity stamps.
- Encode-gap: attempt `msgspec.json.encode(Snowflake(5))` in a test and assert it raises without the
  `enc_hook`, and succeeds (`b'"5"'`) with it.

## 8. Open questions / decisions

Cross-link [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md):

- Q-SCALAR-1: Snowflake encode — keep hand builders (recommended) or register the global `enc_hook`?
  Where is the single `enc_hook`/`dec_hook` registered?
- Q-SCALAR-2 (VERIFY): msgspec native datetime matches ciso8601 on Discord's stamp variants → then
  drop ciso8601.
- Q-SCALAR-3: timedelta — keep residual-factory helpers (first pass) or move to `Annotated`+hook
  (end-state)?
- Q-SCALAR-4: is any request body encoded by msgspec (vs hand builders) such that the int-subclass
  encode gap bites today? (Audit in 04.)
