# Scalars — snowflakes, colors/colours, permissions, locales

Purpose: migrate the four leaf scalar modules every model field is typed against. These are mostly
**not** attrs classes — they are `int`/`str` subclasses and custom `Flag`/`Enum` types — so the work
is (i) making msgspec route them through the global `dec_hook`/`enc_hook`, (ii) porting the two
enum-framework members (`Permissions`, `Locale`) onto stdlib enums, and (iii) turning the one attrs
class here (`colors.ColorGradient`) into a frozen Struct. These land first (dependency order,
`00-README.md` §3) so downstream modules can type their fields against the finished scalars.

--------------------------------------------------------------------------------------------------

## 1. Objective

Serves constraints (b) strict enums and (a)/(c) indirectly (these scalars carry no `app` and are
already immutable). Concretely:

- Keep `Snowflake(int)` and `Color(int)` as int subclasses; wire them to the global scalar hooks
  (`../01-foundations/02-custom-scalar-types-and-hooks.md`, decision D4).
- Port `permissions.Permissions` off `hikari.internal.enums.Flag` onto `enum.IntFlag` + a shared
  set-API mixin (D2, `../02-enums/01-flags-migration.md`), decoded tolerantly.
- Port `locales.Locale` off `hikari.internal.enums.Enum` onto `class Locale(str, enum.Enum)` with a
  value-preserving `_missing_` (D2, `../02-enums/02-int-and-str-enums-migration.md`).
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
arm is the "unknown Discord value" escape hatch (dossier 02 Part C).

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

### 3.3 Permissions → `enum.IntFlag` + set-API mixin (tolerant decode)

Port off `enums.Flag` onto stdlib `IntFlag` with the shared hikari `Flag` set-API re-attached
(`.all/.any/.none/.split/.difference/.intersection/.union/.is_subset/…`, ~20 methods) as designed in
`../02-enums/01-flags-migration.md`:

```python
class Permissions(_FlagMixin, enum.IntFlag):   # _FlagMixin restores hikari's set-API
    NONE = 0
    CREATE_INSTANT_INVITE = 1 << 0
    ...
    BYPASS_SLOWMODE = 1 << 52
    @classmethod
    def all_permissions(cls) -> Permissions: ...   # ports verbatim
```

Decode stays **tolerant regardless of the global strict policy** (D4) — Discord adds permission
bits routinely, and a strict reject would crash decode on the next new bit:

```python
if type_ is permissions.Permissions:
    return permissions.Permissions(int(obj))   # obj is the JSON string bitmask; IntFlag keeps unknown bits
# encode:
if isinstance(obj, permissions.Permissions):
    return str(int(obj))                        # wire is a string
```

- Native `IntFlag` retains unknown bits under the `KEEP` boundary (default on 3.11+; **VERIFY on the
  3.10 floor**, conventions §3 / `../02-enums/01-flags-migration.md`). The `int(obj)` hook still
  fires because the wire is a **string**, not an int, so msgspec never sees a decodable IntFlag.
- Drop the dead `| int` on `Permissions` fields (a `Flag.__call__` never returned a bare int).
- Behavioral members port verbatim: `all_permissions()` (conventions §3).

### 3.4 Locale → `class Locale(str, enum.Enum)` + `_missing_` pseudo-member

```python
class Locale(str, enum.Enum):                  # NOT enum.StrEnum (3.10 floor)
    ID = "id"; DA = "da"; ...; EN_US = "en-US"; ...
    _missing_ = classmethod(_str_enum_missing) # mints a value-preserving pseudo-member (D2)
```

Empirically (dossier 02 §E / 09 §5), msgspec invokes `_missing_` on a lookup miss and accepts the
returned pseudo-member, so fields can be typed as the **bare** `Locale` while an unknown Discord
locale still decodes (`str(x)`, `==`, membership all work). No scalar `dec_hook` is needed — msgspec
decodes the JSON string natively against the enum. Drop the `Locale | str` union (7 field sites,
dossier 05 §3d).

- **Locale as dict keys**: localization maps decode as `dict[Locale, str]`; msgspec applies the
  enum (and `_missing_`) to string keys. Confirm in the enum plan's empirical checks; if key-`_missing_`
  is unsupported, the maps stay a residual transform (they are re-keyed anyway).
- `str(Locale.EN_US) == "en-US"` because it subclasses `str` — encode is native, no `enc_hook`.

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
id-only `__eq__`/`__hash__`. The load-bearing VERIFY (conventions §2) is that msgspec
`frozen=True, eq=False` on a Struct whose non-Struct base (`Unique`) defines `__eq__`/`__hash__`
yields immutability AND uses the inherited dunders (rather than msgspec setting `__hash__ = None`).
That experiment lives in `../01-foundations/01-base-struct-conventions.md`; this module supplies the
base but does not re-run the proof.

--------------------------------------------------------------------------------------------------

## 4. Step-by-step migration

1. **Port `Permissions` to `IntFlag`** using the shared mixin from `../02-enums/01-flags-migration.md`;
   port `all_permissions()` verbatim; keep `@typing.final`. Verify all 55 members and their
   non-contiguous bit values are unchanged (`permissions.py:86-320`).
2. **Port `Locale` to `class Locale(str, enum.Enum)`** with the shared str-enum `_missing_`
   (`../02-enums/02-int-and-str-enums-migration.md`); keep all ~31 members and their string values
   (`locales.py:36-131`).
3. **Register the global hooks** for `Snowflake` (str↔Snowflake), `Color` (int↔Color),
   `Permissions` (str↔int flag) in `../01-foundations/02-custom-scalar-types-and-hooks.md`. `Locale`
   needs no scalar hook (native str-enum decode).
4. **Convert `ColorGradient`** to a frozen Struct (§3.5); drop `with_copy`; keep `holographic`/`of`
   classmethods and the `*_colour` alias properties.
5. **Repoint `colours.py`** aliases at the new `ColorGradient` (no code change if the name is stable).
6. **Sweep downstream field annotations** to the bare strict types once the enums are ported: drop
   `| int` on `Permissions`/`PermissionOverwriteType`/etc. and `| str` on `Locale` (the strict-field
   inventory in `../02-enums/03-strict-enum-field-inventory.md` is the authoritative list).
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
| `hikari/permissions.py:32-336` | `enums.Flag` → `enum.IntFlag` + set-API mixin; `all_permissions` verbatim |
| `hikari/locales.py:32-131` | `enums.Enum` → `str, enum.Enum` + `_missing_` |
| `hikari/internal/data_binding.py:357-408` | `put_snowflake*` retained for encode (recommended) |
| `hikari/impl/entity_factory.py` | 241 `Snowflake(...)`, 14 `Color(...)`, 18 `Permissions(...)`, 22 `Locale(...)` construction sites feed/inform hooks; `burst_colors`/gradient stay transforms |

--------------------------------------------------------------------------------------------------

## 6. Risks / gotchas

1. **Int-subclass encode gap (verified):** `Snowflake`/`Color`/`Permissions` (all int subclasses)
   cannot be msgspec-encoded natively — `enc_hook` or the hand builders are mandatory. Missing this
   surfaces as a runtime `TypeError` only on the encode path (request bodies).
2. **Permissions must stay tolerant** even under a global strict-enum policy — a new Discord bit
   would otherwise crash every decode carrying `permissions`. The string wire form + `int()` hook
   guarantees tolerance; do not "simplify" it to a native IntFlag field.
3. **3.10 IntFlag boundary:** unknown-bit retention is `KEEP` by default on 3.11+ but must be
   verified on the 3.10 floor (`../02-enums/01-flags-migration.md`).
4. **Semantic change (conventions §3):** an unknown int-enum value is a bare `int` today; after the
   port it is an enum pseudo-member — `== the int` and `int(x)` still hold, but `type(x) is int` is
   now `False` and `isinstance(x, TheEnum)` is now `True`. Document in
   `../11-rollout/03-breaking-changes-and-changelog.md`.
5. **Color range guard** is only preserved if the field is typed `Color` (hook fires). A stray plain
   `int` field silently drops validation.
6. **`ColorGradient` received path** is not declarative — `Role.colors` is built from the flat
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
  → an `IntFlag` value equal to that int, no error; `int(result) == 1<<60`.
- **Locale forward-compat:** decode `"xx-YY"` (not a member) → a `Locale` pseudo-member with
  `value == "xx-YY"`, `str(x) == "xx-YY"`; decode `"en-US"` → `Locale.EN_US`.
- **ColorGradient:** `ColorGradient.holographic()` and `.of(0xFF0000)` construct; frozen (attribute
  set raises); default `eq` holds for equal-field instances.
- **Unique identity:** covered by the foundations `eq=False`+`Unique` experiment; assert a decoded
  wire Struct hashes/compares by `id` only (`../10-testing/02-cache-copy-and-enum-tests.md`).

--------------------------------------------------------------------------------------------------

## 8. Open questions / decisions

Cross-link `../00-overview/05-decisions-log.md`:

- **D2 / strict enums:** confirmed value-preserving `_missing_` for `Locale` (open-ended set) and
  `KEEP`-boundary `IntFlag` for `Permissions`. No `UNKNOWN` sentinel.
- **D4 / scalar hooks:** confirm the global-hook-vs-hand-builder split for encode (recommend keeping
  `put_snowflake*` builders for the first pass).
- **VERIFY:** Locale/Snowflake as msgspec **dict keys** — does `_missing_`/subtype-key decode fire?
  If not, the affected localization / re-keyed maps stay residual transforms (they already are).
- **VERIFY:** `eq=False` + inherited `Unique` dunders (conventions §2) — proven in foundations; all
  scalar-typed wire Structs depend on it.
