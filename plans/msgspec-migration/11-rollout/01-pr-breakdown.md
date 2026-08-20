# PR Breakdown

Purpose: decompose the phase plan of [`00-phasing-and-sequencing.md`](00-phasing-and-sequencing.md)
into concrete, review-sized pull requests with explicit dependency edges, rough size, the constraint
each serves, and the towncrier fragment type it must carry. This is the executable work-breakdown a
maintainer can turn into GitHub issues/PRs.

Size legend (rough, orientation only): **S** ≤ ~200 LOC diff; **M** ~200–800; **L** ~800–2000;
**XL** > 2000 or spanning many files. These are diff-size estimates, not effort estimates — several
**M** PRs (enum ports, per-module struct conversions) are mechanically repetitive.

Fragment type (dossier 12 §4.1, `pyproject.toml:214-230`): `breaking`, `deprecation`, `feature`,
`optimization`, `bugfix`, `documentation`. Multiple fragments per PR are allowed (`CONTRIBUTING.md:144`).

---

## 1. Objective

Provide a PR-level plan that:
1. Keeps every PR independently reviewable and, where possible, independently revertible.
2. Encodes the hard ordering constraints (P0/P1 before P2; P2 before P3/P4) as PR dependency edges.
3. Names the towncrier fragment each PR adds, so the CHANGELOG assembles correctly at `3.0.0`.

---

## 2. PR catalog

### Phase P0 — Adopt #2770 strict custom enums (branchable on `master`)

| PR | Title | Size | Depends on | Constraint | Fragment |
|---|---|---|---|---|---|
| **E1** | Adopt/rebase upstream PR hikari-py/hikari#2770: **keep** the custom `Enum`/`Flag`; make `_EnumMeta.__call__` mint an `is_unknown` pseudo-member **instance** on a miss (not the raw value), add `is_unknown` to both, raise `TypeError` on wrong-type input (`__objtype__` guard); keep `enums.pyi` and the `Flag` set-API (`enums.py:683-829`) | M | — | (b) | `breaking`, `feature` (the #2770 fragments) |
| **E2** | Adopt #2770's strict field/param typing sweep: drop the ~150 `\| int`/`\| str` unions on model fields + REST params (delivered upstream by #2770) | L | E1 | (b) | (part of the #2770 `breaking`) |

E1/E2 **keep** the custom enums — no stdlib / `enum.IntFlag` / `_missing_`-mixin port. The enum/flag
routing added to the single global `dec_hook`/`enc_hook`
(`if issubclass(t, (enums.Enum, enums.Flag)): return t(obj)` / `return o.value`) lands with the
foundations hooks (S1). See [`../02-enums/`](../02-enums/).

### Phase P1 — JSON decode seam (branchable on `master`, no break)

| PR | Title | Size | Depends on | Constraint | Fragment |
|---|---|---|---|---|---|
| **J1** | Add `msgspec` to core `dependencies`; remove `orjson` from `speedups`; regenerate `uv.lock`; keep `ciso8601` | S | — | D6/D7 | `optimization` |
| **J2** | Rewrite `data_binding.py:100-123` untyped decode/encode → `msgspec.json`; register global `enc_hook`; `OPT_NON_STR_KEYS` parity | M | J1 | D6/D7 | `optimization` |

J1/J2 must pass on all 15 CI cells (3 OS × 3.10–3.14) — the msgspec 3.14 wheel check gates them
(dossier 14 §11.1). See [`../01-foundations/00-dependencies-and-tooling.md`](../01-foundations/00-dependencies-and-tooling.md)
and [`../01-foundations/04-json-data-binding.md`](../01-foundations/04-json-data-binding.md).

### Pre-work — event freeze gate (branchable on `master`)

| PR | Title | Size | Depends on | Constraint | Fragment |
|---|---|---|---|---|---|
| **EV0** | T-CN: restructure the `on_guild_create` member-chunk nonce — compute it *before* constructing `GuildAvailableEvent`/`GuildJoinEvent` and pass `chunk_nonce=` to the constructor, replacing the post-construction `event.chunk_nonce = nonce` mutation (`event_manager.py:420`; fields `guild_events.py:180/244`). The only event mutation in hikari and a hard gate for freezing events (dossier 19) | S | — | (c) gate | none |

### Phase P2 — attrs → frozen app-less Structs (into the `3.0.0` integration branch)

Foundation PRs (land first):

| PR | Title | Size | Depends on | Constraint | Fragment |
|---|---|---|---|---|---|
| **S0** | Base struct conventions doc-as-code: apply the confirmed base-struct recipe (`UniqueStruct` + `_StructABCMeta` metaclass, per-level `frozen/kw_only`); re-run the V1 probe on the 3.10 floor; retype `ModelT` | M | E2, J2 | (c) | none |
| **S1** | Global `dec_hook`/`enc_hook` + module-level `Decoder`/`Encoder`; scalar hooks (Snowflake/Color/Permissions/UnicodeEmoji/datetime/timedelta) **plus the custom `Enum`/`Flag` routing** (`t(obj)` decode / `o.value` encode) | M | S0, E1 | D4 | none |
| **S2** | `UNDEFINED` on decoded tri-state fields: the D5 VERIFY experiment + shim (or `msgspec.UNSET` fallback) | M | S0 | D5 | `breaking` |

Per-module struct conversion PRs (each: attrs → frozen msgspec Struct, drop `app` field, delete dead
helper bodies, retype enum fields to bare enum, update the paired `deserialize_*` factory methods).
Ordered by dependency (scalars → users → … ), following
[`../06-model-modules/00-README.md`](../06-model-modules/00-README.md):

| PR | Title | Size | Depends on | Fragment |
|---|---|---|---|---|
| **S3** | scalars: snowflakes, colors, permissions, locales | M | S1 | `breaking` |
| **S4** | users | M | S3 | `breaking` |
| **S5** | emojis + files.Resource hazard (`Emoji`/`Attachment` × `WebResource` MI) | M | S3 | `breaking` |
| **S6** | channels (15 concrete + polymorphic dispatch retained) | L | S4,S5 | `breaking` |
| **S7** | guilds / members / roles (incl. lazy `GatewayGuildDefinition`) | XL | S6 | `breaking` |
| **S8** | messages (partial + full; heaviest deserializers) | XL | S6,S7 | `breaking` |
| **S9** | embeds (`from_received_embed` classmethod path) | M | S8 | `breaking` |
| **S10** | components (polymorphic, recursive, soft-skip) | L | S8 | `breaking` |
| **S11** | applications + oauth | M | S4 | `breaking` |
| **S12** | commands | M | S11 | `breaking` |
| **S13** | interactions (polymorphic; app-less per the resolved D10-interactions: remove `PartialInteraction.app` (`base_interactions.py:275`) + the `ExecutableWebhook` subclassing, delete the 9 dead action-helper bodies, reimplement the 8 `build_*` factories as app-free sync constructors in the same PR) | L | S8,S12 | `breaking` |
| **S14** | invites | M | S6,S11 | `breaking` |
| **S15** | webhooks | M | S6 | `breaking` |
| **S16** | presences (epoch-number datetimes, party tuple) | M | S4 | `breaking` |
| **S17** | stickers (tag split vs raw) | S | S3 | `breaking` |
| **S18** | polls | S | S8 | `breaking` |
| **S19** | scheduled_events (polymorphic) | M | S7 | `breaking` |
| **S20** | auto_mod (polymorphic ×2) | M | S7 | `breaking` |
| **S21** | audit_logs (change-key converter table) | L | S7,S15 | `breaking` |
| **S22** | monetization, stage_instances, voices, templates, sessions | M | S7 | `breaking` |
| **S23** | entity_factory residual cleanup: 19 dispatch tables, `_app` removal, shared field intermediates | L | S3–S22 | `breaking` |

The 24–25 `app`-field declarations (64 concrete entities, dossier 05 §7) and the ~114 dead
wire-entity helper bodies are removed *within* the module PR that owns each class — interactions
included: S13 owns the interaction `app` field, its 9 dead action helpers, and the app-free factory
reimplementation ([`../03-app-removal-and-helpers/02-helper-method-inventory/06-interactions.md`](../03-app-removal-and-helpers/02-helper-method-inventory/06-interactions.md)). See
[`../05-entity-factory/00-architecture-and-decode-strategy.md`](../05-entity-factory/00-architecture-and-decode-strategy.md).

Event PRs (D10-events + D12 + D13; [`../07-events/00-events-migration.md`](../07-events/00-events-migration.md),
appendix [`../12-appendices/04-event-pipeline-feasibility.md`](../12-appendices/04-event-pipeline-feasibility.md)):

| PR | Title | Size | Depends on | Fragment |
|---|---|---|---|---|
| **EV1** | Remove the event `app` surface: abstract `Event.app` (`base_events.py:83-86`), 45 own `app` fields, 31 entity-delegating `app` properties, `ExceptionEvent.app` (`base_events.py:207-211`), 42 event helper methods (24 rest + 18 cache call sites), 50 `app=self._app` factory injections; fix the one example (`examples/voice_message/voice_message.py:90`) and the handler-pattern docs ("close over `bot`") | L | — | `breaking` |
| **EV2** | Convert `hikari/events/*.py` (92 concrete events) to frozen `msgspec.Struct`s keeping `shard` per D13: plain required `shard:` field on hand-constructed events; `_shard` storage (defaulted, wire-name poisoned via `msgspec.field(name=...)`) + non-optional `shard` property on direct-decode flat events; lifetime events become field-less markers; `ExceptionEvent` stays non-msgspec | XL | S0, S1, EV0, EV1 | `breaking` |
| **EV3** | D12 event pipeline: `msgspec.Raw` envelope in the shard (`shard.py:844-895`; envelope parse at `:200`), name-keyed `dict[str, msgspec.json.Decoder]` registry behind `consume_raw_event` + `is_enabled` gating, residual hydration layer (shard/`old_*` attachment, guild-vs-DM dispatch, sibling `guild_id` threading, GUILD_CREATE laziness per SD5, synthetic events); reshape the 77-method `EventFactory` ABC; retype `consume_raw_event` payload (`api/event_manager.py:168`), `ShardPayloadEvent.payload` (`shard_events.py:92`), inbound `loads=`/`dumps=` (`shard.py:561-562`, `gateway_bot.py:331-332`); ship the per-name registry fixture smoke test in the same PR | XL | EV2, S3–S22 | `breaking` |

### Phase P3 — helper removal completion, callers, docs (into the `3.0.0` integration branch)

| PR | Title | Size | Depends on | Constraint | Fragment |
|---|---|---|---|---|---|
| **H1** | New `rest.*` methods / free functions for the no-1:1 cluster (`fetch_member_roles`, `send_dm`, webhook token resolution, `edit_overwrite` target_type, `get_my_member`, guild-scoped cache getters, mention getters) | L | S23 | (a) | `feature`, `breaking` |
| **H2** | Migrate hikari's own internal call sites to `rest.*`/`cache.*`; normalize the two `shard_id` styles | M | H1 | (a) | none |
| **H3** | Rewrite `examples/` (mypy-gated) + docs quick-starts; author `3.0` migration guide; wire into `mkdocs.yml` nav; drop attrs inventory (`mkdocs.yml:137`) | L | H1 | (a) | `documentation` |
| **H4** | App-less interaction caller migration (D10-interactions RESOLVED; the code-side removal rides S13): rewrite callers of the 9 deleted action helpers to `rest.*` (the replacement table in [`03-breaking-changes-and-changelog.md`](03-breaking-changes-and-changelog.md) §3.11), lead the migration guide + downstream pre-announcement with it, and document the unchanged REST-bot return-a-builder flow; the events half of D10 lands via EV1–EV3 | M | S13 | (a)/D10 | `breaking`, `documentation` |

See [`../03-app-removal-and-helpers/`](../03-app-removal-and-helpers/) and [`../07-events/`](../07-events/).

### Phase P4 — copy removal + cache (into the `3.0.0` integration branch)

| PR | Title | Size | Depends on | Constraint | Fragment |
|---|---|---|---|---|---|
| **C1** | Slim `internal/attrs_extensions.py` (delete dead deep-copy half + cache shallow path; **keep** `with_copy` for the ~25 deferred non-Struct consumers) + trim its test to the retained surface; drop the ~221 Struct-converted `@with_copy` (retain ~25: `special_endpoints` ~15, `config` 5, `routes` 3, `errors` 2); delete `SKIP_DEEP_COPY` (151 sites) | L | S23 | (c) | `breaking`, `optimization` |
| **C2** | Collapse ~104 cache `copy.copy` sites to identity; delete `Cell` dead code; fix `set_role` asymmetry (`impl/cache.py:1538`) | M | C1 | (c) | `optimization` |
| **C3** | `*Data`/`RefCell` decision: `has_been_deleted`→`RefCell.deleted`; message edits via `msgspec.structs.replace`; `build_entity(app)` param removed; `CacheImpl._app` collapse | L | C2 | (c)/(a) | `optimization` |

See [`../04-frozen-and-cache/`](../04-frozen-and-cache/).

### Cross-cutting PRs (span the integration branch)

| PR | Title | Size | Depends on | Fragment |
|---|---|---|---|---|
| **X1** | Regenerate all 5 `.pyi` stubs (`hikari/__init__.pyi`, `api`, `events`, `impl`, `interactions`); hand-fix `undefined.pyi`, `enums.pyi` | M | S23,EV3,H4,C3 | none |
| **X2** | Assemble/curate the towncrier `breaking`/`optimization`/`documentation` fragments; `towncrier --draft` review | S | all | (the fragments) |
| **X3** | New public-API snapshot test (`hikari.__all__`/`dir(hikari)` drift guard — no such test exists today, dossier 12 §9) | M | S23 | none |
| **X4** | Re-tighten pyright relaxations (`pyproject.toml:180,184,185`) now that attrs is gone; sweep stale `# type: ignore` (`warn_unused_ignores`) | M | S23 | none |

### Optional post-3.0 PRs

| PR | Title | Size | Depends on | Fragment |
|---|---|---|---|---|
| **D1** | Wire Structs + tagged unions for one polymorphic family (channels), bytes-in decode boundary spike | L | S23 (post-3.0) | `optimization` |
| **D2..** | Remaining tagged-union families (interactions, components, scheduled_events, auto_mod, webhooks); reconcile soft-skip vs raise per family | L each | D1 | `optimization` |
| **B1** | Builder conversion: `special_endpoints` → frozen Structs + `UNSET` omit-on-encode | XL | — | `breaking`, `feature` |
| **B2** | Retire the last `attrs_extensions` consumers: drop `with_copy` from `impl/config.py` (5), `internal/routes.py` (3), `errors.py` (2), and any `special_endpoints` builders not covered by B1 (~15); then **delete `internal/attrs_extensions.py` wholesale** + its remaining test | M | B1 | `optimization` |

---

## 3. Dependency edges (condensed)

```
E1 ─▶ E2 ─┐
          ├─▶ S0 ─▶ S1 ─▶ S3 ─▶ (S4..S22 per module) ─▶ S23 ─┬─▶ H1 ─▶ H2,H3
J1 ─▶ J2 ─┘        └─▶ S2                                    │   H4 (needs S13)
                                                                        ├─▶ C1 ─▶ C2 ─▶ C3
                                                                        ├─▶ X1 (after EV3,H4,C3)
                                                                        ├─▶ X3
                                                                        └─▶ X4
events: EV0 (master, T-CN) ─▶ EV2 ; EV1 ─▶ EV2 ─▶ EV3 (also needs S3..S22)
                            post-3.0:  S23 ─▶ D1 ─▶ D2..    ;    B1 ─▶ B2 (delete attrs_extensions.py wholesale)
```

Critical path (longest chain to `3.0.0` readiness):
`E1 → E2 → S0 → S1 → S3 → S6 → S7 → S8 → S13 → S23 → H1 → H3 → X1`. The event chain
(EV1 → EV2 → EV3) runs in parallel off S0/S1, waits on the per-module S PRs at EV3, and rejoins the
critical path at X1.

---

## 4. Branch/merge model

Because P2+P3+P4 all land together in `3.0.0` and CI type-checks `examples/`, a green `master` is
impossible mid-migration. Recommended model:

1. **P0 (E1–E2), P1 (J1–J2), and EV0 (T-CN)** merge directly to `master` (each keeps the tree
   green; either ship on `2.6` or hold for `3.0.0`).
2. Open a long-lived **`feat/msgspec-3.0`** integration branch off `master`.
3. All S/EV/H/C/X PRs target the integration branch and are reviewed there. The integration branch
   is allowed to be red on the example gate until H3 lands.
4. Regenerate stubs (X1), assemble fragments (X2), run the full `linting` job, then merge the
   integration branch to `master` behind the `3.0.0` bump.
5. **D/B** PRs target `master` after `3.0.0`.

Rationale and per-phase revert strategy: [`04-rollback-and-risk-mitigation.md`](04-rollback-and-risk-mitigation.md) §3.

---

## 5. Affected files and symbols (PR-to-anchor map, selected)

| PR group | Key anchors |
|---|---|
| E1–E2 | `hikari/internal/enums.py` (#2770 `__call__` + `is_unknown`, kept), `enums.pyi` (kept); the #2770 strict `\| int`/`\| str` typing sweep across 80 enum/flag types / 22 modules; `pyproject.toml:269` |
| J1–J2 | `hikari/internal/data_binding.py:100-123`; `pyproject.toml:36,70`; `uv.lock:1174-1273` |
| S0–S2 | `hikari/snowflakes.py`, `hikari/undefined.py`; foundations struct/hook/undefined |
| S3–S22 | 58 model files; `hikari/impl/entity_factory.py` (91 `deserialize_*`) |
| S23 | `impl/entity_factory.py:366-529` (19 dispatch tables), `485-486` (`self._app`) |
| EV0–EV3 | `impl/event_manager.py:420` (T-CN); `hikari/events/*.py` (45 `app` fields, 31 delegating properties, 42 helpers); `base_events.py:83-86/207-211`; `impl/event_factory.py` (1216 lines → est. 400–550); `api/event_factory.py` (77-method ABC); `impl/shard.py:200/561-562/844-895`; `api/event_manager.py:168`; `events/shard_events.py:92`; `gateway_bot.py:331-332` |
| H1–H4 | all ~173 app-delegating sites removed plan-wide (~114 wire-entity replacements via H1–H3; the 42 event helpers go via EV1; the 9 interaction action helpers + app-free factory reimplementation ride S13, with H4 owning the caller migration + docs); `examples/`; `docs/`; `mkdocs.yml:137` |
| C1–C3 | `internal/attrs_extensions.py` (**slimmed** in C1, not deleted), `tests/hikari/internal/test_attr_extensions.py`; `internal/cache.py`; `impl/cache.py:1538` |
| X1 | `pipelines/mypy.nox.py:46-69`; the 5 committed `.pyi` files |
| B1–B2 (post-3.0) | `impl/special_endpoints.py` (builders); B2 drops the final ~25 `@with_copy` (`impl/config.py`, `internal/routes.py`, `errors.py`, residual builders) and **deletes `internal/attrs_extensions.py` wholesale** + its remaining test |

---

## 6. Risks / gotchas

- **S7/S8/S13 are the XL risk PRs** (guilds, messages, interactions). Each carries lazy decode
  (`GatewayGuildDefinition`), tri-state `UNDEFINED`, polymorphism, and re-keying. Budget extra review;
  do not bundle unrelated modules into them.
- **S13 must reimplement the 8 interaction builder factories app-free in the same PR** that drops
  the interaction `app` field — their old bodies call `self.app.rest.interaction_*_builder(...)`
  (pure sync constructors, `impl/rest.py:4676-4679`), so deferring the reimplementation leaves
  `RESTBot` listeners without a way to build responses. The return-a-builder flow must survive the
  PR unchanged; the recipe is
  [`../03-app-removal-and-helpers/02-helper-method-inventory/06-interactions.md`](../03-app-removal-and-helpers/02-helper-method-inventory/06-interactions.md).
- **EV0 must merge before EV2** — freezing events with the `chunk_nonce` mutation still present
  breaks GUILD_CREATE member chunking at runtime (`event_manager.py:420`, dossier 19).
- **EV3 must carry its registry fixture smoke test** — Decoder construction is lazy (dossier 18),
  so a bad field annotation in a decoded event struct fails only on the first decode of a live
  payload, not at import or registry build.
- **reaction_add splits on `"member"`, not `"guild_id"`** (`event_factory.py:789`) — the one
  guild-vs-DM discriminator that differs from the rest of the nine split methods; a mechanical
  sweep porting the splits will silently misroute it (dossier 17 §2).
- **X1 (stub regen) must be the last content PR** before the `3.0.0` merge — any later surface change
  re-dirties the stubs and fails the `generate-stubs` drift gate (`ci.yml:130-137`).
- **Fragment PR numbers.** Each `changes/{PR}.{type}.md` is named by its PR number; on an integration
  branch the final PR number differs from the sub-PR numbers. Reconcile fragment filenames before the
  integration-branch merge (X2).

---

## 7. Verification

- Every PR runs the standard `nox` default sessions (`pipelines/nox.py:31`): `pytest`, `ruff`,
  `slotscheck`, `mypy`, `verify-types`, plus `codespell`.
- Struct-conversion PRs (S3–S22) additionally run the golden round-trip corpus for their module
  ([`04-rollback-and-risk-mitigation.md`](04-rollback-and-risk-mitigation.md) §4).
- EV3 additionally runs the registry fixture smoke test (one recorded payload decoded per gateway
  `t` name) and the disabled-consumer check (no full decode of `d` when `is_enabled` is false) —
  see [`../10-testing/00-test-strategy.md`](../10-testing/00-test-strategy.md).
- The integration branch runs the full `linting` job + docs build before merge.
- X3's public-API snapshot test guards against accidental symbol drops across the whole train.

---

## 8. Open questions / decisions

- **Granularity of S7/S8:** split guilds (S7) into guild-core vs `GatewayGuildDefinition`, and
  messages (S8) into partial vs full? Recommended yes if diffs exceed ~1500 LOC.
- **Granularity of EV2/EV3:** split EV2 across 2–3 PRs by event module group if the diff exceeds
  ~2000 LOC (keep the D13 pattern choice — required `shard:` field vs `_shard` storage+property —
  consistent within each PR); EV3 may land the envelope + registry seam first and convert the 45
  one-or-two-liner routes in follow-ups, leaving heavy residuals (GUILD_CREATE family,
  presence_update, thread joins, member_chunk) on the hydration layer by design.
- **Fragment consolidation:** one `breaking` fragment per break cluster (dossier 12 §7) vs one per
  module PR? Recommended: per-cluster at X2, so the CHANGELOG reads as 4–5 clusters, not 20 modules.
  Cross-link [`03-breaking-changes-and-changelog.md`](03-breaking-changes-and-changelog.md).
- **X3 timing:** add the public-API snapshot test *before* the migration (to snapshot the `2.x`
  surface as the baseline) rather than after. Recommended before, on `master`.
