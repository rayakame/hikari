# Enums Module and Machinery — `internal/enums.py` Kept, #2770 Diffs, and Dispatch

Purpose: specify what happens to `hikari/internal/enums.py` and its type stub `enums.pyi` under the
kept-custom-enums decision, describe the exact PR hikari-py/hikari#2770 diffs the module receives, and
draw the boundary between scalar-enum tolerance (this cluster) and the polymorphic
`UnrecognisedEntityError` dispatch (owned by the entity_factory cluster). This is the "what changes in
the module, and what does not" file for the enum migration.

Serves constraint (b) and decision D2 (`../00-overview/05-decisions-log.md`).

--------------------------------------------------------------------------------------------------

## 1. Objective

- **Keep** the custom metaclass machinery in `hikari/internal/enums.py` (`_EnumMeta`, `_FlagMeta`,
  `Enum`, `Flag`, the set-API, the pseudo-member caches). It is faster at runtime than stdlib `enum`,
  which is the reason for the whole decision (`00-strategy-and-forward-compat.md` §7). Do **not** rewrite
  it onto stdlib enum.
- Apply the PR #2770 diffs: `_EnumMeta.__call__` mints a pseudo-member instance on a miss, `_temp_members_`
  is added to the enum namespace, `Enum.is_unknown` / `Flag.is_unknown` are added, and the `__objtype__`
  wrong-type guard raises `TypeError`.
- Keep the module's public export names (`Enum`, `Flag`) so `from hikari.internal import enums` call
  sites are untouched.
- Keep `enums.pyi` (the stub that masquerades hikari enums as stdlib enums for type-checkers).
- Confirm the polymorphic-dispatch tolerance path is a **separate** concern and route it to the
  entity_factory cluster.

--------------------------------------------------------------------------------------------------

## 2. Current state of `hikari/internal/enums.py`

829 lines. `__all__ = ("Enum", "Flag", "deprecated")` (`enums.py:25`). Structure and fate under the
kept-custom-enums decision:

| Symbol | Lines | Role | Fate |
|---|---|---|---|
| `_MAX_CACHED_MEMBERS = 1 << 12` | `:39` | pseudo-member cache cap (4096) | **kept**; #2770 uses it for the enum cache too |
| `_DeprecatedAlias` | `:42-63` | descriptor emitting a deprecation warning + redirect | kept (unused; see §3.2) |
| `deprecated` | `:66-74` | marks an enum member as a deprecated alias | kept (unused; see §3.2) |
| `_EnumNamespace` | `:76-144` | member-collection namespace for `_EnumMeta` | **kept** |
| `_EnumMeta` | `:153-255` | custom enum metaclass; `__call__` returns raw on miss (`:154-156`) | **kept**; `__call__` gets the #2770 pseudo-member rewrite |
| `Enum` | `:257-354` | custom enum base; `name`/`value` properties, `__str__` (`:353-354`) | **kept**; gains `is_unknown`, unknown-`name` rendering |
| `_name_resolver` | `:360-377` | composite/unknown flag name generator | **kept** (custom `Flag` internal) |
| `_FlagMeta` | `:380-513` | custom flag metaclass; pseudo-member mint + cache (`:381-412`), `__everything__` (`:506`) | **kept** (already mints pseudo-members) |
| `Flag` | `:516-829` | custom flag base + full set-API (`:683-829`) | **kept**; gains `is_unknown` |

The module-level singletons `_Enum`/`_Flag` (`:150,357`) that bootstrap the metaclasses are kept. No
metaclass is retired; no base class is replaced. The only edits are the #2770 diffs (§3).

--------------------------------------------------------------------------------------------------

## 3. Target design — the #2770 diffs to the kept module

The 80 concrete types keep their exact declarations:

```python
class MessageType(int, enums.Enum): ...   # 55 int enums, unchanged
class Locale(str, enums.Enum): ...        # 12 str enums, unchanged
class Permissions(enums.Flag): ...        # 13 flags, unchanged
```

No declaration-site edits. The module receives three additive #2770 changes.

### 3.1 `_EnumMeta.__call__` mints a pseudo-member on a miss

Today `_EnumMeta.__call__` returns the raw value on a miss (`enums.py:154-156`), which the msgspec hook
cannot accept (`00-strategy-and-forward-compat.md` §4.2). #2770 replaces it (verbatim from the PR head,
dossier 15 §2):

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

This mirrors `_FlagMeta.__call__` (`enums.py:381-412`), which already mints pseudo-members. #2770 adds
`_temp_members_` to the enum namespace (the metaclass `__new__` already builds `_value_to_member_map_`
etc. at `enums.py:189-193`; #2770 adds the temp-cache dict alongside). The `__objtype__` guard reuses
the class attribute the metaclass already sets (`enums.py:187,333`).

### 3.2 `is_unknown` and unknown-member naming

#2770 adds:

- `Enum.is_unknown` → `self._value_ not in self._value_to_member_map_`.
- `Flag.is_unknown` → `bool(self._value_ & ~self.__class__.__everything__._value_)`.
- `Enum.name` lazily renders an unknown member as `f"UNKNOWN {self._value_!r}"` (the existing
  `_name_resolver` continues to name unknown/composite flag members).

`changes/2770.feature.md`: "Add the `is_unknown` property to enum and flag members, returning whether
the value is an unknown one which is not documented as part of the enum."

### 3.3 `enums.pyi` is kept, unaffected

The stub aliases `Enum = enum.Enum` (`enums.pyi:41`) and declares `class Flag(enum.IntFlag)` with the
full set-API (`enums.pyi:44-66`) so mypy/pyright treat the custom enums as stdlib enums. It is **kept
as-is**:

- msgspec inspects the **real runtime class** and routes through the hook; it never consults the stub
  (dossier 15 §4). So the stub has no bearing on decode/encode.
- The stub is what makes the field-union drops in `03-strict-enum-field-inventory.md` a *narrowing*
  change for type-checkers (they already see these as stdlib enums), keeping mypy/pyright churn small.
- #2770 may add an `is_unknown` declaration to the stub for both `Enum` and `Flag`; that is the only
  stub edit, and it is additive.

The `deprecated`/`_DeprecatedAlias` machinery (`enums.py:42-74`, declared in `enums.pyi:70`) is
**unused** but is **not removed by this migration**: removing it is an orthogonal dead-code cleanup and
a public-ish break (it is in `__all__`), and #2770 does not touch it. Leave it in place; if a future
cleanup removes it, that is a separate change with its own changelog entry.

--------------------------------------------------------------------------------------------------

## 4. Import-site and export impact

- `from hikari.internal import enums` and `enums.Enum` / `enums.Flag` references stay valid (names and
  metaclasses preserved). No model module changes its `import` line.
- `__all__` is unchanged: `("Enum", "Flag", "deprecated")` (`enums.py:25`).
- `enums.pyi` is unchanged except an optional additive `is_unknown` declaration (§3.3).
- The internal-only shard enums (`GatewayDataFormat`, `ChannelInfoField`, `GatewayCompression` in
  `api/shard.py`) and config flags (`CacheComponents`, `GatewayCapabilities`) keep their custom bases
  and receive #2770's `__call__`/`is_unknown` uniformly, with no special handling.

--------------------------------------------------------------------------------------------------

## 5. Polymorphic `UnrecognisedEntityError` dispatch — SEPARATE concern

Scalar-enum tolerance (this cluster) is distinct from **type-discriminator** tolerance. When an unknown
value selects "which subclass to build" and the factory cannot proceed, it raises
`errors.UnrecognisedEntityError` (`hikari/errors.py:127`) rather than widening a field type. This path
is **not** touched by the enum migration and is owned by
`../05-entity-factory/01-polymorphism-and-tagged-unions.md`. Summary of the boundary:

| Behavior today | Anchors | msgspec end-state |
|---|---|---|
| **Raise** on unknown type discriminator | `entity_factory.py:1022,1520,1779,2827,3190,3580,3821,4354,4679`; auto-mod `4788-4789,4842-4843`; `deserialize_guild_thread` dispatch `1514-1520` | msgspec **tagged unions also raise on unknown tag** (dossier 13 §14) → behavior preserved with no extra work |
| **Soft-skip** the element | `data_binding.cast_variants_array` (`data_binding.py:411-438`) used by `impl/rest.py:2040,2049,3129,4960`; audit-log loops `entity_factory.py:1045,1056,1072,1082`; event discard `event_manager_base.py:421-422`; interaction server `interaction_server.py:461` | tagged unions have **no default variant**; reproduce the skip with a `msgspec.Raw` peek-then-dispatch prepass or retained hand dispatch |

Key point for this cluster: **do not** try to solve polymorphic tolerance with the enum pseudo-member.
A minted pseudo-member would let an unknown *type* value slip past the discriminator and then fail
downstream when the factory has no builder for it. The two mechanisms stay independent — scalar fields
tolerate via #2770's pseudo-member `__call__` decoded through the hook; polymorphic dispatch tolerates
via raise-or-skip, unchanged. Note that tagged-union polymorphism dispatches on a raw literal int/str
discriminator (dossier 13 §14), **not** on a custom-enum instance, so the enum decision does not affect
it. Full design in the entity_factory cluster.

--------------------------------------------------------------------------------------------------

## 6. Step-by-step migration

1. Apply the #2770 diffs to `hikari/internal/enums.py`: the pseudo-member `_EnumMeta.__call__` (§3.1),
   `_temp_members_` on the enum namespace, `Enum.is_unknown` / `Flag.is_unknown` and unknown-member
   naming (§3.2). Nothing is deleted; `_MAX_CACHED_MEMBERS` is reused.
2. Keep `enums.pyi`; optionally add the additive `is_unknown` declaration (§3.3).
3. Add the enum/flag branch to the shared `dec_hook`/`enc_hook`
   (`../01-foundations/02-custom-scalar-types-and-hooks.md`) — the single msgspec integration point.
4. Run the full type-check and test suite; the 80 declaration sites compile unchanged (only field
   unions and converters change, per `03-strict-enum-field-inventory.md`).
5. Confirm the polymorphic-dispatch behavior is handled in the entity_factory cluster, not here (§5).

--------------------------------------------------------------------------------------------------

## 7. Affected files & symbols

| Path | Anchor | Change |
|---|---|---|
| `hikari/internal/enums.py` | `:154-156`, `:257-354`, `:39`, `:381-412`, `:506` | #2770 diffs only: pseudo-member `__call__`, `_temp_members_` on `Enum`, `is_unknown`, unknown naming; metaclasses/set-API kept |
| `hikari/internal/enums.pyi` | `:41,44-66,70` | kept; optional additive `is_unknown` declaration |
| `hikari/internal/deprecation.py` | — | unchanged (`deprecated` machinery kept in `enums.py`) |
| `hikari/errors.py` | `:127` | `UnrecognisedEntityError` unchanged (polymorphic path, §5) |
| `hikari/impl/entity_factory.py` | raise/skip sites (§5) | handled in `../05-entity-factory/01-polymorphism-and-tagged-unions.md` |
| `hikari/impl/event_manager_base.py` | `:421-422` | discard-on-unrecognised unchanged (§5) |

The msgspec hook branch lives in `../01-foundations/02-custom-scalar-types-and-hooks.md`.

--------------------------------------------------------------------------------------------------

## 8. Risks / gotchas

1. **`_temp_members_` on `Enum`.** #2770 adds this cache to the enum namespace; confirm the metaclass
   `__new__` (`enums.py:170-199`) initialises it per concrete class (parallel to `_FlagMeta`'s
   `_temp_members_` at `enums.py:463`) so unknown values cache correctly and stay bounded at
   `_MAX_CACHED_MEMBERS`.
2. **`__objtype__` guard on the wire path.** The guard raises `TypeError` on wrong-type input. msgspec
   passes the decoded primitive matching `__objtype__` (int/str), so the happy path never trips it; a
   genuinely wrong wire type surfaces as `ValidationError` through the hook. Verify with a test.
3. **`is_unknown` stub.** If `enums.pyi` gains the additive `is_unknown` declaration, keep it in sync on
   both `Enum` and `Flag`; a missing declaration only affects type-checking, not runtime.
4. **`deprecated` stays public.** It is unused but remains in `__all__`; this migration does not remove
   it. Do not bundle its removal here (§3.2).
5. **Do not conflate the two tolerance paths (§5).** Adding a pseudo-member to a discriminator enum
   (e.g. `ChannelType`, `ComponentType`, `InteractionType`) is fine for scalar *fields* but must **not**
   be relied on to tolerate unknown *types* in polymorphic dispatch — the factory/tagged-union layer
   owns that.

--------------------------------------------------------------------------------------------------

## 9. Verification

- Full test suite green with the #2770 diffs applied and declaration sites unchanged.
- Type-check (mypy + pyright) with `enums.pyi` kept; churn limited to the narrowed field unions.
- Assert `enums.__all__ == ("Enum", "Flag", "deprecated")` (unchanged) and that `Enum.is_unknown` /
  `Flag.is_unknown` exist and behave per #2770.
- Confirm the pseudo-member `__call__` mints an instance on a miss for both int and str enums, caches
  into `_temp_members_`, and stays bounded at `_MAX_CACHED_MEMBERS` (dossier 15
  `../12-appendices/02-custom-enum-feasibility.md`).
- Cross-check the polymorphic raise/skip behavior via the entity_factory cluster's tests, not this
  cluster's.

--------------------------------------------------------------------------------------------------

## 10. Open questions / decisions

Cross-linked to `../00-overview/05-decisions-log.md` (D2):

1. Rebase strategy for #2770: adopt as an upstream prerequisite PR vs vendor the diffs into the
   migration branch. Recommendation: rebase onto / adopt #2770.
2. Add the `is_unknown` declaration to `enums.pyi` (recommended, additive) or leave the stub untouched
   and let it be an untyped runtime attribute? Recommendation: add it.
3. Remove the unused `deprecated`/`_DeprecatedAlias` machinery as a *separate* future cleanup, or leave
   it? Recommendation: out of scope for this migration; leave it, remove later if desired with its own
   changelog entry.
