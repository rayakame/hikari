# Flags Migration — 13 Custom Flags Kept, Strict-Typed, Decoded via the Hook

Purpose: keep hikari's 13 `enums.Flag` types on the custom `_FlagMeta`/`Flag` implementation, adopt PR
hikari-py/hikari#2770's `is_unknown` addition, drop the dead `| int` on flag fields, and decode/encode
them through the shared `dec_hook`/`enc_hook`. Flags are the easy half of the enum migration: the
custom `Flag` **already** mints a pseudo-member instance on any unknown/composite value, so it already
satisfies the hook's instance-of-type invariant (dossier 15 §1). No stdlib port, no set-API
re-implementation.

Serves constraint (b) (strict enum fields) and decision D2 (`../00-overview/05-decisions-log.md`).

--------------------------------------------------------------------------------------------------

## 1. Objective

- **Keep** the 13 `class X(enums.Flag)` types exactly as they are — the custom `Flag` is faster at
  runtime and already forward-compatible. Do **not** port to `enum.IntFlag`; do **not** re-implement the
  set-API.
- Adopt #2770's `Flag.is_unknown` property (`enums.py`, PR head:
  `bool(self._value_ & ~self.__class__.__everything__._value_)`) for introspection of unknown bits.
- Drop the dead `SomeFlag | int` unions (they never held a bare int — a Flag `__call__` always returned
  a Flag instance).
- Route flag fields through the shared `dec_hook`/`enc_hook`
  (`../01-foundations/02-custom-scalar-types-and-hooks.md`): `dec_hook` returns `t(raw)`, `enc_hook`
  returns `o.value`.

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
at runtime (`enums.py:452`), so they are int subclasses. **All of this is kept unchanged.**

### 2.2 The custom `Flag` set-API is kept as-is (`enums.py:683-829`)

hikari's rich set-API — `all/any/none/difference/intersection/union/symmetric_difference/invert/
is_subset/is_superset/is_disjoint/split`, the aliases (`isdisjoint`, `issubset`, `issuperset`,
`symmetricdifference`, `enums.py:788-797`), the dunders (`__bool__`, `__int__`, `__iter__`, `__len__`,
`__repr__`, `__rsub__`, `__str__`, `enums.py:799-822`), and the operator bindings
(`__contains__ = is_subset`, `__rand__ = __and__ = intersection`, `__ror__ = __or__ = union`,
`__sub__ = difference`, `__rxor__ = __xor__ = symmetric_difference`, `__invert__ = invert`,
`enums.py:824-829`) — **stays exactly as written**. Nothing is re-implemented; the migration keeps the
custom `Flag`, so the entire surface and its supporting internals (`__everything__` at
`enums.py:506`, the bounded pseudo-member cache `_temp_members_` capped at `_MAX_CACHED_MEMBERS = 4096`
at `enums.py:39`, `_name_resolver` at `enums.py:360-377`, the `_powers_of_2_to_member_map_` used by
`split()` at `enums.py:759-770`, and the negative-value wrap `__everything__ - ~value` at
`enums.py:394`) remain in place. The `.pyi` stub already declares this surface (`enums.pyi:44-66`); it
too is kept (`04-enums-module-and-machinery.md` §3).

### 2.3 Dead `| int` on flag fields (dossier 02 §C.5)

`GuildMemberFlags` is a Flag yet typed `GuildMemberFlags | int` at `guilds.py:511` and
`internal/cache.py:442`. Its deserialization
(`entity_factory.py:2166,2914`: `GuildMemberFlags(payload.get("flags") or GuildMemberFlags.NONE)`)
can never yield a bare int — `_FlagMeta.__call__` always returns a Flag instance. The union is
dead/defensive typing and must be dropped (PR #2770 lands this drop as part of its strict field-typing
sweep). All other flag fields are already strict (e.g. `messages.py:1589` `flags: MessageFlag`; every
`permissions_.Permissions` field, dossier 02 §C.4).

--------------------------------------------------------------------------------------------------

## 3. Why the custom `Flag` already satisfies the hook invariant

msgspec routes a field typed with a custom `Flag` to `dec_hook(t, raw)` because the custom `Flag` is
**not** an `enum.Enum` subclass (dossier 15 §1). The hook returns `t(raw)`, and msgspec requires the
result to be an instance of `t`. hikari's `Flag` already guarantees this: `_FlagMeta.__call__`
(`enums.py:381-412`) mints a pseudo-member **instance** for any unknown or composite value and caches
it, keeping the raw bits.

```python
class Perm(enums.Flag):
    A = 1; B = 2; C = 4
Perm(4)     # <Perm.C: 4>            (known bit)
Perm(5)     # <Perm.A|C: 5>          (composite)
Perm(64)    # pseudo-member, is_unknown, int(x) == 64 kept    (undefined bit)
```

Decoded through the hook (dossier 15 §3, Probe A — flags passed on both the pre- and post-#2770 runs):

```python
msgspec.json.decode(b'4',  type=Perm)   # -> <Perm.C: 4>       via dec_hook -> Perm(4)
msgspec.json.decode(b'64', type=Perm)   # -> pseudo-member     via dec_hook -> Perm(64), int() == 64
```

Unknown bits are kept inside the flag — exactly hikari's current pseudo-member behavior — and encode
back to the raw int through `enc_hook` (`o.value`). No `_missing_`, no union, no reparent. #2770 adds
`Flag.is_unknown` so callers can ask whether any undefined bit is set.

--------------------------------------------------------------------------------------------------

## 4. Target design — hook routing plus #2770's `is_unknown`

There is **no** new flag base class and **no** set-API re-implementation. The design is:

1. Flags stay `class X(enums.Flag)` on the custom `_FlagMeta`. No declaration-site edits, no member-body
   edits (the `1 << n` values are identical), no internals removed.
2. #2770 adds `Flag.is_unknown` returning `bool(self._value_ & ~self.__class__.__everything__._value_)`
   — True iff any bit outside the flag's documented `__everything__` is set. This is the flag analogue
   of `Enum.is_unknown` (`02-int-and-str-enums-migration.md`).
3. The shared hooks gain the enum/flag branch (design owned by
   `../01-foundations/02-custom-scalar-types-and-hooks.md`):

   ```python
   # decode: t is the annotated flag type, obj the decoded JSON int
   if issubclass(t, (enums.Enum, enums.Flag)):
       return t(obj)          # Flag.__call__ mints a pseudo-member on unknown bits
   # encode: emit a plain int primitive
   if isinstance(o, (enums.Enum, enums.Flag)):
       return o.value
   ```

Returning `o.value` on encode yields a plain `int`, avoiding msgspec's int-subclass encode gap (a
`Flag` is an int subclass; emitting the subclass directly is the gap the hook sidesteps). The KEEP
behavior for unknown bits is intrinsic to the custom `Flag` and therefore version-independent — there
is no `enum.IntFlag` `boundary=` concern, and no CPython-3.10-floor probe (that verification was
withdrawn as moot; see `../12-appendices/01-open-questions-and-verifications.md`).

--------------------------------------------------------------------------------------------------

## 5. Behavioral members — unchanged

Because the base class does not change, `Permissions.all_permissions` (`permissions.py:322`) and
`Intents.is_privileged` (`intents.py:441`) are **not touched**:

```python
# permissions.py:322 — iterate canonical members and OR them.
@classmethod
def all_permissions(cls) -> Permissions:
    all_perms = Permissions.NONE
    for perm in Permissions:      # _FlagMeta.__iter__ yields canonical single-bit members
        all_perms |= perm
    return all_perms

# intents.py:441
@property
def is_privileged(self) -> bool:
    return bool(self & self.ALL_PRIVILEGED)
```

`for perm in Permissions` iterates via `_FlagMeta.__iter__` (`enums.py:420-421`, yielding
`_name_to_member_map_.values()`), unchanged from today. `Intents` composite members
(`ALL_UNPRIVILEGED`, `ALL_PRIVILEGED`, `ALL` at `intents.py:422-433`) remain valid composite members.
No value can drift because no runtime enum semantics change here — only #2770's additive `is_unknown`
and the field-typing sweep land.

--------------------------------------------------------------------------------------------------

## 6. Step-by-step migration

1. Adopt #2770 (which adds `Flag.is_unknown`; the pseudo-member `__call__` was already present for
   `Flag`) as part of the enum prerequisite PR (`04-enums-module-and-machinery.md`). No `_FlagMeta`
   internals are removed.
2. Add the enum/flag branch to the shared `dec_hook`/`enc_hook`
   (`../01-foundations/02-custom-scalar-types-and-hooks.md`). Flags need no other runtime change.
3. Drop the dead `| int` on flag fields (delivered by #2770's typing sweep):
   - `guilds.py:511` `guild_flags: GuildMemberFlags | int` → `GuildMemberFlags`.
   - `internal/cache.py:442` same field → `GuildMemberFlags`.
   - Audit for any other `SomeFlag | int` (none others found in dossier 02 §C; `MessageFlag`,
     `Permissions`, `ChannelFlag`, `GuildSystemChannelFlag`… are already strict).
4. In the declarative end-state, type the flag as a bare field on the wire struct so the hook decodes it
   (see `../05-entity-factory/00-architecture-and-decode-strategy.md`); in the incremental phase the
   manual `GuildMemberFlags(payload.get("flags") or GuildMemberFlags.NONE)` casts
   (`entity_factory.py:2166,2914`) stay valid — the cast still returns a Flag. Keep the `or NONE`
   default so a missing `flags` key stays `NONE`.
5. `events/base_events.py:138` (`intent_group.split()`) — no change; `split()` is a kept custom-`Flag`
   method.

--------------------------------------------------------------------------------------------------

## 7. Affected files & symbols

| Path | Anchor | Change |
|---|---|---|
| `hikari/internal/enums.py` | `Flag` (`:516-829`), `_FlagMeta` (`:380`) | kept; #2770 adds `is_unknown` only |
| `hikari/permissions.py` | `:33`, `:322` | unchanged (base kept); `all_permissions` unchanged |
| `hikari/intents.py` | `:33`, `:441` | unchanged; `is_privileged` unchanged |
| `hikari/guilds.py` | `:369`, `:511` | `GuildMemberFlags` unchanged; drop `\| int` on `guild_flags` |
| `hikari/internal/cache.py` | `:442` | drop `\| int` on `guild_flags` |
| `hikari/impl/entity_factory.py` | `:2166`, `:2914` | flag cast retained/typed (still returns a Flag) |
| other flag modules (`messages.py:201`, `channels.py:138`, `users.py:60`, `invites.py:91`, `applications.py:84`, `monetization.py:56`, `presences.py:284`, `capabilities.py:33`, `api/config.py:36`, `guilds.py:260`) | base clause | **unchanged** (custom `Flag` kept) |
| `hikari/events/base_events.py` | `:138` | `.split()` call unchanged |

The msgspec hook branch itself lives in `../01-foundations/02-custom-scalar-types-and-hooks.md`.

--------------------------------------------------------------------------------------------------

## 8. Risks / gotchas

1. **Encode must go through `enc_hook`.** A `Flag` is an int subclass; a struct field encoded without
   the hook could hit msgspec's int-subclass encode gap. The `enc_hook` branch (`return o.value`) emits
   a plain int and must be present (`../01-foundations/02-custom-scalar-types-and-hooks.md`).
2. **`GuildMemberFlags | int` callers.** Grep for any caller that branched on the int arm of
   `guild_flags` (dossier 02 §C.5 says the arm was dead). Removing the union changes only typing, not
   runtime, but confirm no `isinstance(x, int) and not isinstance(x, GuildMemberFlags)` guard exists.
3. **`is_unknown` is new API.** #2770 adds `Flag.is_unknown`; downstream code that shipped its own
   unknown-bit detection can migrate to it. Purely additive.
4. **`CacheComponents`/`GatewayCapabilities`** are internal config flags, never JSON-decoded — they
   are unchanged and carry no msgspec forward-compat concern.
5. **No `boundary`/3.10 concern.** Unknown-bit tolerance is intrinsic to the custom `Flag`, not an
   `enum.IntFlag` `boundary` default, so there is nothing to verify on the CPython 3.10 floor (the old
   V3 is withdrawn as moot; `../12-appendices/01-open-questions-and-verifications.md`).

--------------------------------------------------------------------------------------------------

## 9. Verification

- Round-trip test per flag through the hook: decode a known composite and an unknown-bit value, assert
  `int()` is preserved, `is_unknown` is correct, and re-encode (via `enc_hook`) matches the raw int.
- Set-API parity is inherited (the custom `Flag` is unchanged); a smoke test over `all/any/none/
  difference/intersection/union/split/is_subset/…` confirms nothing regressed when #2770 lands.
- `Permissions.all_permissions()` and `Intents.is_privileged` value tests pinned to the current int
  results (unchanged base, so they must not move).
- `events/base_events.py:138` (`intent_group.split()`) exercised by an existing event test — confirm
  green.
- Empirical decode/encode of custom flags through the hook is RESOLVED in dossier 15
  (`../12-appendices/02-custom-enum-feasibility.md`).

--------------------------------------------------------------------------------------------------

## 10. Open questions / decisions

Cross-linked to `../00-overview/05-decisions-log.md` (D2):

1. Adopt `Flag.is_unknown` from #2770 as-is (recommended) or expose an additional helper for the
   documented-bit mask? Recommendation: adopt #2770's property; add nothing further.
2. Input-param `SomeFlag | int` lenience in REST signatures — keep (recommended, ergonomic) or tighten?
   #2770 already types REST params strictly; decided in `03-strict-enum-field-inventory.md` §7.
3. Whether to expose `__everything__` publicly. It is a kept custom-`Flag` internal used by
   `invert()`/`is_unknown`; recommendation: leave it internal (unchanged from today).
