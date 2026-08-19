# Enums — Strategy and Forward-Compatibility

Purpose: define the end-state enum architecture for the msgspec migration and prove it preserves
hikari's current tolerance of unknown Discord enum/flag values. This file is the umbrella for the four
sibling files in this folder; it fixes the single-strategy design (**keep** hikari's fast custom
`Enum`/`Flag`, adopt upstream PR hikari-py/hikari#2770, decode/encode through the shared
`dec_hook`/`enc_hook`), explains why the pervasive `SomeEnum | int` union is a hard blocker under
msgspec, and catalogues the resulting semantic change.

This slice implements constraint (b) of the migration (strict enum fields; see
`../00-overview/05-decisions-log.md` decision D2). It is the precondition for typed decode of every
model module in `../06-model-modules/`. The empirical proof that the custom enums decode/encode through
the hook lives in `../12-appendices/02-custom-enum-feasibility.md` (dossier 15, verified msgspec
0.21.1).

--------------------------------------------------------------------------------------------------

## 1. Objective

- **Keep** all **80** concrete enum/flag types on hikari's bespoke metaclasses in
  `hikari/internal/enums.py` — they are significantly faster at runtime than stdlib `enum`, which
  matters under high event/request volume. Do **not** reparent onto stdlib `enum`.
- Adopt upstream PR hikari-py/hikari#2770 as a prerequisite: it makes the custom `Enum.__call__` mint a
  synthetic "unknown member" instance on a miss (the `Flag` already did this), adds an `is_unknown`
  property to both, raises `TypeError` on wrong-type input, and types every model field / REST param
  with the bare enum/flag (dropping the `| int`/`| str` unions).
- Decode and encode the custom enums through the **single global `dec_hook`/`enc_hook`** already used
  for `Snowflake`/`Color` (`../01-foundations/02-custom-scalar-types-and-hooks.md`) — msgspec treats
  the custom enums as custom types because they are not `enum.Enum` subclasses.
- Preserve today's forward-compatibility: a Discord value hikari does not yet know about must still
  decode without raising, keeping its raw scalar recoverable (now via the `is_unknown` pseudo-member).
- Enable every entity field to be annotated with the **bare strict enum type** (dropping ~150
  `SomeEnum | int` / `SomeEnum | str` unions) as constraint (b) requires — exactly the typing sweep
  #2770 performs upstream.

Inventory (verified in dossier 02 Part B): **55 int enums · 12 str enums · 13 flags = 80 types**.

--------------------------------------------------------------------------------------------------

## 2. Current state

### 2.1 hikari enums are NOT stdlib enums — and that is what makes the hook route work

Every concrete enum is declared against `hikari.internal.enums` — `class X(int, enums.Enum)`,
`class X(str, enums.Enum)`, or `class X(enums.Flag)` — built on the custom metaclasses `_EnumMeta`
(`hikari/internal/enums.py:153`) and `_FlagMeta` (`hikari/internal/enums.py:380`). Because these are
**not** `enum.Enum` subclasses, msgspec 0.21.1 does not recognise them as native enums
(`issubclass(t, enum.Enum)` is False) and instead treats a field typed with one of them as a **custom
type**, routing it to `dec_hook(t, raw)` — exactly as it does for `Snowflake` (an `int` subclass).
The hook returns `t(raw)`, i.e. the enum's own constructor (dossier 15 §1, empirically verified). No
stdlib port is needed; the reparent is explicitly **rejected** (§4.3).

### 2.2 Two current tolerance mechanisms

| Layer | Mechanism | Anchor | Result on unknown value |
|---|---|---|---|
| int/str Enum | `_EnumMeta.__call__` returns `_value_to_member_map_.get(value, value)` | `enums.py:154-156` | returns the **raw `int`/`str`** (hence `SomeEnum \| int` fields) |
| Flag | `_FlagMeta.__call__` mints & caches a pseudo-member | `enums.py:381-412` | returns a **Flag instance** holding the unknown bits (never a bare int) |

The int/str path is why ~150 fields are typed `SomeEnum | int` / `SomeEnum | str` — the annotation
has to admit the raw value that `EnumType(raw)` returns on a miss. The Flag path already returns a
strict Flag, so flag fields are (mostly) typed strictly today. PR #2770 makes the **Enum** path behave
like the Flag path (mint a pseudo-member instance instead of returning the raw value); see §4.

Polymorphic dispatch is a **separate** third mechanism: an unknown *type discriminator* raises
`errors.UnrecognisedEntityError` (`hikari/errors.py:127`) and the caller discards the object. That is
orthogonal to scalar tolerance and is covered in `04-enums-module-and-machinery.md` §5 and
`../05-entity-factory/01-polymorphism-and-tagged-unions.md`.

--------------------------------------------------------------------------------------------------

## 3. Why `SomeEnum | int` is a hard msgspec blocker (not a soft one)

This is the load-bearing constraint that forces the strict field typing. msgspec rejects the union
**at type-construction time**, before any decode runs (dossier 13 §15, verified against msgspec
0.21.1):

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
(the full table lives in `03-strict-enum-field-inventory.md`) must be redesigned to a bare enum. This
is exactly the typing sweep PR #2770 lands upstream (`changes/2770.breaking.md`: "model fields and
REST parameters are now typed with only the enum/flag type instead of a union with its raw type"). The
forward-compat that the union used to buy moves **into the enum type itself** — #2770's
pseudo-member `__call__` (§4).

--------------------------------------------------------------------------------------------------

## 4. Target design — keep the custom enums, adopt #2770, route through the hook

### 4.1 Flags already satisfy the hook invariant

hikari's custom `Flag` already mints a pseudo-member instance on any unknown/composite value
(`_FlagMeta.__call__`, `enums.py:381-412`), so `SomeFlag(raw)` is always a `SomeFlag` instance — never a
bare int. That is exactly the invariant `dec_hook` needs (§4.4). The only work on the 13 flags is the
strict-typing sweep: drop the dead `SomeFlag | int` unions (they never held a bare int). Full plan in
`01-flags-migration.md`. #2770 additionally adds `Flag.is_unknown`
(`bool(self._value_ & ~self.__class__.__everything__._value_)`) for introspection.

### 4.2 Int/str scalar enums get #2770's pseudo-member `__call__`

Pre-#2770, `_EnumMeta.__call__` returns the **raw `int`/`str`** on a miss (`enums.py:154-156`), which
is **not** an instance of the enum type — so `dec_hook` returning it would fail msgspec's
instance-of-type check (`ValidationError: Expected 'X', got 'int'`, dossier 15 §3 Probe A). PR #2770
changes `_EnumMeta.__call__` to mint and cache a synthetic pseudo-member instance on a miss, mirroring
what `Flag` already does (dossier 15 §2, verbatim from the PR head):

```python
def __call__(cls, value: object) -> Enum:
    """Cast a value to the enum, returning an unknown member if the value is not a known one."""
    try:
        return cls._value_to_member_map_[value]
    except KeyError:
        try:
            return cls._temp_members_[value]
        except KeyError:
            if not isinstance(value, cls.__objtype__):
                msg = f"{cls.__name__} values must be of type {cls.__objtype__.__name__}, not {type(value).__name__}"
                raise TypeError(msg) from None
            member = cls.__new__(cls, value)
            member._name_ = None
            member._value_ = value
            cls._temp_members_[value] = member
            if len(cls._temp_members_) > _MAX_CACHED_MEMBERS:
                cls._temp_members_.popitem()
            return member
```

Key properties (dossier 15 §2–§3, verified msgspec 0.21.1):

- `MessageType(999)` → a `MessageType` **instance** with `is_unknown == True` and `_value_ == 999`;
  `int(x) == 999`, `x == 999`, `isinstance(x, MessageType) == True`. The raw value is **preserved**
  and `Enum.name` lazily renders unknowns as `f"UNKNOWN {self._value_!r}"`.
- Fields are annotated **strictly** as `MessageType` (constraint (b) satisfied) — no union.
- Known members still hit the fast value→member table; the pseudo-member path runs **only on a miss**.
- The `_temp_members_` cache is bounded by `_MAX_CACHED_MEMBERS = 4096` (`enums.py:39`), so a hostile
  stream of distinct unknown values cannot grow memory without limit.
- Wrong-type input (a value not of `__objtype__`) raises `TypeError`. msgspec passes the decoded JSON
  primitive to the hook (int for an int-enum field, str for a str-enum field), which matches
  `__objtype__`, so the happy path never trips this; a genuinely wrong wire type surfaces as a
  `ValidationError` (msgspec converts a hook `TypeError`/`ValueError` into `ValidationError`).

#2770 also adds `Enum.is_unknown` (`self._value_ not in self._value_to_member_map_`). Full plan in
`02-int-and-str-enums-migration.md`.

### 4.3 Why not reparent onto stdlib enum

Ranked in dossier 15 §5–§6 and the decision log; summarized:

| Rejected option | Why not |
|---|---|
| Port all 80 types to stdlib `enum` (IntFlag + `_missing_` mixin) | Loses hikari's faster custom runtime enum ops (comparisons, flag algebra, member/name access) on the hot path. The maintainer prioritizes runtime speed; the port is withdrawn. |
| Keep `SomeEnum \| int` union | Impossible — hard `TypeError` (§3). Also violates constraint (b). |
| `dec_hook` per stdlib enum wrapper | Heavier and defeats native enum decode; moot once the custom enums are kept (the hook fires for them naturally because they are not `enum.Enum` subclasses). |

The custom enums are kept; the only enum runtime change is adopting #2770's `__call__`/`is_unknown`.

### 4.4 The shared hook (the single integration point)

The same global hooks that already route `Snowflake`/`Color` gain one branch each for the custom
enums (full design in `../01-foundations/02-custom-scalar-types-and-hooks.md`):

```python
def dec_hook(t: type, obj: object) -> object:
    if issubclass(t, (enums.Enum, enums.Flag)):
        return t(obj)                    # #2770 guarantees an instance of t (pseudo-member on miss)
    if t is snowflakes.Snowflake: ...    # existing scalar routing
    ...

def enc_hook(o: object) -> object:
    if isinstance(o, (enums.Enum, enums.Flag)):
        return o.value                   # plain int/str primitive (avoids the int-subclass encode gap)
    ...
```

The load-bearing invariant: `dec_hook` **must** return an instance of the annotated type `t` (msgspec
does an `isinstance` check on the hook's result). #2770's pseudo-member `__call__` guarantees this for
`Enum`; the custom `Flag` already guaranteed it. Without #2770 (raw-value-on-miss), msgspec raises
`ValidationError: Expected 'X', got 'int'` on any unknown value (dossier 15 §3 Probe A). On encode,
returning `o.value` emits a plain int/str primitive, sidestepping msgspec's int-subclass encode gap.

--------------------------------------------------------------------------------------------------

## 5. Forward-compatibility matrix (end-state)

| Type family | Count | Runtime type | Unknown-value handling | Field annotation | Raw value kept? |
|---|---|---|---|---|---|
| Flags | 13 | custom `enums.Flag` (kept) | `_FlagMeta.__call__` mints a pseudo-member; `is_unknown` per #2770 | bare flag, drop `\| int` | yes (bits) |
| Int enums | 55 | custom `(int, enums.Enum)` (kept) | #2770 `__call__` mints an `is_unknown` int pseudo-member | bare enum, drop `\| int` | **yes** |
| Str enums | 12 | custom `(str, enums.Enum)` (kept) | #2770 `__call__` mints an `is_unknown` str pseudo-member | bare enum, drop `\| str` | **yes** |
| Polymorphic type discriminators | n/a | tagged unions / hand dispatch | raise-or-skip preserved (separate concern) | see `../05-entity-factory/01-polymorphism-and-tagged-unions.md` | n/a |

Every family decodes/encodes through the **same** shared `dec_hook`/`enc_hook`. No field family relies
on union widening for tolerance after migration. `http.HTTPStatus` (stdlib `enum.IntEnum`) is
msgspec-native already; its `| int` at `net.py:65` / `errors.py:282` is dropped the same way (dossier
02 §B.5) and needs no hook.

--------------------------------------------------------------------------------------------------

## 6. Documented semantic change (must be socialized)

Today, an unknown int-enum value flows through as a **bare `int`**. After adopting #2770 it is an enum
**pseudo-member** (`is_unknown == True`). This is the #2770 breaking change, not a msgspec artifact.
The observable differences (dossier 02 §F.2, dossier 15 §2):

| Expression on an unknown value `x` (say raw `999` for a `MessageType` field) | Today | After #2770 |
|---|---|---|
| `x == 999` | `True` | `True` (unchanged) |
| `int(x)` | `999` | `999` (unchanged) |
| `x` in arithmetic / as a dict key | works | works (unchanged) |
| `type(x) is int` | `True` | **`False`** |
| `isinstance(x, MessageType)` | `False` | **`True`** |
| `x.name` | `AttributeError` (it is a bare int) | `"UNKNOWN 999"` |
| `x.is_unknown` | `AttributeError` | `True` (new #2770 property) |

Separately, #2770 makes **wrong-type** casts raise `TypeError` (via the `__objtype__` guard) instead of
silently returning the raw value. Both belong in the breaking-changes catalogue
(`../11-rollout/03-breaking-changes-and-changelog.md`, citing `changes/2770.breaking.md`) and the risk
map (`../00-overview/03-risk-and-danger-map.md`). Because the runtime enum types are unchanged, there
is **no** "enums became stdlib" break — only the unknown-value and wrong-type behavior shifts, and
that is #2770.

--------------------------------------------------------------------------------------------------

## 7. The decode-time trade-off (state it honestly)

Keeping the custom enums costs **one Python `dec_hook` call per enum field per decode**, because
msgspec cannot fast-path them in its C core the way it does stdlib enums (native C value→member table,
no Python call). In exchange, **runtime** enum operations — comparisons, flag algebra, member/name
access — stay on hikari's faster custom implementation, which is the hot path for a bot processing many
events/requests where the same decoded enums are touched repeatedly. The maintainer prioritizes runtime
speed and has chosen this deliberately (dossier 15 §5). Keep a benchmark that measures the decode-time
delta (custom-via-hook vs a stdlib-enum control) on enum-dense payloads to confirm the net win; it is a
measurement task, not a blocking probe (`../11-rollout/02-performance-benchmarking.md`).

--------------------------------------------------------------------------------------------------

## 8. Step-by-step (cluster-level sequencing)

The detailed steps live in the sibling files; this is the order to execute them.

1. Adopt/rebase upstream PR #2770 first: it changes `_EnumMeta.__call__` to mint pseudo-members, adds
   `is_unknown` to `Enum`/`Flag`, adds the `__objtype__` wrong-type guard, and performs the strict
   field/param typing sweep. This lands most of the enum work upstream
   (`04-enums-module-and-machinery.md`).
2. Add the enum/flag branch to the shared `dec_hook`/`enc_hook`
   (`../01-foundations/02-custom-scalar-types-and-hooks.md`); this is the single msgspec integration
   point. Flags need no runtime change (they already mint pseudo-members); confirm the `| int` drop on
   flag fields (`01-flags-migration.md`).
3. Confirm the 55 int + 12 str enums decode via the hook with #2770's pseudo-member `__call__`
   (`02-int-and-str-enums-migration.md`).
4. Sweep the ~150 field/param unions per the inventory in `03-strict-enum-field-inventory.md` (delivered
   by #2770 for model fields + REST params), dropping entity-field `| int`/`| str`.
5. No metaclass retirement — `internal/enums.py` and `enums.pyi` are **kept**; only #2770's diffs land
   (`04-enums-module-and-machinery.md`).

Each step is independently testable and can land as its own PR; see
`../11-rollout/01-pr-breakdown.md`.

--------------------------------------------------------------------------------------------------

## 9. Affected files and symbols

This umbrella file changes no source directly; the concrete file/symbol inventory is enumerated per
sibling:

| Sibling file | Affected files & symbols |
|---|---|
| `01-flags-migration.md` | the 13 flag types (kept custom); flag-field `\| int` drops; `is_unknown` per #2770 |
| `02-int-and-str-enums-migration.md` | the 55 int + 12 str enums (kept custom); #2770 `__call__`/`is_unknown` |
| `03-strict-enum-field-inventory.md` | the ~150 `SomeEnum \| int` / `\| str` entity-field & input-param unions (dropped by #2770) |
| `04-enums-module-and-machinery.md` | `hikari/internal/enums.py` #2770 diffs; `enums.pyi` kept |

The msgspec integration itself lives in `../01-foundations/02-custom-scalar-types-and-hooks.md` (the
shared `dec_hook`/`enc_hook`), owned by the foundations cluster.

--------------------------------------------------------------------------------------------------

## 10. Verification

- **RESOLVED (dossier 15, empirical, msgspec 0.21.1):** msgspec decodes/encodes the custom enums via
  the global `dec_hook`/`enc_hook` given #2770's instance-returning `__call__`. Probe B decoded unknown
  int, str, list-element, and dict-key values to pseudo-members and round-tripped their raw values on
  encode (`../12-appendices/02-custom-enum-feasibility.md`). This supersedes the withdrawn stdlib-port
  verifications (V3 IntFlag-on-3.10, V4 `StrEnum` `str()` semantics — both moot; see
  `../12-appendices/01-open-questions-and-verifications.md`).
- Add an unknown-value regression test per enum family that asserts `int(x)==raw` / `str(x)==raw`,
  `isinstance(x, TheEnum)`, `x.is_unknown is True`, and the `name` rendering.
- Confirm wrong-type input raises `TypeError` at the `__objtype__` guard and surfaces as a
  `ValidationError` through the hook.
- Confirm the `_temp_members_` cache stays bounded at `_MAX_CACHED_MEMBERS` under a stream of distinct
  unknown values.
- Benchmark the per-field `dec_hook` decode cost vs a stdlib-enum control on enum-dense payloads (§7);
  record in `../11-rollout/02-performance-benchmarking.md`.

--------------------------------------------------------------------------------------------------

## 11. Open questions / decisions

Cross-linked to `../00-overview/05-decisions-log.md` (D2) and
`../12-appendices/01-open-questions-and-verifications.md`:

1. Rebase strategy for #2770: adopt it as an upstream prerequisite PR, or vendor its diffs into the
   migration branch? Recommendation: rebase onto / adopt #2770 rather than re-deriving the strict
   typing and pseudo-member behavior.
2. Input-param `| int` lenience (~80 signatures, dossier 02 §C.3): keep or tighten? #2770 already types
   REST params strictly; orthogonal to msgspec decode; decided in `03-strict-enum-field-inventory.md`
   §7.
3. Whether to keep the decode-time benchmark (§7) as a standing CI check or a one-off measurement.
   Recommendation: a one-off measurement gate that confirms the net runtime win, not a blocking probe.
