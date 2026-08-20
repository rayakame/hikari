# Research Dossier Index

The 20 research dossiers behind this migration plan: what each one established, which facts are
empirically verified, and which plan sections trace back to it. Every counted claim, `file:line`
anchor, and msgspec behaviour cited anywhere in the plan originates in one of these dossiers.

## 1. Objective

Give any reviewer a single lookup table from a claim in the plan back to the research that
justifies it, and vice versa. Because the dossiers themselves are held in an out-of-tree scratch
directory (see §2), this index also **summarizes each dossier's load-bearing findings inline** so
the plan remains self-contained if the scratch files are ever lost.

## 2. Provenance and status

- **Location (ephemeral, out-of-tree scratch).** The dossiers are working notes held in a scratch
  directory outside the repository tree, not committed artifacts, and may not survive. Because of
  that, every load-bearing fact is reproduced in the inline summaries (§4) and in the owning plan
  files, so the plan stands on its own; cite those, not the scratch files, in shipped docs.
- **Verification tiers.** Seven dossiers ran real probes against **msgspec 0.21.1 / CPython 3.11.x**
  and their behavioural claims are empirically verified: **02** (enum `_missing_`, `IntFlag`
  tolerance), **09** (custom scalars, datetime, `UNDEFINED`), **13** (the full msgspec capability
  matrix, wheel-inspected), **15** (keeping hikari's custom enums under msgspec via the global
  `dec_hook`/`enc_hook`, given PR hikari-py/hikari#2770's instance-returning `__call__` — the enum
  plan of record, reproduced in-plan at [`02-custom-enum-feasibility.md`](02-custom-enum-feasibility.md)),
  **16** (base-struct identity resolved against the real `snowflakes.Unique`: `frozen=True,
  eq=False` inherits `Unique`'s id-only dunders — EMPIRICAL, msgspec 0.21.1),
  **18** (the event-decode probe: P1/P2 event patterns, the name-keyed Decoder registry +
  `msgspec.Raw` envelope, `force_setattr`/`replace` injection costs — reproduced in-plan at
  [`04-event-pipeline-feasibility.md`](04-event-pipeline-feasibility.md)), and **20** (the
  shard-field typing recipe on decoded frozen events, same appendix).
  Prefer their verified facts over any general assumption. The remaining
  dossiers are **source-read** against the tree at research time (every claim `file:line`-anchored);
  **06** explicitly notes its sandbox could not import `attrs`/`orjson`/`msgspec`, so its claims are
  source-grounded only.
- **One doc discrepancy to remember:** msgspec's `/supported-types` page says int subclasses "encode
  fine." Dossier 13 §11 proved this **FALSE** in 0.21.1 — encoding a `Snowflake`/`Color` int subclass
  raises `TypeError`. This drives the `enc_hook` requirement (D4/D7, probe V7).

## 3. Master index

| # | File | Topic | Load-bearing verified facts / counts | Plan sections that rely on it |
|---|---|---|---|---|
| 01 | `01-data-binding-json.md` | orjson→msgspec JSON seam, the three builders, encode gap, gateway/interaction JSON | orjson confined to `data_binding.py:106-123` (1 import site); 6 decode + 14 encode call sites; `OPT_NON_STR_KEYS` driven by `Locale`-keyed localization maps; `msgspec.json.decode` is a drop-in for untyped loads (`ValueError` subclass on bad input) | [01-foundations/04-json-data-binding.md](../01-foundations/04-json-data-binding.md), [01-foundations/05-decode-boundary-and-decoders.md](../01-foundations/05-decode-boundary-and-decoders.md), [09-rest-and-gateway/01-gateway-shard-and-interaction-server.md](../09-rest-and-gateway/01-gateway-shard-and-interaction-server.md); D6, D7 |
| 02 | `02-enums-inventory.md` | Enum/Flag machinery, 80-type inventory, `\|int`/`\|str` table, unknown-value tolerance (**EMPIRICAL**) | 80 concrete types = 55 int + 12 str + 13 flags; custom `_EnumMeta`/`_FlagMeta` are NOT stdlib; msgspec **calls `_missing_`** and accepts a minted pseudo-member; `IntFlag` KEEP-boundary preserves unknown bits; ~150 `\|int`/`\|str` unions (67 on entity fields) | [02-enums/00–04](../02-enums/00-strategy-and-forward-compat.md); D2; probes V3, V4 |
| 03 | `03-attrs-model-patterns.md` | attrs taxonomy across 26 model modules, identity model, wire-vs-internal split, hazards | 175 `@attrs.define` models (273 lib-wide); 103 `@with_copy`; 845 `attrs.field`; id-only identity via `unsafe_hash=True` + one `hash=True` (the `id`); 24 `app` fields; 4 `_x` aliases; `embeds.Embed`/`files.Resource` mixin/`AuditLog(Sequence)` hazards | [01-foundations/01-base-struct-conventions.md](../01-foundations/01-base-struct-conventions.md), [04-frozen-and-cache/00-frozen-structs-and-copy-removal.md](../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md), [06-model-modules/00-README.md](../06-model-modules/00-README.md); D3 |
| 04 | `04-helper-methods-inventory.md` | The 163 `self.app.*` helper methods, per-module tables, no-1:1-rest cluster | 163 distinct helper methods; 126 `rest.*` + 37 `cache.*` sites; taxonomy pure/assert/guard/token/compose; no-1:1 cluster (`Member.fetch_roles`, `PartialUser.send`, webhook token methods, `edit_overwrite`, `Guild.get_my_member`, mention getters) | [03-app-removal-and-helpers/00–04](../03-app-removal-and-helpers/00-strategy.md) incl. [02-helper-method-inventory/](../03-app-removal-and-helpers/02-helper-method-inventory/00-README.md); D9 |
| 05 | `05-entity-factory-deserialize.md` | entity_factory internals, 19 dispatch tables, 13 hard-case categories, 64 app sites | 91 `deserialize_*` + 7 `serialize_*` + 61 private helpers; 19 polymorphic dispatch tables; 13 hard cases (re-keying, flatten, sibling-typing, context injection, lazy `GatewayGuildDefinition`, computed, classmethod); dict-in interface today; two-layer wire→public design | [05-entity-factory/00–03](../05-entity-factory/00-architecture-and-decode-strategy.md); D1; [01-foundations/05-decode-boundary-and-decoders.md](../01-foundations/05-decode-boundary-and-decoders.md) |
| 06 | `06-serialize-and-builders.md` | Outbound `serialize_*` + the 42 `special_endpoints` builders (source-read only) | 40 builder classes (44 interfaces); builders are mutable fluent state machines (cannot freeze); `build()` mutates (`_build_components` OR-s the v2 flag); 7 `serialize_*`; `UNDEFINED` filtered in `JSONObjectBuilder.put*`, not the encoder | [05-entity-factory/03-serialize-methods.md](../05-entity-factory/03-serialize-methods.md), [08-builders/00-special-endpoints-builders.md](../08-builders/00-special-endpoints-builders.md); D11 |
| 07 | `07-cache-deep-dive.md` | Copy sites, `*Data`/`RefCell`/`GuildRecord`, mutation inventory, app rehydration | ~104 cache copy sites; `copy.deepcopy` used **nowhere** (deep-copy half is dead in-tree); `Cell` is dead code; 8 `_build_*(app)` injectors; `RefCell`/`GuildRecord` must stay mutable; `MessageData.update`/`has_been_deleted` resist freezing; `set_role` no-copy asymmetry (`impl/cache.py:1538`) | [04-frozen-and-cache/00–02](../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md); D8 |
| 08 | `08-events-interactions.md` | Event/interaction structure, construction, app handling | Events are hand-constructed, never JSON-decoded; 44 own-`app` event fields + 32 `app`-delegating properties that BREAK when the wrapped entity loses `.app`; interactions are entities-that-are-also-clients (subclass `ExecutableWebhook`); response builders need no `app`; 5 loose `Enum\|int` unions | [07-events/00-events-migration.md](../07-events/00-events-migration.md), [03-app-removal-and-helpers/04-events-and-interactions-app-decision.md](../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md), [03-app-removal-and-helpers/02-helper-method-inventory/06-interactions.md](../03-app-removal-and-helpers/02-helper-method-inventory/06-interactions.md); D10-events (RESOLVED — superseded in part by 17–19), D10-interactions (FLAGGED) |
| 09 | `09-custom-types-time.md` | Snowflake/Color/Permissions/Locale/datetime/timedelta/UNDEFINED/files + hooks (**EMPIRICAL**) | Snowflake wire=string, Color wire=int, Permissions wire=string bitmask; msgspec won't coerce int→int-subclass (needs `dec_hook`); native RFC3339 datetime OK but unix-epoch fields are numbers + timedeltas are per-unit bare numbers (both need field hooks); `UNDEFINED` ~2433 hits / 1714 annotations / 33 modules; ready `dec_hook`/`enc_hook` sketches | [01-foundations/02-custom-scalar-types-and-hooks.md](../01-foundations/02-custom-scalar-types-and-hooks.md), [01-foundations/03-undefined-and-unset.md](../01-foundations/03-undefined-and-unset.md), [06-model-modules/01-scalars-snowflakes-colors-permissions-locales.md](../06-model-modules/01-scalars-snowflakes-colors-permissions-locales.md); D4, D5; probe V5 |
| 10 | `10-rest-client-surface.md` | REST public methods, deserialize/serialize call sites, DX shift | ~188 async endpoints; `impl/rest.py` has **zero** `.app` refs (REST is structurally safe); 90 helpers wrap **existing** endpoints (no mandatory new endpoint); only `User.send` is genuinely compound; `event.app.rest.*` is the blessed replacement path but some events derive app from their entity and must switch to storing it | [09-rest-and-gateway/00-rest-client.md](../09-rest-and-gateway/00-rest-client.md), [03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md](../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md); D9 |
| 11 | `11-tests-fixtures.md` | Test construction patterns, blast radius, frozen/enum/app test impact | 84 test files / ~2940 tests; no `conftest.py`, no stub-entity layer; `mock_class_namespace` used 85×; construct-then-mutate idiom (~250–350 genuine frozen-struct mutation sites); 59 `app is mock_app` asserts; 21 `is not` cache copy-isolation asserts; `test_attr_extensions.py` deleted, `test_enums.py` heavily rewritten | [10-testing/00–02](../10-testing/00-test-strategy.md) |
| 12 | `12-public-api-compat.md` | `__all__`/exports, breaking changes, deprecation, towncrier process | 631 public symbols; 67 enum + 13 flag + 19 exception classes; migration = major bump to **3.0.0**; deprecation slate currently empty; towncrier fragments in `changes/{PR}.{type}.md`; 5 generated `.pyi` stubs must be regenerated; no public-API snapshot test exists | [11-rollout/03-breaking-changes-and-changelog.md](../11-rollout/03-breaking-changes-and-changelog.md), [11-rollout/04-rollback-and-risk-mitigation.md](../11-rollout/04-rollback-and-risk-mitigation.md), [00-overview/03-risk-and-danger-map.md](../00-overview/03-risk-and-danger-map.md) |
| 13 | `13-msgspec-capabilities.md` | msgspec 0.21.1 capability matrix mapped to hikari (**EMPIRICAL, wheel-verified**) | Struct option semantics + inheritance; `frozen`/`kw_only`/`eq`; `UNSET` auto-omit independent of `omit_defaults`; `dec_hook`/`enc_hook` mechanics (Snowflake proof); **`Enum\|int` / `StrEnum\|str` are hard `TypeError`s**; int-subclass encode gap; tagged unions raise on unknown tag; `structs.replace`/`force_setattr` | [01-foundations/00–05](../01-foundations/00-dependencies-and-tooling.md), [02-enums/00-strategy-and-forward-compat.md](../02-enums/00-strategy-and-forward-compat.md), [04-frozen-and-cache/00-frozen-structs-and-copy-removal.md](../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md), [05-entity-factory/01-polymorphism-and-tagged-unions.md](../05-entity-factory/01-polymorphism-and-tagged-unions.md); D1–D8, D11; probes V1, V2, V3, V6, V7 |
| 14 | `14-build-tooling.md` | pyproject/uv.lock/noxfile/ruff/mypy/docs/CI impact | `attrs` core dep (`pyproject.toml:36`); `orjson`/`ciso8601` in `speedups` extra; msgspec absent from `uv.lock` (must regen); msgspec MUST be core (no stdlib fallback); CI = 3 OS × 5 Python (3.10–3.14); 5 `.pyi` stubs are a drift gate; pyright attrs-relaxations candidate to re-tighten; **cp314 wheel availability is the top packaging risk** | [01-foundations/00-dependencies-and-tooling.md](../01-foundations/00-dependencies-and-tooling.md), [11-rollout/02-performance-benchmarking.md](../11-rollout/02-performance-benchmarking.md), [11-rollout/03-breaking-changes-and-changelog.md](../11-rollout/03-breaking-changes-and-changelog.md); D7; probe V6 |
| 15 | `15-custom-enums-msgspec.md` | Keeping hikari's custom enums under msgspec via `dec_hook`/`enc_hook` + PR hikari-py/hikari#2770 (**EMPIRICAL**) | msgspec treats the custom (non-`enum.Enum`) `Enum`/`Flag` as custom types → routes them to `dec_hook`, whose result must be an **instance** of the annotated type; PR #2770 makes `Enum.__call__` mint an `is_unknown` pseudo-member instance on a miss (the `Flag` already did), raises `TypeError` on wrong type, and drops the `\|int`/`\|str` field/param unions; keeping custom costs one Python `dec_hook` call per enum field per decode (the runtime-speed trade-off) | [12-appendices/02-custom-enum-feasibility.md](02-custom-enum-feasibility.md), [02-enums/00–04](../02-enums/00-strategy-and-forward-compat.md), [01-foundations/02-custom-scalar-types-and-hooks.md](../01-foundations/02-custom-scalar-types-and-hooks.md), [11-rollout/02-performance-benchmarking.md](../11-rollout/02-performance-benchmarking.md); D2 (revised) |
| 16 | `16-base-struct-identity-verified.md` | Base-struct identity (VERIFY V1) resolved against the real `snowflakes.Unique` (**EMPIRICAL**) | `frozen=True, eq=False` inherits `Unique`'s id-only `__eq__`/`__hash__` (hash not nulled), hashable despite unhashable fields, immutable, slotted, decode round-trips; **R1** a combined `_StructABCMeta(abc.ABCMeta, type(msgspec.Struct))` is required (StructMeta is not an ABCMeta subclass → `metaclass conflict`), the real `Unique.__slots__=()` is kept; **R2** `kw_only` does not reliably inherit → repeat `frozen=True, kw_only=True` per struct level; residual: 3.10-floor re-run | [12-appendices/03-base-struct-identity-verified.md](03-base-struct-identity-verified.md), [01-foundations/01-base-struct-conventions.md](../01-foundations/01-base-struct-conventions.md); D3; probe V1 (RESOLVED) |
| 17 | `17-event-factory-classification.md` | event_factory's 77 `deserialize_*` methods binned A/B/C/D for msgspec decodability, with line accounting (source-verified) | `impl/event_factory.py` = 1216 lines, 77 methods (73 take a live shard, 17 take `old_*`, 50 inject `app=self._app` — all 50 vanish); **27 A + 18 B + 21 C + 11 D**; 45/77 become one-or-two-liners, ~73% end trivial, file → est. **400–550 lines** (55–65% deleted); 9 guild-vs-DM splits on THREE discriminators incl. reaction_add's `"member" in payload` (event_factory.py:789); hard residual cores: GUILD_CREATE laziness + `shard.get_user_id()` decode input, presence_update UNDEFINED-partial user, list→dict joins, emoji flatten, unix-seconds timestamps, hex burst_colors, auto_mod coercions | [07-events/00-events-migration.md](../07-events/00-events-migration.md), [12-appendices/04-event-pipeline-feasibility.md](04-event-pipeline-feasibility.md); D12 |
| 18 | `18-event-decode-probe.md` | The event-decode pattern proven end-to-end: frozen event structs + name-keyed Decoder registry + post-decode `shard`/`old_*` injection (**EMPIRICAL**, msgspec 0.21.1 + real #2770 enums/`Snowflake`/`UniqueStruct`) | P1 two-step, P2 direct-decode, registry + `msgspec.Raw` envelope, `old_*` (ctor + `replace`), and the guild/DM split all **PASS**; enum decode returns the canonical member by identity; `force_setattr` 78 ns vs `replace` 132 ns; typed decode 3.20 µs/op vs 7.66 stdlib-json→dict→hand-attrs (~2.4×) and 4.03 msgspec→dict→hand-construct (~1.3×) — no-speedups caveat; Decoder construction is **LAZY** (annotate `shard` as the REAL class, never `Any`/`object`); `forbid_unknown_fields` verified to break on Discord extras | [07-events/00-events-migration.md](../07-events/00-events-migration.md), [09-rest-and-gateway/01-gateway-shard-and-interaction-server.md](../09-rest-and-gateway/01-gateway-shard-and-interaction-server.md), [12-appendices/04-event-pipeline-feasibility.md](04-event-pipeline-feasibility.md); D12, D13; gate note N-EV |
| 19 | `19-event-manager-interplay.md` | event_manager ↔ event_factory ↔ cache interplay; the Raw envelope seam; app/shard blast radius (source-verified) | `impl/cache.py` has **ZERO** raw-payload reads (every `set_*`/`update_*` takes an entity); handlers read the raw dict in exactly **19** places, all covered by decoded fields; dispatch already name-keyed with `is_enabled` lazy gating (event_manager_base.py:339-348, consume at :404-420) — Raw capture of `d` (shard.py:844-895) is a strict win; **zero** internal readers of `event.app`; the `chunk_nonce` mutation (event_manager.py:420) is the ONLY event mutation in hikari → T-CN; GUILD_CREATE laziness + `get_user_id` decode context → SD5; Raw public breaks (consume_raw_event, ShardPayloadEvent.payload, `loads=`/`dumps=`, EventFactory ABC) | [07-events/00-events-migration.md](../07-events/00-events-migration.md), [09-rest-and-gateway/01-gateway-shard-and-interaction-server.md](../09-rest-and-gateway/01-gateway-shard-and-interaction-server.md), [03-app-removal-and-helpers/04-events-and-interactions-app-decision.md](../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md), [12-appendices/04-event-pipeline-feasibility.md](04-event-pipeline-feasibility.md); D10-events, D12; T-CN, SD5 |
| 20 | `20-shard-typing-probe.md` | shard-field typing on decoded frozen events: no `Optional` in the public API (**EMPIRICAL**, msgspec 0.21.1) | **P1** hand-constructed events: plain required `shard: GatewayShard` (`TypeError` if omitted); **P2** direct-decode events: `_shard: GatewayShard \| None = msgspec.field(default=None, name="__hikari_runtime_shard__")` storage + NON-optional `shard` property + `force_setattr` injection pre-dispatch; the `name=` rename is **load-bearing** (a literal `"_shard"` wire key is skipped as unknown instead of hitting the global dec_hook — verified); matches the abstract `ShardEvent.shard` property (shard_events.py:69) | [07-events/00-events-migration.md](../07-events/00-events-migration.md), [12-appendices/04-event-pipeline-feasibility.md](04-event-pipeline-feasibility.md); D13 |

## 4. Inline summaries (self-contained digest)

Enough of each dossier to act on without re-reading it. Counts are the dossiers' own verified
figures — do not re-derive or invent alternatives.

### 01 — data_binding / JSON seam
One JSON abstraction module, `hikari/internal/data_binding.py`, exports `default_json_dumps`
(encoder → `bytes`) and `default_json_loads` (decoder, `str|bytes` → dict/list, raises `ValueError`).
`orjson` lives only at `data_binding.py:106-123` behind a `try/except ModuleNotFoundError` stdlib
fallback. Decode call sites: 6 (`net.py:47`, `ux.py:494`, `rest.py:895,1012`, `shard.py:200`,
`interaction_server.py:442`). Encode call sites: 14 (incl. 11 `payload_json` multipart fields). Six
components carry pluggable `_dumps`/`_loads` (a documented public feature). The `JSONObjectBuilder`/
`StringMapBuilder`/`URLEncodedFormBuilder` builders emit plain dicts and are orthogonal to
`entity_factory`. `OPT_NON_STR_KEYS` exists for `Locale`-keyed localization maps.
`msgspec.json.decode`/`encode` are drop-ins (bytes contract matches; `DecodeError` subclasses
`ValueError`); `msgspec.Raw` enables peek-then-dispatch for the gateway/interaction envelopes.

### 02 — enums (EMPIRICAL)
80 concrete types on hikari's custom `enums.py` metaclasses: 55 `(int, enums.Enum)`, 12
`(str, enums.Enum)`, 13 `enums.Flag`. Today's tolerance: `_EnumMeta.__call__` returns the **raw
value** on a miss (hence ~150 `Enum|int`/`|str` unions, 67 on entity fields); `_FlagMeta.__call__`
mints a cached pseudo-member (cap `_MAX_CACHED_MEMBERS = 4096`, `enums.py:39`). Verified against
msgspec 0.21.1: unknown int/str enum value → `ValidationError`; `IntFlag` (KEEP boundary, default
3.11+) preserves unknown bits losslessly; msgspec **invokes `_missing_`** and accepts a returned
value-preserving pseudo-member (`int.__new__`/`str.__new__` + set `_name_`/`_value_`). The rich
`Flag` set-API (`.all/.any/.none/.split/.difference/.intersection/.union/.is_subset/…`, ~20
methods, `enums.py:683-829`) must be re-attached. `GuildMemberFlags | int` is a dead union (a Flag
never returns a raw int). The `.pyi` already presents these as stdlib enums to type checkers.

### 03 — attrs model patterns
175 `@attrs.define` models in the 26 model modules (273 lib-wide). Canonical wire model:
`@attrs.define(unsafe_hash=True, kw_only=True, weakref_slot=False)` with one `hash=True` field (the
`id`) and ~580 `eq=False`/`hash=False` opt-outs → **id-only identity** via `snowflakes.Unique`
(`snowflakes.py:103-132`). msgspec has **no per-field eq/hash** — the plan keeps `Unique` and
declares structs `eq=False` (probe V1). 24 `app` fields; 8 `converter=`; 7 `factory=`; 4 `_x`
aliases; 0 `frozen`, 0 `__attrs_post_init__`, 0 `on_setattr` (models are already write-once in
practice). Hazards needing bespoke handling: `embeds.Embed` (hand-written builder + `from_received_
embed`), the `files.Resource` multiple-inheritance family (`Attachment`, `MediaResource`,
`EmbedImage/Video`), `AuditLog(Sequence)`, `ActionRowComponent(Generic)`, `Member`/`TeamMember`
(`eq=False`, inherit eq from `User`). Errors (`errors.py`, 22 `auto_exc`) stay exceptions.

### 04 — helper methods (`self.app.*`)
163 distinct helper methods reference `self.app`: 126 `rest.*` + 37 `cache.*` call sites across 20
modules (`guilds.py` largest at 45 methods). Taxonomy: pure / assert / guard / token / compose /
arg-default. Most are thin `rest.*` sugar → delete, caller calls `rest.<method>(entity.<id>, …)`.
The no-1:1-rest cluster becomes free functions or new rest methods: `Member.fetch_roles`
(client-side role filter), `PartialUser.send` (DM resolve+create), the webhook token-resolution
methods, `PermissibleGuildChannel.edit_overwrite` (target_type inference), `Guild.get_my_member`
(needs `app.get_me()`), guild-scoped cache getters with ownership filters, message mention getters.
Two `shard_id` styles (pass `self.app` vs `self.app.shard_count`); `app` is sometimes an abstract
property (40 `def app` sites) not a field. 10 "dead" `app` fields carry no `self.app.*` call.

### 05 — entity_factory deserialization
The single largest migration target (`impl/entity_factory.py`, 4857 lines). 91 `deserialize_*`, 7
`serialize_*`, 61 private helpers, 19 polymorphic dispatch tables built in `__init__`. Interface is
dict-in (`JSONObject`) today; bytes-in is the fast msgspec path (interface-wide churn). 64
`app=self._app` injection sites (constraint a blocker). Thirteen hard-case categories resist
declarative decode: array→keyed-`Mapping` re-keying, flattened grandchild fields, sibling-dependent
value typing (command-option value, audit-log change values, forum-tag emoji, role color), context
injection (`guild_id`/`user_id` threaded from parent), the lazy `GatewayGuildDefinition`, computed
fields, `Embed.from_received_embed`, enum leniency, `UNDEFINED` tri-state, enum-keyed dicts,
epoch-number datetimes, `undefined.UNDEFINED` (111 sites). Recommended two-layer design: msgspec
wire structs (tagged unions, native types, `UNSET`) → transform layer → public frozen structs.

### 06 — serialize + builders (source-read only)
40 builder classes in `impl/special_endpoints.py`. Builders are **mutable fluent state machines**
(`set_*`/`add_*` return `self`; `__attrs_post_init__` writes derived fields; `InteractionMessage
Builder.build()` mutates `self._flags`) → they **must NOT be frozen** (constraint c waiver). They
hold no `app`. `UNDEFINED` filtering lives in `JSONObjectBuilder.put*`, not the encoder, so the
builder subsystem is orthogonal to the encode swap. All hikari enums, `Snowflake`, `Color` subclass
`int`; orjson serialized them fine but msgspec cannot (int-subclass encode gap) → `enc_hook` or
pre-lowering. `_build_message_payload` (`rest.py:1430-1596`) duplicates builder logic and must be
kept in sync. Recommendation: keep the 40 builders mutable/attrs in the first pass; only swap the
encoder implementation.

### 07 — cache deep dive
The cache never mutates a built public entity in place; defensive copies exist only to isolate
external callers → **frozen structs make the public copy layer dead**. ~104 copy sites collapse to
identity returns; `copy.deepcopy` is used nowhere (the whole deep-copy half of `attrs_extensions.py`
is dead in-tree); `Cell` is dead code. Two storage strategies: "Data-object" (rebuild app-less via
`build_entity(self._app)`) and "direct-entity" (`copy.copy`, app rides inside). `RefCell`
(ref-count + shared-slot) and `GuildRecord` (per-guild indexes) **stay mutable**. Blockers to freezing
the `*Data` layer: `MessageData.update()` (8 in-place fields), `MemberData.has_been_deleted` flag,
`RichActivityData.emoji` reassignment. `set_role` stores without copying (`impl/cache.py:1538`) — an
asymmetry that becomes uniformly correct under frozen. `FreezableDict.freeze` stays (dict snapshot
still needed even with frozen values).

### 08 — events & interactions
Events are hand-constructed by `event_factory` (never JSON-decoded), so they can stay attrs — but 32
`app`-delegating `@property` methods (`return self.<entity>.app`) **break** once the wrapped entity
loses `.app`; fix by giving every event its own `app` field and threading `app=self._app` at the
~30 currently-appless construction sites. Interactions subclass `webhooks.ExecutableWebhook` and
carry ~17 `self.app.*` helpers; under constraint (a) they lose `app` and the `ExecutableWebhook`
base. Response builders (`build_response`/`build_deferred_response`/`build_modal_response`) need no
`app` and can be preserved app-free. 5 loose `Enum|int` unions in the subtree. `ExceptionEvent`
(holds `Exception` + callback), `ShardPayloadEvent.payload` (raw Mapping), `MemberChunkEvent`
(Sequence) stay non-msgspec. This is the source of the original FLAGGED D10 decision — **since
superseded in part**: the maintainer resolved the events half (app-less events, D10-events) and
dossiers 17–19 replaced the "events stay attrs / give every event its own app field" framing with
the typed-decode pipeline (D12); the interactions half stays FLAGGED as D10-interactions.

### 09 — custom scalars / time / undefined / files (EMPIRICAL)
`Snowflake(int)` wire=string; `Color(int)` wire=int with `0..0xFFFFFF` validation; `Permissions(Flag)`
wire=string bitmask; `Locale(str, Enum)`; `UnicodeEmoji(str)`. msgspec will not coerce a JSON scalar
into an int/str **subclass** → each needs `dec_hook: T(obj)` with the field typed as the exact type;
encode needs `enc_hook` (Snowflake→`str(int)`, Color→`int`, Permissions→`str(int)`). Native RFC3339
datetime decode works (verify `Z`/offset/6-µs → probe V5) and would make `ciso8601` redundant for
entity timestamps — BUT unix-epoch fields are JSON numbers and timedeltas are per-unit bare numbers,
both requiring field-specific hooks; keep `time.unix_epoch_to_datetime` (with its max/min clamping).
`UNDEFINED` is a tri-state singleton used in two roles: REST request "don't send" (keep unchanged)
and decoded-entity "key omitted" (role ii → `default=UNDEFINED` on the struct field, or
`msgspec.UNSET` fallback). `files.*` is never decoded (upload-only) → no dec_hook. Ready hook
sketches in §10 of the dossier.

### 10 — REST client surface
`hikari/api/rest.py` has ~188 async endpoints; `impl/rest.py` has **zero** `.app` references, so REST
is structurally unaffected by all three constraints. Request bodies are built from plain dicts/query
maps/forms (58 `JSONObjectBuilder`, 19 `StringMapBuilder`, 7 form builders, 318 `put*`), independent
of attrs/structs/app. Responses decode to dicts then go through 143 `deserialize_*` calls; `app` is
injected factory-wide (`self._app`), the single seam constraint (a) severs. All 90 removed entity
helpers wrap **existing** endpoints → no mandatory new REST endpoint; only `User.send` is genuinely
compound (candidate `rest.send_dm`). The DX cost lands on `message.respond` /
`interaction.create_initial_response` / `user.send` — the exact patterns every example uses. Blessed
replacement path is `event.app.rest.*`, which requires fixing events that source app from their
(soon app-less) entities (`message_events.py:87-89`).

### 11 — tests & fixtures
84 test files, ~2940 tests, no `conftest.py`, no stub-entity factory — every entity is hand-built
with full kwargs including `app=`. `mock_class_namespace` (85 uses) instantiates abstract bases and
is attrs/ABC-coupled → needs a frozen-aware sibling. Frozen breaks the pervasive construct-then-
mutate idiom (~250–350 genuine field-mutation sites) → convert to construct-final or
`msgspec.structs.replace`. 59 `assert entity.app is mock_app` asserts and every `app=` kwarg in
expected literals go away. Strict enums break the raise/skip/preserve tolerance tests. 21 `is not`
cache copy-isolation asserts flip to `is`. `test_attr_extensions.py` (419 lines) deleted;
`test_enums.py` (1308 lines) heavily rewritten. Recommends a shared `evolve`/stub-entity helper.

### 12 — public API & compat
631 public symbols across 82 `__all__`s; top-level namespace is star-import + explicit re-export, no
`__all__` in `hikari/__init__.py`. 67 enum + 13 flag + 19 exception classes. Migration is a major
bump to **3.0.0** (per CONTRIBUTING EffVer). Deprecation tooling (`internal/deprecation.py`) exists
but the live slate is empty. Breaking-change catalog by severity: S1 helper/app removal + strict-enum
silent behaviour + `UNDEFINED` identity; S2 frozen mutation + lost `Flag` API; S3 attrs
copy/`evolve`/`asdict`/`isinstance`. Change management: towncrier fragments (`changes/{PR}.{type}.md`,
types breaking/deprecation/feature/optimization/bugfix/documentation); 5 generated `.pyi` stubs are a
CI drift gate; first-ever migration guide required; no public-API snapshot test exists (recommend
adding one).

### 13 — msgspec capabilities (EMPIRICAL, wheel-verified)
`msgspec.Struct` options and defaults, all runtime-inspected; config **inherits** to subclasses.
`frozen=True` → immutable + auto `__hash__`; `kw_only=True` lifts the required-after-optional ban
(per-class); `eq` is all-or-nothing per struct (no per-field control). `UNSET`/`UnsetType` auto-omits
on encode **independent of `omit_defaults`** and models undefined-vs-null on decode. `dec_hook(type,
obj)` fires for custom-typed fields and receives the raw scalar (handles str- and int-on-wire
Snowflakes); `enc_hook(obj)` dispatches by `type(obj)`. Hard limits: `Enum|int` and `StrEnum|str`
unions raise `TypeError` at type-construction; int subclasses **cannot** be encoded (doc says
otherwise — false); tagged unions raise on unknown tag (matches today's `UnrecognisedEntityError`).
`msgspec.structs.replace`/`force_setattr`/`asdict`/`fields` replace `attrs_extensions.py`. Enums:
only stdlib enums are native; `IntFlag` KEEP tolerates unknown bits; `_missing_` is honoured on miss.

### 14 — build & tooling
`attrs` is a core dep (`pyproject.toml:36`); `orjson`~=3.11 and `ciso8601`~=2.3 live in the
`speedups` extra. msgspec is absent from `uv.lock` → full `uv lock` regen needed; it MUST become a
**core** dep (no stdlib fallback, unlike orjson). CI: 3 OS × 5 Python (3.10–3.14) = 15 cells; **cp314
wheels are the top packaging risk** (probe V6). 5 generated `.pyi` stubs (`nox -s generate-stubs`)
are a drift gate. pyright carries three attrs-motivated relaxations (`pyproject.toml:180,184,185`) —
candidates to re-tighten. slotscheck expected to keep passing (msgspec auto-slots). No mypy `plugins`
entry needed (both mypy and pyright understand `msgspec.Struct` natively — confirm on pinned
versions). `ruff select = ["ALL"]` will surface new findings on Struct class-body fields.

### 15 — keeping custom enums under msgspec (EMPIRICAL)
The maintainer **keeps** hikari's fast custom `internal/enums.py` `Enum`/`Flag` rather than porting to
stdlib `enum`. msgspec detects native enums by `issubclass(t, enum.Enum)`; the custom types are not
`enum.Enum` subclasses (bespoke metaclasses), so msgspec treats a field typed as one as a **custom
type** and routes it to `dec_hook(t, raw)` — the same path as `Snowflake`; the hook returns `t(raw)`.
The load-bearing invariant: `dec_hook`'s result **must be an instance of the annotated type** (msgspec
`isinstance`-checks it). The custom `Flag` already mints a pseudo-member instance on a miss; the `Enum`
(pre-#2770) returns the raw `int`/`str`, which fails the invariant (`ValidationError: Expected 'X',
got 'int'`). **PR hikari-py/hikari#2770** changes `Enum.__call__` to mint an `is_unknown` pseudo-member
instance on a miss (with the bounded `_temp_members_` cache, `_MAX_CACHED_MEMBERS`, `enums.py:39`), adds
`is_unknown` to both, raises `TypeError` on wrong-type input (`__objtype__` guard), and types all model
fields + REST params with only the enum/flag type — so #2770 is the PREREQUISITE and also delivers the
strict-typing sweep. Empirically (msgspec 0.21.1, against the real enums module): with #2770's
`__call__`, known and unknown int/str enum and flag values all decode/encode through the single global
hook (encode returns `o.value` to avoid the int-subclass encode gap). Trade-off: one Python `dec_hook`
call per enum field per decode (msgspec fast-paths stdlib enums in its C core but not custom ones); in
exchange runtime enum operations stay on the faster custom implementation. This removes the stdlib
port, the `IntFlag` set-API re-implementation, and the `_missing_` mixin from the plan, and makes
VERIFY V3/V4 moot. Reproduced in-plan at
[12-appendices/02-custom-enum-feasibility.md](02-custom-enum-feasibility.md).

### 16 — base-struct identity (EMPIRICAL)
VERIFY V1 resolved against the real `snowflakes.Unique` (`snowflakes.py:103-132`). A frozen msgspec
`Struct` declared `eq=False` over `Unique` **inherits `Unique`'s id-only `__eq__`/`__hash__`** —
msgspec's `eq=False` does NOT null the inherited `__hash__`; the instance stays immutable, slotted,
hashable despite unhashable `list`/`dict` fields, and decode round-trips. No hand-written dunder
re-attachment is needed. Two mechanical requirements surfaced. **R1 — combined metaclass:**
`StructMeta` is not an `abc.ABCMeta` subclass, so a bare `class X(Unique, msgspec.Struct, …)` raises
`TypeError: metaclass conflict`; define `class _StructABCMeta(abc.ABCMeta, type(msgspec.Struct)): ...`
once and set it on the shared `UniqueStruct` base (subclasses inherit it), keeping the real `Unique`
unchanged (its `__slots__=()` composes fine — do NOT remove it). **R2 — per-level `kw_only`:** `frozen`
inherits via `__struct_config__` but `kw_only` does **not** reliably (it is not stored in
`StructConfig`); repeat `frozen=True, kw_only=True` on every struct level that adds fields. Residual: a
CPython **3.10**-floor re-run (the confirming run was 3.11; the mechanism is version-independent).

### 17 — event_factory classification
All 77 `deserialize_*` methods of `EventFactoryImpl` (`impl/event_factory.py`, 1216 lines; 73 take
a live shard, 17 take cache-fed `old_*` params, 50 inject `app=self._app` — all 50 vanish under
D10-events) binned for msgspec decodability: **27 A** (pure entity wrappers → one-liners
`EventCls(shard=shard, entity=DECODER.decode(d))`), **18 B** (flat events — the event struct ITSELF
decodes; shard attached after), **21 C** (residual reshaping: 5 split-only, 3 split+emoji-flatten,
3 sibling `guild_id` threading, 6 heavy, 4 misc-light), **11 D** (4 lifetime, 3 no-payload shard
events, shard_payload passthrough, ready, member_chunk, interaction_create → D10-interactions).
Net: **45/77 become one-or-two-liners, ~73% end trivial, the file shrinks to an estimated 400–550
lines (55–65% deleted)**. Guild-vs-DM splits: exactly 9 methods on THREE discriminators —
`"guild_id" in payload` (pins/typing/message_delete/3 reaction-removes), post-decode
`message.guild_id is None` (message create/update), and `"member" in payload` (reaction_add,
event_factory.py:789); each is a ≤4-line post-decode dispatch, and the GUILD_CREATE/DELETE
availability variants dispatch in event_manager.py:278-289/:503-504, outside the factory. Hard
residual cores: the GUILD_CREATE family (lazy `_GatewayGuildDefinition`, entity_factory.py:261;
`shard.get_user_id()` consumed as DECODE INPUT at entity_factory.py:427/1543-1556), presence_update's
UNDEFINED-partial user (:503-527), thread list/member-chunk list→dict joins, the shared
reaction-emoji flatten (`_split_reaction_emoji`, :818-824), unix-SECONDS timestamps (typing :312,
channel_info :993, voice start :1071), hex-string burst_colors (:787), auto_mod falsy coercions
(:1210-1215).

### 18 — event-decode probe (EMPIRICAL)
The target event pipeline proven on msgspec 0.21.1 with the real #2770 enums, `Snowflake`, and the
`UniqueStruct` base: **P1** two-step (decode frozen entity, hand-construct frozen event — enum
decode returns the canonical member by IDENTITY), **P2** direct-decode flat events, the name-keyed
`dict[str, msgspec.json.Decoder]` registry over a `msgspec.Raw` envelope (decode `op`/`t`/`s`/`d`
once, dispatch `d`), cache-fed `old_*` via constructor or `structs.replace`, and the 3-line
guild/DM post-decode split — **all PASS**. Injection on frozen structs: `force_setattr` **78 ns**
(recommended in the single-owner decode→dispatch window) vs `structs.replace` **132 ns**. Informal
bench: typed decode + dec_hook **3.20 µs/op** vs 7.66 stdlib-json→dict→hand-attrs (~2.4×) and 4.03
msgspec→dict→hand-construct (~1.3×) — caveat: the probe venv lacked orjson/ciso8601, so the hand
paths ran hikari's no-speedups fallbacks. Two hazards pinned: Decoder construction is **LAZY**
(a runtime-class annotation never breaks `Decoder()` construction — annotate `shard` as the REAL
class, never `typing.Any` (silent raw-JSON acceptance) or `object` (routes to the global dec_hook);
a typo'd field type fails on first decode, hence the per-event fixture smoke test, gate note N-EV),
and `forbid_unknown_fields` is **verified breaking** on Discord's extra fields — registry decoders
keep the default skip-unknown. Reproduced in-plan at
[`04-event-pipeline-feasibility.md`](04-event-pipeline-feasibility.md).

### 19 — event_manager/cache interplay
Consumer-side verdict: **no blocker**. `impl/cache.py` has **zero** raw-payload reads — every
`set_*`/`update_*` takes an entity, so decode-once-share-everywhere works and msgspec's unknown-key
drop is invisible to the cache by construction. Handlers read the raw dict in exactly **19** places,
all covered by decoded fields (old_* ID extraction, branch discriminators, `payload.get("large")`)
— the migration just inverts to decode-first. Dispatch is already name-keyed with `is_enabled` lazy
gating (`event_manager_base.py:339-348`, consume at `:404-420`); capturing `d` as `msgspec.Raw` in
`shard._poll_events` (shard.py:844-895; envelope parsed at :200) is a strict win — disabled
consumers stop paying full-dict parsing. Public breaks from Raw: `consume_raw_event`'s payload type
(api/event_manager.py:168), `ShardPayloadEvent.payload` (shard_events.py:92), the injectable
`loads=`/`dumps=` params (shard.py:561-562, gateway_bot.py:331-332), and the `EventFactory` ABC (77
abstract methods) reshaped. The app blast radius on events is purely public API — **zero** internal
readers of `event.app`. Two watch items became gate items: the **`chunk_nonce` mutation**
(`event.chunk_nonce = nonce`, event_manager.py:420; fields at guild_events.py:180/244) is the only
event mutation in hikari and must be restructured before events freeze (**T-CN**), and GUILD_CREATE's
two-layer laziness + the `user_id=shard.get_user_id()` decode context (event_manager.py:308/:453 →
entity_factory.py:427/1543-1556) need preserving (**SD5**). `on_guild_create`/`on_guild_update` are
deliberately NOT `filtered()` (always-called, event_manager_base.py:348); `ExceptionEvent` stays
non-msgspec and loses only its `app` proxy (base_events.py:207-211).

### 20 — shard-typing probe (EMPIRICAL)
The D13 recipe of record, verified on msgspec 0.21.1: **P1** hand-constructed events need no
Optional anywhere — a plain required `shard: GatewayShard` field raises
`TypeError: Missing required argument 'shard'` if omitted and never meets a Decoder. **P2**
direct-decode flat events use defaulted storage + a NON-optional property:
`_shard: GatewayShard | None = msgspec.field(default=None, name="__hikari_runtime_shard__")` with
`def shard(self) -> GatewayShard`, injected via `force_setattr` pre-dispatch on the frozen struct.
The **`name=` rename is load-bearing**: without it, a wire payload containing a literal `"_shard"`
key routes the raw JSON into the global dec_hook with `t=GatewayShard` and raises (loud, not
silent, but avoidable); with the rename the same key is skipped as unknown (verified with
`{"_shard": {...}}` planted in the payload). The storage+property form matches the existing
abstract `ShardEvent.shard` property (shard_events.py:69). Weaker alternatives recorded: a public
Optional field with user narrowing, or a `.pyi` stub masquerade (precedent: `enums.pyi`/
`undefined.pyi`). Never annotate runtime fields `typing.Any` or `object`.

## 5. Traceability: decisions and probes → dossiers

| Decision / probe | Primary dossier(s) |
|---|---|
| D1 target architecture | 05, 13 |
| D2 keep custom enums (adopt PR #2770) + dec_hook | 02, 13, 15 |
| D3 base struct conventions | 03, 13, 16 |
| D4 custom scalar hooks | 09, 13 |
| D5 UNDEFINED vs UNSET | 09, 13 |
| D6 JSON decode | 01, 13 |
| D7 JSON encode + msgspec core dep | 01, 06, 13, 14 |
| D8 cache / copy removal | 07, 13 |
| D9 app removal & helpers | 04, 10 |
| D10-events — events go app-less (RESOLVED by maintainer) | 08, 10, 17, 19 |
| D10-interactions — keep app + response sugar (FLAGGED) | 08, 10 |
| D11 builders deferred | 06 |
| D12 event pipeline: Decoder registry + Raw envelope + residual hydration | 17, 18, 19 |
| D13 shard stays on the event object (two patterns) | 18, 20 |
| T-CN chunk_nonce mutation fix before events freeze (blocking task) | 19 |
| SD5 GUILD_CREATE laziness under typed decode (sub-decision) | 19 |
| V1 `eq=False`+`Unique` inheritance (RESOLVED) | 03, 13, 16 |
| V2 `T\|UndefinedType` union legality | 09, 13 |
| V3 `IntFlag` KEEP on 3.10 — WITHDRAWN, moot (custom `Flag` kept) | 02, 13, 15 |
| V4 str-enum `str()` semantics — WITHDRAWN, moot (custom enums keep `__str__`) | 02, 15 |
| V5 native datetime vs ciso8601 | 09, 13, 14 |
| V6 msgspec wheel coverage 3.10–3.14 | 13, 14 |
| V7 int-subclass encode leak audit | 06, 09, 13 |
| V8 string-key → int-enum dict key | 05, 13 |
| V9 soft-skip prepass log-and-drop + wire order | 05, 13 |

The consolidated, actionable form of the FLAGGED and VERIFY items is
[01-open-questions-and-verifications.md](01-open-questions-and-verifications.md); the authoritative
decision records are [../00-overview/05-decisions-log.md](../00-overview/05-decisions-log.md).
