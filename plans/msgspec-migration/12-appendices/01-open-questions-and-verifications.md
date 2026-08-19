# Open Questions and Verifications — Pre-Implementation Gate

Every maintainer decision and empirical probe raised anywhere in this plan, consolidated into one
checklist. This is the gate: no code that depends on an item below should merge until that item is
resolved (a maintainer choice recorded, or a probe run with its result documented).

## 1. Objective

The plan locks D1–D11 ([../00-overview/05-decisions-log.md](../00-overview/05-decisions-log.md)) but
several of those decisions are gated — one is FLAGGED for a maintainer choice, six ride on still-open
empirical probes with named fallbacks (V2, V5–V9; V1 is now RESOLVED and V3/V4 WITHDRAWN, see §5),
four carry a maintainer sub-choice, and the dossiers surfaced a tail of smaller decisions. This file
collects all of them so a reviewer can sign the gate in one pass. It is the single source of "what is
still open," referenced from the decisions log §4.

## 2. How to use this file

- Work **FLAGGED (§4)** and **VERIFY (§5)** items first — they gate the foundations and enums work.
- Each item states: **What** must be decided/verified · **Why** it matters · **Recommended** answer ·
  **Closes when** (the experiment output or the maintainer sign-off that retires it) · **Fallback**
  where one exists.
- Run the VERIFY probes against the pinned **msgspec 0.21.1** (or the version being adopted) on the
  **3.10 floor** where the item names it — several behaviours are version-sensitive.
- When an item resolves, record the outcome in the owning plan file and flip its status here and in
  the decisions log.

## 3. Master gate checklist

| ID | Item | Type | Gates | Recommended | Status |
|---|---|---|---|---|---|
| F-D10 | Events & interactions `app` handling | FLAGGED | D10; events/interactions | Option 2 (keep app on events; inject for interaction response sugar; also on `rest.*`) | OPEN |
| V1 | `frozen=True, eq=False` + inherited `Unique` dunders | RESOLVED | D3; all wire structs | Confirmed: inherits id-only dunders, immutable; needs combined metaclass (R1) + per-level `kw_only` (R2); residual: 3.10 floor re-run | RESOLVED (residual: 3.10) |
| V2 | `T \| UndefinedType` union legality + default-on-absent | VERIFY | D5; ~1714 UndefinedOr fields | Keep `UNDEFINED` as field default | OPEN |
| V3 | ~~`IntFlag` KEEP-boundary on the 3.10 floor~~ | WITHDRAWN | moot: custom `Flag` kept | Moot under the custom-enum decision (§5) | WITHDRAWN |
| V4 | ~~`str()` output per enum family~~ | WITHDRAWN | moot: custom enums keep `__str__` | Moot under the custom-enum decision (§5) | WITHDRAWN |
| R-CE | Custom enums decode/encode via the global `dec_hook`/`enc_hook` given #2770's instance-returning `__call__` | RESOLVED | D2; all enum fields | Empirically verified, msgspec 0.21.1 (dossier 15) — no stdlib port needed | RESOLVED |
| B-CE | Benchmark the per-field custom-enum `dec_hook` decode cost vs a stdlib control | BENCHMARK | D2 perf trade-off | Non-blocking; measured in `../11-rollout/02` §3.3 | OPEN (non-gating) |
| V5 | Native datetime vs `ciso8601` edge cases | VERIFY | D4/D7; timestamp fields | Drop `ciso8601` for entity decode if it matches | OPEN |
| V6 | msgspec wheel coverage 3.10–3.14 incl. free-threaded | VERIFY | D7; core dependency | Confirm before pinning; pick a floor with cp314 wheels | OPEN |
| V7 | int-subclass encode leak into builder dicts | VERIFY | D4/D7; request bodies | Global `enc_hook` + builders lower to int/str | OPEN |
| V8 | String JSON key decodes into an int-enum dict key | VERIFY | D1/D2; EF enum-keyed dicts | msgspec coerces string key → `IntEnum`; else re-key in layer 2 | OPEN |
| V9 | Soft-skip prepass reproduces log-and-drop + wire order | VERIFY | D1; EF soft-skip unions | `msgspec.Raw` peek-then-dispatch prepass; else hand dispatch | OPEN |
| SD1 | `*Data` cache layer keep-vs-drop | SUB-DECISION | D8; cache | Keep mutable `*Data` carriers wrapping frozen structs | OPEN |
| SD2 | Scalar-enum pseudo-member cache cap | SUB-DECISION | D2; int/str enums | Keep #2770's bounded `_temp_members_` cap (`_MAX_CACHED_MEMBERS`) | OPEN |
| SD3 | Decode boundary bytes-in vs dict-in | SUB-DECISION | D6; factory interface | bytes-in end-state, `msgspec.convert` bridge | OPEN |
| SD4 | Builder conversion defer | SUB-DECISION | D11; builders | Confirm defer; keep 40 builders mutable in pass 1 | OPEN |
| Q1 | Tighten method-parameter `\| int` unions | DECISION | enums | Keep input lenience | OPEN |
| Q2 | Fix `explicit_content_filter` copy-paste bug | DECISION | guilds factory | Fix + changelog note | OPEN |
| Q3 | Fate of `deprecated`/`_DeprecatedAlias` enum machinery | DECISION | enums module | Drop (unused); re-add shim only if needed | OPEN |
| Q4 | Scope of the custom `Flag` set-API to preserve | DECISION | flags | Keep the full ~20-method public surface | OPEN |
| Q5 | Event-side `fetch_*`/`get_*` helper symmetry | DECISION | events | Keep (folds into F-D10 option 2) | OPEN |
| Q6 | `cache.get_*` returns bare struct vs app wrapper | DECISION | cache | Bare app-less struct; confirm no consumer needs `.app` | OPEN |
| Q7 | Keep the pluggable-json public API | DECISION | data_binding | Keep encode override + typedefs; limit decode override | OPEN |
| Q8 | Soft-skip vs raise on unknown polymorphic type | DECISION | entity_factory | Raw-peek prepass where skip semantics are required | OPEN |
| Q9 | Add a public-API `__all__` snapshot test | DECISION | testing/CI | Add it for this refactor | OPEN |
| Q10 | Restore pyright attrs-relaxations to strict | VERIFY | tooling | Attempt after first module migrated | OPEN |
| Q11 | mypy/pyright native `msgspec.Struct` support on pins | VERIFY | tooling | No plugin expected; confirm | OPEN |
| Q12 | msgspec under `python -OO` | VERIFY | CI | Confirm asserts-stripped behaviour | OPEN |
| Q13 | Shape of abstract model bases (Struct/Protocol/ABC) | DECISION | model-modules/testing | Concrete leaves = frozen Structs; bases per hazard | OPEN |
| Q14 | Introduce a shared `evolve`/stub-entity test helper | DECISION | testing | Yes | OPEN |
| Q15 | Delete vs port helper-method delegation tests | DECISION | testing | Delete delegation tests; port arg-shaping only | OPEN |
| Q16 | Optional `2.6` deprecation pre-warn pass | DECISION | rollout | Optional; only helper removal fits `warn_deprecated` | OPEN |
| Q17 | Examples must migrate in lockstep (mypy-gated) | GATE | docs/examples | Rewrite `examples/*` to `rest.*` with the code | OPEN |

## 4. FLAGGED — maintainer must choose

### F-D10 — Events & interactions `app` handling
- **What.** Do events (44 own-`app` fields + 32 delegating properties) and interactions (subclass
  `ExecutableWebhook`, ~17 `self.app.*` helpers) also go app-less and helper-less, or do they keep
  `app`?
- **Why.** Events and interactions are **hand-constructed** by the event/entity factory, not
  JSON-decoded — so the "cannot inject `app` during decode" constraint does not force removal here.
  Option choice sets the size of the public break and whether latency-critical response sugar
  (`build_response`, `create_initial_response`) survives (dossier 08 §10; dossier 10 §8).
- **Options.** (1) app-less + helper-less everywhere — maximum consistency, maximally breaking, kills
  `interaction.create_initial_response`/`event.fetch_*`. (2) events keep `app` + helpers; interactions
  are constructed via a non-declarative path that injects `app` so response sugar survives, with those
  methods **also** on `rest.*`.
- **Recommended.** **Option 2.** It preserves the DX-critical response path and shrinks the break;
  the delegating-`app` event properties are fixed by giving every event its own `app` field and
  threading `app=self._app` at the ~30 appless construction sites regardless of option.
- **Closes when.** Maintainer records the choice in
  [../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md](../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md)
  and the decisions log F-D10 row. Q5 resolves with it.

## 5. VERIFY — empirical probes gating a locked default

Each has a named fallback; the locked default holds only if the probe passes.

The global **V1–V9** in this section (and the §3 checklist) are the authoritative numbering, and the
other plan files refer to them by these global IDs. In particular
[../01-foundations/00-dependencies-and-tooling.md](../01-foundations/00-dependencies-and-tooling.md)
cites its wheel-coverage probe as global **V6** and its type-checker-native-`Struct` probe as **Q11**
(§7 below).

Integer tagged-union `tag` dispatch — the mechanism behind every int-discriminated polymorphic family
(`type`/`entity_type`/`trigger_type`, OQ-EF-5) — is **already verified**: dossier 13 §14 tested
`tag=0`/`tag=2` int dispatch end-to-end. It is settled, not an open probe, and so is **not** listed as a
VERIFY item here.

**Withdrawn probes (moot under the custom-enum decision, D2).** V3 and V4 existed only for the
now-abandoned stdlib-enum port. hikari **keeps** its fast custom `Enum`/`Flag` (adopt PR
hikari-py/hikari#2770), so both are moot: **V3** (`IntFlag` KEEP-boundary on the 3.10 floor) — there is
no `IntFlag`; the custom `Flag` already preserves unknown bits on every supported Python and flags them
via `is_unknown`. **V4** (`str()` semantics of `(int,Enum)`/`(str,Enum)` vs `StrEnum`) — the custom
enums keep their existing `__str__` unchanged. The V-numbers stay reserved (V3/V4 are referenced
elsewhere) and are marked WITHDRAWN, not reused.

**RESOLVED — custom enums decode/encode via the global hooks (replaces the V3/V4 work).** msgspec
treats the custom (non-`enum.Enum`) `Enum`/`Flag` as custom types and routes them to the global
`dec_hook` (`t(obj)`) and `enc_hook` (`o.value`); given PR hikari-py/hikari#2770's instance-returning
`__call__`, the decoded pseudo-member satisfies the hook's instance-of-type invariant — **empirically
verified on msgspec 0.21.1** (dossier 15; reproduced in-plan at
[`02-custom-enum-feasibility.md`](02-custom-enum-feasibility.md)). No stdlib port, no `IntFlag`
re-implementation, no `_missing_` mixin. One residual, **non-blocking** item remains — **B-CE**:
benchmark the per-enum-field `dec_hook` decode cost against a stdlib-enum control on enum-dense payloads
(the KEEP trade-off measurement), tracked in
[`../11-rollout/02-performance-benchmarking.md`](../11-rollout/02-performance-benchmarking.md) §3.3. It
confirms the net win but does **not** gate the decision.

### V1 — `frozen=True, eq=False` inherits `Unique`'s id-only dunders (gates D3) — RESOLVED
- **What.** On a msgspec `Struct(frozen=True, eq=False)` whose non-Struct base (`snowflakes.Unique`,
  `snowflakes.py:103-132`) defines `__eq__`/`__hash__`, confirm the instance is immutable **and** uses
  the inherited id-only dunders — i.e. msgspec neither generates all-field `__eq__` nor sets
  `__hash__ = None` under `eq=False`.
- **Why.** hikari's identity is id-only; msgspec's default all-field `eq` would break on unhashable
  list/dict fields and change identity semantics (dossier 03 §2.1; dossier 13 §19). Every wire struct
  depends on this.
- **Result (CONFIRMED, msgspec 0.21.1, CPython 3.11, against the real `Unique`; dossier 16 /
  [`03-base-struct-identity-verified.md`](03-base-struct-identity-verified.md)).** Passes on all
  points: immutable, id-only `__eq__`/`__hash__` inherited from `Unique` (`__hash__` not nulled),
  hashable despite an unhashable `list` field, slotted, decode round-trips. Two mechanical
  requirements were uncovered and folded into
  [`../01-foundations/01-base-struct-conventions.md`](../01-foundations/01-base-struct-conventions.md):
  - **R1 — combined metaclass.** `StructMeta` is not an `ABCMeta` subclass, so a bare
    `class X(Unique, msgspec.Struct)` raises `TypeError: metaclass conflict`. Define
    `class _StructABCMeta(abc.ABCMeta, type(msgspec.Struct)): ...` once and set it on the shared base
    (inherited by subclasses). Keep the real `Unique` unchanged (its `__slots__=()` composes fine —
    do NOT remove it).
  - **R2 — per-level `kw_only=True`.** `frozen` inherits via `__struct_config__`, but `kw_only` does
    not reliably (it is not in `StructConfig`); a subclass adding a required field after an inherited
    optional one fails unless it re-declares `kw_only=True`. Declare `frozen=True, kw_only=True` on
    every field-adding struct.
- **Corrected experiment (as run).**
  ```python
  import abc, msgspec
  from hikari.snowflakes import Snowflake, Unique
  class _StructABCMeta(abc.ABCMeta, type(msgspec.Struct)): ...
  class Base(Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False, metaclass=_StructABCMeta): ...
  class S(Base, frozen=True, kw_only=True):
      id: Snowflake
      name: str | None = None
      perms: list[int] = []
  a, b = S(id=Snowflake(1), name="x", perms=[1]), S(id=Snowflake(1), name="y", perms=[2])
  assert a == b and hash(a) == hash(Snowflake(1))     # inherited id-only identity, unhashable field OK
  assert type(a).__hash__ is Unique.__hash__          # not clobbered
  try: a.name = "z"; assert False
  except AttributeError: pass                          # immutable
  ```
- **Residual.** Re-run on the CPython **3.10** floor (the confirming run was 3.11; version-independent
  mechanism, but the floor is unverified). This is the only remaining V1 item.
- **Fallback.** Not needed — no dunder re-attachment required.
- **Owner.** [../01-foundations/01-base-struct-conventions.md](../01-foundations/01-base-struct-conventions.md).

### V2 — `T | UndefinedType` is a legal union with a working default-on-absent (gates D5)
- **What.** Confirm (1) msgspec produces `default=undefined.UNDEFINED` on an absent key, and — the
  risky half — (2) `T | UndefinedType` is a **legal msgspec union arm**, given `UndefinedType` is a
  bespoke singleton class never decoded from JSON.
- **Why.** D5's preferred path keeps `hikari.UNDEFINED` untouched across ~1714 `UndefinedOr` fields
  and thousands of `is UNDEFINED` checks. But dossier 13 §8 warns "custom types in unions are
  unsupported beyond `CustomType | None`" — so `str | UndefinedType` may be rejected at
  type-construction. This is the specific unknown V2 exists to settle.
- **Experiment.**
  ```python
  import msgspec
  class UndefinedType:
      __slots__ = ()
  UNDEFINED = UndefinedType()
  try:
      class M(msgspec.Struct):
          a: str | UndefinedType = UNDEFINED     # is this a legal union arm?
      out = msgspec.json.decode(b'{}', type=M)
      assert out.a is UNDEFINED                  # default produced on absent key
      out2 = msgspec.json.decode(b'{"a":"x"}', type=M)
      assert out2.a == "x"
      print("V2 PASS")
  except TypeError as e:
      print("V2 FAIL — fall back to msgspec.UNSET:", e)
  ```
- **Recommended.** If it passes, keep `UNDEFINED` as the struct-field default (least invasive).
- **Fallback.** Adopt `msgspec.UNSET` (`T | UnsetType`, `default=UNSET`, auto-omitted on encode) for
  decoded-struct tri-state fields, and expose a public `UndefinedOr`/`is UNDEFINED` compatibility shim.
  REST **request** params keep `undefined.UNDEFINED` either way.
- **Owner.** [../01-foundations/03-undefined-and-unset.md](../01-foundations/03-undefined-and-unset.md).

### V3 — WITHDRAWN (moot under the custom-enum decision)
Existed only for the stdlib `enum.IntFlag` port. hikari keeps its custom `Flag` (adopt PR
hikari-py/hikari#2770), which already preserves unknown bits losslessly on every supported Python
(3.10+) and reports them via `is_unknown` — so there is no `IntFlag` KEEP-boundary to verify. Number
retained (it is referenced elsewhere); do not reuse. See the RESOLVED custom-enum finding above and
dossier 15.

### V4 — WITHDRAWN (moot under the custom-enum decision)
Existed only for the stdlib `(int,Enum)`/`(str,Enum)`/`StrEnum` port, whose `str()` output differs from
today's. hikari keeps its custom enums (adopt PR hikari-py/hikari#2770), which retain their existing
`__str__` unchanged — so there is nothing to reproduce or verify. Number retained (it is referenced
elsewhere); do not reuse. See the RESOLVED custom-enum finding above and dossier 15.

### V5 — native datetime decode matches `ciso8601` before dropping the dep (gates D4/D7)
- **What.** Confirm msgspec native RFC3339 decode matches `ciso8601.parse_rfc3339` on Discord's exact
  stamp variants: trailing `Z`, arbitrary offsets, and 6-digit microseconds.
- **Why.** If it matches, `ciso8601` becomes redundant for entity timestamp decode (dossier 09 §2.4;
  dossier 14 §6.2) and can leave the `speedups` extra. Unix-epoch fields and per-unit timedeltas do
  NOT go through native decode regardless (they are numbers) — keep `time.unix_epoch_to_datetime`
  with its max/min clamping.
- **Experiment.** Decode a battery of real Discord stamps (`...Z`, `...+00:00`, non-UTC offsets,
  6-µs) with both parsers and assert equality; check naive/no-offset behaviour (Discord always sends
  aware — audit that no endpoint returns naive).
- **Recommended.** Drop `ciso8601` for entity decode if it matches; keep `time.py` epoch/uuid helpers.
- **Fallback.** Keep `ciso8601` / `time.iso8601_datetime_string_to_datetime` for entity timestamps.
- **Owner.** [../01-foundations/02-custom-scalar-types-and-hooks.md](../01-foundations/02-custom-scalar-types-and-hooks.md),
  [../01-foundations/00-dependencies-and-tooling.md](../01-foundations/00-dependencies-and-tooling.md).

### V6 — msgspec wheel coverage across 3.10–3.14 incl. free-threaded (gates D7)
- **What.** Confirm msgspec publishes C wheels for CPython 3.10–3.14 on ubuntu/macos/windows (the 15
  CI cells, `ci.yml:15-23`), including any free-threaded target hikari intends to support, before
  pinning it as a **core** dependency.
- **Why.** msgspec has no stdlib fallback (unlike orjson) — a missing cp314 wheel fails install on
  that cell with no sdist toolchain assumed on Windows. This is the top packaging risk (dossier 14 §11).
- **Experiment.** Inspect the candidate msgspec release on PyPI for the cp310–cp314 (and
  `cp3xx-cp3xx` free-threaded / `abi3`) wheel matrix across the 3 OSes; pick the floor that covers
  cp314. Fold in Q12 (`-OO`).
- **Recommended.** Verify, then pin a floor with full coverage (dossier 14 suggests `~=0.19` pending
  the check; the empirical work used 0.21.1).
- **Fallback.** Constrain `requires-python`/targets or gate free-threaded support until wheels exist.
- **Owner.** [../01-foundations/00-dependencies-and-tooling.md](../01-foundations/00-dependencies-and-tooling.md).

### V7 — no raw `Snowflake`/`Color` int-subclass leaks into a builder dict (gates D4/D7)
- **What.** Audit that no raw `Snowflake`/`Color` (int subclasses) reaches a dict handed to
  `msgspec.json.encode`, which `TypeError`s on int subclasses (dossier 13 §11 — the doc says
  otherwise and is wrong).
- **Why.** orjson serialized int subclasses silently; msgspec does not. `put_snowflake` already
  stringifies, but the 7 `serialize_*` methods and some builders emit raw values (e.g.
  `serialize_forum_tag` leaves `id` as a `Snowflake`, dossier 06 §5).
- **Experiment.** Grep builder/serialize paths for raw `Snowflake`/`Color` values; add an encode test
  over each request-body shape; register the global `enc_hook` (Snowflake→`str(int)`, Color→`int`,
  Permissions→`str(int)`, datetime→isoformat) and/or lower to plain int/str at the source.
- **Recommended.** Register the global `enc_hook` **and** keep the stringifying builders.
- **Owner.** [../01-foundations/04-json-data-binding.md](../01-foundations/04-json-data-binding.md).

### V8 — string JSON object key decodes into an int-enum dict key (gates D1/D2, OQ-EF-8)
- **What.** Confirm msgspec decodes a JSON object whose keys are **strings** into a
  `Mapping[ApplicationIntegrationType, …]` — routing each string key through the custom int-enum (via
  the shared `dec_hook`), i.e. reproducing `ApplicationIntegrationType(int(k))`. Applies to
  `Application.integration_types_config` (`deserialize_application:703`) and interactions'
  `authorizing_integration_owners`
  (`3039-3043`: `{ApplicationIntegrationType(int(k)): Snowflake(v)}`).
- **Why.** JSON object keys are always strings on the wire; the target type keys on a custom int enum.
  If msgspec does not route the string key through the custom enum for a dict-key type, the declarative
  decode cannot produce the enum-keyed mapping and it must be re-keyed after decode (dossier 05 §6.13).
- **Experiment.** Decode `b'{"0":"123","2":"456"}'` into `Mapping[ApplicationIntegrationType, Snowflake]`
  (with the `dec_hook` routing both the key enum and `Snowflake`) and assert the keys are
  `ApplicationIntegrationType` members and the values `Snowflake`. Repeat for an unknown int key to
  confirm the #2770 pseudo-member behaviour on the key type.
- **Recommended.** Rely on msgspec's string-key coercion if it passes; keep the mapping declarative.
- **Fallback.** Re-key in a **layer-2 transform** after decode (decode with `Mapping[str, …]` or `Raw`,
  then `{ApplicationIntegrationType(int(k)): v …}`), matching today's factory transform.
- **Owner.** [../06-model-modules/09-applications-and-oauth.md](../06-model-modules/09-applications-and-oauth.md) §3.4,
  [../06-model-modules/11-interactions.md](../06-model-modules/11-interactions.md) §3.4,
  [../05-entity-factory/02-hard-cases-and-transforms.md](../05-entity-factory/02-hard-cases-and-transforms.md).

### V9 — soft-skip prepass reproduces log-and-drop + wire order (gates D1, OQ-EF-4)
- **What.** Confirm the `msgspec.Raw` peek-then-dispatch prepass reproduces today's **soft-skip**
  (log + drop) semantics for unknown polymorphic elements — components in action-rows/containers and
  some audit-log entries — and preserves the **wire order** of the surviving elements.
- **Why.** Native tagged unions **raise** on an unknown tag (the correct behaviour for the raise
  families), but the soft-skip families must silently drop unknown elements without failing the whole
  decode, and downstream code depends on the surviving elements staying in wire order (dossier 05 Q6;
  dossier 13 §14). This is the empirical half of the Q8 decision.
- **Experiment.** Decode a components array containing one unknown component type through the Raw
  peek-then-dispatch prepass; assert the unknown element is dropped (and logged), the known elements
  decode, and their relative order is unchanged. Repeat for a nested container and an audit-log entry.
- **Recommended.** Use the `msgspec.Raw` peek-then-dispatch prepass (iterating in wire order) exactly
  where skip semantics are required; native unions elsewhere.
- **Fallback.** Keep a hand-written dispatch loop retaining the current soft-skip + ordering.
- **Owner.** [../05-entity-factory/01-polymorphism-and-tagged-unions.md](../05-entity-factory/01-polymorphism-and-tagged-unions.md),
  [../06-model-modules/08-components.md](../06-model-modules/08-components.md).

## 6. SUB-DECISIONS — locked default, maintainer sub-choice

### SD1 — `*Data` cache layer: keep vs drop (under D8)
- **What.** After frozen + no-app, the `*Data` layer's remaining jobs are (i) hold `RefCell`
  cross-references, (ii) in-place edit (`MessageData.update`), (iii) the `has_been_deleted` meta-flag.
  Keep `*Data` as mutable non-frozen carriers wrapping frozen public structs, **or** store frozen
  structs directly and move mutation to `RefCell` + `msgspec.structs.replace`?
- **Why.** `RefCell`/`GuildRecord` must stay mutable; `MessageData.update` and `has_been_deleted`
  cannot live on a frozen struct (dossier 07 §10.2).
- **Recommended.** Keep `*Data` as mutable carriers (least churn); move `has_been_deleted` to a
  `RefCell.deleted` flag; apply message edits via `structs.replace` + `RefCell.object` swap.
- **Closes when.** Maintainer picks the path in
  [../04-frozen-and-cache/01-cache-data-layer-and-mutation.md](../04-frozen-and-cache/01-cache-data-layer-and-mutation.md).

### SD2 — Scalar-enum pseudo-member cache cap (under D2)
- **What.** PR hikari-py/hikari#2770 mints unknown `Enum` members through the same bounded
  `_temp_members_` cache the custom `Flag` already uses (cap `_MAX_CACHED_MEMBERS = 1 << 12`,
  `enums.py:39`), evicting the oldest on overflow. Confirm the cap is retained for scalar enums (it is,
  by #2770) rather than left unbounded.
- **Why.** `__call__` mints a real member per unknown value; an open-ended value space (rare for scalar
  enums, more plausible for flag-like int spaces) could grow unbounded without a cap.
- **Recommended.** Keep #2770's bounded `_temp_members_` cap for uniformity and to bound worst-case
  growth; the fast known-value path is unaffected (only misses pay the mint cost).
- **Closes when.** Maintainer confirms the cap value in
  [../02-enums/02-int-and-str-enums-migration.md](../02-enums/02-int-and-str-enums-migration.md).

### SD3 — Decode boundary: bytes-in vs dict-in (under D6)
- **What.** Push the decode boundary down into the factory (bytes-in typed decode) or keep the
  `deserialize_*(JSONObject)` dict-in interface and bridge with `msgspec.convert`?
- **Why.** bytes-in is a single-pass typed decode (faster, keeps msgspec's advantage) but changes
  every abstract signature and the rest/shard/interaction-server callers; dict-in via `convert` is
  localized but materially slower (dossier 05 §1, §9).
- **Recommended.** bytes-in for the declarative end-state; dict-in via `msgspec.convert` as the
  incremental bridge in early passes.
- **Closes when.** Sequencing recorded in
  [../01-foundations/05-decode-boundary-and-decoders.md](../01-foundations/05-decode-boundary-and-decoders.md)
  and the rollout phasing.

### SD4 — Builder conversion deferral (confirm D11)
- **What.** Confirm the 42 `special_endpoints` builders stay mutable (attrs) in the first pass and are
  NOT converted to frozen structs now.
- **Why.** Builders are mutable fluent state machines that also mutate during `build()`; they never
  decode from JSON and their conversion is a large orthogonal change to the public builder API
  (dossier 06 §10.1; D11).
- **Recommended.** Defer — keep them mutable; only the encoder implementation swaps under them.
  Optionally convert to frozen structs + `enc_hook` + `UNSET` in a later, separate change.
- **Closes when.** Maintainer confirms deferral in
  [../08-builders/00-special-endpoints-builders.md](../08-builders/00-special-endpoints-builders.md).

## 7. Secondary decisions and tooling gates

Smaller items surfaced across the dossiers. Individually low-risk, but each is a decision or gate that
should be settled before or during the relevant work-stream.

### Q1 — Tighten method-parameter `| int` unions?
Method PARAMETER unions (~80 `| int` sites in REST/builder signatures, dossier 02 C.3) exist for
input lenience and are orthogonal to msgspec decode. **Recommended: keep the lenience.** Closes on
maintainer sign-off; owned by [../02-enums/03-strict-enum-field-inventory.md](../02-enums/03-strict-enum-field-inventory.md).

### Q2 — Fix the `explicit_content_filter` copy-paste bug?
`_GuildFields.explicit_content_filter` is typed `GuildVerificationLevel | int`
(`entity_factory.py:152`) where it should be `GuildExplicitContentFilterLevel` (dossier 02 C.1, F.2).
**Recommended: fix during migration + changelog note** (behaviour-adjacent). Closes on sign-off;
owned by [../06-model-modules/05-guilds-members-roles.md](../06-model-modules/05-guilds-members-roles.md).

### Q3 — Fate of the `deprecated`/`_DeprecatedAlias` enum machinery
`enums.deprecated` is unused by any concrete enum today (dossier 02 A.4). **Recommended: drop it;**
re-express via stdlib enum aliasing only if a future deprecation needs it. Closes on sign-off; owned
by [../02-enums/04-enums-module-and-machinery.md](../02-enums/04-enums-module-and-machinery.md).

### Q4 — Scope of the custom `Flag` set-API to preserve
The `Flag` public API is large (~20 methods/aliases: `.all/.any/.none/.split/.difference/
.intersection/.union/.is_subset/…`, `enums.py:683-829`) and public. **Recommended: keep all of it** on
a shared `IntFlag` mixin/subclass; the `.pyi` already models it. Closes on sign-off; owned by
[../02-enums/01-flags-migration.md](../02-enums/01-flags-migration.md).

### Q5 — Event-side `fetch_*`/`get_*` helper symmetry
Event helpers share the exact `self.app.rest.*`/`cache.*` shape as entity helpers, but events keep
`app` legitimately (they are constructed, not decoded). Keep them, or move to `rest.*` for symmetry?
**Recommended: keep (folds into F-D10 option 2).** Closes with F-D10; owned by
[../07-events/00-events-migration.md](../07-events/00-events-migration.md).

### Q6 — `cache.get_*` returns a bare struct vs an app-carrying wrapper
Constraint (a) points to returning a bare app-less frozen struct. **Recommended: bare struct;** grep-
confirm no internal cache consumer reads `.app` on a returned object (dossier 07 Q4). Closes on the
grep audit + sign-off; owned by [../04-frozen-and-cache/02-cache-app-and-views.md](../04-frozen-and-cache/02-cache-app-and-views.md).

### Q7 — Keep the pluggable-json public API?
Six components accept `dumps`/`loads` overrides (a documented feature). Typed decode into structs can
no longer honour a user-supplied generic `loads`. **Recommended: keep the encode override and the
`JSONEncoder`/`JSONDecoder` typedefs; limit/deprecate the decode override on Struct-typed paths** and
flag it as a public break (dossier 01 §8.6). Closes on sign-off + changelog fragment; owned by
[../01-foundations/04-json-data-binding.md](../01-foundations/04-json-data-binding.md).

### Q8 — Soft-skip vs raise on unknown polymorphic type
msgspec tagged unions raise on unknown tag — matching the factory's `UnrecognisedEntityError` for
channels/threads/interactions/auto-mod/scheduled-events. But components in action rows/containers and
some audit entries currently **soft-skip** (log + drop). **Recommended: retain a `msgspec.Raw`
peek-then-dispatch prepass (or hand dispatch) exactly where skip semantics are required;** decide
per-union (dossier 05 Q6; dossier 13 §14). The empirical half — that the prepass reproduces the
log-and-drop behaviour and preserves wire order — is probe **V9** (§5). Closes per-union in
[../05-entity-factory/01-polymorphism-and-tagged-unions.md](../05-entity-factory/01-polymorphism-and-tagged-unions.md).

### Q9 — Add a public-API `__all__` snapshot test?
No test enumerates `dir(hikari)`/`__all__` for drift; the only machine guard is the generated `.pyi` +
mypy/pyright (dossier 12 §9). **Recommended: add a snapshot test** to catch accidental symbol drops
during this large refactor. Closes on sign-off; owned by [../10-testing/00-test-strategy.md](../10-testing/00-test-strategy.md).

### Q10 — Restore pyright attrs-relaxations to strict?
`reportIncompatibleVariableOverride`/`reportUnknownMemberType`/`reportUntypedFunctionDecorator`
(`pyproject.toml:180,184,185`) were relaxed because of attrs. **Recommended: attempt to restore to
`"error"`** after the first module migrates, confirming frozen Structs don't reproduce the abstract-
property-override limitation (dossier 14 §4.2, Q7). Closes on the spike result; owned by
[../01-foundations/00-dependencies-and-tooling.md](../01-foundations/00-dependencies-and-tooling.md).

### Q11 — mypy/pyright native `msgspec.Struct` support on the pinned versions
Both mypy (`2.3.1`) and pyright (`1.1.411`) are expected to understand `msgspec.Struct` natively with
**no `[tool.mypy] plugins` entry** (contrast attrs' bundled plugin). **Recommended: confirm on a
migrated sample module;** add a plugins entry only if msgspec requires one (dossier 14 Q4). Closes on
the sample check; owned by [../01-foundations/00-dependencies-and-tooling.md](../01-foundations/00-dependencies-and-tooling.md).

### Q12 — msgspec under `python -OO`
`pytest-all-features` runs under `-OO` (asserts stripped). **Recommended: confirm msgspec Structs
behave under `-OO`** (dossier 14 Q2). Fold into the V6 verification run. Owned by
[../10-testing/00-test-strategy.md](../10-testing/00-test-strategy.md).

### Q13 — Shape of abstract model bases
Do abstract bases (`PartialChannel`, `GuildChannel`, `User`, `Guild`, `PartialCommand`,
`InviteWithMetadata`, the `files.Resource` mixin family) become frozen Structs, Protocols, or stay
ABCs? This decides whether `mock_class_namespace` (85 uses) survives (dossier 11 Q1; dossier 03 §5).
**Recommended: concrete leaves become frozen Structs; keep abstract bases as non-Struct ABCs where the
multiple-inheritance/mixin hazard bites (the `Resource` family, `AuditLog(Sequence)`), Struct bases
elsewhere** — decide per hierarchy. Closes per hierarchy in
[../06-model-modules/00-README.md](../06-model-modules/00-README.md) and
[../10-testing/01-fixtures-and-helpers.md](../10-testing/01-fixtures-and-helpers.md).

### Q14 — Shared `evolve`/stub-entity test helper
There is no stub-entity layer today; removing `app=` and freezing touches every literal constructor
(~250–350 mutation sites). **Recommended: add a suite-wide `evolve(model, **overrides)` (wrapping
`msgspec.structs.replace`) and `make_*` stub builders now** to absorb the churn (dossier 11 §10.1).
Closes on sign-off; owned by [../10-testing/01-fixtures-and-helpers.md](../10-testing/01-fixtures-and-helpers.md).

### Q15 — Delete vs port helper-method delegation tests
~390 `.app.rest`/`.app.cache` assertion lines test delegation that vanishes with the helpers.
**Recommended: delete the delegation tests (rely on `impl/test_rest.py`/`test_cache.py`) and port only
non-trivial argument-shaping** (e.g. `Message.respond`'s `reply=True→self`) into whatever free
function replaces it (dossier 11 §10.2). Closes on sign-off; owned by
[../10-testing/00-test-strategy.md](../10-testing/00-test-strategy.md).

### Q16 — Optional `2.6` deprecation pre-warn pass
Only the helper-method removal maps cleanly onto the existing `warn_deprecated` tooling; strict enums
and frozen models are purely behavioural and cannot be softened by a warning window (dossier 12 §6).
**Recommended: optional** — ship a `2.6` that emits `DeprecationWarning` from the still-attrs helpers
pointing at `rest.*`, if the maintainer wants the pre-warn. Closes on sign-off; owned by
[../11-rollout/03-breaking-changes-and-changelog.md](../11-rollout/03-breaking-changes-and-changelog.md).

### Q17 — Examples migrate in lockstep (hard CI gate, not optional)
`examples/*` use `.respond`/helper methods and are mypy-gated in CI (dossier 12 §8; dossier 10 §8.1).
They **must** be rewritten to `rest.*` in the same change that removes the helpers or CI fails. Not a
decision — a delivery gate to track. Owned by
[../11-rollout/03-breaking-changes-and-changelog.md](../11-rollout/03-breaking-changes-and-changelog.md).

## 8. Sign-off

The migration's foundations work (base structs, hooks, undefined, JSON, dependencies) should not be
considered ready to build until **V2, V5–V9** are run (V1 is RESOLVED — dossier 16, with only the
3.10-floor re-run remaining; V3 and V4 are WITHDRAWN as moot under the custom-enum decision; the
custom-enum feasibility is already RESOLVED — dossier 15, with the non-gating B-CE benchmark
remaining) and **F-D10, SD1–SD4** are chosen. The remaining `Q` items gate
their individual work-streams. Record each resolution in the owning plan file and in
[../00-overview/05-decisions-log.md](../00-overview/05-decisions-log.md), then flip the item's status
in §3 above.
