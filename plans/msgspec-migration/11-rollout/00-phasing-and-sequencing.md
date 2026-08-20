# Phasing and Sequencing

Purpose: the ordered, de-risked phase plan for the `attrs`+`orjson` → `msgspec` migration. Each
phase is a self-contained, independently-reviewable body of work with explicit entry/exit gates,
a stated dependency on prior phases, and a mapping to the three maintainer constraints. The intent
is that constraints (a) app-less, (b) strict enums, and (c) frozen structs are all satisfied by the
end of Phase 2, with the later phases delivering the caller/doc migration, the cache cleanup, and
two optional optimization passes.

Constraint legend (from [`../../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md)):
- **(a)** No `app` injection during deserialization — app-less decoded entities, helpers removed.
- **(b)** Strict enums — bare-enum fields, forward-compat via the enum design, not union widening.
- **(c)** Frozen structs — immutable models, cache drops its copy machinery.

---

## 1. Objective

Sequence the migration so that:
1. The largest, riskiest change (mechanical `attrs` → frozen `msgspec.Struct`) is preceded by two
   independent, individually-shippable prerequisites (adopting the strict custom enums of PR
   hikari-py/hikari#2770; the `msgspec.json` decode seam) that can be landed, tested, and even
   released on the `2.x` line.
2. The single hard-break release (`3.0.0`) is reached in as few coupled steps as possible, and every
   step before it is revertible in isolation.
3. The optional performance work (declarative typed decode, tagged unions, builder conversion) is
   cleanly separable and can be deferred past `3.0.0` without blocking the constraint deliverables.
   One exception: the event-pipeline registry (D12) carries public signature breaks
   (`consume_raw_event`, `ShardPayloadEvent.payload`, inbound `loads=`/`dumps=`, the `EventFactory`
   ABC) that must ride the `3.0.0` major even though per-route decode conversion can trail into P5.

Version vehicle: current `2.5.1.dev0` (`hikari/_about.py:41`) → **`3.0.0` major bump**. See
[`03-breaking-changes-and-changelog.md`](03-breaking-changes-and-changelog.md) and dossier 12 §2.

---

## 2. Phase overview

| Phase | Name | Delivers constraint | Breaking? | Depends on | Ship vehicle |
|---|---|---|---|---|---|
| **P0** | Adopt #2770 strict custom enums + enum hook routing | (b) foundation | Behavioral (#2770) | — | `2.6` (optional) or `3.0.0` |
| **P1** | `msgspec.json` decode seam in `data_binding` | D6/D7 seam | No (internal) | — | `2.6` (optional) or `3.0.0` |
| **P2** | `attrs` → frozen, app-less `msgspec.Struct` — entities **and events** (residual hand-factories / hydration layer retained; event registry D12) | **(a)+(b)+(c)** | **Yes** | P0, P1 | `3.0.0` |
| **P3** | Remove helper methods, provide replacements, migrate callers/docs/examples | (a) completion | **Yes** | P2 | `3.0.0` |
| **P4** | Slim `attrs_extensions` (wholesale delete rides post-3.0 B2), drop Struct-side `with_copy`, collapse cache copies | (c) payoff | Mostly internal | P2 | `3.0.0` |
| **P5** | *(optional)* Declarative typed decode + tagged unions (REST/interaction-server bytes-in; residual event routes → typed Decoders) | perf | Internal | P2 | `3.x` |
| **P6** | *(optional)* Builder conversion to Structs + `UNSET` | perf/ergonomics | Public builder API | — | `3.x`+ |

P0 and P1 are mutually independent and both independent of everything else — they can be developed
in parallel and merged in either order. P2 requires **both** (the strict custom enums must return an
instance on every value so the shared `dec_hook` can decode them, D2 / PR hikari-py/hikari#2770;
msgspec must be a core dependency and the JSON seam in place, D6). P3 and P4 both require P2 but are
independent of each other. P5 and P6 are optional and gated behind `3.0.0` shipping.

One additional pre-work item rides ahead of P2: **T-CN**, the chunk-nonce restructure.
`event_manager.py:420` mutates a constructed event (`event.chunk_nonce = nonce`; fields at
`guild_events.py:180/244`) — the only event mutation in hikari (dossier 19). Computing the nonce
*before* event construction is a tiny, behavior-preserving PR, mergeable to `master` at any time,
and a hard gate for freezing events in P2.

### 2.1 Dependency graph

```
        P0 (adopt #2770 enums) ─┐
                                ├──▶ P2 (attrs→frozen app-less Structs) ──┬──▶ P3 (helpers/callers/docs)
        P1 (json seam) ─────────┘                                        └──▶ P4 (copy removal)
                                                                          │
                                                     (optional) P5 (declarative decode) ◀── P2
                                                     (optional) P6 (builder conversion)  ── independent
```

P2 is the fulcrum: it is the release-blocking, hard-break workstream. P3 and P4 land in the **same
`3.0.0` train** as P2 (P3 because deleting the `app` field forces deleting the helpers that
dereference it; P4 because frozen structs make the copy machinery dead code), but they are distinct
review units.

### 2.2 The P2/P3 coupling (read this before planning the release train)

Constraint (a) is "app-less decoded entities **and** the removal of the app-delegating helper
methods" (dossier 04 §0; [`../03-app-removal-and-helpers/00-strategy.md`](../03-app-removal-and-helpers/00-strategy.md)).
Plan-wide accounting: 173 app-delegating sites total (163 `self.app.*` + 10 `self.user.app.*`);
**all ~173 are removed** (~114 wire-entity + 42 event + 17 interaction sites); of the 17, the 9
action helpers are deleted outright, while the other 8 are the builder-factory sites — those
methods survive as app-free sync constructors (D10-interactions, RESOLVED).
The field/helper halves cannot be separated in a compiling tree:

- The moment P2 removes the `app` field from a model (24–25 base-class declarations inherited by 64
  concrete deserialized entities, dossier 05 §7), every method whose body reads `self.app.rest.*`
  (126 sites) / `self.app.cache.*` (37 sites) is dead code — it references an attribute that no
  longer exists.
- Therefore **P2 mechanically deletes the dead helper bodies together with the field**. What P3 owns
  is the *replacement surface and migration*, which is separable design work:
  - new `rest.*` methods / free functions for the no-1:1-equivalent cluster
    (`Member.fetch_roles`, `PartialUser.send`, webhook token resolution,
    `PermissibleGuildChannel.edit_overwrite`, `Guild.get_my_member`, guild-scoped cache getters,
    message mention getters — dossier 04 §7.2), specified in
    [`../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md`](../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md);
  - migrating hikari's own internal call sites to `rest.*`/`cache.*`;
  - rewriting every example (`examples/` is mypy-gated in CI, `pipelines/mypy.nox.py:43`) and the
    docs quick-starts, and authoring the first-ever `3.0` migration guide;
  - executing the **D10** outcome — both halves RESOLVED (maintainer decisions,
    [`../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md`](../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md)):
    events are app-less (the removal lands with the event PRs in P2), and interactions are
    app-less too (the field/dead-helper removal + app-free factory reimplementation land with the
    S13 interactions PR in P2; P3 owns the caller migration onto `rest.*` and the migration-guide
    replacement table).

Practical implication: **P2 must not merge to a green tree without the P3 example/doc fixes**,
because CI type-checks `examples/`. Plan P2+P3 as one merge train (a long-lived integration branch,
per-module PRs merged into it, examples/docs fixed before the train merges to `master`). See
[`01-pr-breakdown.md`](01-pr-breakdown.md) §4 for the branch model.

---

## 3. Phase detail

### P0 — Adopt #2770 strict custom enums + enum hook routing

**Objective.** **Keep** hikari's fast custom `hikari/internal/enums.py` `Enum`/`Flag` (they are much
faster at runtime than stdlib, which matters under high event/request volume) and adopt/rebase
upstream PR hikari-py/hikari#2770, which makes the custom `Enum.__call__` mint a synthetic
`is_unknown` member **instance** on unrecognised values (the `Flag` already did this,
`enums.py:381-412`), adds an `is_unknown` property to both, raises `TypeError` on wrong-type input
(via the `__objtype__` guard), and types all model fields + REST params with **only** the enum/flag
type (dropping the `| int`/`| str` unions). Do **not** port to stdlib `enum`, `enum.IntFlag`, or a
`_missing_` mixin. Preserve forward-compatibility and the rich `Flag` API (they are already custom
and are kept).

**Scope (from [`../02-enums/00-strategy-and-forward-compat.md`](../02-enums/00-strategy-and-forward-compat.md)):**
- Adopt #2770's `_EnumMeta.__call__` (pseudo-member-on-miss with the bounded `_temp_members_` cache,
  `_MAX_CACHED_MEMBERS`, `enums.py:39`) and `is_unknown` on `Enum`/`Flag`; the `Flag` set-API
  (`.all/.any/.none/.split/…`, `enums.py:683-829`) and the `enums.pyi` stub are **kept unchanged**
  ([`../02-enums/01-flags-migration.md`](../02-enums/01-flags-migration.md),
  [`../02-enums/02-int-and-str-enums-migration.md`](../02-enums/02-int-and-str-enums-migration.md),
  [`../02-enums/04-enums-module-and-machinery.md`](../02-enums/04-enums-module-and-machinery.md)).
- Add the enum/flag routing to the single global `dec_hook`/`enc_hook`
  (`if issubclass(t, (enums.Enum, enums.Flag)): return t(obj)` on decode; `return o.value` on encode)
  — this lands with the foundations hooks (the P2 foundation PR S1) so msgspec, which treats the
  non-`enum.Enum` custom types as custom types, routes them to the hook
  ([`../01-foundations/02-custom-scalar-types-and-hooks.md`](../01-foundations/02-custom-scalar-types-and-hooks.md)).
- The strict field/param typing sweep (drop the `| int`/`| str` unions) is delivered by #2770 itself
  ([`../02-enums/03-strict-enum-field-inventory.md`](../02-enums/03-strict-enum-field-inventory.md)).

**Constraint served:** (b) foundation. The strict field/param retyping is exactly what #2770 lands
upstream; the migration rebases onto it rather than re-deriving it.

**Independence.** No msgspec dependency and no struct change beyond adopting #2770. Fully testable
against the current attrs models. Can be released on `2.6` (the semantic change — unknown values
become `is_unknown` pseudo-members instead of bare ints, and wrong-type casts now raise `TypeError`
— is behavioral and carries the #2770 `breaking` fragment; more likely it lands *in* `3.0.0`).

**Entry gate:** none. **Exit gate:** `nox -s pytest slotscheck mypy ruff` green; enum tolerance
tests (unknown int/str → `is_unknown` pseudo-member, `int(x)==x`, `isinstance(x, TheEnum)` True,
wrong type → `TypeError`) pass
([`../10-testing/02-cache-copy-and-enum-tests.md`](../10-testing/02-cache-copy-and-enum-tests.md));
`slotscheck` enum-exclusion regex still valid (`pyproject.toml:269`).

### P1 — `msgspec.json` decode seam in `data_binding`

**Objective.** Add `msgspec` as a core dependency and replace `orjson` in
`hikari/internal/data_binding.py:100-123` with `msgspec.json` for untyped decode and encode, keeping
the hand-built `JSONObjectBuilder`/`StringMapBuilder`/`URLEncodedFormBuilder` (D6/D7).

**Scope (from [`../01-foundations/04-json-data-binding.md`](../01-foundations/04-json-data-binding.md)
and [`../01-foundations/00-dependencies-and-tooling.md`](../01-foundations/00-dependencies-and-tooling.md)):**
- `default_json_loads` → `msgspec.json.decode` (drop-in, returns dict/list).
- `default_json_dumps` → `msgspec.json.encode`, with the global `enc_hook` registered to cover the
  int-subclass encode gap (msgspec cannot encode `Snowflake`/`Color` int subclasses natively —
  empirically verified, D4) and to match orjson's `OPT_NON_STR_KEYS` int-key→str behavior.
- Add `msgspec` to core `dependencies` (`pyproject.toml:36` region), remove `orjson` from the
  `speedups` extra (`pyproject.toml:70`), keep `ciso8601` pending the datetime decision, regenerate
  `uv.lock` (dossier 14 §2, §10.2).

**Constraint served:** none directly; it is the enabling seam for P2. Delivered value: a single fast
JSON engine with no stdlib fallback branch.

**Independence.** Untyped decode is a drop-in; typed `msgspec.json.Decoder(Type)` instances are not
introduced until P2. Can release on `2.6` (msgspec becomes a hard dep — a `2.6` that adds a core dep
is a minor bump per EffVer).

**Entry gate:** none. **Exit gate:** `nox -s pytest pytest-all-features` green on all 15 CI cells
(3 OS × 3.10–3.14) — the **msgspec 3.14 wheel availability check is the top packaging risk**
(dossier 14 §11.1); `OPT_NON_STR_KEYS` parity test passes; no raw `Snowflake`/`Color` leaks through
`msgspec.json.encode` (audit per D6).

### P2 — attrs → frozen, app-less msgspec Structs

**Objective.** Convert every wire/entity `attrs` class — and the event classes (D12/D13) — to a
frozen, kw-only, app-less `msgspec.Struct` (D3), retyping enum fields to bare strict enums (b), and
keep the hand-written entity factory constructing these Structs field-by-field (the *residual*
factory of D1 — the declarative decode optimization is deferred to P5; the **event** pipeline, by
contrast, gets its name-keyed Decoder registry inside this train because the design is locked and
empirically verified, dossiers 17–19). **This single phase delivers (a)+(b)+(c) for all decoded
data entities and events.**

**Scope:**
- Base struct conventions: `frozen=True, kw_only=True, eq=False`, keep `snowflakes.Unique` for
  id-only identity — VERIFY V1 is **RESOLVED** (dossier 16): `eq=False` does **not** null the
  inherited hash, so a frozen Struct over `Unique` keeps `Unique`'s id-only `__eq__`/`__hash__`,
  stays immutable, and is hashable; no hand-written dunder re-attachment is needed. Two mechanical
  requirements apply (D3):
  - **R1 (combined metaclass):** `StructMeta` is **not** an `abc.ABCMeta` subclass, so a bare
    `class X(Unique, msgspec.Struct, ...)` raises `TypeError: metaclass conflict`. Define
    `class _StructABCMeta(abc.ABCMeta, type(msgspec.Struct)): ...` once and set it on the shared
    `UniqueStruct` base; subclasses inherit it. Keep the real `Unique` unchanged — its
    `__slots__=()` composes fine.
  - **R2 (per-level kw_only):** `frozen` inherits via `__struct_config__`, but `kw_only` does **not**
    (it is not stored in `StructConfig`); repeat `frozen=True, kw_only=True` on every struct level
    that adds fields.
  ([`../01-foundations/01-base-struct-conventions.md`](../01-foundations/01-base-struct-conventions.md)).
- Global `dec_hook`/`enc_hook` and module-level `Decoder`/`Encoder`
  ([`../01-foundations/02-custom-scalar-types-and-hooks.md`](../01-foundations/02-custom-scalar-types-and-hooks.md)).
- `UNDEFINED` default handling on decoded tri-state fields, per the D5 VERIFY gate
  ([`../01-foundations/03-undefined-and-unset.md`](../01-foundations/03-undefined-and-unset.md)).
- Per-module conversion in dependency order ([`../06-model-modules/00-README.md`](../06-model-modules/00-README.md)),
  each paired with its `deserialize_*` factory methods
  ([`../05-entity-factory/00-architecture-and-decode-strategy.md`](../05-entity-factory/00-architecture-and-decode-strategy.md)).
- Remove the `app` field (24–25 declarations / 64 concrete entities) and delete the ~114 dead
  wire-entity helper bodies (their replacement is P3; the 42 event helpers go with the event work
  item below). Interactions are app-less too (D10-interactions, RESOLVED): the S13 interactions PR
  removes `PartialInteraction.app` (`base_interactions.py:275`) and the `ExecutableWebhook`
  subclassing, deletes the 9 dead action-helper bodies, and reimplements the 8 `build_*` factories
  as app-free sync constructors in the same PR — the REST-bot return-a-builder flow must survive
  the PR unchanged
  ([`../03-app-removal-and-helpers/02-helper-method-inventory/06-interactions.md`](../03-app-removal-and-helpers/02-helper-method-inventory/06-interactions.md)).
- **Events** (D10-events + D12 + D13; [`../07-events/00-events-migration.md`](../07-events/00-events-migration.md),
  appendix [`../12-appendices/04-event-pipeline-feasibility.md`](../12-appendices/04-event-pipeline-feasibility.md)), in order:
  1. *Pre-work (T-CN):* restructure the `event.chunk_nonce = nonce` mutation
     (`event_manager.py:420`) so the nonce is computed before event construction — the only event
     mutation in hikari and a hard gate for freezing events (dossier 19).
  2. Remove the event `app` surface: the abstract `Event.app` (`base_events.py:83-86`), 45 own
     `app` fields, 31 entity-delegating `app` properties, the `ExceptionEvent.app` proxy
     (`base_events.py:207-211`), the 42 event helper methods (24 rest + 18 cache call sites), and
     all 50 `app=self._app` factory injections. Zero internal readers of `event.app` exist
     (dossier 19) — the break is purely public; the blessed handler pattern becomes "close over
     the bot object".
  3. Convert events to frozen `msgspec.Struct`s that **keep `shard`** per D13 (dossier 20):
     hand-constructed events take a plain required `shard: GatewayShard` field; direct-decode flat
     events use `_shard` storage (defaulted, wire-name poisoned via `msgspec.field(name=...)`) plus
     a non-optional `shard` property, injected pre-dispatch via `force_setattr`. Lifetime events
     become field-less markers; `ExceptionEvent` stays non-msgspec.
  4. Introduce the **name-keyed Decoder registry + `msgspec.Raw` envelope** (D12, dossiers 17–19):
     the shard captures `d` as `Raw`, `consume_raw_event` hands it to a
     `dict[str, msgspec.json.Decoder]`, and typed decode runs only when the consumer's
     `is_enabled` gate passes. The 77-method `EventFactory` ABC reshapes into the registry plus a
     **residual hydration layer** (shard/`old_*` attachment, guild-vs-DM class dispatch, sibling
     `guild_id` threading, GUILD_CREATE laziness, synthetic events); `impl/event_factory.py`
     shrinks from 1216 lines to an estimated 400–550 (45/77 methods become one-or-two-liners,
     ~73% end trivial). The registry's public breaks (`consume_raw_event` payload type,
     `ShardPayloadEvent.payload`, inbound `loads=`/`dumps=`, the ABC reshape) must ride the
     `3.0.0` major ([`03-breaking-changes-and-changelog.md`](03-breaking-changes-and-changelog.md)
     §3.10); routes not yet on a typed Decoder at release keep an untyped decode-to-dict residual
     path, and finishing route conversion is P5 material. Design detail:
     [`../09-rest-and-gateway/01-gateway-shard-and-interaction-server.md`](../09-rest-and-gateway/01-gateway-shard-and-interaction-server.md) §3.2.
- `errors.py` (22 `auto_exc` classes) is **excluded** — stays exceptions, not Structs (D3, dossier 12 §5.6).
- Builders (`Embed`, 40 `special_endpoints` builders) are **excluded** — stay mutable (D11, dossier 12 §5.4).

**Constraint served:** (a) structurally (app-less + dead helpers deleted), (b) (bare-enum fields),
(c) (frozen). This is where the "P2 alone delivers (a)+(b)+(c)" claim holds: the decoded structs
are immutable, strict-enum-typed, and carry no `app`.

**Dependency.** Requires P0 (strict custom enums via #2770 + the enum hook routing) and P1 (msgspec
core dep + JSON seam). Within P2,
the entity factory still calls the JSON layer to get a dict, then builds Structs via
`msgspec.convert(dict, type=Struct)` or hand construction — the incremental bridge of D6, avoiding
the bytes-in interface churn until P5.

**Entry gate:** P0 and P1 merged; **T-CN merged before any event freezes**. **Exit gate (the
`3.0.0` readiness bar, jointly with P3/P4):** all model + factory tests pass; frozen-immutability
tests (`model.attr = x` raises) pass; golden round-trip corpus (real recorded Discord payloads)
decodes equal to the pre-migration tree
([`04-rollback-and-risk-mitigation.md`](04-rollback-and-risk-mitigation.md) §4); the registry
fixture smoke test passes (one recorded payload decoded per registry entry — Decoder construction
is lazy, so annotation errors only surface on first decode, dossier 18;
[`../10-testing/00-test-strategy.md`](../10-testing/00-test-strategy.md)); 5 `.pyi` stubs
regenerated (`pipelines/mypy.nox.py:46-69`); `verify-types` green.

### P3 — Helper removal, replacements, caller/doc/example migration

**Objective.** Complete constraint (a) by providing the replacement surface for the deleted helpers
and migrating all consumers.

**Scope (from dossier 04 §7 and [`../03-app-removal-and-helpers/`](../03-app-removal-and-helpers/)):**
1. New `rest.*` methods / free functions for the no-1:1 cluster (dossier 04 §7.2).
2. Migrate hikari's own internal callers.
3. Rewrite `examples/` (mypy-gated) and docs quick-starts; author the `3.0` migration guide
   (dossier 12 §8). Replace/drop the attrs docs inventory (`mkdocs.yml:137`).
4. Execute the resolved **D10-interactions** removal on the caller side: migrate callers of the 9
   deleted interaction action helpers onto `rest.*` (every replacement is an existing method; the
   table lives in [`03-breaking-changes-and-changelog.md`](03-breaking-changes-and-changelog.md)
   §3.11), and lead the migration guide + downstream pre-announcement with it — this is the
   headline ecosystem break (every command framework's `ctx.respond` wraps
   `create_initial_response`). The 8 builder factories are already app-free after S13, so REST-bot
   listeners returning builders need no change. Both halves of D10 are RESOLVED; the events half is
   handled in P2, and P3 carries its doc side: rewrite the gateway-handler pattern docs to "close
   over `bot`" (exactly one shipped example reads `event.app` today —
   `examples/voice_message/voice_message.py:90`).

**Constraint served:** (a) completion. **Dependency:** P2. **Exit gate:** examples mypy-green; docs
build green (`docs` CI job); migration guide wired into `mkdocs.yml` nav; public-API snapshot test
(new, recommended) green.

### P4 — Copy removal and cache simplification

**Objective.** Realize the constraint (c) payoff: frozen structs are safe to share by reference.

**Scope (from [`../04-frozen-and-cache/`](../04-frozen-and-cache/)):**
- Slim `hikari/internal/attrs_extensions.py` (delete the dead deep-copy half and the cache-only
  shallow path; retain `with_copy` for the ~25 deferred non-Struct consumers — `special_endpoints`
  ~15, `config.py` 5, `routes.py` 3, `errors.py` 2); drop the ~221 Struct-converted `@with_copy`
  decorations (of 246); trim `test_attr_extensions.py` to the retained surface; retype `ModelT`
  (D8, PR C1; wholesale deletion + the remaining test ride the post-3.0 B2 step).
- Collapse the ~104 cache `copy.copy` sites to identity returns; delete `Cell` dead code; fix the
  `set_role` no-copy asymmetry (`impl/cache.py:1538`).
- `*Data`/`RefCell`/`GuildRecord` decisions, `has_been_deleted` → `RefCell.deleted`, message edits via
  `msgspec.structs.replace` ([`../04-frozen-and-cache/01-cache-data-layer-and-mutation.md`](../04-frozen-and-cache/01-cache-data-layer-and-mutation.md)).
- `build_entity(app)` loses its `app` param; the 8 `_build_*` app-injectors and `CacheImpl._app` simplify
  ([`../04-frozen-and-cache/02-cache-app-and-views.md`](../04-frozen-and-cache/02-cache-app-and-views.md)).

**Constraint served:** (c) payoff. **Dependency:** P2 (structs must be frozen first). Independent of P3.
**Exit gate:** cache identity tests assert `cache.get_*(id) is cache.get_*(id)` (no-copy);
`test_attr_extensions.py` trimmed to the retained `with_copy` surface (deleted only in post-3.0 B2);
`slotscheck` green.

### P5 — Declarative typed decode + tagged unions (optional, post-3.0)

**Objective.** The D1 end-state optimization: `msgspec.json.decode(bytes, type=Struct)` decoding
Discord JSON directly into public Structs wherever the shape allows, with tagged unions for
polymorphism, pushing the decode boundary to bytes-in.

**Scope:** [`../05-entity-factory/01-polymorphism-and-tagged-unions.md`](../05-entity-factory/01-polymorphism-and-tagged-unions.md)
and [`../05-entity-factory/02-hard-cases-and-transforms.md`](../05-entity-factory/02-hard-cases-and-transforms.md);
bytes-in interface change touching `rest.py`/`interaction_server.py`
([`../09-rest-and-gateway/01-gateway-shard-and-interaction-server.md`](../09-rest-and-gateway/01-gateway-shard-and-interaction-server.md)).
The gateway side is already bytes-in after P2 (the D12 `Raw` envelope); what P5 adds there is
moving any gateway `t` names still on the untyped decode-to-dict residual path onto their typed
registry Decoders. The ~13 hard-case categories (dossier 05 §6) keep the residual transform layer.

**Constraint served:** none new (all constraints already met at P2); pure performance/architecture.
**Dependency:** P2. **Optional** — `3.0.0` ships correct and app-less without it. Land per-union so
each polymorphic family (channels, interactions, components, …) is independently revertible, and
reconcile soft-skip-vs-raise semantics per family (dossier 05 §6.2, §9).

### P6 — Builder conversion (optional, deferred)

**Objective.** Optionally convert the 40 `special_endpoints` builder classes to frozen Structs with
`enc_hook` + `UNSET` omit-on-encode (D11).

**Scope:** [`../08-builders/00-special-endpoints-builders.md`](../08-builders/00-special-endpoints-builders.md).
**Constraint served:** none; ergonomics/consistency. **Dependency:** none structural; orthogonal.
**Recommendation:** defer past `3.0.0` — it touches the public builder API and is a large orthogonal
change with no constraint payoff.

---

## 4. Step-by-step sequencing checklist

1. Land **P0** (adopt #2770 strict custom enums + enum hook routing), **P1** (JSON seam), and the
   tiny **T-CN** chunk-nonce restructure (`event_manager.py:420`) in parallel; each is
   independently mergeable to `master` on the `2.x` line or held for `3.0.0`.
2. Verify P0 exit gate (enum tolerance + slotscheck) and P1 exit gate (msgspec wheels on all 15 CI
   cells, `OPT_NON_STR_KEYS` parity) before opening the P2 integration branch.
3. Open a long-lived `3.0.0` integration branch. Land the P2 infra PR (base struct conventions,
   dec_hook/enc_hook, module Decoders, UNDEFINED handling) first.
4. Convert model modules in dependency order (P2), each PR paired with its factory deserializers,
   merging into the integration branch. Keep the residual factory constructing structs by hand.
5. Convert the events (P2 events work item): remove the event `app` surface, freeze events with
   `shard` per D13, then land the D12 `Raw` envelope + name-keyed Decoder registry once the entity
   structs it decodes exist (event PRs EV1–EV3, [`01-pr-breakdown.md`](01-pr-breakdown.md) §2).
6. In lockstep with the model conversions, land **P3** replacements (new rest methods / free
   functions), migrate internal callers — including callers of the 9 deleted interaction action
   helpers onto `rest.*` — and rewrite examples and docs.
7. Land **P4** (attrs_extensions slimming, copy collapse, cache `*Data` decision) once the structs
   are frozen; the wholesale module deletion rides the post-3.0 B2 step.
8. Regenerate all 5 `.pyi` stubs and run the full `linting` job (`generate-stubs` drift, `mypy`,
   `verify-types`, `ruff`, `slotscheck`, `audit`) on the integration branch; add the towncrier
   fragments ([`03-breaking-changes-and-changelog.md`](03-breaking-changes-and-changelog.md)).
9. Merge the integration branch to `master`, bump to `3.0.0`, release.
10. **Post-3.0:** land **P5** per-union declarative decode (+ residual event-route conversion) and,
    if desired, **P6** builder conversion.

---

## 5. Affected files and symbols (phase-to-anchor map)

| Phase | Primary files / anchors | Sibling plan |
|---|---|---|
| P0 | `hikari/internal/enums.py` (#2770 pseudo-member `__call__` + `is_unknown`, kept), `enums.pyi` (kept); #2770 strict `| int`/`| str` field/param typing sweep across the 80 enum/flag types / 22 modules | `../02-enums/*` |
| P1 | `hikari/internal/data_binding.py:100-123`; `pyproject.toml:36,70`; `uv.lock:1174-1273` | `../01-foundations/00,04` |
| P2 | 58 model files under `hikari/`; `hikari/impl/entity_factory.py` (91 `deserialize_*`, 19 dispatch tables); `hikari/events/*.py` (20 modules, 92 concrete events; 45 `app` fields + 31 delegating properties + 42 helpers removed); `impl/event_factory.py` (1216 lines, 77 `deserialize_*` → registry + residual hydration, est. 400–550); `impl/event_manager.py:420` (T-CN); `impl/shard.py:844-895` + `api/event_manager.py:168` (D12 `Raw` envelope); `hikari/errors.py` (excluded) | `../01-foundations/01-03`, `../05-entity-factory/*`, `../06-model-modules/*`, `../07-events/*`, `../09-rest-and-gateway/01` |
| P3 | helper replacement surface (all ~173 app-delegating sites removed plan-wide; P3 owns the wire-entity replacements and the interaction action-helper caller migration onto `rest.*`); `examples/`; `docs/`; `mkdocs.yml:137` | `../03-app-removal-and-helpers/*` |
| P4 | `hikari/internal/attrs_extensions.py` (slim; wholesale delete post-3.0 B2); `hikari/internal/cache.py` (~104 copy sites); `impl/cache.py:1538` | `../04-frozen-and-cache/*` |
| P5 | `impl/entity_factory.py`, `impl/rest.py:1012,1062`, `impl/interaction_server.py:442`; residual event routes → typed registry Decoders | `../05-entity-factory/01,02`, `../09-rest-and-gateway/01` |
| P6 | `hikari/impl/special_endpoints.py` (40 builders) | `../08-builders/00` |

---

## 6. Risks / gotchas

- **P2/P3 coupling (see §2.2).** Do not treat helper removal as a later, separable phase in the
  release calendar — the field removal forces it. The separable work is the *replacement + docs*, and
  CI's example type-check makes them a merge-blocker for P2.
- **Ordering P0 before P2 is mandatory,** not a preference: the shared `dec_hook` returns `t(obj)` for
  a custom-enum field, and msgspec rejects the result unless it is an **instance** of `t`. Before #2770
  the custom `Enum.__call__` returns the raw `int`/`str` on an unknown value, so any unknown Discord
  value fails decode with `ValidationError: Expected 'X', got 'int'`. #2770's instance-returning
  `__call__` is the prerequisite; attempting P2 without P0 fails at decode on unknown values.
- **P1's msgspec-as-core-dep is irreversible in the same sense as attrs was** — there is no stdlib
  fallback for typed decode (dossier 14 §6.3). The 3.14 wheel check gates the whole migration.
- **Releasing P0/P1 on `2.6` vs folding into `3.0.0`.** Folding into `3.0.0` is simpler (one release,
  one migration guide) but forgoes the optional `2.6` deprecation pre-warning window for the helper
  removal (dossier 12 §6). See [`03-breaking-changes-and-changelog.md`](03-breaking-changes-and-changelog.md) §5.
- **P5 soft-skip semantics.** Where the current factory soft-skips unknown polymorphic types
  (components, some audit entries) rather than raising, naive tagged unions will raise — a behavior
  regression unless a `Raw` peek-then-dispatch prepass is retained (D2, dossier 05 §6.2).
- **T-CN gates the event freeze.** `event_manager.py:420` mutates a constructed event
  (`event.chunk_nonce = nonce`) — the only event mutation in hikari (dossier 19). Freezing events
  without the restructure breaks GUILD_CREATE member chunking at runtime.
- **Decoder construction is lazy** (dossier 18): a typo'd/undecodable field annotation in a decoded
  event struct fails on the *first decode* of a matching payload, not at import or registry build.
  The per-event-name fixture smoke test
  ([`../10-testing/00-test-strategy.md`](../10-testing/00-test-strategy.md)) is the CI gate.
- **Do not defer the D12 public breaks past `3.0.0`.** The registry's signature changes
  (`consume_raw_event` payload type, `ShardPayloadEvent.payload`, inbound `loads=`/`dumps=`, the
  `EventFactory` ABC reshape) must ship with the major bump even if some routes convert to typed
  Decoders later under P5 — otherwise a second major is needed.

---

## 7. Verification

- Per-phase exit gates above are the primary checkable outcomes.
- The end-to-end correctness gate spanning P2–P4 is the **golden round-trip corpus**: record a
  representative set of real REST + gateway payloads on `2.5.x`, snapshot the deserialized entities,
  and assert the `3.0.0` tree produces equal public data (modulo the documented `app`/enum/frozen
  semantics changes). Detailed in [`04-rollback-and-risk-mitigation.md`](04-rollback-and-risk-mitigation.md) §4.
- Performance gates (decode throughput, cache read path, memory) are defined in
  [`02-performance-benchmarking.md`](02-performance-benchmarking.md).

---

## 8. Open questions / decisions

- **Q-P1:** Release P0+P1 on a `2.6` line, or fold both into `3.0.0`? (Affects whether a helper
  deprecation pre-warning is possible.) Cross-link
  [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md) and dossier 12 §6.
- **Q-P2:** Incremental bridge — `msgspec.convert(dict, type=Struct)` (dict-in, localized) for P2,
  deferring bytes-in to P5? Recommended yes (D6). Confirm the `convert` cost is acceptable via
  [`02-performance-benchmarking.md`](02-performance-benchmarking.md).
- **SD5 (GUILD_CREATE laziness):** preserve the two-layer laziness (lazy sub-decodes via
  per-section Decoders / `Raw` fields on the guild-definition struct) vs accept eager decode of the
  largest gateway payload. Recommended: preserve. See
  [`../07-events/00-events-migration.md`](../07-events/00-events-migration.md).
- **Q-P5/P6:** Are the two optional phases in scope for `3.0.0` or explicitly `3.x`? Recommended
  `3.x` — keep `3.0.0` focused on the constraint deliverables.
