# Risk and Danger Map

The ranked hazards of the migration, each with severity, likelihood, blast radius, and mitigation.
This is the triage reference for sequencing ([../11-rollout/00-phasing-and-sequencing.md](../11-rollout/00-phasing-and-sequencing.md))
and rollback ([../11-rollout/04-rollback-and-risk-mitigation.md](../11-rollout/04-rollback-and-risk-mitigation.md)).
Decisions referenced by number are in [05-decisions-log.md](05-decisions-log.md).

## 1. Objective

Surface, rank, and mitigate the ways this migration can go wrong, so that the highest-severity
dangers are addressed by design (locked decisions and VERIFY probes) before implementation, not
discovered in production. Severity is rated on user impact × reversibility; likelihood on how easily
a mechanical migration trips the hazard by default.

## 2. Severity scale

| Level | Meaning |
|---|---|
| S1 Critical | Silent data corruption or crash-on-live-data; hard to detect in tests |
| S2 High | Breaks a large, documented public API surface; user code must change |
| S3 Medium | Behavior change that is observable and must be documented, but contained |
| S4 Low | Localized, low-blast-radius, or performance-only |

## 3. Ranked danger table

| # | Danger | Sev | Likelihood | Blast radius | Mitigation (locked) |
|---|---|:--:|:--:|---|---|
| R1 | Forward-compat regression: strict enum crashes on new Discord value | S1 | High (default behavior) | Every bot, on Discord's schedule | D2: stdlib `IntFlag` (native unknown-bit tolerance) + value-preserving `_missing_` pseudo-member; both empirically verified (dossier 02 Part E) |
| R2 | Public API breakage: app-delegating helper methods + `app` field removed (163 `self.app.*` floor; **173** total with the 10 `self.user.app.*` Member sites) | S2 | Certain (by design) | Every documented example / most bots | D9: full break catalog + changelog; `rest.*` migration guide; FLAGGED D10 Option 2 removes only the ~114 wire-entity helpers and keeps the ~59 event/interaction helpers, Option 1 removes all ~173 |
| R3 | Cache correctness under frozen + no-app | S1 | Medium | Cache read/write, ref-count GC | D8: `RefCell`/`GuildRecord` stay mutable; `has_been_deleted`→`RefCell` flag; edits via `structs.replace` |
| R4 | Wire-format edge cases (int-subclass encode gap, epoch datetimes, timedelta units) | S1 | Medium | Request bodies, presence/voice/avatar-decoration fields | D4/D7: global `enc_hook`; field-specific hooks; keep `time.unix_epoch_to_datetime` clamping |
| R5 | Soft-skip vs raise mismatch on unknown polymorphic type | S2 | Medium | Components, audit entries, thread/channel dispatch | D1: `msgspec.Raw` peek-then-dispatch prepass preserves soft-skip; tagged-union raise matches hard-fail |
| R6 | Identity semantics change (all-field eq/hash vs id-only) | S1 | High if unguarded | Every model used as dict key / in a set / compared | D3: keep `Unique` base + `eq=False`; VERIFY inherited dunders survive under frozen |
| R7 | `UNDEFINED` vs `msgspec.UNSET` divergence | S2 | Medium | ~1714 `UndefinedOr` sites, REST param layer | D5: keep `hikari.UNDEFINED` (preferred); VERIFY `T \| UndefinedType` union legality; UNSET shim fallback |
| R8 | Lazy `GatewayGuildDefinition` regressed to eager decode | S2 | Medium | Large-guild memory/CPU on `GUILD_CREATE` | D1: preserve the lazy contract; residual factory keeps the bespoke lazy object |
| R9 | Performance regression from per-field hook cost | S3 | Medium | Snowflake-dense payloads (every entity) | D4: single reusable module-level Decoders; hooks only on custom fields; benchmark ([../11-rollout/02-performance-benchmarking.md](../11-rollout/02-performance-benchmarking.md)) |
| R10 | `str()` semantics drift on str enums (member name vs value) | S3 | Medium | Logging, user-visible output | D2: preserve `str()` **generically** — override `__str__` on the `_IntEnum` base (→ member name) and on the `_StrEnum` base (→ value); not via a per-enum method (the `MessageType.__str__` (messages.py:327) anchor is a misattribution — line 327 is the `Attachment` class); see [../02-enums/02-int-and-str-enums-migration.md](../02-enums/02-int-and-str-enums-migration.md) §5-6 |
| R11 | IntFlag unknown-bit tolerance differs on the 3.10 floor | S2 | Low-Medium | All 13 flags, on 3.10 only | D2: VERIFY KEEP-boundary behavior on 3.10 before relying on it |
| R12 | `_x`-alias / property collapse breaks construction-by-keyword | S3 | Medium | 4 model-module alias fields + tests | D3: collapse `_x`+trivial property to public `x`; keep `_x` only where the property computes |
| R13 | Dropping `ciso8601` loses a datetime edge case | S3 | Low | Entity timestamp decode | D4: VERIFY `Z`/offset/6-µs edge cases before removing the dep |
| R14 | Wheel unavailability across 3.10–3.14 incl. free-threaded | S2 | Low | Install/CI on some targets | D7: confirm msgspec C-wheel coverage before making it a hard dep ([../01-foundations/00-dependencies-and-tooling.md](../01-foundations/00-dependencies-and-tooling.md)) |
| R15 | Multiple-inheritance hazard (`files.Resource` + Struct) | S2 | Medium | `Attachment`, `MediaResource`, `EmbedImage/Video` | Bespoke design per class; do not assume mechanical swap (dossier 03 §5) |
| R16 | Behavior-adjacent bug fix during migration masks a real change | S4 | Low | e.g. `_GuildFields.explicit_content_filter` wrong-enum copy-paste (dossier 02 §F.2) | Fix separately with an explicit changelog note |

## 4. The top four, expanded

### R1 — Forward-compat regression (S1)

Today hikari tolerates unknown Discord enum values: `EnumType(value)` returns the raw `int`/`str` on a
lookup miss (`enums.py:154`), which is why ~150 fields are typed `SomeEnum | int`. A naive strict-enum
migration makes msgspec **raise `ValidationError` on every unknown value** (empirically confirmed,
dossier 02 §E.2), so hikari would **crash whenever Discord ships a new enum value before a hikari
release** — a severe, time-bomb regression that tests will not catch (the value does not exist yet).

Mitigation is designed into D2 and both halves are empirically verified:

- **Flags → `enum.IntFlag`.** Unknown bits are preserved natively (KEEP boundary), lossless, no hook
  (dossier 02 §E.3). Drop the dead `| int` on flag fields.
- **Scalar enums → stdlib enum + `_missing_` minting a value-preserving pseudo-member** via
  `int.__new__`/`str.__new__`. msgspec invokes `_missing_` on a miss and accepts the returned member;
  `int(x)`/`str(x)`/`==` all still work (dossier 02 §E.4). This keeps the field strictly typed while
  never raising on unknown values.

The one residual behavior change (R6-adjacent): an unknown value is now an enum pseudo-member rather
than a bare `int` — `type(x) is int` becomes `False`, `isinstance(x, TheEnum)` becomes `True`. Must
be documented ([../11-rollout/03-breaking-changes-and-changelog.md](../11-rollout/03-breaking-changes-and-changelog.md)).

### R2 — Public API breakage (S2)

Removing the `app` field deletes every `entity.app.rest.*` / `entity.app.cache.*` helper. The
`self.app.*` count is 163 across 20 modules (dossier 04 §0); the **true total is 173** once the 10
`self.user.app.*` sites on `guilds.Member` are counted (so `Member` alone carries ~11 app-delegating
helpers, not 1). These are heavily documented (each carries a full docstring with a Raises section)
and are a major part of hikari's public surface. Every example doing `await message.respond(...)`,
`await channel.send(...)`, `guild.get_member(...)` breaks. Mitigation: this is intentional under
constraint (a) and cannot be avoided, so it is managed rather than prevented — a complete break
catalog, a `rest.*` migration guide, and `changes/` news fragments (dossier 12). The FLAGGED D10
decision materially shrinks the break: recommended **Option 2** removes only the ~114 **wire-entity**
helpers and retains the ~59 hand-constructed event/interaction helpers; **Option 1** removes all
~173.

### R3 — Cache correctness (S1)

The cache never mutates a built entity in place; mutation is confined to `RefCell`, `GuildRecord`,
and the `*Data` layer (dossier 07 §0). Freezing the public structs is therefore safe for the cache's
public surface, but three internal flows resist freezing: `MessageData.update()` mutates 8 fields in
place (`internal/cache.py:884-925`), `MemberData.has_been_deleted` is a mutable meta-flag, and
`RichActivityData.emoji` is reassigned during presence caching. Mitigation (D8): `RefCell` and
`GuildRecord` stay mutable; `has_been_deleted` moves to a `RefCell.deleted` flag; message edits apply
via `msgspec.structs.replace` + `RefCell.object` swap. The `set_role` no-copy asymmetry
(`impl/cache.py:1538`) becomes uniformly correct under frozen and must be re-verified.

### R4 — Wire-format edge cases (S1)

Three concrete traps:

1. **int-subclass encode gap.** msgspec **cannot encode `int`/`str` subclasses natively**
   (`Snowflake`, `Color`), contradicting its own docs (dossier 13 §11). Any raw `Snowflake` leaking
   into a builder dict raises `TypeError` on encode. Mitigation: global `enc_hook` (`Snowflake→str`,
   `Color→int`, `Permissions→str`) plus an audit of builder dicts (D4/D7).
2. **Epoch-number datetimes.** Activity/voice/avatar-decoration timestamps are JSON **numbers**, not
   RFC3339 strings, and `time.unix_epoch_to_datetime` clamps out-of-range values to `datetime.max/min`
   (`time.py:160-166`) — behavior msgspec's native datetime decode does not replicate. Mitigation:
   field-specific hook or int field + transform; keep the clamping helper (D4).
3. **timedelta units.** Discord sends bare numbers with a per-field unit (seconds vs days); msgspec's
   native timedelta expects ISO-8601 durations and is unusable here. Mitigation: `Annotated` metadata
   inspected in the hook, or per-field conversion in the residual factory (D4).

## 5. Cross-cutting mitigations

- **VERIFY before locking.** The S1/S2 dangers R6, R7, R11, R13 each ride on an empirical
  assumption. Those probes are consolidated in
  [../12-appendices/01-open-questions-and-verifications.md](../12-appendices/01-open-questions-and-verifications.md)
  and must pass before the dependent decision is relied upon in code.
- **Two-layer incremental path.** Sequencing the mechanical passes (enums, frozen, app removal)
  before declarative decode limits the blast radius of any single PR and keeps the tree releasable
  between phases (dossier 05 §9).
- **Test-suite realignment.** The identity/copy assertions (~24 lines asserting distinctness after
  `copy.copy`, dossier 07 §10.3) become invalid or trivially true under frozen and must be rewritten
  to assert value-equality / identity-is-safe ([../10-testing/02-cache-copy-and-enum-tests.md](../10-testing/02-cache-copy-and-enum-tests.md)).

## 6. Open questions

The residual maintainer decisions that carry their own risk — chiefly D10 (events/interactions app)
and the VERIFY gates — are tracked in [05-decisions-log.md](05-decisions-log.md). No danger in this
map is un-owned: each maps to a locked decision or a VERIFY probe.
