# Custom-enum feasibility under msgspec (in-plan evidence)

The plan of record keeps hikari's fast custom `hikari/internal/enums.py` `Enum`/`Flag` rather than
porting them to stdlib `enum`, and decodes/encodes them through the same single global
`dec_hook`/`enc_hook` already used for `Snowflake`/`Color`. This appendix is the plan's own,
self-contained evidence for that decision (dossier 15, EMPIRICAL against msgspec 0.21.1 / CPython
3.11) so a reviewer need not reach the out-of-tree research note: the verdict, the mechanism, the exact
upstream PR hikari-py/hikari#2770 code it depends on, the empirical results, the hook integration, and
the trade-off it accepts.

It underpins decision D2 ([`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md))
and is referenced from [`../02-enums/`](../02-enums/00-strategy-and-forward-compat.md),
[`../01-foundations/02-custom-scalar-types-and-hooks.md`](../01-foundations/02-custom-scalar-types-and-hooks.md),
and the rollout benchmark [`../11-rollout/02-performance-benchmarking.md`](../11-rollout/02-performance-benchmarking.md) §3.3.

---

## 1. Verdict — FEASIBLE (empirically proven)

msgspec can decode and encode hikari's custom-metaclass enums directly as struct field types, via the
same single global `dec_hook`/`enc_hook`. **No stdlib port is needed.** The one hard requirement is
satisfied by PR hikari-py/hikari#2770: the enum constructor must return an **instance of the enum type
for every input** (known or unknown). Adopting #2770 is therefore the prerequisite; it also removes a
large slice of the originally-planned enum work (§7).

Why the maintainer chose this: hikari's custom enums are significantly faster at runtime than stdlib
enums (comparisons, flag algebra, member/name access), which matters for a bot processing many events
and requests. The custom enums are kept deliberately for that runtime win.

---

## 2. Mechanism — why it works

msgspec detects a "native" enum by `issubclass(t, enum.Enum)`. hikari's custom `Enum`/`Flag` are **not**
`enum.Enum` subclasses (they use bespoke `_EnumMeta`/`_FlagMeta` metaclasses), so msgspec treats a
field typed as one of them as a **custom type** and routes it to `dec_hook(t, raw)` — exactly as it does
for `Snowflake` (an `int` subclass). The hook returns `t(raw)`, i.e. the enum's own constructor.

The load-bearing invariant on `dec_hook`: **the returned object must be an instance of the annotated
type `t`** (msgspec runs an `isinstance` check on the hook's result). Against that invariant:

- hikari's custom **`Flag`** already mints a pseudo-member **instance** on unknown/composite values
  (`_FlagMeta.__call__`, `hikari/internal/enums.py:381-412`), so it already satisfies the invariant.
- hikari's custom **`Enum`** (pre-#2770) returns the **raw `int`/`str`** on a miss
  (`_EnumMeta.__call__`, `hikari/internal/enums.py:154-156`:
  `return cls._value_to_member_map_.get(value, value)`), which is **not** an instance of the enum type
  → msgspec rejects it with `ValidationError: Expected 'X', got 'int'`.
- **PR hikari-py/hikari#2770 changes `Enum.__call__` to mint a pseudo-member instance on a miss** (like
  `Flag`), which makes the invariant hold for scalar enums too. #2770 is therefore a **prerequisite**
  for this approach.

---

## 3. PR hikari-py/hikari#2770 — exact behavior

Changelog fragments (verbatim from the PR head):

`changes/2770.breaking.md`:
> Casting an unknown value to an enum or flag type now returns an unknown member which keeps hold of
> the raw value instead of returning the value unchanged, and casting a value of the wrong type now
> raises `TypeError`; model fields and REST parameters are now typed with only the enum/flag type
> instead of a union with its raw type.

`changes/2770.feature.md`:
> Add the `is_unknown` property to enum and flag members, returning whether the value is an unknown
> one which is not documented as part of the enum.

New `_EnumMeta.__call__` (`hikari/internal/enums.py`, PR head — replaces the raw-on-miss body at
`:154-156`):

```python
def __call__(cls, value: object) -> Enum:
    """Cast a value to the enum, returning an unknown member if the value is not a known one."""
    try:
        return cls._value_to_member_map_[value]
    except KeyError:
        # Discord adds new variants over time; unknown values must never error — they become
        # synthetic "unknown members" that keep the raw value for introspection and serialization.
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

The bounded pseudo-member cache reuses the existing `_MAX_CACHED_MEMBERS = 1 << 12`
(`hikari/internal/enums.py:39`) and the `_temp_members_` map that the custom `Flag` already uses, so
unknown scalar values are bounded exactly as unknown flag values already are. `Enum.name` lazily names
unknowns `f"UNKNOWN {self._value_!r}"`. The new `is_unknown` properties:

- `Enum.is_unknown` → `return self._value_ not in self._value_to_member_map_`.
- `Flag.is_unknown` → `return bool(self._value_ & ~self.__class__.__everything__._value_)`.

Consequences relevant to msgspec:

- `MessageType(999)` → a `MessageType` **instance** (`is_unknown=True`, `_value_=999`) — accepted by the
  `dec_hook` invariant.
- Wrong-type input raises `TypeError` via the `__objtype__` guard. msgspec passes the decoded JSON
  primitive to the hook (an `int` for an int-enum field, a `str` for a str-enum field), which matches
  `__objtype__`, so the happy path never trips this; a genuinely wrong wire type surfaces as a
  `ValidationError` (msgspec converts a hook's `TypeError`/`ValueError` into `ValidationError`).
- #2770 also performs the strict field/param typing sweep (drops the `| int`/`| str` unions), which is
  exactly the plan's strict-enum field inventory
  ([`../02-enums/03-strict-enum-field-inventory.md`](../02-enums/03-strict-enum-field-inventory.md)).
  The migration **rebases onto / adopts #2770** rather than re-deriving it.

---

## 4. Empirical results (msgspec 0.21.1, CPython 3.11, against the real hikari enums module)

Two probes imported the real `hikari.internal.enums` and built `int`/`str` `Enum`s and a `Flag`.

| Probe | Case | Result |
|---|---|---|
| A (pre-#2770, tolerant `Enum`) | Known int/str enum + `Flag` values decode via `dec_hook` → members | PASS |
| A | Nested in a `Struct`; `dict[Locale, str]` keys; `MessageType \| None`; encode via `enc_hook` | PASS |
| A | Unknown `Flag` bit `Permissions(64)` → pseudo-member | PASS |
| A | Unknown **int/str** enum values | **FAIL** — `ValidationError: Expected 'X', got 'int'` (pre-#2770 `Enum` returns a raw `int`, not an instance of the annotated type) |
| B (#2770 strict, pseudo-member on miss) | `decode 999 → StrictInt` → `<StrictInt.None: 999>`; `isinstance` True; `int()==999`; `==999` True | PASS |
| B | `decode "zz" → StrictStr` → pseudo-member; `isinstance` True | PASS |
| B | `Struct {"t":999,"ls":[1,2,888],"mp":{"x":"a","zz":"b"}}` — unknown scalar, unknown list element, unknown dict key all decode to pseudo-members | PASS |
| B | Encode an unknown pseudo-member — round-trips the raw value (`999` → `b'999'`) | PASS |

Conclusion: with #2770's pseudo-member `Enum.__call__`, every decode/encode case for custom int enums,
str enums, and flags works through the single global hook. Probe A is the exact failure mode that #2770
fixes; probe B is the plan-of-record behavior.

---

## 5. Hook integration (what the plan adopts)

The custom enum/flag routing is added to the single global hooks (extending the existing
Snowflake/Color routing), specified in
[`../01-foundations/02-custom-scalar-types-and-hooks.md`](../01-foundations/02-custom-scalar-types-and-hooks.md):

```python
def dec_hook(t: type, obj: object) -> object:
    if issubclass(t, (enums.Enum, enums.Flag)):
        return t(obj)                    # #2770 guarantees an instance (pseudo-member on miss)
    if t is snowflakes.Snowflake: ...    # existing scalar routing
    ...

def enc_hook(o: object) -> object:
    if isinstance(o, (enums.Enum, enums.Flag)):
        return o.value                   # a plain int/str primitive (avoids the int-subclass encode gap)
    ...
```

- **Field types** on structs are the bare custom enum/flag (strict), matching #2770 — no `| int`/`| str`.
- **Forward-compat:** unknown Discord values → `is_unknown` pseudo-member, raw value preserved, encodes
  back to the raw value. Uniform for `Enum` and `Flag`.
- **Encode:** returning `o.value` avoids msgspec's int-subclass encode gap (msgspec cannot natively
  encode `int`/`str` subclasses — the same gap that forces the `Snowflake`/`Color` `enc_hook`, D4).
- **Polymorphic tagged-union tags** are unaffected — those dispatch on a raw literal `int`/`str`
  discriminator (verified in dossier 13 §14), not on a custom-enum instance.
- The **`enums.pyi`** stub (which masquerades as stdlib enum for type-checkers) is **unaffected and
  kept** — msgspec inspects the real runtime class and uses the hook; the stub only drives mypy/pyright.

---

## 6. Trade-off (stated honestly)

Keeping the custom enums costs **one Python `dec_hook` call per enum field per decode**, because msgspec
cannot fast-path them in its C core the way it does stdlib enums (a native C table lookup, no Python
call). In exchange, **runtime** enum operations (comparisons, flag algebra, member/name access) stay on
hikari's faster custom implementation — the hot path for a bot processing many events/requests, where
the same decoded enums are touched repeatedly. The maintainer prioritizes runtime speed and has chosen
this deliberately.

The plan keeps a **benchmark** (non-blocking) to measure the decode-time delta — custom-via-hook vs a
stdlib-enum control on enum-dense payloads — to confirm the net win
([`../11-rollout/02-performance-benchmarking.md`](../11-rollout/02-performance-benchmarking.md) §3.3,
gate item B-CE in [`01-open-questions-and-verifications.md`](01-open-questions-and-verifications.md)
§5). The decision to keep the custom enums stands regardless of that number.

---

## 7. What the decision removes and keeps

Removed from the original ("port to stdlib") plan:

- No reparenting of the 80 enum/flag types onto stdlib `enum`.
- No `enum.IntFlag` port and no re-implementation of the custom `Flag` set-API (~20 methods,
  `hikari/internal/enums.py:661-829`).
- No shared `_missing_` pseudo-member mixin — #2770's `__call__` already does it.
- VERIFY V3 (`IntFlag` KEEP boundary on the 3.10 floor) — **MOOT** (no `IntFlag`).
- VERIFY V4 (`str()` semantics of `(str, Enum)` vs `StrEnum`) — **MOOT** (custom enums keep their
  existing `__str__`).
- No `StrEnum`-unavailable-on-3.10 concern.

Kept from the original plan:

- The strict-enum field inventory (drop the `| int`/`| str` unions) — now delivered by #2770.
- The `dec_hook`/`enc_hook` infrastructure (shared with `Snowflake`/`Color`).
- Tagged-union polymorphism and the soft-skip/raise-on-unknown-type dispatch (independent of scalar
  enum decoding).
