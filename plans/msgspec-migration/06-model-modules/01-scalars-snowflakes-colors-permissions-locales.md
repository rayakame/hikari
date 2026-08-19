# Scalars — snowflakes, colors/colours, permissions, locales

Purpose: migrate the four leaf scalar modules every model field is typed against. These are mostly
**not** attrs classes — they are `int`/`str` subclasses and custom `Flag`/`Enum` types — so the work
is (i) making msgspec route them through the global `dec_hook`/`enc_hook`, (ii) **keeping** the two
enum-framework members (`Permissions`, `Locale`) as hikari's fast custom enums and adopting upstream
PR hikari-py/hikari#2770 for strict typing + `is_unknown`, and (iii) turning the one attrs class here
(`colors.ColorGradient`) into a frozen Struct. These land first (dependency order, `00-README.md` §3)
so downstream modules can type their fields against the finished scalars.

--------------------------------------------------------------------------------------------------

## 1. Objective

Serves constraints (b) strict enums and (a)/(c) indirectly (these scalars carry no `app` and are
already immutable). Concretely:

- Keep `Snowflake(int)` and `Color(int)` as int subclasses; wire them to the global scalar hooks
  (`../01-foundations/02-custom-scalar-types-and-hooks.md`, decision D4).
- Keep `permissions.Permissions` as the custom `hikari.internal.enums.Flag` (adopt #2770 for strict
  typing + `is_unknown`); type fields as the bare `Permissions` and decode via the shared `dec_hook`,
  tolerating unknown bits (D2, `../02-enums/00-strategy-and-forward-compat.md`).
- Keep `locales.Locale` as the custom `hikari.internal.enums.Enum` `(str, Enum)` (adopt #2770); type
  fields as the bare `Locale` and decode via the shared `dec_hook`, tolerating unknown Discord locales
  as `is_unknown` pseudo-members (D2, `../02-enums/00-strategy-and-forward-compat.md`).
- Convert `colors.ColorGradient` to a frozen Struct; keep `colours.py` a pure alias module.
- Preserve `snowflakes.Unique` unchanged — it is the id-only identity base every wire Struct relies
  on (`../01-foundations/01-base-struct-conventions.md`).

Decode classification: `Snowflake`/`Color`/`Permissions`/`Locale` are scalar hooks (not Structs);
`ColorGradient` is **T** (built via `ColorGradient.of(...)` classmethod today, see §4.4);
`Unique` is not a data type at all.

--------------------------------------------------------------------------------------------------

## 2. Current state (file:line anchors)

| Symbol | Location | Shape today |
|---|---|---|
| `Snowflake(int)` | `snowflakes.py:50-100` | `int` subclass, `__slots__=()`, `@typing.final`; computed `created_at`/`internal_*`/`increment` props; `from_datetime`/`from_data`/`min`/`max` classmethods |
| `Unique(abc.ABC)` | `snowflakes.py:103-132` | id-only identity mixin: `__hash__`=`hash(self.id)` (`:127-128`), `__eq__`=`isinstance(other, type(self)) and self.id == other.id` (`:130-132`), `__int__`/`__index__`, `created_at` |
| `Snowflakeish` aliases | `snowflakes.py:155-181` | `Union[Snowflake, int]`, `SearchableSnowflakeish` (+`datetime`) |
| `Color(int)` | `colors.py:75-181` | `int` subclass; `__init__` **validates** `0 <= v <= 0xFFFFFF` (`:174-177`) and raises `ValueError`; rich `rgb`/`hex_code`/`from_hex_code`/`of` API; `__str__`→`hex_code` |
| `ColorGradient` | `colors.py:596-678` | `@attrs_extensions.with_copy` + `@attrs.define(kw_only=True, weakref_slot=False)`; `primary_color: Color`, `secondary_color/tertiary_color: Color \| None = None`; `holographic()`/`of()` classmethods; `*_colour` alias props |
| `colours.py` | `colours.py:31-38` | pure aliases: `Colour = colors.Color`, `ColourGradient = colors.ColorGradient`, `Colourish` |
| `Permissions(enums.Flag)` | `permissions.py:32-336` | custom `Flag` (int subclass via `_FlagMeta`), ~55 non-contiguous members `1<<0`..`1<<52`; `all_permissions()` classmethod (`:322-335`) |
| `Locale(str, enums.Enum)` | `locales.py:32-131` | custom `str`-`Enum`, ~31 members (`ID="id"`, `EN_US="en-US"`, …) |

Wire forms and current decode (dossier 09 §§1-5):
- Snowflake — JSON **string** of digits; factory wraps `snowflakes.Snowflake(payload["id"])` (241
  sites in `entity_factory.py`); encode stringifies via `data_binding.py:357-408`
  (`put_snowflake*`).
- Color — JSON **int**; `Color(payload["color"])` (14 sites); `burst_colors` are hex **strings**
  (`Color.from_hex_code`, `entity_factory.py:3726`); role gradient is an **object**
  (`ColorGradient.of`, `entity_factory.py:2223,2561`).
- Permissions — JSON **string** bitmask; `Permissions(int(payload["permissions"]))` (18 sites,
  6 with explicit `int()`).
- Locale — JSON **string**; `Locale(payload["locale"])` (22 sites); also used as **dict keys** in
  localization maps (`entity_factory.py:831,2671,…`).

Tolerance today comes from the custom metaclasses: `_EnumMeta.__call__` returns the raw value on a
miss (`enums.py:153-156`) and `_FlagMeta.__call__` synthesises a pseudo-member for unknown bits
(`enums.py:381-412`). This is why fields are typed `Locale | str` / `SomeEnum | int` — the union
arm is the "unknown Discord value" escape hatch (dossier 02 Part C). PR #2770 makes the custom
`Enum.__call__` mint a pseudo-member **instance** on a miss too (aligning `Enum` with `Flag`) and
types every field with only the enum/flag, so the union arm is dropped and the pseudo-member becomes
the escape hatch — decoded through the shared `dec_hook` (§3.3/§3.4).

--------------------------------------------------------------------------------------------------

## 3. Target design

### 3.1 Snowflake — unchanged type, add hooks

`Snowflake(int)` stays exactly as-is (already immutable, final, slotted). It is **not** made a
Struct. Route it through the global hooks:

```python
# in the global dec_hook (foundations 02):
if type_ is snowflakes.Snowflake:
    return snowflakes.Snowflake(obj)          # obj is the JSON str "123"; int("123") == 123
# in the global enc_hook:
if isinstance(obj, snowflakes.Snowflake):
    return str(int(obj))                       # Discord wants a string
```

Fields are typed as the bare `snowflakes.Snowflake` so the hook fires (a plain `int` field would
NOT route to the hook — conventions §4). Nullable IDs stay `Snowflake | None`.

- **Encode gap (empirically verified, dossier 09 §1.3 / 13):** msgspec cannot encode an int subclass
  natively — it raises `TypeError`, the docs notwithstanding. Two viable paths, both in D4:
  (i) register the `enc_hook` above, or (ii) keep the hand-built `JSONObjectBuilder.put_snowflake`
  for request bodies (recommended first pass — it already stringifies). See
  `../01-foundations/04-json-data-binding.md`.
- **Snowflake dict keys** (`Mapping[Snowflake, T]`): JSON object keys are always strings; msgspec
  parses string keys to `int`, but a `Snowflake` **subtype** key needs verification — flagged in
  `../05-entity-factory/02-hard-cases-and-transforms.md` (the array→Mapping re-keying is a transform
  anyway, so the keyed-map is built in Python, sidestepping the key-decode question).

### 3.2 Color / Colour — unchanged type, add hook (keeps the range guard)

```python
if type_ is colors.Color:
    return colors.Color(obj)                   # obj is a JSON int; runs the 0..0xFFFFFF __init__ guard
# encode: Color IS an int subclass -> same int-subclass encode gap as Snowflake
if isinstance(obj, colors.Color):
    return int(obj)                            # Discord wants an int
```

- The `dec_hook` **preserves** `Color.__init__`'s `ValueError` on out-of-range (`colors.py:174-177`);
  a plain-`int` field would silently accept garbage (dossier 09 §3.3 / risk 8).
- **Mixed wire forms** cannot share the plain-int hook: `burst_colors` (hex strings) → a
  field-specific `Color.from_hex_code` hook or residual transform; role gradient (object) →
  `ColorGradient` Struct (§3.4). These are **T**, handled in the residual factory
  (`../05-entity-factory/02-hard-cases-and-transforms.md`).
- `colours.py` stays a 3-line alias module; `ColourGradient` re-points to the new Struct
  automatically. No change beyond keeping the re-export.

### 3.3 Permissions — keep the custom `Flag`, decode via the shared `dec_hook`

`Permissions` STAYS `hikari.internal.enums.Flag` (a fast int subclass via `_FlagMeta`); it is **not**
ported to `enum.IntFlag`, and its ~20-method set-API
(`.all/.any/.none/.split/.difference/.intersection/.union/.is_subset/…`) is kept as-is. The custom
`Flag` already mints a pseudo-member for unknown/composite bits (`enums.py:381-412`); #2770 only adds
the `is_unknown` property (`Flag.is_unknown = bool(self._value_ & ~self.__class__.__everything__._value_)`)
and drops the raw-type unions on flag fields. See `../02-enums/00-strategy-and-forward-compat.md`.

Because a custom `Flag` is not an `enum.Enum` subclass, msgspec treats a `Permissions`-typed field as a
custom type and routes it through the global `dec_hook`/`enc_hook`
(`../01-foundations/02-custom-scalar-types-and-hooks.md`):

```python
# dec_hook: t is the annotated field type, obj the decoded JSON primitive (here the string bitmask)
if issubclass(t, (enums.Enum, enums.Flag)):
    return t(obj)          # _FlagMeta.__call__ coerces the string via int(); #2770 guarantees an instance
# enc_hook: custom Flag is an int subclass -> emit a plain primitive (encode gap, D4/D7)
if isinstance(obj, permissions.Permissions):
    return str(int(obj))   # wire is a string
```

- Decode is inherently **tolerant** — Discord adds permission bits routinely, and the custom `Flag`
  keeps unknown bits in an `is_unknown` pseudo-member rather than raising. No stdlib `KEEP`-boundary or
  3.10-floor concern applies (those only existed for the withdrawn `IntFlag` port).
- Drop the dead `| int` on `Permissions` fields (a `Flag.__call__` never returned a bare int; #2770
  lands this strict-typing sweep upstream, `../02-enums/03-strict-enum-field-inventory.md`).
- The `all_permissions()` classmethod (`permissions.py:322-335`) is unchanged.

### 3.4 Locale — keep the custom `(str, Enum)`, decode via the shared `dec_hook`

`Locale` STAYS `hikari.internal.enums.Enum` `(str, Enum)`; it is **not** ported to `enum.StrEnum` (no
3.10-floor concern) and keeps its existing `__str__`. #2770 changes the custom `Enum.__call__` to mint
a value-preserving pseudo-member instance on a lookup miss (matching what `Flag` already did) and adds
`is_unknown` (`Enum.is_unknown = self._value_ not in self._value_to_member_map_`). See
`../02-enums/00-strategy-and-forward-compat.md`.

```python
class Locale(str, enums.Enum):                 # custom hikari Enum, unchanged type
    ID = "id"; DA = "da"; ...; EN_US = "en-US"; ...
```

Because the custom `Enum` is not an `enum.Enum` subclass, msgspec routes a `Locale`-typed field to the
global `dec_hook`, which calls `Locale(obj)`; #2770 guarantees the result is a `Locale` instance even
for an unknown Discord locale (`is_unknown=True`; `str(x)`, `==`, membership all work). Empirically
verified against msgspec 0.21.1 (dossier 15, `../12-appendices/02-custom-enum-feasibility.md`). Drop
the `Locale | str` union (7 field sites, dossier 05 §3d).

- **Locale as dict keys**: localization maps decode as `Mapping[Locale, str]`. JSON object keys are
  strings; msgspec routes each custom-enum key through the same `dec_hook` (`Locale(k)`), so unknown
  locales become `is_unknown` pseudo-member keys — empirically verified for `dict[Locale, str]`
  (dossier 15 §3, `../12-appendices/02-custom-enum-feasibility.md`). Maps that are re-keyed for other
  reasons build the key in Python via the same cast (`../05-entity-factory/02-hard-cases-and-transforms.md`).
- `str(Locale.EN_US) == "en-US"` because it subclasses `str`; on encode the `enc_hook` lowers a
  `Locale` to its plain `str` value (uniform with the other custom enums,
  `../01-foundations/02-custom-scalar-types-and-hooks.md`).

### 3.5 ColorGradient → frozen Struct (builder + received)

```python
class ColorGradient(msgspec.Struct, frozen=True, kw_only=True):   # not Unique -> default eq is fine
    primary_color: colors.Color
    secondary_color: colors.Color | None = None
    tertiary_color: colors.Color | None = None

    @classmethod
    def holographic(cls) -> ColorGradient: ...     # ports verbatim (colors.py:623-636)
    @classmethod
    def of(cls, primary, secondary=None, tertiary=None) -> ColorGradient: ...   # ports verbatim

    @property
    def primary_colour(self): return self.primary_color   # + secondary_colour/tertiary_colour aliases
```

- Not `Unique` → accept msgspec's default all-field `eq` (immutable scalar record; conventions §2
  value-object rule).
- `Color` members route through the `Color` hook when a gradient is decoded from an object; but the
  received-role path builds it via `ColorGradient.of(payload["color"])` from a **flat int**
  (`entity_factory.py:2223`) — a **T** transform, not declarative decode.
- Drop `@attrs_extensions.with_copy` (frozen ⇒ copy machinery is dead, D8).

### 3.6 Unique — keep as-is

`snowflakes.Unique` (`:103-132`) is unchanged and remains the base every wire Struct inherits for
id-only `__eq__`/`__hash__`. The load-bearing behavior — RESOLVED in foundations §3–§4 (V1, dossier 16)
— is that msgspec `frozen=True, eq=False` on a Struct whose non-Struct base (`Unique`) defines
`__eq__`/`__hash__` yields immutability AND uses the inherited dunders (msgspec does **not** set
`__hash__ = None`).
That experiment lives in `../01-foundations/01-base-struct-conventions.md`; this module supplies the
base but does not re-run the proof.

--------------------------------------------------------------------------------------------------

## 4. Step-by-step migration

1. **Adopt #2770 for `Permissions`** — keep the custom `Flag` (do not port to `IntFlag`); #2770 adds
   `is_unknown`, and the custom `Flag` already mints unknown-bit pseudo-members. Keep the ~20-method
   set-API and `@typing.final`; confirm all 55 members and their non-contiguous bit values are
   unchanged (`permissions.py:86-320`). See `../02-enums/00-strategy-and-forward-compat.md`.
2. **Adopt #2770 for `Locale`** — keep the custom `(str, Enum)` (do not port to `StrEnum`); #2770
   makes `Enum.__call__` mint a value-preserving pseudo-member on a miss and adds `is_unknown`. Keep
   all ~31 members and their string values (`locales.py:36-131`).
3. **Register the global hooks** in `../01-foundations/02-custom-scalar-types-and-hooks.md`:
   `Snowflake` (str↔Snowflake), `Color` (int↔Color), and the shared custom-enum/flag routing
   (`return t(obj)` on decode, `return o.value` on encode) that covers both `Permissions` and `Locale`.
4. **Convert `ColorGradient`** to a frozen Struct (§3.5); drop `with_copy`; keep `holographic`/`of`
   classmethods and the `*_colour` alias properties.
5. **Repoint `colours.py`** aliases at the new `ColorGradient` (no code change if the name is stable).
6. **Sweep downstream field annotations** to the bare strict types (this is #2770's strict-typing
   sweep): drop `| int` on `Permissions`/`PermissionOverwriteType`/etc. and `| str` on `Locale` (the
   strict-field inventory in `../02-enums/03-strict-enum-field-inventory.md` is the authoritative list).
7. **Audit builder dicts for leaking int subclasses** (conventions §6/D7): any `Snowflake`/`Color`
   handed to `msgspec.json.encode` inside a builder dict TypeErrors unless the `enc_hook` is
   registered or the builder lowers to plain `int`/`str`. `put_snowflake` already stringifies; audit
   `Color`/`Permissions` paths.

--------------------------------------------------------------------------------------------------

## 5. Affected files & symbols

| Path / anchor | Change |
|---|---|
| `hikari/snowflakes.py:50-100` | unchanged type; hook registration lives in foundations |
| `hikari/snowflakes.py:103-132` | `Unique` unchanged; identity base for all wire Structs |
| `hikari/colors.py:75-181` | `Color` unchanged; add dec/enc hook |
| `hikari/colors.py:596-678` | `ColorGradient` attrs → frozen Struct; drop `with_copy` |
| `hikari/colours.py:31-38` | alias re-export unchanged |
| `hikari/permissions.py:32-336` | stays custom `enums.Flag`; adopt #2770 (`is_unknown`); `all_permissions` unchanged |
| `hikari/locales.py:32-131` | stays custom `(str, enums.Enum)`; adopt #2770 (pseudo-member `__call__`, `is_unknown`) |
| `hikari/internal/data_binding.py:357-408` | `put_snowflake*` retained for encode (recommended) |
| `hikari/impl/entity_factory.py` | 241 `Snowflake(...)`, 14 `Color(...)`, 18 `Permissions(...)`, 22 `Locale(...)` construction sites feed/inform hooks; `burst_colors`/gradient stay transforms |

--------------------------------------------------------------------------------------------------

## 6. Risks / gotchas

1. **Int-subclass encode gap (verified):** `Snowflake`/`Color`/`Permissions` (all int subclasses)
   cannot be msgspec-encoded natively — `enc_hook` or the hand builders are mandatory. Missing this
   surfaces as a runtime `TypeError` only on the encode path (request bodies).
2. **Permissions stays tolerant by construction** — the custom `Flag` mints an `is_unknown`
   pseudo-member for unknown bits, so a new Discord permission bit never crashes decode. Do not
   "simplify" it to a native stdlib `IntFlag` field (that would reintroduce the `KEEP`-boundary /
   3.10-floor question the custom `Flag` avoids entirely).
3. **Semantic change (conventions §3, delivered by #2770):** an unknown scalar-enum value is a bare
   `int`/`str` today (the custom `Enum` returns the raw value on a miss, `enums.py:153-156`); after
   #2770 it is an `is_unknown` pseudo-member — `== the raw value` and `int(x)`/`str(x)` still hold,
   but `isinstance(x, TheEnum)` is now `True`. Document in
   `../11-rollout/03-breaking-changes-and-changelog.md`.
4. **Color range guard** is only preserved if the field is typed `Color` (hook fires). A stray plain
   `int` field silently drops validation.
5. **`ColorGradient` received path** is not declarative — `Role.colors` is built from the flat
   `color` int when no `colors` object is present (`entity_factory.py:2216-2220`, see
   `05-guilds-members-roles.md` §Role).

--------------------------------------------------------------------------------------------------

## 7. Verification

- **Snowflake round-trip:** `Decoder(Snowflake).decode(b'"123"') == 123` and is a `Snowflake`;
  `encode(Snowflake(123)) == b'"123"'` (with the enc_hook). Confirm the empirical int-subclass
  encode `TypeError` reproduces without the hook (guards against silently relying on native encode).
- **Color guard:** decoding `16777216` (0x1000000) raises `ValidationError`/`ValueError` via the hook;
  `16711680` decodes to `Color(0xFF0000)`.
- **Permissions tolerance:** decode a bitmask string with an undefined high bit (e.g. `str(1<<60)`)
  → a `Permissions` value equal to that int with `is_unknown` True, no error; `int(result) == 1<<60`.
- **Locale forward-compat:** decode `"xx-YY"` (not a member) → a `Locale` `is_unknown` pseudo-member
  with `value == "xx-YY"`, `str(x) == "xx-YY"`; decode `"en-US"` → `Locale.EN_US`.
- **ColorGradient:** `ColorGradient.holographic()` and `.of(0xFF0000)` construct; frozen (attribute
  set raises); default `eq` holds for equal-field instances.
- **Unique identity:** the foundations `eq=False`+`Unique` design is RESOLVED (V1); assert a decoded
  wire Struct hashes/compares by `id` only (`../10-testing/02-cache-copy-and-enum-tests.md`).

--------------------------------------------------------------------------------------------------

## 8. Open questions / decisions

Cross-link `../00-overview/05-decisions-log.md`:

- **D2 / strict enums:** keep the custom `Enum`/`Flag`; adopt #2770 (value-preserving pseudo-member on
  unknown for both `Locale` and `Permissions`, `is_unknown`, strict field typing). No `UNKNOWN`
  sentinel; no stdlib `IntFlag`/`StrEnum` port.
- **D4 / scalar hooks:** confirm the global-hook-vs-hand-builder split for encode (recommend keeping
  `put_snowflake*` builders for the first pass).
- **VERIFY:** Locale/Snowflake as msgspec **dict keys** — the custom-enum `dec_hook` fires for
  `dict[Locale, str]` keys (verified, dossier 15 §3); Snowflake **subtype** keys still need a check.
  Either way the affected localization / re-keyed maps stay residual transforms (they already are).
- **RESOLVED:** `eq=False` + inherited `Unique` dunders (conventions §3–§4, V1 / dossier 16) — proven
  in foundations; all scalar-typed wire Structs depend on it. Only the CPython 3.10-floor re-run remains.
