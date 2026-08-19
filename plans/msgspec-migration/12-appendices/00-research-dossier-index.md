# Research Dossier Index

The 15 research dossiers behind this migration plan: what each one established, which facts are
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
- **Verification tiers.** Four dossiers ran real probes against **msgspec 0.21.1 / CPython 3.11.x**
  and their behavioural claims are empirically verified: **02** (enum `_missing_`, `IntFlag`
  tolerance), **09** (custom scalars, datetime, `UNDEFINED`), **13** (the full msgspec capability
  matrix, wheel-inspected), and **15** (keeping hikari's custom enums under msgspec via the global
  `dec_hook`/`enc_hook`, given PR hikari-py/hikari#2770's instance-returning `__call__` — the enum
  plan of record, reproduced in-plan at [`02-custom-enum-feasibility.md`](02-custom-enum-feasibility.md)).
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
| 08 | `08-events-interactions.md` | Event/interaction structure, construction, app handling | Events are hand-constructed, never JSON-decoded; 44 own-`app` event fields + 32 `app`-delegating properties that BREAK when the wrapped entity loses `.app`; interactions are entities-that-are-also-clients (subclass `ExecutableWebhook`); response builders need no `app`; 5 loose `Enum\|int` unions | [07-events/00-events-migration.md](../07-events/00-events-migration.md), [03-app-removal-and-helpers/04-events-and-interactions-app-decision.md](../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md), [03-app-removal-and-helpers/02-helper-method-inventory/06-interactions.md](../03-app-removal-and-helpers/02-helper-method-inventory/06-interactions.md); D10 (FLAGGED) |
| 09 | `09-custom-types-time.md` | Snowflake/Color/Permissions/Locale/datetime/timedelta/UNDEFINED/files + hooks (**EMPIRICAL**) | Snowflake wire=string, Color wire=int, Permissions wire=string bitmask; msgspec won't coerce int→int-subclass (needs `dec_hook`); native RFC3339 datetime OK but unix-epoch fields are numbers + timedeltas are per-unit bare numbers (both need field hooks); `UNDEFINED` ~2433 hits / 1714 annotations / 33 modules; ready `dec_hook`/`enc_hook` sketches | [01-foundations/02-custom-scalar-types-and-hooks.md](../01-foundations/02-custom-scalar-types-and-hooks.md), [01-foundations/03-undefined-and-unset.md](../01-foundations/03-undefined-and-unset.md), [06-model-modules/01-scalars-snowflakes-colors-permissions-locales.md](../06-model-modules/01-scalars-snowflakes-colors-permissions-locales.md); D4, D5; probe V5 |
| 10 | `10-rest-client-surface.md` | REST public methods, deserialize/serialize call sites, DX shift | ~188 async endpoints; `impl/rest.py` has **zero** `.app` refs (REST is structurally safe); 90 helpers wrap **existing** endpoints (no mandatory new endpoint); only `User.send` is genuinely compound; `event.app.rest.*` is the blessed replacement path but some events derive app from their entity and must switch to storing it | [09-rest-and-gateway/00-rest-client.md](../09-rest-and-gateway/00-rest-client.md), [03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md](../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md); D9 |
| 11 | `11-tests-fixtures.md` | Test construction patterns, blast radius, frozen/enum/app test impact | 84 test files / ~2940 tests; no `conftest.py`, no stub-entity layer; `mock_class_namespace` used 85×; construct-then-mutate idiom (~250–350 genuine frozen-struct mutation sites); 59 `app is mock_app` asserts; 21 `is not` cache copy-isolation asserts; `test_attr_extensions.py` deleted, `test_enums.py` heavily rewritten | [10-testing/00–02](../10-testing/00-test-strategy.md) |
| 12 | `12-public-api-compat.md` | `__all__`/exports, breaking changes, deprecation, towncrier process | 631 public symbols; 67 enum + 13 flag + 19 exception classes; migration = major bump to **3.0.0**; deprecation slate currently empty; towncrier fragments in `changes/{PR}.{type}.md`; 5 generated `.pyi` stubs must be regenerated; no public-API snapshot test exists | [11-rollout/03-breaking-changes-and-changelog.md](../11-rollout/03-breaking-changes-and-changelog.md), [11-rollout/04-rollback-and-risk-mitigation.md](../11-rollout/04-rollback-and-risk-mitigation.md), [00-overview/03-risk-and-danger-map.md](../00-overview/03-risk-and-danger-map.md) |
| 13 | `13-msgspec-capabilities.md` | msgspec 0.21.1 capability matrix mapped to hikari (**EMPIRICAL, wheel-verified**) | Struct option semantics + inheritance; `frozen`/`kw_only`/`eq`; `UNSET` auto-omit independent of `omit_defaults`; `dec_hook`/`enc_hook` mechanics (Snowflake proof); **`Enum\|int` / `StrEnum\|str` are hard `TypeError`s**; int-subclass encode gap; tagged unions raise on unknown tag; `structs.replace`/`force_setattr` | [01-foundations/00–05](../01-foundations/00-dependencies-and-tooling.md), [02-enums/00-strategy-and-forward-compat.md](../02-enums/00-strategy-and-forward-compat.md), [04-frozen-and-cache/00-frozen-structs-and-copy-removal.md](../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md), [05-entity-factory/01-polymorphism-and-tagged-unions.md](../05-entity-factory/01-polymorphism-and-tagged-unions.md); D1–D8, D11; probes V1, V2, V3, V6, V7 |
| 14 | `14-build-tooling.md` | pyproject/uv.lock/noxfile/ruff/mypy/docs/CI impact | `attrs` core dep (`pyproject.toml:36`); `orjson`/`ciso8601` in `speedups` extra; msgspec absent from `uv.lock` (must regen); msgspec MUST be core (no stdlib fallback); CI = 3 OS × 5 Python (3.10–3.14); 5 `.pyi` stubs are a drift gate; pyright attrs-relaxations candidate to re-tighten; **cp314 wheel availability is the top packaging risk** | [01-foundations/00-dependencies-and-tooling.md](../01-foundations/00-dependencies-and-tooling.md), [11-rollout/02-performance-benchmarking.md](../11-rollout/02-performance-benchmarking.md), [11-rollout/03-breaking-changes-and-changelog.md](../11-rollout/03-breaking-changes-and-changelog.md); D7; probe V6 |
| 15 | `15-custom-enums-msgspec.md` | Keeping hikari's custom enums under msgspec via `dec_hook`/`enc_hook` + PR hikari-py/hikari#2770 (**EMPIRICAL**) | msgspec treats the custom (non-`enum.Enum`) `Enum`/`Flag` as custom types → routes them to `dec_hook`, whose result must be an **instance** of the annotated type; PR #2770 makes `Enum.__call__` mint an `is_unknown` pseudo-member instance on a miss (the `Flag` already did), raises `TypeError` on wrong type, and drops the `\|int`/`\|str` field/param unions; keeping custom costs one Python `dec_hook` call per enum field per decode (the runtime-speed trade-off) | [12-appendices/02-custom-enum-feasibility.md](02-custom-enum-feasibility.md), [02-enums/00–04](../02-enums/00-strategy-and-forward-compat.md), [01-foundations/02-custom-scalar-types-and-hooks.md](../01-foundations/02-custom-scalar-types-and-hooks.md), [11-rollout/02-performance-benchmarking.md](../11-rollout/02-performance-benchmarking.md); D2 (revised) |
| 16 | `16-base-struct-identity-verified.md` | Base-struct identity (VERIFY V1) resolved against the real `snowflakes.Unique` (**EMPIRICAL**) | `frozen=True, eq=False` inherits `Unique`'s id-only `__eq__`/`__hash__` (hash not nulled), hashable despite unhashable fields, immutable, slotted, decode round-trips; **R1** a combined `_StructABCMeta(abc.ABCMeta, type(msgspec.Struct))` is required (StructMeta is not an ABCMeta subclass → `metaclass conflict`), the real `Unique.__slots__=()` is kept; **R2** `kw_only` does not reliably inherit → repeat `frozen=True, kw_only=True` per struct level; residual: 3.10-floor re-run | [12-appendices/03-base-struct-identity-verified.md](03-base-struct-identity-verified.md), [01-foundations/01-base-struct-conventions.md](../01-foundations/01-base-struct-conventions.md); D3; probe V1 (RESOLVED) |

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
(Sequence) stay non-msgspec. This is the source of the FLAGGED D10 decision.

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

## 5. Traceability: decisions and probes → dossiers

| Decision / probe | Primary dossier(s) |
|---|---|
| D1 target architecture | 05, 13 |
| D2 keep custom enums (adopt PR #2770) + dec_hook | 02, 13, 15 |
| D3 base struct conventions | 03, 13 |
| D4 custom scalar hooks | 09, 13 |
| D5 UNDEFINED vs UNSET | 09, 13 |
| D6 JSON decode | 01, 13 |
| D7 JSON encode + msgspec core dep | 01, 06, 13, 14 |
| D8 cache / copy removal | 07, 13 |
| D9 app removal & helpers | 04, 10 |
| D10 events/interactions app (FLAGGED) | 08, 10 |
| D11 builders deferred | 06 |
| V1 `eq=False`+`Unique` inheritance | 03, 13 |
| V2 `T\|UndefinedType` union legality | 09, 13 |
| V3 `IntFlag` KEEP on 3.10 — WITHDRAWN, moot (custom `Flag` kept) | 02, 13, 15 |
| V4 str-enum `str()` semantics — WITHDRAWN, moot (custom enums keep `__str__`) | 02, 15 |
| V5 native datetime vs ciso8601 | 09, 13, 14 |
| V6 msgspec wheel coverage 3.10–3.14 | 13, 14 |
| V7 int-subclass encode leak audit | 06, 09, 13 |

The consolidated, actionable form of the FLAGGED and VERIFY items is
[01-open-questions-and-verifications.md](01-open-questions-and-verifications.md); the authoritative
decision records are [../00-overview/05-decisions-log.md](../00-overview/05-decisions-log.md).
