# Enums Module and Machinery — Fate of `internal/enums.py`, the `.pyi`, and Dispatch

Purpose: specify what happens to `hikari/internal/enums.py` and its type stub `enums.pyi`, retire the
unused `deprecated`/`_DeprecatedAlias` machinery, and draw the boundary between scalar-enum tolerance
(this cluster) and the polymorphic `UnrecognisedEntityError` dispatch (owned by the entity_factory
cluster). This is the "clean-up and delineation" file for the enum migration.

Serves constraint (b) and decision D2 (`../00-overview/05-decisions-log.md`).

--------------------------------------------------------------------------------------------------

## 1. Objective

- Replace the custom metaclass machinery in `hikari/internal/enums.py` with the stdlib-backed bases
  designed in `01-flags-migration.md` and `02-int-and-str-enums-migration.md`, ideally **without
  editing any of the 80 declaration sites' base clauses**.
- Keep the module's public export names (`Enum`, `Flag`) so `from hikari.internal import enums` call
  sites are untouched; drop `deprecated`.
- Decide the fate of `enums.pyi` (the stub that already masquerades hikari enums as stdlib enums).
- Delete the unused `deprecated`/`_DeprecatedAlias` alias machinery.
- Confirm the polymorphic-dispatch tolerance path is a **separate** concern and route it to the
  entity_factory cluster.

--------------------------------------------------------------------------------------------------

## 2. Current state of `hikari/internal/enums.py`

830 lines. `__all__ = ("Enum", "Flag", "deprecated")` (`enums.py:25`). Structure:

| Symbol | Lines | Role | Fate |
|---|---|---|---|
| `_MAX_CACHED_MEMBERS = 1 << 12` | `:39` | Flag pseudo-member cache cap (4096) | reused as the scalar-enum + flag cache cap |
| `_DeprecatedAlias` | `:42-63` | descriptor emitting a deprecation warning + redirect | **delete** (unused) |
| `deprecated` | `:66-74` | marks an enum member as a deprecated alias | **delete** (unused) |
| `_EnumNamespace` | `:76-144` | member-collection namespace for `_EnumMeta` | **delete** (metaclass internal) |
| `_EnumMeta` | `:153-255` | custom enum metaclass; `__call__` returns raw value on miss (`:154-156`) | **delete** |
| `Enum` | `:257-354` | custom enum base; `name`/`value` properties, `__str__`→name (`:352-354`) | **replace** with stdlib-backed base |
| `_name_resolver` | `:360-377` | composite/unknown flag name generator (`"UNKNOWN 0x…"`) | **delete** (IntFlag names it) |
| `_FlagMeta` | `:380-513` | custom flag metaclass; pseudo-member mint + cache (`:381-412`), `__everything__` (`:502-506`) | **delete** |
| `Flag` | `:516-829` | custom flag base + the full set-API (`:683-829`) | **replace** with the `IntFlag` mixin |

Two module-level singletons `_Enum`/`_Flag` (`:150,357`) exist only to bootstrap the metaclasses and
also go away.

--------------------------------------------------------------------------------------------------

## 3. Target design — a stdlib-backed `enums` module, zero declaration-site edits

The 80 concrete types are declared exactly three ways:

```python
class MessageType(int, enums.Enum): ...   # 55 int enums
class Locale(str, enums.Enum): ...        # 12 str enums
class Permissions(enums.Flag): ...        # 13 flags
```

If `enums.Enum` and `enums.Flag` become **subclassable stdlib-enum bases** (no members of their own),
every one of those declarations keeps working untouched. This folds the `_IntEnum`/`_StrEnum` split
from `02-int-and-str-enums-migration.md` §4 into a **single** `enums.Enum` base whose `__str__`
branches on the member type — reproducing hikari's current split (int→name, str→value) with no
metaclass:

```python
import enum, typing

_MAX_CACHED_MEMBERS: typing.Final[int] = 1 << 12
_PSEUDO_CACHES: dict[type, dict[object, typing.Any]] = {}


class _MissingMixin:
    @classmethod
    def _missing_(cls, value: object) -> typing.Any:
        cache = _PSEUDO_CACHES.setdefault(cls, {})
        if (hit := cache.get(value)) is not None:
            return hit
        member = cls._member_type_.__new__(cls, value)   # int or str per family
        member._name_ = f"UNKNOWN_{value}"
        member._value_ = value
        cache[value] = member
        if len(cache) > _MAX_CACHED_MEMBERS:
            cache.pop(next(iter(cache)))
        return member


class Enum(_MissingMixin, enum.Enum):
    """Stdlib-backed replacement base; subclassable because it declares no members.

    `class X(int, enums.Enum)` / `class X(str, enums.Enum)` keep working unchanged.
    """

    @typing.override
    def __str__(self) -> str:
        # Reproduce today's split: str enums -> value (enums.py:201-203),
        # everything else -> member name (enums.py:352-354).
        if issubclass(type(self)._member_type_, str):
            return self._value_
        return self._name_


class Flag(enum.IntFlag):
    """Stdlib IntFlag base re-exposing hikari's set-API (see 01-flags-migration.md §4)."""
    # all/any/none/difference/intersection/union/symmetric_difference/invert/
    # is_subset/is_superset/is_disjoint/split + aliases + operator bindings.
    ...


__all__: typing.Sequence[str] = ("Enum", "Flag")   # 'deprecated' removed
```

Consequences:

- **No base-clause edits** at the 80 declaration sites. The only source edits in model modules are the
  field-union sweep (`03-strict-enum-field-inventory.md`) and converter removal.
- `enums.Enum` is now a genuine stdlib-enum subclass, so msgspec decodes it natively; `_missing_`
  provides forward-compat; the conditional `__str__` preserves the exact current `str()` behavior
  across both families in one place.
- `enums.Flag` is a genuine `enum.IntFlag`, natively msgspec-decodable with lossless unknown-bit
  tolerance, carrying the ported set-API.

If, instead, the maintainer prefers explicit per-family bases (`_IntEnum`/`_StrEnum`), that also works
but requires editing the 67 int/str declaration sites; the single-`Enum`-base form above is the
recommended minimal-churn shape.

### 3.1 `enums.pyi` fate

The stub exists solely because the old custom metaclasses did not type-check; it aliases
`Enum = enum.Enum` (`enums.pyi:41`) and declares `class Flag(enum.IntFlag)` with the full set-API
(`enums.pyi:44-66`) plus `deprecated` (`enums.pyi:70`). After migration:

- The runtime types are **now genuinely** stdlib enums with real, type-checkable set-API methods on the
  `Flag` mixin — so the stub is largely redundant.
- **Recommended:** attempt to **delete `enums.pyi`** and let mypy/pyright check the real module. The
  set-API methods now exist as real source, and `enums.Enum`/`enums.Flag` are real stdlib subclasses.
  If any tooling still stumbles (e.g. on the conditional `__str__` or `_member_type_`), keep a
  **trimmed** stub: retain the `Enum`/`Flag` shapes, **remove the `deprecated` declaration**
  (`enums.pyi:70`).
- Either way, type-checker churn on downstream modules is expected to be **small**: static tooling
  already treats these as stdlib enums (dossier 02 §A.3), so the field-union drops in
  `03-strict-enum-field-inventory.md` are the main mypy-visible change and they only *narrow* types.

### 3.2 `deprecated` / `_DeprecatedAlias` removal

Grep across `hikari/**` (dossier 02 §A.4, re-confirmed) finds **zero** usages of `deprecated(` on any
concrete enum — only the definitions in `enums.py`/`enums.pyi` and the unrelated
`internal/deprecation.py`. The machinery is dead:

- Delete `_DeprecatedAlias` (`enums.py:42-63`) and `deprecated` (`enums.py:66-74`).
- Remove `deprecated` from `__all__` (`enums.py:25`) and from `enums.pyi:70`.
- Drop the in-line imports of `internal/deprecation` that only served `_DeprecatedAlias`
  (`enums.py:51,57`).
- If a deprecated enum alias is ever needed later, stdlib enums express **value aliases** natively
  (`NEW = 1; OLD = 1` makes `OLD` an alias of `NEW`); a deprecation *warning* would need a small
  re-added descriptor, but nothing needs it today. Note this in the changelog as removed-internal-API.

--------------------------------------------------------------------------------------------------

## 4. Import-site and export impact

- `from hikari.internal import enums` and `enums.Enum` / `enums.Flag` references stay valid (names
  preserved). No model module changes its `import` line.
- Anything importing `enums.deprecated` breaks — but there are none (§3.2).
- `enums.pyi` deletion (if chosen) is invisible at runtime; only affects type-checking.
- The internal-only shard enums (`GatewayDataFormat`, `ChannelInfoField`, `GatewayCompression` in
  `api/shard.py`) and config flags (`CacheComponents`, `GatewayCapabilities`) migrate through the same
  `enums.Enum`/`enums.Flag` bases with no special handling.

--------------------------------------------------------------------------------------------------

## 5. Polymorphic `UnrecognisedEntityError` dispatch — SEPARATE concern

Scalar-enum tolerance (this cluster) is distinct from **type-discriminator** tolerance. When an unknown
value selects "which subclass to build" and the factory cannot proceed, it raises
`errors.UnrecognisedEntityError` (`hikari/errors.py:127`) rather than widening a field type. This path
is **not** touched by the enum-type migration and is owned by
`../05-entity-factory/01-polymorphism-and-tagged-unions.md`. Summary of the boundary:

| Behavior today | Anchors | msgspec end-state |
|---|---|---|
| **Raise** on unknown type discriminator | `entity_factory.py:1022,1520,1779,2827,3190,3580,3821,4354,4679`; auto-mod `4788-4789,4842-4843`; `deserialize_guild_thread` dispatch `1514-1520` | msgspec **tagged unions also raise on unknown tag** (dossier 13 §14) → behavior preserved with no extra work |
| **Soft-skip** the element | `data_binding.cast_variants_array` (`data_binding.py:411-438`) used by `impl/rest.py:2040,2049,3129,4960`; audit-log loops `entity_factory.py:1045,1056,1072,1082`; event discard `event_manager_base.py:421-422`; interaction server `interaction_server.py:461` | tagged unions have **no default variant**; reproduce the skip with a `msgspec.Raw` peek-then-dispatch prepass or retained hand dispatch |

Key point for this cluster: **do not** try to solve polymorphic tolerance with enum `_missing_`. A
minted pseudo-member would let an unknown *type* value slip past the discriminator and then fail
downstream when the factory has no builder for it. The two mechanisms stay independent — scalar fields
tolerate via `_missing_`/IntFlag; polymorphic dispatch tolerates via raise-or-skip, unchanged. Full
design in the entity_factory cluster.

--------------------------------------------------------------------------------------------------

## 6. Step-by-step migration

1. Rewrite `hikari/internal/enums.py`: add `_MissingMixin`, `_PSEUDO_CACHES`, the stdlib-backed
   `Enum(_MissingMixin, enum.Enum)` base with conditional `__str__`, and the `Flag(enum.IntFlag)`
   set-API mixin (from `01-flags-migration.md` §4). Preserve `_MAX_CACHED_MEMBERS`.
2. Delete `_DeprecatedAlias`, `deprecated`, `_EnumNamespace`, `_EnumMeta`, `_FlagMeta`,
   `_name_resolver`, and the `_Enum`/`_Flag` bootstrap singletons.
3. Update `__all__` to `("Enum", "Flag")` (`enums.py:25`).
4. Delete or trim `enums.pyi` (§3.1); remove its `deprecated` declaration regardless.
5. Run the full type-check and test suite; the 80 declaration sites should compile unchanged (only
   field unions and converters change, per `03-strict-enum-field-inventory.md`).
6. Confirm the polymorphic-dispatch behavior is handled in the entity_factory cluster, not here (§5).

--------------------------------------------------------------------------------------------------

## 7. Affected files & symbols

| Path | Anchor | Change |
|---|---|---|
| `hikari/internal/enums.py` | whole file | rewrite to stdlib-backed bases; delete metaclasses + `deprecated` |
| `hikari/internal/enums.pyi` | `:41,44-66,70` | delete (recommended) or trim; drop `deprecated` |
| `hikari/internal/deprecation.py` | (import removed from `enums.py:51,57`) | no change to `deprecation.py` itself; only `enums.py` stops importing it |
| `hikari/errors.py` | `:127` | `UnrecognisedEntityError` unchanged (polymorphic path, §5) |
| `hikari/impl/entity_factory.py` | raise/skip sites (§5) | handled in `../05-entity-factory/01-polymorphism-and-tagged-unions.md` |
| `hikari/impl/event_manager_base.py` | `:421-422` | discard-on-unrecognised unchanged (§5) |

--------------------------------------------------------------------------------------------------

## 8. Risks / gotchas

1. **Subclassable base.** `enums.Enum` must declare **no members** to remain subclassable (stdlib bans
   subclassing an enum that has members). The base above has none — verify `class X(int, enums.Enum)`
   still creates members correctly after the rewrite.
2. **`_member_type_` availability in `__str__`.** The conditional `__str__` reads
   `type(self)._member_type_`; stdlib sets this on the concrete class. Confirm it is populated for both
   int and str families (it is, for any mixed-in enum) and that `enums.Enum` itself (no member type)
   never has `__str__` called on an instance (it has no instances).
3. **Stub deletion regressions.** Deleting `enums.pyi` shifts type-checking onto the real module; a
   subtle mypy error (e.g. IntFlag `__invert__` typed as `int` in typeshed, the reason `enums.pyi:64-66`
   special-cased it) may resurface. Keep the trimmed stub if so.
4. **`deprecated` removal is a public-ish break.** Though unused internally, `enums.deprecated` is in
   `__all__` today; a downstream user could theoretically import it. Announce its removal in
   `../11-rollout/03-breaking-changes-and-changelog.md`.
5. **Do not conflate the two tolerance paths (§5).** Adding `_missing_` to a discriminator enum
   (e.g. `ChannelType`, `ComponentType`, `InteractionType`) is fine for scalar *fields* but must **not**
   be relied on to tolerate unknown *types* in polymorphic dispatch — the factory/tagged-union layer
   owns that.

--------------------------------------------------------------------------------------------------

## 9. Verification

- Full test suite green with `enums.py` rewritten and declaration sites unchanged.
- Type-check (mypy + pyright) with `enums.pyi` deleted; if clean, keep it deleted, else restore a
  trimmed stub. Record the outcome in `../12-appendices/01-open-questions-and-verifications.md`.
- Assert `enums.__all__ == ("Enum", "Flag")` and that `import`ing `enums.deprecated` raises
  `ImportError`.
- Confirm (grep + test) that no concrete enum relied on `deprecated`, `_name_resolver`,
  `__everything__`, or negative-value flag wrap.
- Cross-check the polymorphic raise/skip behavior via the entity_factory cluster's tests, not this
  cluster's.

--------------------------------------------------------------------------------------------------

## 10. Open questions / decisions

Cross-linked to `../00-overview/05-decisions-log.md` (D2):

1. Single `enums.Enum` base with conditional `__str__` (recommended, zero declaration edits) vs
   explicit `_IntEnum`/`_StrEnum` bases (clearer, but 67 declaration edits)?
2. Delete `enums.pyi` entirely (recommended) or keep a trimmed stub? Gate on the mypy/pyright result.
3. Remove `deprecated` outright (recommended — unused) or retain a stdlib-alias-based shim for future
   use? Recommend remove; re-add if/when a real deprecation is needed.
4. Preserve the public `__everything__` flag member? Unused outside `enums.py`; recommend dropping
   (see `01-flags-migration.md` §10).
