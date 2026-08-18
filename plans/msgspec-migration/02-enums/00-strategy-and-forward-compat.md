# Enums — Strategy and Forward-Compatibility

Purpose: define the end-state enum architecture for the msgspec migration and prove it preserves
hikari's current tolerance of unknown Discord enum/flag values. This file is the umbrella for the four
sibling files in this folder; it fixes the two-strategy design (`IntFlag` for flags, stdlib enum +
value-preserving `_missing_` for scalar enums), explains why the pervasive `SomeEnum | int` union is a
hard blocker under msgspec, and catalogues the resulting semantic change.

This slice implements constraint (b) of the migration (strict enum fields; see
`../00-overview/05-decisions-log.md` decision D2). It is the precondition for typed decode of every
model module in `../06-model-modules/`.

--------------------------------------------------------------------------------------------------

## 1. Objective

- Move all **80** concrete enum/flag types off hikari's bespoke metaclasses in
  `hikari/internal/enums.py` onto **stdlib `enum`**, because msgspec only understands stdlib enums.
- Preserve today's forward-compatibility: a Discord value hikari does not yet know about must still
  decode without raising, keeping its raw scalar recoverable.
- Enable every entity field to be annotated with the **bare strict enum type** (dropping ~150
  `SomeEnum | int` / `SomeEnum | str` unions) as constraint (b) requires — while `msgspec.json.decode`
  never raises `ValidationError` on an unknown value.
- Do all of the above with **zero happy-path decode overhead** (unknown values take a slow Python path
  only on a miss).

Inventory (verified in dossier 02 Part B): **55 int enums · 12 str enums · 13 flags = 80 types**.

--------------------------------------------------------------------------------------------------

## 2. Current state

### 2.1 hikari enums are NOT stdlib enums

Every concrete enum is declared against `hikari.internal.enums` — `class X(int, enums.Enum)`,
`class X(str, enums.Enum)`, or `class X(enums.Flag)` — built on the custom metaclasses `_EnumMeta`
(`hikari/internal/enums.py:153`) and `_FlagMeta` (`hikari/internal/enums.py:380`). msgspec 0.21.1 has
**zero** knowledge of these metaclasses: a field typed with such an enum decodes as
`ValidationError: Expected 'ChannelType', got 'int'` (dossier 13 §10, empirically verified). So the
reparent is mandatory, not optional.

### 2.2 Two current tolerance mechanisms

| Layer | Mechanism | Anchor | Result on unknown value |
|---|---|---|---|
| int/str Enum | `_EnumMeta.__call__` returns `_value_to_member_map_.get(value, value)` | `enums.py:154-156` | returns the **raw `int`/`str`** (hence `SomeEnum \| int` fields) |
| Flag | `_FlagMeta.__call__` mints & caches a pseudo-member | `enums.py:381-412` | returns a **Flag instance** holding the unknown bits (never a bare int) |

The int/str path is why ~150 fields are typed `SomeEnum | int` / `SomeEnum | str` — the annotation
has to admit the raw value that `EnumType(raw)` returns on a miss. The Flag path already returns a
strict Flag, so flag fields are (mostly) typed strictly today.

Polymorphic dispatch is a **separate** third mechanism: an unknown *type discriminator* raises
`errors.UnrecognisedEntityError` (`hikari/errors.py:127`) and the caller discards the object. That is
orthogonal to scalar tolerance and is covered in `04-enums-module-and-machinery.md` §5 and
`../05-entity-factory/01-polymorphism-and-tagged-unions.md`.

--------------------------------------------------------------------------------------------------

## 3. Why `SomeEnum | int` is a hard msgspec blocker (not a soft one)

This is the load-bearing constraint. msgspec rejects the union **at type-construction time**, before
any decode runs (dossier 13 §15, verified against msgspec 0.21.1):

```python
class M(msgspec.Struct):
    t: MessageType | int            # TypeError at class creation
# TypeError: Type unions may not contain more than one int-like type
#            ('int', 'Enum', 'Literal[int values]')
```

The same rule kills `SomeStrEnum | str` (str-like collision) and `SomeIntEnum | Literal[...]`. msgspec
permits **at most one** int-like arm, one str-like arm, one untagged object-like arm, and one untagged
array-like arm in a union; multiple struct arms only via tagged unions; custom types only as
`Custom | None`.

Consequence: the `SomeEnum | int` idiom **cannot be carried forward at all**. It is not a stylistic
choice to tighten — it is impossible to express. Every one of the ~150 unions in dossier 02 Part C
(the full table lives in `03-strict-enum-field-inventory.md`) must be redesigned to a bare enum. The
forward-compat that the union used to buy must therefore move **into the enum type itself**.

--------------------------------------------------------------------------------------------------

## 4. Target design — the two-strategy split

### 4.1 Flags → `enum.IntFlag` (forward-compat for free)

`enum.IntFlag` tolerates unknown bits natively. Verified (dossier 02 §E.3, dossier 13 §10):

```python
class F(enum.IntFlag):
    ONE = 1; TWO = 2; FOUR = 4
msgspec.json.decode(b'8',  type=F)   # -> <F: 8>          (undefined bit kept, no error)
msgspec.json.decode(b'15', type=F)   # -> <F.ONE|TWO|FOUR|8: 15>   (composite + stray bit)
```

This exactly matches hikari's current pseudo-member behavior — unknown bits are preserved and
`int(x)` round-trips losslessly. So the 13 flags need **no `_missing_`** and **no hook**: they just
become `IntFlag`, keep forward-compat, and drop the dead `| int`. The only work is re-attaching
hikari's rich `Flag` set-API (~20 methods) as an `IntFlag` mixin. Full plan in
`01-flags-migration.md`.

`boundary` caveat: the KEEP boundary that preserves unknown bits is the **default on CPython 3.11+**.
hikari's floor is 3.10 (`pyproject.toml:33`, `requires-python = ">=3.10.0,<3.15"`). On 3.10 `IntFlag`
also tolerates unknown bits by default, but this must be **empirically confirmed on the 3.10 floor**
before relying on it (VERIFY-E1, see §9).

### 4.2 Int/str scalar enums → stdlib enum + value-preserving `_missing_`

msgspec calls the enum's `_missing_` classmethod on a value-table miss and **accepts a dynamically
minted pseudo-member** it returns (dossier 02 §E.4, verified). We exploit that to mint a
value-preserving pseudo-member — the direct analogue of `_FlagMeta`'s pseudo-member, applied to scalar
enums:

```python
class _MissingMixin:
    """Shared mixin: mint a value-preserving pseudo-member on an unknown Discord value."""

    _hikari_pseudo_cache: typing.ClassVar[dict[object, typing.Any]]

    @classmethod
    def _missing_(cls, value: object) -> typing.Any:
        cache = cls.__dict__.get("_hikari_pseudo_cache")
        if cache is None:
            cache = {}
            cls._hikari_pseudo_cache = cache
        if value in cache:
            return cache[value]
        # int enums mint via int.__new__, str enums via str.__new__ (the enum's value base).
        member = cls._value_base_.__new__(cls, value)
        member._name_ = f"UNKNOWN_{value}"
        member._value_ = value
        cache[value] = member
        if len(cache) > _MAX_CACHED_MEMBERS:      # bounded like enums.py:39 (4096)
            cache.pop(next(iter(cache)))
        return member

class MessageType(_MissingMixin, int, enum.Enum):
    _value_base_ = int
    DEFAULT = 0
    ...

msgspec.json.decode(b'999', type=MessageType)   # -> <MessageType.UNKNOWN_999: 999>, int(x) == 999
```

Key properties, all verified in the dossiers:

- Field is annotated **strictly** as `MessageType` (constraint (b) satisfied) — no union.
- Unknown value **decodes** to a real enum instance whose `int(x)`/`str(x)`/`== raw` all work — the
  raw value is **preserved** (this is Strategy 2 in dossier 02 §E.5, the value-preserving one).
- Known members hit the fast C value→member table; `_missing_` runs **only on a miss** → happy-path
  decode speed is unchanged (dossier 02 §E.4, dossier 13 §10).
- The pseudo-member cache is bounded, mirroring hikari's `_MAX_CACHED_MEMBERS = 4096`
  (`enums.py:39`), so a hostile stream of distinct unknown values cannot grow memory without limit.

We deliberately reject the alternative Strategy 1 (a fixed `UNKNOWN = -1` sentinel returned by
`_missing_`): it is native and fast but **loses the raw value** (`decode(12345)` → `UNKNOWN`), which is
a regression against today's pass-through behavior. Full plan and the shared mixin in
`02-int-and-str-enums-migration.md`.

### 4.3 Why not the other candidates

Ranked in dossier 02 §E.5 / dossier 13 §10; summarized:

| Rejected option | Why not |
|---|---|
| Keep `SomeEnum \| int` union | Impossible — hard `TypeError` (§3). Also violates constraint (b). |
| `_missing_ → fixed UNKNOWN` sentinel | Value-lossy; regresses today's raw-value pass-through. |
| Field typed plain `int`/`str` + `@property` casting to the enum | Value-preserving but changes the public attribute **type** (bigger API break) and drops static typing on the field. Kept as a fallback only. |
| `dec_hook` per enum | msgspec's hook only fires for types it does **not** handle; stdlib enums ARE handled, so a hook never intercepts them without wrapping each in a custom class — heavier and defeats native enum decode. |

--------------------------------------------------------------------------------------------------

## 5. Forward-compatibility matrix (end-state)

| Type family | Count | Target base | Unknown-value handling | Field annotation | Raw value kept? |
|---|---|---|---|---|---|
| Flags | 13 | `enum.IntFlag` (+ set-API mixin) | native KEEP boundary (unknown bits preserved) | bare flag, drop `\| int` | yes (bits) |
| Int enums | 55 | `(int, enum.Enum)` + `_MissingMixin` | `_missing_` mints int pseudo-member | bare enum, drop `\| int` | **yes** |
| Str enums | 12 | `(str, enum.Enum)` + `_MissingMixin` | `_missing_` mints str pseudo-member | bare enum, drop `\| str` | **yes** |
| Polymorphic type discriminators | n/a | tagged unions / hand dispatch | raise-or-skip preserved (separate concern) | see `../05-entity-factory/01-polymorphism-and-tagged-unions.md` | n/a |

No field family relies on union widening for tolerance after migration. `http.HTTPStatus` (already
stdlib `enum.IntEnum`) is msgspec-native already; its `| int` at `net.py:65` / `errors.py:282` is
dropped the same way (dossier 02 §B.5).

--------------------------------------------------------------------------------------------------

## 6. Documented semantic change (must be socialized)

Today, an unknown int-enum value flows through as a **bare `int`**. After migration it is an enum
**pseudo-member**. The observable differences (dossier 02 §F.2):

| Expression on an unknown value `x` (say raw `999` for a `MessageType` field) | Today | After migration |
|---|---|---|
| `x == 999` | `True` | `True` (unchanged) |
| `int(x)` | `999` | `999` (unchanged) |
| `x` in arithmetic / as a dict key | works | works (unchanged) |
| `type(x) is int` | `True` | **`False`** |
| `isinstance(x, MessageType)` | `False` | **`True`** |
| `x.name` | `AttributeError` (it is a bare int) | `"UNKNOWN_999"` |

This is arguably an improvement (unknown values are now typed and introspectable), but it is a
behavior change and belongs in the breaking-changes catalogue
(`../11-rollout/03-breaking-changes-and-changelog.md`) and the risk map
(`../00-overview/03-risk-and-danger-map.md`). Str enums have the analogous change plus a `str()`
subtlety documented in `02-int-and-str-enums-migration.md` §6.

--------------------------------------------------------------------------------------------------

## 7. Step-by-step (cluster-level sequencing)

The detailed steps live in the sibling files; this is the order to execute them.

1. Build the shared machinery first: the `IntFlag` set-API mixin (`01-flags-migration.md` §4) and the
   `_MissingMixin` for scalar enums (`02-int-and-str-enums-migration.md` §4). Land these as a new
   internal module (proposed `hikari/internal/enums.py` rewrite — see
   `04-enums-module-and-machinery.md`).
2. Reparent the 13 flags onto `enum.IntFlag` + mixin; port `Permissions.all_permissions`
   (`permissions.py:322`) and `Intents.is_privileged` (`intents.py:441`); drop dead `| int` on flag
   fields (`01-flags-migration.md`).
3. Reparent the 55 int + 12 str enums onto stdlib + `_MissingMixin`; preserve `str()` semantics
   explicitly (`02-int-and-str-enums-migration.md`).
4. Sweep the ~150 field/param unions per the inventory in `03-strict-enum-field-inventory.md`,
   dropping entity-field `| int`/`| str` and deciding input-param lenience separately.
5. Retire the custom metaclasses and dead `deprecated` machinery
   (`04-enums-module-and-machinery.md`).

Each step is independently testable and can land as its own PR; see
`../11-rollout/01-pr-breakdown.md`.

--------------------------------------------------------------------------------------------------

## 8. Affected files and symbols

This umbrella file changes no source directly; the concrete file/symbol inventory is enumerated per
sibling:

| Sibling file | Affected files & symbols |
|---|---|
| `01-flags-migration.md` | the 13 flag types + set-API mixin; `Permissions.all_permissions`, `Intents.is_privileged`; flag-field `\| int` drops |
| `02-int-and-str-enums-migration.md` | the 55 int + 12 str enums; the shared `_MissingMixin`; per-family `str()` semantics |
| `03-strict-enum-field-inventory.md` | the ~150 `SomeEnum \| int` / `\| str` entity-field & input-param unions |
| `04-enums-module-and-machinery.md` | `hikari/internal/enums.py` metaclass retirement; the pyright-exclusion drop |

--------------------------------------------------------------------------------------------------

## 9. Verification

- **VERIFY-E1 (3.10 floor):** Confirm `enum.IntFlag` preserves unknown bits by default on CPython
  3.10 (no explicit `boundary=KEEP`). Probe: `msgspec.json.decode(b'8', type=SomeFlag)` on 3.10 must
  return `<SomeFlag: 8>` with `int(x) == 8`, not raise. Recorded in
  `../12-appendices/01-open-questions-and-verifications.md`.
- **VERIFY-E2 (`_missing_` acceptance):** Confirm msgspec 0.21.1 accepts a returned minted
  pseudo-member for both int (`int.__new__`) and str (`str.__new__`) enums, standalone and nested in
  `list[...]` and as a `dict[...]` **key** (localization maps, dossier 02 §C.2). Already verified in
  dossier 02 §E.4; re-run in the hikari test suite as regression tests.
- **VERIFY-E3 (`str()` semantics):** Confirm `str(member)` output is preserved per enum family (see
  `02-int-and-str-enums-migration.md` §6).
- Add an unknown-value regression test per enum family that asserts `int(x)==raw` / `str(x)==raw`,
  `isinstance(x, TheEnum)`, and `x.name == "UNKNOWN_<raw>"`.
- Benchmark happy-path decode before/after to confirm no regression from the mixin (the fast table is
  untouched); record in `../11-rollout/02-performance-benchmarking.md`.

--------------------------------------------------------------------------------------------------

## 10. Open questions / decisions

Cross-linked to `../00-overview/05-decisions-log.md` (D2) and
`../12-appendices/01-open-questions-and-verifications.md`:

1. Scalar-enum tolerance policy: value-preserving `_missing_` (recommended here) vs value-lossy
   sentinel vs raw-primitive+property. Recommendation: value-preserving `_missing_` for all 67
   int/str enums.
2. Bounded pseudo-member cache: replicate the `_MAX_CACHED_MEMBERS = 4096` cap (recommended) or accept
   stdlib's unbounded composite caching? Recommend the cap for parity with `enums.py:39`.
3. Input-param `| int` lenience (~80 signatures, dossier 02 §C.3): keep or tighten? Orthogonal to
   msgspec decode; recommend keeping (decided in `03-strict-enum-field-inventory.md` §5).
4. Whether the public `Flag` set-API surface is kept in full or trimmed — see `01-flags-migration.md`
   §7. Recommendation: keep in full (it is public and the `.pyi` already declares it).
