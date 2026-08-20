# Executive Summary

Migration of hikari from `attrs` + `orjson` to `msgspec`. This document opens the planning set:
it states why the migration is being undertaken, its measured scope, the three non-negotiable
constraints that shape every downstream decision, and the recommended end-state. Every other plan
file elaborates one slice of what is summarized here.

## 1. Objective

Replace hikari's two data-layer dependencies — `attrs~=26.1` (`pyproject.toml:36`) for model classes
and `orjson~=3.11` (`pyproject.toml:70`) for JSON — with a single library, `msgspec`, that unifies
schema definition, JSON decode, and JSON encode behind one typed C-accelerated core. The migration
is undertaken to:

- **Collapse the deserialization pipeline.** Today Discord bytes are decoded to a plain `dict` by
  `orjson.loads` and then hand-walked into `attrs` models by a 4857-line `entity_factory`
  (`hikari/impl/entity_factory.py`). msgspec decodes bytes straight into typed structs in one pass,
  and typed decode into a struct is frequently faster than decode into an untyped `dict`
  (dossier 13 §16).
- **Delete the bespoke copy engine.** `hikari/internal/attrs_extensions.py` (256 lines) exists solely
  because `attrs` models are mutable and the cache must defensively copy them. Immutable structs make
  that engine and ~104 cache copy sites dead code (dossier 07 §0, §10.1).
- **Adopt a real immutable model layer** with forward-compatible enums. hikari's fast custom enum
  metaclasses (`hikari/internal/enums.py`) are **kept** — they are much faster at runtime than stdlib
  and are decoded through the same global `dec_hook` msgspec already uses for `Snowflake`/`Color`,
  given upstream PR hikari-py/hikari#2770, which makes an unknown value mint a value-preserving member
  instance rather than crash (dossier 15).

The migration is also the occasion for three deliberate, maintainer-mandated semantic changes
(Section 3) that could not be made incrementally without a rewrite of this size.

## 2. Scope (measured, not estimated)

All counts below are the dossier-verified figures; each downstream plan file reuses them. Do not
substitute rounded numbers.

| Dimension | Count | Source |
|---|---:|---|
| `@attrs.define` classes across `hikari/**` | **273** | dossier 03 §0 |
| `@attrs.define` classes in the 26 model modules | **175** | dossier 03 §0 |
| Wire data models constructed by `entity_factory` | **157** decorated (**158** incl. the decorator-less `GuildNewsThread`) | dossier 03 §4.1; [06-model-modules/00-README.md](../06-model-modules/00-README.md) |
| Concrete enum/flag types on the custom metaclass | **80** (55 int, 12 str, 13 flag) | dossier 02 Part B |
| `SomeEnum \| int` / `\| str` tolerance unions | **~150** (67 on entity fields) | dossier 02 Part C |
| Deserializer methods (`deserialize_*` 91 + `_deserialize_*` 61) | **152** | dossier 05 §2 |
| `serialize_*` methods (outbound) | **7** | dossier 05 §2 |
| Dispatch tables in `EntityFactoryImpl.__init__` | **19** | dossier 05 §2 |
| `impl/event_factory.py` (77 `deserialize_*` methods) after the D12 Decoder-registry migration | **1216 lines → est. 400–550** | dossier 17 §4–§5 |
| Entity helper methods referencing `self.app` | **163** (126 `rest.*` + 37 `cache.*`) | dossier 04 §0 |
| `app: traits.RESTAware` model field declarations | **~25** base-class decls, inherited by 64 entities | dossier 04 §0, dossier 05 §7 |
| `app=self._app` injection sites (entity factory) | **64** | dossier 05 §7 |
| `@attrs_extensions.with_copy` decorations | **246** | dossier 07 §2.1 |
| Cache `copy.copy` / copier call sites | **104** (internal 85 + impl 19) | dossier 07 §0, §3 |
| `SKIP_DEEP_COPY` field-metadata markers | **149** (almost all `app`) | dossier 07 §2.3 |
| `UndefinedOr[...]` annotations | **~1714** across 33 modules | CONVENTIONS §5 |
| Errors (`auto_exc`) classes — excluded from the migration | **22** | dossier 03 §4.3 |

Files that are attrs classes but are **not** wire models and follow separate lanes: `errors.py`
(22 exceptions, stay exceptions), `files.py` (6 readers), `impl/special_endpoints.py` (40 outbound
builders), `internal/cache.py` (11 cache cells), `impl/config.py` (5 config), `internal/routes.py`
(3 route objects), `impl/entity_factory.py` (6 `_*Fields` helpers) — dossier 03 §4.3.

## 3. The three constraints (non-negotiable)

Every design decision in this plan is downstream of three maintainer-mandated constraints. They are
restated verbatim from the conventions contract and each is expanded in a dedicated cluster.

- **(a) No `app` injection during deserialization.** msgspec decodes JSON straight into structs and
  cannot attach a runtime `RESTAware` client per object. The `app` field is removed from all
  JSON-decoded entities — and, by maintainer decision, from all **events** (D10-events) and all
  **interactions** (D10-interactions) as well (both are hand-constructed, so for them this is a
  policy choice, not a technical forcing). The app-delegating helper methods that use
  `self.app.rest.*` / `self.app.cache.*` (e.g. `Channel.send`, `Message.respond`,
  `Guild.get_member`, `interaction.create_initial_response`) are removed; callers use `rest.*` /
  `cache.*` directly, and gateway handlers close over the bot object. Accounting (final): **all
  ~173** app-delegating helper call sites are removed (~114 wire-entity + 42 event + the 17
  interaction sites); the 8 interaction builder factories survive, reimplemented as app-free sync
  constructors, so the REST-bot return-a-builder flow is unchanged.
  See [03-app-removal-and-helpers](../03-app-removal-and-helpers/00-strategy.md).
- **(b) Strict enums.** The pervasive `SomeEnum | int` / `SomeEnum | str` tolerance unions are
  removed; fields are typed as the bare enum — exactly the typing sweep in PR hikari-py/hikari#2770.
  Forward-compatibility with unknown Discord values is preserved by **keeping** hikari's custom
  `Enum`/`Flag`: under #2770 an unknown value becomes a value-preserving `is_unknown` pseudo-member
  instance, decoded through the global `dec_hook`, never by union widening. See [02-enums](../02-enums/00-strategy-and-forward-compat.md).
- **(c) Frozen structs.** Models become immutable, so the cache drops its copy/deepcopy machinery.
  See [04-frozen-and-cache](../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md).

The constraints are interlocking: (a) removes the only field the cache refused to deep-copy
(`app`, marked `SKIP_DEEP_COPY` 149 times); (c) makes copies unnecessary; together they let the
entire copy subsystem be deleted (dossier 04 §7.5, dossier 07 §10.1).

## 4. Recommended end-state

The target architecture (locked as decision D1, detailed in
[02-target-architecture.md](02-target-architecture.md)) is **declarative-first, transform-residual,
app-less**:

1. **Declarative decode wherever the shape allows.** `msgspec.json.decode(bytes, type=SomeStruct)`
   decodes Discord JSON directly into frozen, app-less public structs, using a single global
   `dec_hook` for custom scalars (`Snowflake`, `Color`, `Permissions`, `UnicodeEmoji`),
   `msgspec.field(name=…)` for JSON-key mapping, and **tagged unions** for polymorphic dispatch
   (channels, interactions, components, commands, auto-mod, scheduled events).

2. **A residual, slimmed `entity_factory`** remains only for the ~13 hard-case categories that cannot
   be expressed declaratively (dossier 05 §6): array→keyed-`Mapping` re-keying, flattened grandchild
   fields, sibling-dependent value typing, parent→child context injection (`guild_id`/`user_id`
   threading), the lazy `GatewayGuildDefinition`, computed fields, and classmethod-constructed types
   (`Embed.from_received_embed`). This residual layer transforms wire structs (or `msgspec.Raw`) into
   public structs and **never injects `app`**.

3. **A single JSON boundary.** `hikari/internal/data_binding.py:107-123` drops `orjson`; untyped
   decode becomes `msgspec.json.decode(b)`, typed decode uses module-level
   `msgspec.json.Decoder(SomeType)` instances. The hand-built request-body builders
   (`JSONObjectBuilder`, etc.) are retained in the first pass, feeding their dict output to
   `msgspec.json.encode` (dossier 01; dossier 13 §11).

msgspec becomes a **hard/core dependency** (no stdlib fallback for typed decode); `orjson` is
removed, and `ciso8601` is a removal candidate pending datetime edge-case verification
(dossier 13 §13; [decisions D6/D7](05-decisions-log.md)).

## 5. Sequencing

The recommended end-state is reached incrementally, not in one leap. The first mechanical passes can
keep the hand-written factory constructing msgspec structs, achieving constraints (a) + (b) + (c)
before the declarative-decode optimization lands. This yields a **two-layer** design as the realistic
shape (dossier 05 §9): fast msgspec "wire" structs mirroring Discord JSON, and a shrunken transform
factory producing the public frozen structs. A pure single-layer
`decode(bytes, type=PublicStruct)` is **not achievable** for the hard-case categories. The full
phase plan lives in [11-rollout/00-phasing-and-sequencing.md](../11-rollout/00-phasing-and-sequencing.md).

## 6. Principal risks (headline)

Ranked and mitigated in full in [03-risk-and-danger-map.md](03-risk-and-danger-map.md):

1. **Public API breakage.** Removing all ~173 app-delegating helper sites (~114 wire-entity +
   42 event + 17 interaction) plus the `app` surface on entities, events, and interactions breaks
   every documented example that does `await message.respond(...)` / `channel.send(...)` /
   `guild.get_member(...)` — and, the single largest ecosystem break, every command framework's
   `ctx.respond`, which wraps `interaction.create_initial_response`. The 8 interaction builder
   factories survive as app-free sync constructors (the REST-bot return-a-builder flow is
   unchanged). This is the largest user-visible break of the migration.
2. **Forward-compat regression on unknown enum values.** A naive strict-enum migration makes hikari
   crash on every new Discord enum value. Mitigated by keeping the custom enums and adopting #2770's
   value-preserving pseudo-members, decoded through the global `dec_hook` (empirically verified on
   msgspec 0.21.1, dossier 15).
3. **Cache correctness under frozen + no-app.** `RefCell`/`GuildRecord` stay mutable; `MessageData`
   in-place edits and `has_been_deleted` need a new home. See dossier 07 §10.2.
4. **Wire-format edge cases.** int-subclass encode gap (msgspec cannot encode `Snowflake` natively —
   the docs are wrong, dossier 13 §11), epoch-number datetimes, per-field `timedelta` units.

## 7. Decisions and open items

Thirteen numbered decisions (D1–D13) are recorded in [05-decisions-log.md](05-decisions-log.md) —
**all thirteen are resolved**; no FLAGGED maintainer chooser remains. The last to close was D10, on
both halves: by maintainer decision **events are app-less** (D10-events: 45 `app` fields, 31
entity-delegating properties, the `ExceptionEvent.app` proxy, and all 42 event helpers removed; zero
internal readers of `event.app`) and **interactions are app-less** too (D10-interactions: the 9
interaction action helpers are deleted — each a pure delegation to an existing `rest.*`/`cache.*`
method — while the 8 builder factories are kept, reimplemented as app-free sync constructors, so the
REST-bot return-a-builder flow is unchanged; see
[03-app-removal-and-helpers/04-events-and-interactions-app-decision.md](../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md)).
The two newest decisions lock the event pipeline: under D12 the gateway envelope is decoded once with
the `d` payload captured as `msgspec.Raw` and dispatched through a name-keyed `Decoder` registry
topped by a thin hydration layer (`shard`/`old_*` attachment, guild-vs-DM class splits,
sibling-context threading), and under D13 `shard` stays on the event object (maintainer-confirmed; see
[../07-events/00-events-migration.md](../07-events/00-events-migration.md)). The open items that
remain are narrower — empirical probes, sub-decisions, and one blocking task:

- **VERIFY:** a small set of empirical probes gate the locked defaults. Two are already **RESOLVED**
  empirically (msgspec 0.21.1): `frozen=True, eq=False` inherits `snowflakes.Unique`'s id-only dunders
  under frozen — msgspec does not null the inherited `__hash__` — which also established that the base
  needs a combined `ABCMeta`+`StructMeta` metaclass and that `kw_only=True` must be repeated per struct
  level (dossier 16; only a CPython 3.10-floor re-run remains), and keeping the custom enums via
  `dec_hook` under PR #2770 (dossier 15). Still open (V2, V5–V9): the `T | UndefinedType` union
  legality, native RFC3339 datetime parity with `ciso8601` before dropping the dep, msgspec wheel
  coverage across 3.10–3.14, and the encode-leak / enum-dict-key / soft-skip-prepass probes.
  Consolidated in
  [12-appendices/01-open-questions-and-verifications.md](../12-appendices/01-open-questions-and-verifications.md).
- **Sub-decisions and the blocking task:** five maintainer sub-choices under already-locked
  decisions (SD1–SD5: the `*Data` cache layer, the pseudo-member cache cap, the decode boundary,
  builder-conversion deferral, and `GUILD_CREATE` laziness) plus the blocking task **T-CN** — fix
  the `event.chunk_nonce` post-construction mutation before any event freezes — tracked in the same
  gate file.

## 8. Reading order

Start with [01-goals-and-non-goals.md](01-goals-and-non-goals.md) for what is in and out of scope,
then [02-target-architecture.md](02-target-architecture.md) for the data-flow model,
[03-risk-and-danger-map.md](03-risk-and-danger-map.md) for the ranked hazards,
[04-glossary.md](04-glossary.md) for terminology, and [05-decisions-log.md](05-decisions-log.md) as
the canonical decision reference cited by every later file.
