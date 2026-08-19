# Rollback and Risk Mitigation

Purpose: the safety net for the migration — feature-flag / parallel-path options, per-phase rollback
procedures, the correctness verification gates that must pass before each phase merges, and a risk
register with mitigations. The migration is a large, mostly-hard-break change landing in one `3.0.0`
train; this file makes each step reversible and each correctness claim checkable.

Cross-references: phases in [`00-phasing-and-sequencing.md`](00-phasing-and-sequencing.md), PR units
in [`01-pr-breakdown.md`](01-pr-breakdown.md), perf gates in
[`02-performance-benchmarking.md`](02-performance-benchmarking.md), the break catalog in
[`03-breaking-changes-and-changelog.md`](03-breaking-changes-and-changelog.md).

---

## 1. Objective

1. Keep every phase revertible in isolation (or explain why it is not, and what the recovery is).
2. Define correctness gates that prove each slice preserves behavior modulo the documented breaks.
3. Enumerate the concrete risks (msgspec wheels, encode parity, datetime edges, enum-cache growth,
   soft-skip semantics) and their mitigations.

---

## 2. Feature-flag / parallel-path options

msgspec is a **hard core dependency** with no stdlib fallback for typed decode (dossier 14 §6.3), so
a global "attrs vs msgspec" runtime flag is **not** feasible — you cannot subclass `msgspec.Struct`
conditionally. Flagging is therefore limited to specific seams:

| Seam | Flag feasible? | How |
|---|---|---|
| **JSON engine (P1)** | Yes (temporarily) | Keep the `default_json_loads`/`default_json_dumps` indirection (`data_binding.py:100-123`) and allow an env/config switch between `msgspec.json` and the retained orjson path for A/B during P1, then delete orjson once P1 is proven. |
| **Decode boundary (P2 vs P5)** | Yes (structural) | The two-layer design (D1) makes the residual factory the swap point: P2 builds Structs via `msgspec.convert(dict, ...)` / hand construction; P5 swaps in `msgspec.json.decode(bytes, type=...)` per family. Either can be reverted per family without touching the public Struct shape. |
| **Models (attrs vs Struct)** | No | Cannot coexist; the revert unit is a git revert of the module PR (see §3). |
| **Enums (#2770 strict custom)** | Partial | The custom enums stay either way; the revert unit is the #2770 adoption PR (E1/E2). Reverting restores the tolerant raw-value-on-miss `__call__` and the `\| int`/`\| str` unions. |
| **Cache copy removal (P4)** | Yes (partial) | Copy collapse (C2) is independently revertible from the struct freeze (P2); re-introducing `copy.copy` on frozen structs is harmless (a no-op copy) if a regression appears. |

Parallel-path principle: the **two-layer architecture is itself the main rollback lever**. Because the
residual factory still constructs the public Structs by hand in P2, each model family can be converted,
tested, and reverted independently, and the P5 declarative optimization is opt-in per family.

---

## 3. Per-phase rollback

| Phase | Revert unit | Difficulty | Recovery notes |
|---|---|---|---|
| **P0** enums | `git revert` E1–E2 (the #2770 adoption) | Low | Isolated — no msgspec/struct dependency; the custom enums stay. Revert restores the tolerant raw-value-on-miss `__call__` and the `EnumType | int`/`| str` leniency exactly. |
| **P1** JSON seam | `git revert` J2 (keep J1 dep add or revert both) | Low | Restore the orjson `try/except` in `data_binding.py`. If J1 already removed orjson from `speedups`, re-add it. The retained indirection (§2) means J2 can be reverted without touching callers. |
| **P2** structs | `git revert` the offending S-PR (per module) | High per-module, very high in aggregate | Each module PR is a revert unit, but reverting one may break a dependent module (e.g. reverting S6 channels breaks S7 guilds). Revert in reverse dependency order. A full P2 rollback is a `3.0.0`-scope decision, not a hotfix. |
| **P3** helpers | `git revert` H-PRs; restore helper bodies | Medium | Helpers can be restored only if the `app` field is restored (P2), so a P3-only rollback also requires reverting the relevant P2 field removal. In practice P2+P3 revert together. |
| **P4** copy removal | `git revert` C1/C2/C3 | Low–Medium | Re-introducing `copy.copy` on frozen structs is safe (no-op). Restoring `attrs_extensions.py` (C1) is a clean file re-add. The `*Data`/`RefCell` changes (C3) are the trickiest — revert C3 independently. |
| **P5** declarative | Don't land, or `git revert` the family PR | Low | Optional and per-family; reverting a D-PR falls back to the P2 residual construction for that family. |
| **P6** builders | Don't land | Low | Deferred; never a rollback concern for `3.0.0`. |

Rollback rule of thumb: **P0, P1, P4, P5 are cheap to revert; P2/P3 are the expensive, coupled core.**
Concentrate the strongest correctness gates (§4) on P2/P3 so a rollback is rarely needed there.

---

## 4. Correctness verification gates

These are the gates that prove each slice is correct. They are the primary defense against needing a
rollback at all.

### 4.1 Golden round-trip corpus (the central gate for P2–P4)

1. On `2.5.x`, record a representative corpus of **real** REST responses and gateway payloads
   (GUILD_CREATE, MESSAGE_CREATE/UPDATE, READY, INTERACTION_CREATE, small events — the same fixtures as
   [`02-performance-benchmarking.md`](02-performance-benchmarking.md) §3.1), tokens/PII scrubbed.
2. Snapshot the deserialized entities' public data (via `attrs.asdict` on `2.5.x`).
3. On the migration branch, decode the same corpus and assert the public data is **equal** to the
   snapshot, modulo the documented, enumerated deltas:
   - `app` attribute absent (constraint a);
   - unknown enum values are pseudo-members not bare ints (constraint b, dossier 12 §5.2);
   - frozen (mutation raises) — assert immutability separately (§4.3).
4. Run per module in the S-PR that converts it, and in aggregate on the integration branch.

This corpus is the single most important artifact for de-risking P2 — it catches re-keying, flatten,
context-injection, tri-state, and enum-tolerance regressions (the 13 hard cases, dossier 05 §6).

### 4.2 Enum tolerance property tests

- `SomeEnum(known)` → the member; `SomeEnum(unknown_int)` → an `is_unknown` pseudo-member with
  `x == unknown_int`, `int(x) == unknown_int`, `isinstance(x, SomeEnum)` True, `type(x) is int` False
  (PR hikari-py/hikari#2770).
- the custom `Flag(unknown_bits)` preserves the bits (round-trips) and reports `is_unknown`; the `Flag`
  set-API methods work unchanged.
- casting the wrong type (a `str` into an int-enum) raises `TypeError` (the #2770 `__objtype__` guard).
- the bounded pseudo-member cache (`_temp_members_`) does not grow past the `_MAX_CACHED_MEMBERS`
  (`enums.py:39`) cap under a stream of distinct unknown values (memory-safety, dossier 02 /
  CONVENTIONS §3).
- Detailed in [`../10-testing/02-cache-copy-and-enum-tests.md`](../10-testing/02-cache-copy-and-enum-tests.md).

### 4.3 Frozen-immutability tests

- `model.attr = x` raises for every decoded entity type; `Embed`/builders remain settable.
- `msgspec.structs.replace(model, field=...)` produces a modified copy; the original is unchanged.
- id-only identity holds: `eq=False` + inherited `Unique` dunders give `a == b` iff `a.id == b.id`,
  and `hash(a)` is id-based (confirmed in dossier 16 — msgspec does **not** set `__hash__ = None`
  under `eq=False`; [`../01-foundations/01-base-struct-conventions.md`](../01-foundations/01-base-struct-conventions.md)).

### 4.4 Cache identity / no-copy tests

- `cache.get_x(id) is cache.get_x(id)` is True post-migration (was a fresh copy).
- bulk views return shared frozen instances; no `copy.copy` remains on the read path.
- `has_been_deleted` semantics preserved via `RefCell.deleted`; message edits via
  `msgspec.structs.replace` + `RefCell.object` swap ([`../04-frozen-and-cache/01-cache-data-layer-and-mutation.md`](../04-frozen-and-cache/01-cache-data-layer-and-mutation.md)).

### 4.5 Tooling gates (CI, per PR and pre-merge)

| Gate | Command / anchor | Catches |
|---|---|---|
| Unit + feature tests | `nox -s pytest pytest-all-features` | behavioral regressions |
| Type check (strict) | `nox -s mypy` (`pyproject.toml:232-261`) | stale `# type: ignore` (`warn_unused_ignores`), signature drift |
| Type completeness | `nox -s verify-types` | newly-untyped public exports after helper removal |
| Stub drift | `nox -s generate-stubs` + clean `git status` (`ci.yml:130-137`) | un-regenerated `.pyi` |
| Slots | `nox -s slotscheck` | missing `__slots__` on Structs; stale enum exclude regex |
| Lint | `nox -s ruff` (`select = ["ALL"]`) | new Struct class-body findings (RUF012, etc.) |
| Dep audit | `nox -s audit` | msgspec vulnerabilities in the regenerated `uv.lock` |
| Docs build | `docs` CI job | griffe rendering of Structs; dangling attrs inventory refs |
| Public-API snapshot | new test (X3, dossier 12 §9) | accidental symbol drops |
| Perf | [`02-performance-benchmarking.md`](02-performance-benchmarking.md) §6 | throughput/memory regressions |

### 4.6 The `-OO` and 3.14 gates

- `pytest-all-features` runs under `python -OO` (`pipelines/pytest.nox.py:60`) — confirm Structs
  behave with asserts stripped (dossier 14 §11.2).
- All 15 CI cells (3 OS × 3.10–3.14) must install and pass; the msgspec 3.14 wheel availability is the
  packaging precondition for the whole migration (dossier 14 §11.1).

---

## 5. Risk register

| # | Risk | Likelihood | Impact | Mitigation | Owner plan |
|---|---|---|---|---|---|
| R1 | **msgspec has no cp314 wheel** for some OS in the CI matrix | Med | Blocks the whole migration (install fails) | Verify wheels on PyPI for the chosen msgspec version across cp310–cp314 / 3 OSes **before** pinning; hold P1 until confirmed | [`../01-foundations/00-dependencies-and-tooling.md`](../01-foundations/00-dependencies-and-tooling.md) |
| R2 | **`OPT_NON_STR_KEYS` parity** — msgspec encodes non-str dict keys differently from orjson | Med | Silent malformed request bodies | Parity test on request-body encode (int-keyed maps); register `enc_hook`; audit builder dicts for int-subclass leaks (D6) | [`../01-foundations/04-json-data-binding.md`](../01-foundations/04-json-data-binding.md) |
| R3 | **Datetime edge cases** — native msgspec datetime vs ciso8601 (`Z`/offset/6-µs) and epoch-number fields + max/min clamping (`time.py:160-166`) | Med | Wrong timestamps, lost clamping | Keep ciso8601 / per-field hooks for epoch fields; verify RFC3339 edges before dropping ciso8601 (D4) | [`../01-foundations/02-custom-scalar-types-and-hooks.md`](../01-foundations/02-custom-scalar-types-and-hooks.md) |
| R4 | **Enum pseudo-member cache (`_temp_members_`) unbounded growth** under adversarial unknown values | Low | Memory leak | Bounded cache with the `_MAX_CACHED_MEMBERS` cap (kept by #2770); property test (§4.2) | [`../02-enums/02-int-and-str-enums-migration.md`](../02-enums/02-int-and-str-enums-migration.md) |
| R5 | **Tagged-union soft-skip regression (P5)** — msgspec raises on unknown tag; components/audit soft-skip today | Med (P5 only) | Bots crash on new Discord component/type | Keep the `Raw` peek-then-dispatch prepass or hand dispatch for soft-skip families; reconcile per union (D2, dossier 05 §6.2) | [`../05-entity-factory/01-polymorphism-and-tagged-unions.md`](../05-entity-factory/01-polymorphism-and-tagged-unions.md) |
| R6 | **D5 `UNDEFINED` union rejected by msgspec** (`T \| UndefinedType`) | Med | Forces the `UNSET` fallback + shim; touches ~1912 sites | Run the D5 VERIFY spike first; if it fails, adopt `msgspec.UNSET` + public alias shim | [`../01-foundations/03-undefined-and-unset.md`](../01-foundations/03-undefined-and-unset.md) |
| R7 | **D3 `eq=False` + `Unique` hash** — RESOLVED | — | — | Dossier 16 confirmed msgspec does **not** set `__hash__ = None` under `eq=False`: a frozen Struct over `Unique` keeps `Unique`'s id-only `__eq__`/`__hash__`, stays immutable, and is hashable despite unhashable list/dict fields. **No** hand-written dunder re-attachment is needed. Residual: re-run the base-struct probe on the CPython 3.10 floor (confirming run was 3.11; the mechanism is version-independent) | [`../01-foundations/01-base-struct-conventions.md`](../01-foundations/01-base-struct-conventions.md) |
| R13 | **Forgetting the combined `_StructABCMeta` metaclass** (dossier 16 R1) — a bare `class X(Unique, msgspec.Struct, …)` | Low | Class creation fails, but **loudly** | `StructMeta` is not an `ABCMeta` subclass, so the omission raises `TypeError: metaclass conflict` immediately; define `_StructABCMeta(abc.ABCMeta, type(msgspec.Struct))` once, set it on the shared `UniqueStruct` base, and let subclasses inherit it | [`../01-foundations/01-base-struct-conventions.md`](../01-foundations/01-base-struct-conventions.md) |
| R14 | **Forgetting per-level `kw_only=True`** (dossier 16 R2) — `kw_only` is not stored in `StructConfig` and does not reliably inherit | Med | **Silent** until a subclass adds a required field after an inherited optional one, then class creation fails with `Required field '…' cannot follow optional fields` | Declare `frozen=True, kw_only=True` on every field-adding struct as a lint/review rule; do not trust inheritance | [`../01-foundations/01-base-struct-conventions.md`](../01-foundations/01-base-struct-conventions.md) |
| R8 | **P2 two-layer regresses the hot path** vs orjson+attrs | Med | `3.0.0` ships slower | Perf gate §6 of benchmarking; hand-construct hot types or prioritize P5 for offenders | [`02-performance-benchmarking.md`](02-performance-benchmarking.md) |
| R9 | **`.pyi` stub / verify-types drift** missed | High (easy to forget) | CI red at integration merge | Regenerate stubs as the last content PR (X1); make it a merge checklist item | [`01-pr-breakdown.md`](01-pr-breakdown.md) X1 |
| R10 | **Example/doc breakage** unmigrated (mypy-gated) | High | CI red; users hit broken tutorials | Rewrite examples in lockstep (H3); author the migration guide | [`03-breaking-changes-and-changelog.md`](03-breaking-changes-and-changelog.md) §8 |
| R11 | **`GatewayGuildDefinition` laziness lost** — eager decode of GUILD_CREATE | Med | Memory/CPU regression on large guilds | Preserve the lazy contract (dossier 05 §9); benchmark lazy vs realized | [`../05-entity-factory/02-hard-cases-and-transforms.md`](../05-entity-factory/02-hard-cases-and-transforms.md) |
| R12 | **Accidental public-symbol drop** during the large refactor | Med | Silent API removal | Public-API snapshot test (X3), baselined on `2.x` before migration | [`01-pr-breakdown.md`](01-pr-breakdown.md) X3 |

---

## 6. Step-by-step: applying the safety net per phase

1. Before P1: verify R1 (msgspec wheels on all 15 cells) and add the public-API snapshot baseline (R12).
2. During P1: keep the JSON-engine indirection (§2) so J2 is A/B-testable and revertible; run R2 parity.
3. Before P2: land the D5/D7 VERIFY spikes (R6) and the enum tolerance tests (R4). D3 is resolved
   (dossier 16); its only residual is the CPython 3.10-floor re-run of the base-struct probe.
4. During P2: per module, run the golden corpus (§4.1) + frozen (§4.3) gates in the S-PR; keep the
   residual factory as the per-family revert lever.
5. During P3: run examples mypy + docs build (R10); migrate callers; apply D10.
6. During P4: run cache identity tests (§4.4); copy re-introduction is the cheap escape hatch.
7. Pre-merge: regenerate stubs (R9), run full `linting` + `verify-types` + perf gates (R8), assemble
   fragments, `towncrier --draft`.
8. Post-3.0 (P5): reconcile soft-skip semantics per union (R5) before each declarative family lands.

---

## 7. Affected files and symbols

| Area | Anchor |
|---|---|
| JSON indirection (flag point) | `hikari/internal/data_binding.py:100-123` |
| Decode boundary (swap point) | `impl/entity_factory.py`; `impl/rest.py:1012,1062`; `impl/shard.py:200`; `impl/interaction_server.py:442` |
| Cache copy (cheap-revert) | `hikari/internal/cache.py` (~104 sites); `impl/cache.py:1538` |
| Golden corpus (new) | `tests/` fixtures + recorded payloads |
| Tooling gates | `pipelines/*.nox.py`; `.github/workflows/ci.yml:15-23,112-186` |
| Stub regen | `pipelines/mypy.nox.py:46-69`; the 5 `.pyi` files |

---

## 8. Verification

- Each gate in §4 is itself the verification; the golden corpus (§4.1) is the acceptance test for
  P2–P4.
- A phase merges only when its §4 gates and the relevant §5 mitigations are green.
- Rollback procedures (§3) are validated by confirming each phase's revert PR restores a green tree in
  a dry run before the phase merges (rehearse the revert on P2 module PRs given their coupling).

---

## 9. Open questions / decisions

- **Retain the JSON-engine indirection past P1** (as a permanent flag) or delete it once msgspec is
  proven? Recommended: delete after P1 to avoid re-introducing the branch the migration removes
  (dossier 14 §11.5). Cross-link [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md).
- **How much of the golden corpus to commit** vs generate — commit a curated, PII-scrubbed set;
  document the recording procedure so it can be refreshed as Discord evolves.
- **R5/R6 spikes must resolve before P2 coding** (R7 is resolved — dossier 16; only the CPython
  3.10-floor re-run remains) — track them against the VERIFY/FLAGGED items in
  [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md) (and the consolidated
  `12-appendices/01-open-questions-and-verifications.md` once authored).
