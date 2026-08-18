# UNDEFINED and UNSET

How hikari's tri-state `UNDEFINED` sentinel survives the migration: kept unchanged for REST
request params, and reconciled with `msgspec.UNSET` for the handful of decoded-entity fields that
genuinely mean "key absent". Locks decision D5 (with a VERIFY gate). Serves the declarative-decode
end-state (D1) without churning the ~1714 `UndefinedOr` annotations more than necessary.

## 1. Objective

- Decide, empirically, whether decoded-struct tri-state fields can keep `hikari.UNDEFINED` or must
  adopt `msgspec.UNSET`, and specify the exact compatibility shim for the fallback.
- Leave the REST **request** param layer (the vast majority of `UndefinedOr` usage) untouched.

## 2. Current state (file:line)

`UndefinedType` and the singleton (`hikari/undefined.py:43-87`):

```python
class UndefinedType:
    __slots__ = ()
    def __bool__(self) -> Literal[False]: return False      # falsy
    def __copy__(self): return self                          # singleton
    def __deepcopy__(self, memo): memo[id(self)] = self; return self
    def __getstate__(self): return False                     # pickle: skip __setstate__
    def __repr__(self): return "UNDEFINED"
    def __reduce__(self): return "UNDEFINED"                 # pickle -> module global
    def __str__(self):  return "UNDEFINED"
UNDEFINED = UndefinedType()
UndefinedType.__new__ = _forbidden_new                       # enforce singleton
```

- Aliases (`undefined.py:89-130`): `UndefinedOr[T] = Union[T, UndefinedType]`,
  `UndefinedNoneOr[T] = Union[UndefinedOr[T], None]` (i.e. `T | UNDEFINED | None`).
- **The `.pyi` stub diverges** (`undefined.pyi:28-41`): to type-checkers `UndefinedType` is a
  single-member `enum.Enum` (`UNDEFINED = auto()`), so `x is UNDEFINED` narrows precisely. Runtime and
  stub are different classes — any design must respect the runtime plain class.
- Footprint (dossier 09 §6.3): ~2433 textual hits; **1714** `UndefinedOr`/`UndefinedNoneOr`
  annotations; imported in **33** modules.
- **Two roles:**
  1. **REST request params** (the majority — `impl/rest.py` 589, `api/rest.py` 496,
     `special_endpoints.py` 129, …): default `= UNDEFINED` meaning "caller didn't specify → don't
     send". Consumed by the builders, which **skip** `UNDEFINED`
     (`data_binding.py:222,299,346,373,402`). **Orthogonal to msgspec** — unchanged.
  2. **Decoded entity fields** meaning "this partial payload omitted the key", distinct from `None`.
     `PartialMessage` has ~24 such fields (`messages.py:543-785`); the factory sets them to
     `UNDEFINED` when the key is absent and to `None`/value otherwise (`entity_factory.py:3888-3919`).
     Also `GatewayGuild` lazy caches use `init=False, default=UNDEFINED` (`entity_factory.py:268-286`).
     111 `undefined.UNDEFINED` occurrences in `entity_factory.py`.

msgspec's own absence machinery (dossier 13 §3, verified):

```python
class UnsetType(enum.Enum):
    UNSET = "UNSET"
    def __bool__(self) -> Literal[False]: ...     # UNSET is falsy, singleton (enum member)
UNSET = UnsetType.UNSET
```

- A field `T | UnsetType = UNSET`, when the JSON key is **absent**, decodes to `UNSET`; explicit
  `null` decodes to `None`. This is exactly role (ii).
- On **encode**, an `UNSET` field is omitted **even when `omit_defaults=False`** — a special,
  always-on omission (verified: `encode(NoOmit())` == `b'{"age":5}'`, name dropped). This matches role
  (i)'s "don't send".
- `bool(UNSET) is False` — matches `bool(UNDEFINED) is False`.

The hard constraint that forces the decision (dossier 13 §8, §15): **custom (non-native) types are
unsupported in unions beyond `Custom | None`.** At runtime `UndefinedType` is a plain class (not an
enum), so `T | UndefinedType` is a union containing a custom type — msgspec is expected to reject it
at `Decoder` construction.

## 3. VERIFY experiments (run before choosing)

### 3.1 Experiment A — is `T | UndefinedType` a msgspec-legal decode type?

```python
# expA.py
import msgspec
from hikari import undefined   # runtime UndefinedType is a plain class

class M(msgspec.Struct):
    x: str | undefined.UndefinedType = undefined.UNDEFINED

try:
    dec = msgspec.json.Decoder(M)           # does construction raise?
    r_absent  = dec.decode(b'{}')           # -> M(x=UNDEFINED)?
    r_present = dec.decode(b'{"x":"a"}')    # -> M(x='a')?
    print("A-OK", r_absent.x is undefined.UNDEFINED, r_present.x)
except Exception as e:
    print("A-REJECTED", type(e).__name__, e)
```

Prediction (from §2 union rule): **A-REJECTED** — a custom type in a union is illegal. This makes the
CONVENTIONS "Preferred" option (annotate `T | UndefinedType`, `default=UNDEFINED`) non-viable as a
**typed** decode annotation.

### 3.2 Experiment B — out-of-annotation default (does msgspec type-check defaults?)

```python
# expB.py
import msgspec
from hikari import undefined

class N(msgspec.Struct):
    x: str | None = undefined.UNDEFINED     # annotation legal; default is the foreign sentinel

dec = msgspec.json.Decoder(N)
print("B", dec.decode(b'{}').x is undefined.UNDEFINED,   # absent -> default?
           dec.decode(b'{"x":"a"}').x,                    # present -> 'a'?
           dec.decode(b'{"x":null}').x)                   # null -> None?
```

Prediction: msgspec does **not** type-check defaults, so this **works at runtime** (`x` is `UNDEFINED`
on absence). But the annotation `str | None` does **not** include the sentinel, so mypy/pyright will
not know `x` can be `UNDEFINED`, breaking `is UNDEFINED` narrowing at every call site. Runtime-correct
but statically dishonest → **not viable for a well-typed public API.**

### 3.3 Experiment C — the `UNSET` fallback

```python
# expC.py
import msgspec

class E(msgspec.Struct):
    name: str | msgspec.UnsetType = msgspec.UNSET

dec = msgspec.json.Decoder(E)
enc = msgspec.json.Encoder()
print("C", dec.decode(b'{}').name is msgspec.UNSET,          # absent -> UNSET
           dec.decode(b'{"name":null}').name,                 # null -> None (needs `| None` too)
           enc.encode(E()))                                   # -> b'{}' (UNSET omitted)
```

Prediction: **C-OK** — `T | UnsetType` is explicitly supported; absent→`UNSET`, encode omits `UNSET`.
For a field that can also be `null`, type it `T | None | msgspec.UnsetType = msgspec.UNSET`.

Record all three outcomes and the CPython versions in
[`../12-appendices/01-open-questions-and-verifications.md`](../12-appendices/01-open-questions-and-verifications.md).

## 4. Target design and recommendation

Given the predicted outcomes (A rejected, B statically dishonest, C works), the recommendation is:

> **Keep `hikari.UNDEFINED` for REST request params (unchanged), and adopt `msgspec.UNSET` for the
> decoded-entity tri-state fields (role ii), unified behind a compatibility shim so `UndefinedOr` and
> `is UNDEFINED` keep working everywhere.**

If Experiment A unexpectedly passes, prefer the CONVENTIONS "Preferred" path (keep `UNDEFINED`,
`default=UNDEFINED`, annotate `T | UndefinedType`) and skip the shim. The plan below assumes the
fallback because it is the predicted outcome.

### 4.1 The shim (fallback design)

Unify the two sentinels by making `hikari.UNDEFINED` an alias of `msgspec.UNSET`:

```python
# hikari/undefined.py  (fallback rewrite)
from __future__ import annotations
import typing
import msgspec

UndefinedType = msgspec.UnsetType                    # the enum CLASS
UNDEFINED: typing.Final[UndefinedType] = msgspec.UNSET   # the single member
"""Sentinel for a missing/omitted value (aliased to msgspec.UNSET)."""

T_co = typing.TypeVar("T_co", covariant=True)
UndefinedOr = typing.Union[T_co, UndefinedType]                 # == T | UnsetType (msgspec-legal)
UndefinedNoneOr = typing.Union[T_co, None, UndefinedType]        # == T | None | UnsetType

def all_undefined(*items: object) -> bool:
    return all(item is UNDEFINED for item in items)
# any_undefined / count unchanged in spirit
```

Why this works end-to-end:

- `x is UNDEFINED` becomes `x is msgspec.UNSET` — the **same object**, so all ~thousands of identity
  checks keep working, on both request params and decoded fields.
- Decoded struct fields annotated `UndefinedOr[T]` (== `T | UnsetType`) are a **legal** msgspec union
  and decode absent→`UNSET`==`UNDEFINED`, `null`→`None` (when `| None` is included), value→value.
- REST request params default to `UNDEFINED` (== `UNSET`); the builders' `value is undefined.UNDEFINED`
  skip check (`data_binding.py:222,…`) now compares against `UNSET` and still skips. If Structs are
  ever encoded directly, `UNSET` auto-omits too — consistent.
- `bool(UNDEFINED) is False`, singleton identity, `copy`/`deepcopy`/`pickle` all hold because
  `UnsetType.UNSET` is an `enum` member (enum members are singletons and pickle by qualified name).

Behavioral deltas to re-create or accept (the four bespoke behaviors on the old `UndefinedType`):

| Old behavior (`undefined.py`) | Under `msgspec.UnsetType` | Action |
|-------------------------------|---------------------------|--------|
| `repr()` == `"UNDEFINED"` (`:65-66`) | enum repr `<UnsetType.UNSET: 'UNSET'>` | cosmetic; accept, or keep a thin wrapper name in docs |
| `str()` == `"UNDEFINED"` (`:72-74`) | `"UnsetType.UNSET"` | cosmetic; accept |
| `__reduce__` / `__getstate__` pickle → module global (`:61-70`) | enum pickles by name automatically | drop hikari's custom pickle hooks |
| singleton `__new__` guard (`:81-87`) | enum guarantees single member | drop the guard |
| `.pyi` enum-stub trick (`undefined.pyi:28-41`) | `UnsetType` **is** already a single-member enum | the stub trick is now real at runtime — simplify/retire the divergent stub |

The `.pyi` divergence that existed purely to make type-checkers treat `UNDEFINED` as an enum member
disappears, because `msgspec.UnsetType` genuinely is one.

### 4.2 Where each sentinel lands

| Surface | Field/param shape | Sentinel |
|---------|-------------------|----------|
| REST request params (role i) | `x: UndefinedOr[T] = UNDEFINED` | `UNDEFINED` (== `UNSET`) — builders skip it |
| Decoded entity tri-state (role ii) — `PartialMessage`'s ~24 fields (`messages.py:543-785`) | `x: UndefinedOr[T] = UNDEFINED` on the Struct | `UNSET` produced on absent key |
| Nullable-and-omittable (role ii) | `x: UndefinedNoneOr[T] = UNDEFINED` (`T | None | UnsetType`) | `UNSET` absent, `None` on `null` |
| `GatewayGuild` lazy "unfetched" markers (`entity_factory.py:268-286`) | `init=False`-style default | keep as a default `UNSET`; the lazy `GatewayGuildDefinition` is a residual-factory concern (see [`../05-entity-factory/02-hard-cases-and-transforms.md`](../05-entity-factory/02-hard-cases-and-transforms.md)) |

## 5. Step-by-step migration

1. Run Experiments A/B/C on CPython 3.10 and 3.11+; record outcomes. If A passes, take the Preferred
   path (§4) and stop here for the shim.
2. Rewrite `hikari/undefined.py` to alias `msgspec.UnsetType`/`UNSET` (§4.1); drop the custom
   pickle/singleton/`__new__` machinery; simplify `undefined.pyi`.
3. Keep `UndefinedOr`/`UndefinedNoneOr` names; confirm they now expand to msgspec-legal unions.
4. Leave every REST request param signature and every builder skip-check as-is — they resolve through
   the alias unchanged.
5. For decoded-entity tri-state Structs (`PartialMessage`, `MessageSnapshot`, `PinnedMessage`, and the
   ~24-field set), declare fields `UndefinedOr[T]`/`UndefinedNoneOr[T]` with `default=UNDEFINED`; let
   msgspec produce `UNSET` on absence. Remove the corresponding hand `if "key" in payload` branches
   from the factory where declarative decode covers them (coordinate with
   [`../05-entity-factory/02-hard-cases-and-transforms.md`](../05-entity-factory/02-hard-cases-and-transforms.md)).
6. Grep for any code depending on `repr(UNDEFINED) == "UNDEFINED"` or on the custom pickle string, and
   adjust or accept the enum forms.

## 6. Affected files and symbols

| Path | Anchor | Change |
|------|--------|--------|
| `hikari/undefined.py` | `:43-145` | alias to `msgspec.UnsetType`/`UNSET`; drop bespoke hooks |
| `hikari/undefined.pyi` | `:28-41` | simplify — runtime is now genuinely a single-member enum |
| `hikari/internal/data_binding.py` | `:222,299,346,373,402` | skip-check unchanged (resolves via alias) |
| `hikari/messages.py` | `:543-785` | `PartialMessage` ~24 tri-state fields → `UndefinedOr` Struct fields |
| `hikari/impl/entity_factory.py` | `:268-286,3888-3919` | drop hand `in payload` branches where declarative decode covers them |
| REST param layer (33 modules) | 1714 annotations | untouched (alias) |

## 7. Risks and gotchas

1. **Union legality is the crux.** If Experiment A is rejected (predicted), the Preferred "keep
   UNDEFINED as a union arm" path is dead — do not ship it without A passing.
2. **Identity aliasing must be exact.** `UNDEFINED` must be the *same object* as `msgspec.UNSET`, or
   the thousands of `is UNDEFINED` checks silently fail. `UNDEFINED = msgspec.UNSET` (not a copy).
3. **`repr`/`str` change.** Logs and any string-comparison on the sentinel's repr change from
   `"UNDEFINED"` to the enum form. Grep and accept/adjust.
4. **`null` vs absent must be typed.** A tri-state field that can be `null` needs
   `UndefinedNoneOr[T]` (`T | None | UnsetType`); omitting `| None` makes a `null` payload raise
   `ValidationError: Expected 'T', got 'null'` (dossier 13 §15).
5. **omit_defaults interaction.** `UNSET` omission is independent of `omit_defaults`, so turning
   `omit_defaults` on/off does not affect the sentinel — but do not rely on `omit_defaults` to drop
   `UNDEFINED`-valued fields on any non-UNSET default (it compares by equality).
6. **Public API break framing.** Even aliased, `UndefinedType`'s identity changes class
   (`msgspec.UnsetType`); anything doing `isinstance(x, undefined.UndefinedType)` still works via the
   alias, but `type(UNDEFINED).__name__` changes. Catalogue in
   [`../11-rollout/03-breaking-changes-and-changelog.md`](../11-rollout/03-breaking-changes-and-changelog.md).

## 8. Verification

- Experiments A/B/C reproduced and recorded (the decision hinges on A).
- Identity: after the alias, `undefined.UNDEFINED is msgspec.UNSET` and `bool(undefined.UNDEFINED) is
  False`.
- Decode: a `PartialMessage`-shaped Struct decodes a partial payload with `content` absent →
  `content is UNDEFINED`; with `content: null` → `content is None`; encode of a struct carrying
  `UNSET` fields omits them.
- Regression: existing tests that assert `x is UNDEFINED` on decoded partials pass unchanged; builder
  round-trips still omit unspecified params.

## 9. Open questions / decisions

Cross-link [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md):

- Q-UNDEF-1 (VERIFY, gating): Experiment A result — is `T | UndefinedType` a legal msgspec union? Drives
  Preferred vs Fallback.
- Q-UNDEF-2: adopt the global alias `UNDEFINED = msgspec.UNSET` (recommended fallback) vs a narrower
  two-sentinel shim with an `is_undefined()` helper? The alias is least-churn; confirm the repr/str
  change is acceptable.
- Q-UNDEF-3: retire the divergent `undefined.pyi` now that the runtime type is genuinely a
  single-member enum?
