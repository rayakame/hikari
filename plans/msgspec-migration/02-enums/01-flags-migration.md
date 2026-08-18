# Flags Migration — 13 Flags to `enum.IntFlag`

Purpose: reparent hikari's 13 `enums.Flag` types onto stdlib `enum.IntFlag`, re-attach the rich
`Flag` set-API (~20 methods/aliases) as a shared `IntFlag` mixin, drop the dead `| int` on flag
fields, and port the two behavioral flag members. Flags are the easy half of the enum migration:
`IntFlag` gives lossless forward-compat natively (dossier 02 §E.3, dossier 13 §10).

Serves constraint (b) (strict enum fields) and decision D2 (`../00-overview/05-decisions-log.md`).

--------------------------------------------------------------------------------------------------

## 1. Objective

- Convert the 13 `class X(enums.Flag)` types to `class X(<SetApiMixin>, enum.IntFlag)`.
- Reproduce hikari's public `Flag` set-API so `Permissions`, `Intents`, `MessageFlag`, etc. keep
  `.all/.any/.none/.split/.difference/.intersection/.union/.is_subset/.is_superset/.is_disjoint/…`.
- Drop the dead `SomeFlag | int` unions (they never held a bare int — a Flag `__call__` always
  returned a Flag).
- Port `Permissions.all_permissions` and `Intents.is_privileged` verbatim.
- Confirm KEEP-boundary forward-compat on the CPython 3.10 floor.

--------------------------------------------------------------------------------------------------

## 2. Current state

### 2.1 The 13 flags (dossier 02 §B.1)

| Flag | file:line | Behavioral extras |
|---|---|---|
| `GatewayCapabilities` | `capabilities.py:33` | — |
| `SKUFlags` | `monetization.py:56` | — |
| `Intents` | `intents.py:33` | `is_privileged` @property (`intents.py:441`) |
| `InviteFlags` | `invites.py:91` | — |
| `ApplicationFlags` | `applications.py:84` | — |
| `ChannelFlag` | `channels.py:138` | — |
| `MessageFlag` | `messages.py:201` | — |
| `CacheComponents` | `api/config.py:36` | — (internal config, not a wire field) |
| `Permissions` | `permissions.py:33` | `all_permissions` @classmethod (`permissions.py:322`) |
| `ActivityFlag` | `presences.py:284` | — |
| `GuildSystemChannelFlag` | `guilds.py:260` | — |
| `GuildMemberFlags` | `guilds.py:369` | — |
| `UserFlag` | `users.py:60` | — |

All are declared `class X(enums.Flag)` (single base); `_FlagMeta` injects `int` as the real first base
at runtime (`enums.py:479`), so they are int subclasses.

### 2.2 The custom `Flag` set-API to reproduce (`enums.py:683-829`)

`enum.IntFlag` provides `| & ^ ~`, `in`, and (3.11+) iteration and `len`, but **none** of hikari's
named set methods. The full surface that must survive (all public; the `.pyi` at `enums.pyi:44-66`
already declares them against `enum.IntFlag`):

| Member | `enums.py` line | Definition (semantics to preserve) |
|---|---|---|
| `all(*flags)` | 683 | `all((f & self) == f for f in flags)` |
| `any(*flags)` | 694 | `any((f & self) == f for f in flags)` |
| `none(*flags)` | 745 | `not self.any(*flags)` |
| `difference(other)` | 705 | `type(self)(self & ~int(other))` |
| `intersection(other)` | 714 | `type(self)(self._value_ & int(other))` |
| `union(other)` | 781 | `type(self)(self._value_ | int(other))` |
| `symmetric_difference(other)` | 772 | `type(self)(self._value_ ^ int(other))` |
| `invert()` | 721 | `type(self)(__everything__._value_ & ~self._value_)` |
| `is_subset(other)` | 734 | `(self & other) == other` |
| `is_superset(other)` | 741 | `(self & other) == self` |
| `is_disjoint(other)` | 725 | `not (self & other)` |
| `split()` | 759 | name-sorted sequence of the power-of-2 members present |
| Aliases | 788-797 | `isdisjoint`, `issubset`, `issuperset`, `symmetricdifference` |
| Dunders | 799-822 | `__bool__`, `__int__`, `__iter__ = iter(split())`, `__len__ = len(split())`, `__repr__`, `__rsub__`, `__str__ = self.name` |
| Operator bindings | 824-829 | `__contains__ = is_subset`, `__rand__ = __and__ = intersection`, `__ror__ = __or__ = union`, `__sub__ = difference`, `__rxor__ = __xor__ = symmetric_difference`, `__invert__ = invert` |

Supporting internals: `__everything__` (OR of all documented bits, `enums.py:502-506`), the bounded
pseudo-member cache `_temp_members_` capped at `_MAX_CACHED_MEMBERS = 4096` (`enums.py:39,463`),
`_name_resolver` for composite/unknown names (`enums.py:360-377`, yields `"UNKNOWN 0x{value:x}"`), and
the negative-value wrap `__everything__ - ~value` (`enums.py:392-394`).

### 2.3 Dead `| int` on flag fields (dossier 02 §C.5)

`GuildMemberFlags` is a Flag yet typed `GuildMemberFlags | int` at `guilds.py:511` and
`internal/cache.py:442`. Its deserialization
(`entity_factory.py:2166,2914`: `GuildMemberFlags(payload.get("flags") or GuildMemberFlags.NONE)`)
can never yield a bare int — `_FlagMeta.__call__` always returns a Flag. The union is dead/defensive
typing and must be dropped. All other flag fields are already strict (e.g. `messages.py:1589`
`flags: MessageFlag`; every `permissions_.Permissions` field, dossier 02 §C.4).

--------------------------------------------------------------------------------------------------

## 3. Why `IntFlag` preserves forward-compat for free

Verified (dossier 02 §E.3, dossier 13 §10, msgspec 0.21.1 / CPython 3.11):

```python
class Perm(enum.IntFlag):
    A = 1; B = 2; C = 4
msgspec.json.decode(b'4',  type=Perm)   # <Perm.C: 4>
msgspec.json.decode(b'5',  type=Perm)   # <Perm.A|4: 5>  (bit 4 undefined, kept)
# int() round-trips; re-encodes to 5 losslessly.
```

Under the default KEEP boundary, unknown bits are kept inside the flag — exactly hikari's current
pseudo-member behavior (`_FlagMeta.__call__`, `enums.py:405-408`). No `_missing_`, no `dec_hook`, no
union. This is the single biggest simplification in the whole enum migration.

--------------------------------------------------------------------------------------------------

## 4. Target design — the set-API mixin

Place a single shared mixin next to the flag base (proposed home:
`hikari/internal/enums.py` rewrite, see `04-enums-module-and-machinery.md`). Every flag inherits it.

```python
import enum, typing
from typing_extensions import Self

_MAX_CACHED_MEMBERS: typing.Final[int] = 1 << 12  # 4096, mirrors today's cap (enums.py:39)


class Flag(enum.IntFlag):
    """IntFlag base re-exposing hikari's historical set-algebra API.

    Subclasses declare members exactly as before:  class Intents(Flag): GUILDS = 1 << 0 ; ...
    """

    # --- named set operations (absent from stdlib IntFlag) ---
    def all(self, *flags: Self) -> bool:
        return all((flag & self) == flag for flag in flags)

    def any(self, *flags: Self) -> bool:
        return any((flag & self) == flag for flag in flags)

    def none(self, *flags: Self) -> bool:
        return not self.any(*flags)

    def difference(self, other: Self | int) -> Self:
        return self.__class__(self & ~int(other))

    def intersection(self, other: Self | int) -> Self:
        return self.__class__(int(self) & int(other))

    def union(self, other: Self | int) -> Self:
        return self.__class__(int(self) | int(other))

    def symmetric_difference(self, other: Self | int) -> Self:
        return self.__class__(int(self) ^ int(other))

    def invert(self) -> Self:
        # all DEFINED bits XOR self — reproduces hikari's __everything__ & ~value.
        return self.__class__(self._all_defined_bits() & ~int(self))

    def is_subset(self, other: Self | int) -> bool:
        return (self & other) == other

    def is_superset(self, other: Self | int) -> bool:
        return (self & other) == self

    def is_disjoint(self, other: Self | int) -> bool:
        return not (self & other)

    def split(self) -> typing.Sequence[Self]:
        # name-sorted power-of-two members present in self (unknown bits omitted).
        return sorted(
            (m for m in type(self) if m.value and not (m.value & (m.value - 1)) and (m.value & int(self))),
            key=lambda m: m._name_,
        )

    # --- aliases (enums.py:788-797) ---
    isdisjoint = is_disjoint
    issubset = is_subset
    issuperset = is_superset
    symmetricdifference = symmetric_difference

    # --- dunders (enums.py:799-822) ---
    def __iter__(self) -> typing.Iterator[Self]:
        return iter(self.split())

    def __len__(self) -> int:
        return len(self.split())

    def __rsub__(self, other: Self | int) -> Self:
        return self.__class__(other) - self

    def __str__(self) -> str:
        return self.name

    # --- operator bindings (enums.py:824-829) ---
    __contains__ = is_subset
    __rand__ = __and__ = intersection
    __ror__ = __or__ = union
    __sub__ = difference
    __rxor__ = __xor__ = symmetric_difference
    __invert__ = invert

    @classmethod
    def _all_defined_bits(cls) -> int:
        # cached OR of every canonical member — the __everything__ replacement.
        cached = cls.__dict__.get("_hikari_all_bits")
        if cached is None:
            cached = 0
            for m in cls:
                cached |= int(m)
            cls._hikari_all_bits = cached
        return cached
```

Notes on faithfulness:

- **`intersection`/`union`/`symmetric_difference`/`difference`** are reimplemented on top of `int()`
  arithmetic (not `self._value_`, which is a hikari-Flag internal) and re-wrap via `self.__class__(...)`
  so the KEEP boundary keeps unknown bits — identical results to `enums.py:705-786`.
- **`split()`** is reimplemented without `_powers_of_2_to_member_map_`; it filters canonical members
  (`m.value` a nonzero power of two) present in `self`, name-sorted, matching `enums.py:759-770`
  (unrecognised bits omitted). `__iter__`/`__len__` delegate to it, preserving today's iteration order
  and length.
- **`invert()`** targets `_all_defined_bits()` (the `__everything__` replacement), not a raw bitwise
  `~`, so `~Permissions.X` still returns "all *documented* permissions except X" rather than a
  two's-complement blob — matching `enums.py:721-723`. `__everything__` itself is not referenced
  anywhere outside `enums.py` (grep: only the compiled `.pyc`), so it need not be exposed as a public
  member; if a public `__everything__` is desired, add `SomeFlag.__everything__ = SomeFlag(all_bits)`
  at class build.
- **Operator overrides shadow stdlib IntFlag's**: hikari binds `__contains__ = is_subset`, which accepts
  a plain `int` on the right-hand side (`Permissions.SEND_MESSAGES in perms` and `1 << 11 in perms`
  both work). stdlib IntFlag's own `__contains__` historically rejected non-member ints — keeping
  hikari's binding preserves the looser, documented behavior (`enums.py:603-605`).

Type-checker impact is minimal: `enums.pyi:44-66` already declares this exact surface against
`enum.IntFlag` (`04-enums-module-and-machinery.md` §3).

--------------------------------------------------------------------------------------------------

## 5. Behavioral members — port verbatim

Both are ordinary Python and port unchanged onto stdlib `IntFlag`:

```python
# permissions.py:322 — iterate canonical members and OR them.
@classmethod
def all_permissions(cls) -> Permissions:
    all_perms = Permissions.NONE
    for perm in Permissions:      # stdlib IntFlag iterates canonical single-bit members
        all_perms |= perm
    return all_perms

# intents.py:441
@property
def is_privileged(self) -> bool:
    return bool(self & self.ALL_PRIVILEGED)
```

Gotcha for `all_permissions`: `for perm in Permissions` iterates the **class**. Under stdlib IntFlag
(3.11+) class iteration yields canonical single-bit members only (aliases and composites excluded) —
which is what this loop wants (`all_permissions()` unions single bits). This is equivalent to today's
`_FlagMeta.__iter__` (`enums.py:420-421`) yielding `_name_to_member_map_.values()`. Add a test pinning
`Permissions.all_permissions()` to the same int value before and after (see §8). `Intents` composite
members (`ALL_UNPRIVILEGED`, `ALL_PRIVILEGED`, `ALL` at `intents.py:422-433`) are defined as ORs of
other members and remain valid IntFlag composite members.

--------------------------------------------------------------------------------------------------

## 6. Step-by-step migration

1. Land the shared `Flag(enum.IntFlag)` mixin (§4) in the rewritten `hikari/internal/enums.py`
   (`04-enums-module-and-machinery.md`). Keep the export name `Flag` so `from hikari.internal import
   enums` call sites are untouched.
2. For each of the 13 flags, change the declaration `class X(enums.Flag)` → `class X(enums.Flag)`
   **unchanged in source text** — because `enums.Flag` is now the IntFlag mixin. (No member bodies
   change; the `1 << n` values are identical.)
3. Remove `_temp_members_`, `_powers_of_2_to_member_map_`, `__everything__`, `_name_resolver`, and
   negative-value-wrap references — these were `_FlagMeta` internals; the mixin above replaces the
   behaviors that mattered. Grep confirms none are referenced outside `enums.py`.
4. Port `Permissions.all_permissions` (`permissions.py:322`) and `Intents.is_privileged`
   (`intents.py:441`) verbatim (they already are plain methods; only the base class changes).
5. Drop the dead `| int` on flag fields:
   - `guilds.py:511` `guild_flags: GuildMemberFlags | int` → `GuildMemberFlags`.
   - `internal/cache.py:442` same field → `GuildMemberFlags`.
   - Audit for any other `SomeFlag | int` (none others found in dossier 02 §C; `MessageFlag`,
     `Permissions`, `ChannelFlag`, `GuildSystemChannelFlag`, `GuildNSFWLevel`… are already strict).
6. Replace the manual flag casts in `entity_factory.py` (`GuildMemberFlags(payload.get("flags") or
   GuildMemberFlags.NONE)` at `:2166,2914`) with either the same cast (still valid — `IntFlag(int)`
   works) or, in the declarative end-state, a typed field on the wire struct (see
   `../05-entity-factory/00-architecture-and-decode-strategy.md`). Keep the `or NONE` default so a
   missing `flags` key stays `NONE`.
7. Update `events/base_events.py:138` (`intent_group.split()`) — no change needed; `split()` is
   preserved by the mixin (§4).

--------------------------------------------------------------------------------------------------

## 7. Affected files & symbols

| Path | Anchor | Change |
|---|---|---|
| `hikari/internal/enums.py` | rewrite | `Flag` becomes an `enum.IntFlag` mixin; `_FlagMeta`, `_temp_members_`, `_name_resolver`, `__everything__` removed |
| `hikari/permissions.py` | `:33`, `:322` | base `enums.Flag` (now IntFlag); `all_permissions` unchanged |
| `hikari/intents.py` | `:33`, `:441` | base change; `is_privileged` unchanged |
| `hikari/messages.py` | `:201` | `MessageFlag` base change |
| `hikari/channels.py` | `:138` | `ChannelFlag` base change |
| `hikari/guilds.py` | `:260`, `:369`, `:511` | `GuildSystemChannelFlag`, `GuildMemberFlags` base change; drop `\| int` on `guild_flags` |
| `hikari/users.py` | `:60` | `UserFlag` base change |
| `hikari/invites.py` | `:91` | `InviteFlags` base change |
| `hikari/applications.py` | `:84` | `ApplicationFlags` base change |
| `hikari/monetization.py` | `:56` | `SKUFlags` base change |
| `hikari/presences.py` | `:284` | `ActivityFlag` base change |
| `hikari/capabilities.py` | `:33` | `GatewayCapabilities` base change |
| `hikari/api/config.py` | `:36` | `CacheComponents` base change (internal, not decoded) |
| `hikari/internal/cache.py` | `:442` | drop `\| int` on `guild_flags` |
| `hikari/impl/entity_factory.py` | `:2166`, `:2914` | flag cast retained/typed |
| `hikari/events/base_events.py` | `:138` | `.split()` call unchanged (preserved) |

--------------------------------------------------------------------------------------------------

## 8. Risks / gotchas

1. **3.10 KEEP boundary (VERIFY-E1).** The unknown-bit-preserving KEEP boundary is the documented
   default only on 3.11+. On the 3.10 floor, confirm empirically that `IntFlag` keeps unknown bits by
   default (no `boundary=` kwarg available pre-3.11) — probe in §9. If 3.10 differs, set
   `boundary=enum.KEEP` conditionally or gate on version.
2. **`str()` of a flag member.** hikari's `Flag.__str__` returns `self.name` (`enums.py:820-822`), and
   `name` for a composite is produced by `_name_resolver` ("A|B", or "UNKNOWN 0x…"). stdlib IntFlag's
   own `__str__`/`name` differ (e.g. `"Perm.A|B"` qualified, and 3.11 vs 3.12 formatting changes). The
   mixin overrides `__str__` to `self.name`; verify the composite/unknown `name` text is close enough
   to today's, and pin it with a test if any logging/serialization depends on the exact string.
3. **Iteration order.** hikari `split()`/`iter()` are **name-sorted**; stdlib class iteration is
   definition-ordered. The mixin's `split()` re-sorts by name, preserving today's order for member
   iteration on an instance. Class-level `for m in SomeFlag` (used by `all_permissions`) is
   definition-ordered under stdlib — acceptable there (union is order-independent) but note the
   difference if any code assumed sorted class iteration.
4. **Operator return types.** stdlib IntFlag operators return `Self`; the mixin's re-bindings also
   return `Self`. Confirm `~x`, `x - y`, `x ^ y` still yield the flag type, not a bare int, via tests.
5. **`GuildMemberFlags | int` callers.** Grep for any caller that branched on the int arm of
   `guild_flags` (dossier 02 §C.5 says the arm was dead). Removing the union changes only typing, not
   runtime, but confirm no `isinstance(x, int) and not isinstance(x, GuildMemberFlags)` guard exists.
6. **`CacheComponents`/`GatewayCapabilities`** are internal config flags, never JSON-decoded — they
   migrate for consistency but carry no msgspec forward-compat concern.

--------------------------------------------------------------------------------------------------

## 9. Verification

- **VERIFY-E1:** On CPython 3.10, `msgspec.json.decode(b'8', type=MessageFlag)` must return a member
  with `int(x) == 8` (unknown bit kept), not raise. Record in
  `../12-appendices/01-open-questions-and-verifications.md`.
- Round-trip test per flag: decode a known composite and an unknown-bit value, assert `int()` is
  preserved and re-encode matches.
- Set-API parity tests: for each method in §2.2, assert the new mixin returns the same result as the
  pre-migration implementation on a fixed battery of inputs (including int right-hand operands and
  negative inputs to `__rsub__`).
- `Permissions.all_permissions()` and `Intents.is_privileged` value tests pinned to the current int
  results.
- `events/base_events.py:138` (`intent_group.split()`) exercised by an existing event test — confirm
  green.

--------------------------------------------------------------------------------------------------

## 10. Open questions / decisions

Cross-linked to `../00-overview/05-decisions-log.md` (D2):

1. Keep the full public `Flag` set-API (recommended — it is public and declared in `enums.pyi`) or
   deprecate the rarely-used aliases (`isdisjoint`, `symmetricdifference`)? Recommendation: keep all.
2. Expose a public `__everything__` member per flag, or drop it (unused outside `enums.py`)?
   Recommendation: drop unless a downstream consumer is found; provide `_all_defined_bits()` for the
   `invert()` implementation only.
3. Composite `name`/`str()` text: match hikari's `"A|B"` / `"UNKNOWN 0x…"` exactly, or accept stdlib's
   formatting? Recommendation: override `__str__ = self.name` (done in §4) and pin with a test; accept
   minor differences in the composite name string if no consumer depends on it.
