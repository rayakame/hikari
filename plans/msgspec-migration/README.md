# hikari: attrs + orjson to msgspec migration plan

This directory is the complete planning set for migrating hikari's data layer from `attrs` (models)
and `orjson` (JSON) to a single library, **msgspec**. It is a design and execution plan, not an
implementation. The work is large and high-risk; the plan is split into many focused files so each
concern can be reviewed and executed independently.

The migration retires two dependencies (`attrs~=26.1`, `orjson~=3.11`) and makes three deliberate,
interlocking semantic changes:

- **(a) No `app` on deserialized entities — or on events.** msgspec decodes JSON straight into
  structs and cannot attach a runtime `RESTAware` client per object, so the `app` field and the
  app-delegating helper methods that use `self.app.rest.*` / `self.app.cache.*` (`Channel.send`,
  `Message.respond`, `Guild.get_member`, …) are removed; callers use `rest.*` / `cache.*` directly,
  and gateway handlers close over the bot object. By maintainer decision events go app-less too
  (D10-events, resolved). Of the 173 app-delegating helper sites (163 `self.app.*` + 10
  `self.user.app.*` on `guilds.Member`), **~156 are removed** (~114 wire-entity + 42 event); the
  ~17 interaction helpers are retained pending the D10-interactions decision.
- **(b) Strict enums.** The ~150 `SomeEnum | int` / `| str` tolerance unions are removed and fields
  are typed as the bare enum — the typing sweep delivered upstream by PR hikari-py/hikari#2770.
  hikari's fast custom `Enum`/`Flag` are **kept** (not ported to stdlib) and decoded through the same
  global `dec_hook` used for `Snowflake`/`Color`; forward-compatibility with unknown Discord values is
  preserved because #2770 makes an unknown value mint a value-preserving `is_unknown` pseudo-member
  instance, not by union widening.
- **(c) Frozen structs.** Models become immutable, so the cache drops its copy/deepcopy machinery
  (the whole of `internal/attrs_extensions.py` plus ~104 cache copy sites).

The recommended end-state is **declarative-first, transform-residual, app-less**: decode Discord
bytes directly into frozen app-less structs where the shape allows (with a single `dec_hook` for
custom scalars and tagged unions for polymorphism), and keep a slimmed `entity_factory` only for the
~13 hard-case categories msgspec cannot express declaratively. It is reached incrementally — see the
phase plan in [11-rollout](11-rollout/00-phasing-and-sequencing.md).

## How to read this plan

1. **Start here:** [00-overview/00-executive-summary.md](00-overview/00-executive-summary.md) — why,
   measured scope, the three constraints, the end-state.
2. [00-overview/02-target-architecture.md](00-overview/02-target-architecture.md) — the data-flow
   model and the declarative-vs-residual classification every module recipe uses.
3. [00-overview/05-decisions-log.md](00-overview/05-decisions-log.md) — the canonical decisions
   (D1–D13) plus the OPEN items; cited by every later file.
4. [12-appendices/01-open-questions-and-verifications.md](12-appendices/01-open-questions-and-verifications.md)
   — the pre-implementation gate: every maintainer decision (FLAGGED) and empirical probe (VERIFY)
   that must be resolved before coding.
5. Then read the cluster for whatever you are executing (map below).

## Section map

| # | Directory | Covers |
|---|---|---|
| 00 | [00-overview/](00-overview/) | Executive summary, goals/non-goals, target architecture, risk map, glossary, decisions log. |
| 01 | [01-foundations/](01-foundations/) | Dependencies & tooling, base-struct conventions, custom scalar hooks, UNDEFINED vs UNSET, the `data_binding` JSON rewrite, decode boundary & Decoders. |
| 02 | [02-enums/](02-enums/) | Enum strategy & forward-compat, flags (kept custom `Flag`), int/str enums (kept custom, #2770 pseudo-members), the strict-enum field inventory, the kept `internal/enums.py`. |
| 03 | [03-app-removal-and-helpers/](03-app-removal-and-helpers/) | App-removal strategy, field-removal mechanics, the per-module helper-removal inventory (subfolder), new rest methods / free functions, and the FLAGGED events/interactions decision. |
| 04 | [04-frozen-and-cache/](04-frozen-and-cache/) | Freezing + copy-engine deletion, the cache `*Data`/`RefCell` mutation redesign, app-rehydration and views. |
| 05 | [05-entity-factory/](05-entity-factory/) | Factory architecture & decode strategy, polymorphism via tagged unions, the hard-case transforms, the `serialize_*` methods. |
| 06 | [06-model-modules/](06-model-modules/) | Per-module migration recipes for every wire model module (scalars, users, emojis, channels, guilds, messages, embeds, components, applications, commands, interactions, invites, webhooks, presences, stickers, polls, scheduled events, auto-mod, audit logs, and the tail modules). |
| 07 | [07-events/](07-events/) | Event classes and the event pipeline: app-less frozen events, the name-keyed Decoder registry + `msgspec.Raw` envelope + thin hydration layer (D12), and `shard` kept on the event object (D13). |
| 08 | [08-builders/](08-builders/) | The `special_endpoints` outbound builders (serialize-only). |
| 09 | [09-rest-and-gateway/](09-rest-and-gateway/) | REST client usage shift after helper removal; the gateway/shard/interaction-server JSON boundary. |
| 10 | [10-testing/](10-testing/) | Test strategy for frozen structs, fixtures/helpers, and the copy/enum test rewrites. |
| 11 | [11-rollout/](11-rollout/) | Phasing & sequencing, PR breakdown, performance benchmarking, breaking-change catalog & changelog, rollback. |
| 12 | [12-appendices/](12-appendices/) | Research-dossier index (traceability) and the consolidated open-questions/verification gate. |

## Open items requiring a maintainer decision

Two classes of item are deliberately left open rather than decided here; both are consolidated in the
[open-questions gate](12-appendices/01-open-questions-and-verifications.md) and summarized in the
[decisions log](00-overview/05-decisions-log.md):

- **FLAGGED (D10-interactions) — interactions only.** The events half of D10 is **RESOLVED** by the
  maintainer: events go app-less (44 `app` fields + 31 entity-delegating properties + the
  `ExceptionEvent.app` proxy + all 42 event helpers removed; zero internal readers of `event.app`).
  What remains flagged is whether **interactions** also lose `app` and their helpers (the
  `interaction.create_initial_response` response sugar, ~17 helpers). The plan **recommends keeping
  them** — removing them would be the single largest ecosystem break — but this is a maintainer call
  with real ergonomic/latency stakes for interaction responses.
- **Event-pipeline gate items (new).** The open-questions gate also carries **T-CN** — restructure
  the `event.chunk_nonce` post-construction mutation (`event_manager.py:420`, the only event mutation
  in hikari) by computing the nonce before construction, a blocker for freezing events — and **SD5**
  — whether `GUILD_CREATE` keeps its lazy sub-entity decode via `msgspec.Raw`/lazy accessors or
  accepts eager decode (recommendation: preserve laziness), plus the per-event fixture smoke test
  (Decoder construction is lazy, so a bad field type only surfaces on first decode).
- **VERIFY — empirical probes** that gate locked defaults. Two are already RESOLVED empirically
  (msgspec 0.21.1): keeping the custom enums via `dec_hook` under PR #2770 (dossier 15), and
  `frozen=True, eq=False` inheriting `snowflakes.Unique`'s id-only dunders — which also established
  that the base needs a combined `ABCMeta`+`StructMeta` metaclass and that `kw_only=True` must be
  repeated per struct level (dossier 16; only a 3.10-floor re-run remains). Still open: the legality
  of a `T | UndefinedType` union with a default-on-absent (vs adopting `msgspec.UNSET`); native
  RFC3339 datetime parity with `ciso8601`; msgspec wheel coverage across 3.10–3.14.

## How this plan was produced

The plan is grounded in a 14-part initial reconnaissance of the current codebase plus follow-up
empirical verifications (dossiers 15 and 16) and the event-pipeline investigation (dossiers 17–20,
with 18 and 20 empirical) — 20 research dossiers in total, indexed in
[12-appendices/00-research-dossier-index.md](12-appendices/00-research-dossier-index.md).
Several dossiers were verified empirically against `msgspec 0.21.1`. Every count and `file:line`
anchor in the plan traces back to that research; downstream files reuse the verified figures rather
than re-estimating. When a claim about msgspec behavior matters, the plan prefers the empirically
verified dossiers (enums, custom types, msgspec capabilities) over general assumptions.

## Status

All planning files are drafted. The plan is ready for maintainer review of the OPEN items above;
resolving the remaining FLAGGED decision (D10-interactions), the event-pipeline gate items (T-CN,
SD5), and the VERIFY probes is the gate to starting Phase P0 (see
[11-rollout/00-phasing-and-sequencing.md](11-rollout/00-phasing-and-sequencing.md)).
