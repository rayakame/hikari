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
- **Adopt a real immutable model layer** with native forward-compatible enums, removing hikari's
  custom enum metaclasses (`hikari/internal/enums.py`) in favour of stdlib `enum`, which msgspec
  understands natively (dossier 02 §0; dossier 13 §10).

The migration is also the occasion for three deliberate, maintainer-mandated semantic changes
(Section 3) that could not be made incrementally without a rewrite of this size.

## 2. Scope (measured, not estimated)

All counts below are the dossier-verified figures; each downstream plan file reuses them. Do not
substitute rounded numbers.

| Dimension | Count | Source |
|---|---:|---|
| `@attrs.define` classes across `hikari/**` | **273** | dossier 03 §0 |
| `@attrs.define` classes in the 26 model modules | **175** | dossier 03 §0 |
| Wire data models constructed by `entity_factory` | **157** | dossier 03 §4.1 |
| Concrete enum/flag types on the custom metaclass | **80** (55 int, 12 str, 13 flag) | dossier 02 Part B |
| `SomeEnum \| int` / `\| str` tolerance unions | **~150** (67 on entity fields) | dossier 02 Part C |
| Deserializer methods (`deserialize_*` 91 + `_deserialize_*` 61) | **152** | dossier 05 §2 |
| `serialize_*` methods (outbound) | **7** | dossier 05 §2 |
| Dispatch tables in `EntityFactoryImpl.__init__` | **19** | dossier 05 §2 |
| Entity helper methods referencing `self.app` | **163** (126 `rest.*` + 37 `cache.*`) | dossier 04 §0 |
| `app: traits.RESTAware` model field declarations | **~25** base-class decls, inherited by 64 entities | dossier 04 §0, dossier 05 §7 |
| `app=self._app` injection sites (entity factory) | **64** | dossier 05 §7 |
| `@attrs_extensions.with_copy` decorations | **246** | dossier 07 §2.1 |
| Cache `copy.copy` / copier call sites | **104** (internal 85 + impl 19) | dossier 07 §0, §3 |
| `SKIP_DEEP_COPY` field-metadata markers | **149** (almost all `app`) | dossier 07 §2.3 |
| `UndefinedOr[...]` annotations | **~1714** across 33 modules | CONVENTIONS §5 |
| Errors (`auto_exc`) classes — excluded from the migration | **22** | dossier 03 §4.3 |

Files that are attrs classes but are **not** wire models and follow separate lanes: `errors.py`
(22 exceptions, stay exceptions), `files.py` (6 readers), `impl/special_endpoints.py` (42 outbound
builders), `internal/cache.py` (11 cache cells), `impl/config.py` (5 config), `internal/routes.py`
(3 route objects), `impl/entity_factory.py` (6 `_*Fields` helpers) — dossier 03 §4.3.

## 3. The three constraints (non-negotiable)

Every design decision in this plan is downstream of three maintainer-mandated constraints. They are
restated verbatim from the conventions contract and each is expanded in a dedicated cluster.

- **(a) No `app` injection during deserialization.** msgspec decodes JSON straight into structs and
  cannot attach a runtime `RESTAware` client per object. The `app` field is removed from all
  JSON-decoded entities, and the 163 helper methods that delegate to `self.app.rest.*` /
  `self.app.cache.*` (e.g. `Channel.send`, `Message.respond`, `Guild.get_member`) are removed;
  callers use `rest.*` / `cache.*` directly. See [03-app-removal-and-helpers](../03-app-removal-and-helpers/00-strategy.md).
- **(b) Strict enums.** The pervasive `SomeEnum | int` / `SomeEnum | str` tolerance unions are
  removed; fields are typed as the bare enum. Forward-compatibility with unknown Discord values is
  preserved by the enum design (stdlib `IntFlag` for flags, a value-preserving `_missing_`
  pseudo-member for scalar enums), never by union widening. See [02-enums](../02-enums/00-strategy-and-forward-compat.md).
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

1. **Public API breakage.** Removing 163 helper methods and the `app` field breaks every documented
   example that does `await message.respond(...)` / `channel.send(...)` / `guild.get_member(...)`.
   This is the largest user-visible break.
2. **Forward-compat regression on unknown enum values.** A naive strict-enum migration makes hikari
   crash on every new Discord enum value. Mitigated by the `IntFlag` + `_missing_` design (both
   empirically verified, dossier 02 Part E).
3. **Cache correctness under frozen + no-app.** `RefCell`/`GuildRecord` stay mutable; `MessageData`
   in-place edits and `has_been_deleted` need a new home. See dossier 07 §10.2.
4. **Wire-format edge cases.** int-subclass encode gap (msgspec cannot encode `Snowflake` natively —
   the docs are wrong, dossier 13 §11), epoch-number datetimes, per-field `timedelta` units.

## 7. Decisions and open items

Eleven decisions (D1–D11) are locked in [05-decisions-log.md](05-decisions-log.md). Two classes of
open item remain for the maintainer:

- **FLAGGED (D10):** whether events and interactions also go app-less+helper-less (maximally
  consistent, maximally breaking) or keep app+helpers (they are hand-constructed, so the
  "can't inject on decode" constraint does not bite). The recommendation is to keep them; this is a
  maintainer call. See [03-app-removal-and-helpers/04-events-and-interactions-app-decision.md](../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md).
- **VERIFY:** a small set of empirical probes gate the locked defaults — `eq=False` + inherited
  `Unique` dunders under frozen, the `T | UndefinedType` union legality, and `IntFlag` unknown-bit
  tolerance on the Python 3.10 floor. Consolidated in
  [12-appendices/01-open-questions-and-verifications.md](../12-appendices/01-open-questions-and-verifications.md).

## 8. Reading order

Start with [01-goals-and-non-goals.md](01-goals-and-non-goals.md) for what is in and out of scope,
then [02-target-architecture.md](02-target-architecture.md) for the data-flow model,
[03-risk-and-danger-map.md](03-risk-and-danger-map.md) for the ranked hazards,
[04-glossary.md](04-glossary.md) for terminology, and [05-decisions-log.md](05-decisions-log.md) as
the canonical decision reference cited by every later file.
