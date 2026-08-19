# Appendix: Base-struct identity (VERIFY V1) — verified

Self-contained record of the V1 empirical result (msgspec 0.21.1, CPython 3.11, against the real
`hikari.snowflakes.Unique`). Source: dossier 16. The recipe and rules live in
[`../01-foundations/01-base-struct-conventions.md`](../01-foundations/01-base-struct-conventions.md);
this appendix is the evidence and the exact findings so a reader need not reach the out-of-tree
dossier.

## Verdict

The D3 identity design is confirmed: `msgspec.Struct(frozen=True, eq=False)` layered over the
`snowflakes.Unique` ABC inherits `Unique`'s id-only `__eq__`/`__hash__` (msgspec does **not** null the
hash under `eq=False`). Structs with unhashable `list`/`dict` fields stay hashable by `id`,
immutability holds, slotting holds, and typed decode round-trips. Two mechanical requirements were
uncovered and folded into the base-struct conventions.

## R1 — a combined metaclass is required

`type(msgspec.Struct)` is `StructMeta`; `type(Unique)` is `ABCMeta`; `issubclass(StructMeta, ABCMeta)`
is **False**. So `class X(Unique, msgspec.Struct, …)` raises
`TypeError: metaclass conflict: the metaclass of a derived class must be a (non-strict) subclass of
the metaclasses of all its bases`.

Fix (verified), defined once and set on the shared base — inherited by all subclasses:

```python
class _StructABCMeta(abc.ABCMeta, type(msgspec.Struct)): ...
class UniqueStruct(Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False, metaclass=_StructABCMeta): ...
```

The real `Unique` is kept **unchanged**: `__slots__ = ()` and the abstract `id` @property compose
fine (`hasattr(inst, "__dict__")` is False; the struct `id` field satisfies the abstract property). A
separate external run concluded `Unique.__slots__` must be removed — that is **incorrect** and was an
artifact of rewriting `Unique` itself.

## R2 — repeat `kw_only=True` per struct level

`frozen` is stored in `__struct_config__` and inherits reliably. `kw_only` is **not** in `StructConfig`
and does not reliably propagate. Verified matrix:

| Case | Shape | Result |
|---|---|---|
| 1 | kw_only base that DECLARES the initial fields; child adds a required field | OK |
| 2 | kw_only on an EMPTY base; intermediate class declares fields (no kw_only); leaf adds required field | **FAILS**: `Required field '…' cannot follow optional fields` |
| 3 | kw_only re-declared on every level | OK |

hikari's hierarchies match Case 2 (a data-less shared base; required fields added at multiple levels),
so the rule is: declare `frozen=True, kw_only=True` on every struct class that adds fields. The failure
is silent until a subclass adds a required field after an inherited optional one, so it must be a
convention enforced by review/lint, not left to inheritance.

## The verified recipe and checks

```python
import abc, msgspec
from hikari.snowflakes import Snowflake, Unique

class _StructABCMeta(abc.ABCMeta, type(msgspec.Struct)): ...
class UniqueStruct(Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False, metaclass=_StructABCMeta): ...
class PartialChannel(UniqueStruct, frozen=True, kw_only=True):
    id: Snowflake
    name: str | None = None
class GuildChannel(PartialChannel, frozen=True, kw_only=True):
    guild_id: Snowflake
    perms: list[int] = []
class GuildTextChannel(GuildChannel, frozen=True, kw_only=True):
    topic: str | None = None
```

`final_recipe.py` — ALL PASS at depth 3: build; id-only `==`/`!=`; frozen immutability; hashable
despite an unhashable `list` field with `hash(x)==hash(id)`; set-dedup by id; `__eq__`/`__hash__` are
`Unique`'s (`which_eq`/`which_hash` True, `hash_is_none` False); `isinstance(x, Unique)`;
`__struct_config__.frozen` True; slotted (no `__dict__`); kw_only enforced (positional rejected);
decode of a leaf with STRING snowflakes via the `dec_hook` (`Snowflake("5") -> Snowflake`); decoded
`==` constructed (through `Unique.__eq__`); `Unique.created_at` still works.

Note: a `Snowflake` field **requires** the Snowflake `dec_hook` (already planned) — without it, decode
raises `ValidationError: Expected 'Snowflake', got 'int'`.

## Residual

Only the CPython **3.10** floor re-run remains (the confirming run was 3.11; the mechanism is
version-independent but unverified on 3.10). Tracked as the V1 residual in
[`01-open-questions-and-verifications.md`](01-open-questions-and-verifications.md).

## Scope

Non-`Unique` value objects (embed pieces, poll value objects) stay plain
`msgspec.Struct(frozen=True, kw_only=True)` and need neither the combined metaclass nor `Unique`; they
use msgspec's default all-field `eq` (or `eq=False` per case, e.g. poll unhashability).
