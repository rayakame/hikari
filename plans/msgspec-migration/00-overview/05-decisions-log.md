# Decisions Log

The canonical record of the eleven locked decisions (D1–D11) that govern the migration, plus the
open items the maintainer must resolve before or during implementation. Every other plan file cites
these by number. When a downstream file deviates from a decision it must say so explicitly and link
back here.

## 1. Objective

Give every author and reviewer one authoritative place to look up what was decided, why, what was
rejected, and whether the decision is fully locked or still gated by a probe or a maintainer choice.
The three constraints (a no-app, b strict-enums, c frozen) are the axioms; D1–D11 are the design
decisions derived from them.

## 2. Status legend

| Status | Meaning |
|---|---|
| LOCKED | Decided; implement as written |
| LOCKED (VERIFY) | Default is locked but gated by an empirical probe; a named fallback applies if the probe fails |
| FLAGGED | Two options presented; the maintainer must choose. Plan recommends but does not silently pick |

## 3. Locked decisions D1–D11

| # | Decision | Rationale | Alternatives rejected | Status | Owner file |
|---|---|---|---|---|---|
| **D1** | **Target architecture: declarative-first, transform-residual, app-less.** Decode Discord JSON directly into frozen app-less structs where the shape allows (dec_hook, `field(name=…)`, tagged unions); keep a slimmed residual factory for the ~13 hard-case categories. Sequence incrementally (two-layer). | A single-layer `decode(bytes, type=PublicStruct)` is not achievable for re-keying, flattening, sibling-typing, context injection, lazy guild, computed/classmethod cases (dossier 05 §6, §9). | (i) Full declarative decode — impossible for hard cases. (ii) Keep the whole hand-written factory — forgoes msgspec's decode speed. | LOCKED | [02-target-architecture.md](02-target-architecture.md) |
| **D2** | **Enums: port all 80 concrete types to stdlib `enum`.** 13 flags → `enum.IntFlag` (native unknown-bit tolerance) + re-attached set-API mixin; 55 int → `(int, enum.Enum)`; 12 str → `(str, enum.Enum)` (not `StrEnum`, 3.10 floor); attach a value-preserving `_missing_` pseudo-member for scalar enums. Drop ~150 `\| int`/`\| str` entity-field unions. | msgspec only understands stdlib enums (dossier 02 §E.1). `IntFlag` KEEP-boundary and `_missing_` pseudo-member both empirically preserve forward-compat (dossier 02 §E.3–E.4). | (i) `Enum \| int` union — a hard `TypeError` in msgspec (dossier 13 §15). (ii) `_missing_ → fixed UNKNOWN` sentinel — loses the raw value. (iii) plain int/str field + property — changes the public attribute type. | LOCKED (VERIFY: IntFlag on 3.10; `str()` semantics per enum family) | [../02-enums/00-strategy-and-forward-compat.md](../02-enums/00-strategy-and-forward-compat.md) |
| **D3** | **Base struct conventions: `frozen=True, kw_only=True, eq=False`, id-only identity via `snowflakes.Unique`.** Automatic slots; accept default reprs except for secret fields; collapse trivial `_x`+property aliases to public `x`. | `frozen` gives immutability + hash (constraint c); `kw_only` lifts the required-after-optional ban for deep hierarchies (dossier 13 §4); `eq=False` + inherited `Unique` dunders preserve id-only identity, which msgspec's all-field eq would break on unhashable fields (dossier 03 §2.1). | (i) msgspec default all-field `eq` — breaks id-only identity and hashing of list/dict fields. (ii) Hand-write `__eq__`/`__hash__` on every struct — redundant with `Unique`. | LOCKED (VERIFY: inherited `Unique` dunders survive under frozen+`eq=False`) | [../01-foundations/01-base-struct-conventions.md](../01-foundations/01-base-struct-conventions.md) |
| **D4** | **Custom scalar hooks: single global `dec_hook` (routes by annotation type) + single global `enc_hook` (routes by `type(obj)`), on reusable module-level Decoder/Encoder.** `Snowflake`, `Color`, `Permissions`, `UnicodeEmoji` covered; epoch-number datetimes and per-unit timedeltas via field-specific hooks; keep `time.unix_epoch_to_datetime` clamping. | Fields must be typed as the exact custom type for `dec_hook` to fire; msgspec cannot encode int subclasses natively, so encode needs a hook or pre-lowering (dossier 13 §8, §11). | (i) Type fields as plain int/str — loses the custom type. (ii) `strict=False` global — a blunt instrument that still won't coerce int→int-subclass (dossier 13 §8–9). | LOCKED (VERIFY: native datetime `Z`/offset/6-µs edges before dropping `ciso8601`) | [../01-foundations/02-custom-scalar-types-and-hooks.md](../01-foundations/02-custom-scalar-types-and-hooks.md) |
| **D5** | **UNDEFINED vs UNSET: keep `hikari.UNDEFINED`** as the field default for decoded tri-state fields (role ii); REST request params keep `UNDEFINED` unchanged. Fallback: adopt `msgspec.UNSET` for decoded-struct tri-state fields with a public `UndefinedOr`/`is UNDEFINED` compatibility shim. | Least invasive: thousands of `is UNDEFINED` checks and the whole REST-param layer are untouched (CONVENTIONS §5). UNDEFINED is largely a request concept; responses mostly need `None`/defaults. | (i) Replace `UNDEFINED` with `UNSET` project-wide — large public-API change to `UndefinedOr[T]`. | LOCKED (VERIFY: msgspec accepts `T \| UndefinedType` union + non-UNSET default producing default on absent keys) | [../01-foundations/03-undefined-and-unset.md](../01-foundations/03-undefined-and-unset.md) |
| **D6** | **JSON decode: replace `orjson` in `data_binding.py` with `msgspec.json`.** Untyped decode → `msgspec.json.decode(b)` (drop-in for `default_json_loads`); typed decode → module-level `msgspec.json.Decoder(SomeType).decode` per top-level entity type. | msgspec untyped decode returns plain dict/list exactly like `orjson.loads`; typed decode is the fast path and often beats dict decode (dossier 13 §11, §16). | (i) Keep orjson for decode, msgspec only for structs — two JSON engines, no single boundary. | LOCKED | [../01-foundations/04-json-data-binding.md](../01-foundations/04-json-data-binding.md), [../01-foundations/05-decode-boundary-and-decoders.md](../01-foundations/05-decode-boundary-and-decoders.md) |
| **D7** | **JSON encode + dependency: keep the hand-built request-body builders** feeding `msgspec.json.encode`; register the global `enc_hook`; audit for raw `Snowflake`/`Color` leaking into builder dicts. **msgspec becomes a core dependency; remove `orjson`; evaluate removing `ciso8601`.** | Builders already skip `UNDEFINED` and stringify snowflakes; msgspec int-key→str matches orjson `OPT_NON_STR_KEYS`. msgspec ships C wheels for CPython 3.10–3.14 (dossier 13 §11). | (i) Rewrite request encoding as declarative struct encode now — large orthogonal change (see D11). (ii) Keep orjson as an optional speedup — defeats the single-boundary goal. | LOCKED (VERIFY: wheel coverage across 3.10–3.14 incl. free-threaded) | [../01-foundations/00-dependencies-and-tooling.md](../01-foundations/00-dependencies-and-tooling.md), [../01-foundations/04-json-data-binding.md](../01-foundations/04-json-data-binding.md) |
| **D8** | **Cache: delete `attrs_extensions.py` entirely; drop 246 `@with_copy`; collapse 104 copy sites to identity returns; delete dead `Cell`.** `RefCell` and `GuildRecord` stay mutable. `*Data` layer decision presented (keep mutable carriers vs store frozen structs + `structs.replace`); `has_been_deleted` → `RefCell.deleted` flag; message edits via `structs.replace` + `RefCell.object` swap. `build_entity(app)` loses its `app` param; `FreezableDict.freeze`/`LimitedCapacityCacheMap.freeze` stay; repair the `set_role` no-copy asymmetry. | Frozen structs are safe to share by reference, so defensive copies are dead; `copy.deepcopy` is used nowhere and the deep-copy half is already dead in-tree (dossier 07 §0, §2.3, §10.1). | (i) Keep copying — pointless on immutable structs. (ii) Freeze `RefCell`/`GuildRecord` — impossible, they are the mutable GC primitives. | LOCKED (`*Data` keep-vs-drop is a maintainer sub-choice) | [../04-frozen-and-cache/01-cache-data-layer-and-mutation.md](../04-frozen-and-cache/01-cache-data-layer-and-mutation.md) |
| **D9** | **app removal & helpers: remove the `app` field from all JSON-decoded entities (24 decls, 64 injected entities) and the 163 `self.app.*` helper methods.** Pure/assert/arg-default helpers → delete + caller uses `rest.*`; the no-1:1-equivalent cluster → free functions or new rest methods; 10 "dead" `app` fields dropped free of fallout; normalize the two `shard_id` styles and the abstract-`app`-property vs field distinction. | msgspec cannot inject a runtime client during decode (constraint a); the target rest methods already exist — helpers are thin sugar, not new capability (dossier 04 §7.1). | (i) Post-decode `app` injection via `force_setattr` tree walk — needs a declared field on every node + a recursive walk; invasive and slow (dossier 13 §18). | LOCKED (events/interactions carved out to D10) | [../03-app-removal-and-helpers/00-strategy.md](../03-app-removal-and-helpers/00-strategy.md), [../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md](../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md) |
| **D10** | **Events & interactions app handling — FLAGGED.** Option 1: events (44 app fields) and interactions also go app-less + helper-less (max consistency, maximally breaking). Option 2 (recommended): events keep app + helpers (they are hand-constructed by the event/entity factory, so injection is trivial and the decode constraint does not bite), and interactions are constructed via a non-declarative path that injects app so latency-critical response sugar (`build_response`, `create_initial_response`) survives — with those methods also available on `rest.*`. | Events are not pure JSON-decoded structs; the "can't inject on decode" constraint only applies to decoded entities (dossier 08; CONVENTIONS §8). | Option 1 is the most-breaking reading; not silently chosen. | **FLAGGED — maintainer must choose** | [../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md](../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md), [../07-events/00-events-migration.md](../07-events/00-events-migration.md) |
| **D11** | **Special-endpoints builders: keep as-is in the first pass** (emit dicts via existing builders; `msgspec.json.encode` serializes the dict). Optionally later convert the 42 builders to frozen structs with `enc_hook` + `UNSET` omit-on-encode. | Builders serialize to Discord and are never decoded; converting them is a large orthogonal change touching the public builder API (CONVENTIONS §9). | (i) Convert builders now — scope creep into the public builder API. | LOCKED (builder conversion DEFERRED) | [../08-builders/00-special-endpoints-builders.md](../08-builders/00-special-endpoints-builders.md) |

## 4. OPEN — maintainer must confirm

Two categories of open item. Nothing in D1–D11 should be treated as final until the corresponding
item here is resolved. The consolidated tracker is
[../12-appendices/01-open-questions-and-verifications.md](../12-appendices/01-open-questions-and-verifications.md).

### 4.1 FLAGGED — design choices requiring a maintainer decision

| ID | Decision | Options | Recommendation | Owner file |
|---|---|---|---|---|
| **F-D10** | Events & interactions `app` handling (D10) | (1) app-less + helper-less, maximally consistent and maximally breaking; (2) keep app + helpers on events, inject app for interaction response sugar, also expose on `rest.*` | **Option 2** — events/interactions are hand-constructed, so the decode constraint does not force removal; option 2 preserves latency-critical response sugar and shrinks the public break | [../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md](../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md) |

### 4.2 VERIFY — empirical probes gating a locked default

Each probe has a named fallback if it fails. These must be run (foundations/enums authors) before the
dependent decision is relied on in code.

The global **V1–V9** here are the authoritative numbering. The local "VERIFY V1/V2" labels inside
[../01-foundations/00-dependencies-and-tooling.md](../01-foundations/00-dependencies-and-tooling.md)
are file-local and do **not** map to these: its wheel-coverage probe is global **V6**, and its
type-checker-native-`Struct` probe is **Q11** (see the tracker,
[../12-appendices/01-open-questions-and-verifications.md](../12-appendices/01-open-questions-and-verifications.md) §3).

Integer tagged-union `tag` dispatch (the mechanism behind every int-discriminated polymorphic family —
`type`/`entity_type`/`trigger_type`, OQ-EF-5) is **already verified**: dossier 13 §14 tested `tag=0`/`tag=2`
int dispatch end-to-end. It is settled, not an open VERIFY, and is therefore not listed below.

| ID | Gates | Probe | Fallback if it fails |
|---|---|---|---|
| **V1** | D3 | On msgspec `frozen=True, eq=False` where a non-Struct base (`snowflakes.Unique`) defines `__eq__`/`__hash__`: confirm the instance is immutable AND uses the inherited id-only dunders (msgspec does not set `__hash__ = None`). | Hand-write `__hash__`/`__eq__` on each struct or set them from `Unique`. |
| **V2** | D5 | Confirm (1) msgspec accepts a field annotated `T \| UndefinedType` with a non-UNSET default and produces the default on absent keys; (2) `T \| UndefinedType` is a legal msgspec union (UndefinedType is a bespoke singleton never decoded from JSON). | Adopt `msgspec.UNSET` (`T \| UnsetType`, `default=UNSET`) for decoded-struct tri-state fields + expose a public `UndefinedOr`/`is UNDEFINED` shim. |
| **V3** | D2 | Confirm `enum.IntFlag` preserves unknown bits (KEEP boundary) on the Python **3.10** floor, not just 3.11+. | Set `boundary=KEEP` explicitly or add a 3.10 shim; document per-flag. |
| **V4** | D2 | Confirm `str()` output **per enum family** — today it differs by base: **int** enums return the member **name** (base `Enum.__str__`, `enums.py:352-354`); **str** enums return the **value** (`str(Locale.EN_US) == "en-US"`, because `__str__` is popped for str-based enums at `enums.py:201-203`). Override `__str__` to the member **name** on the `_IntEnum` base and to the **value** on the `_StrEnum` base, reproducing today's behaviour exactly. (The "`MessageType.__str__` / `messages.py:327`" anchor cited elsewhere is a misattribution — `messages.py:327` is `Attachment.__str__`.) | Override `__str__` on each enum base to reproduce current output; note in the enums plan. |
| **V5** | D4/D7 | Confirm msgspec native RFC3339 datetime decode matches `ciso8601` on the `Z` suffix, arbitrary offsets, and 6-µs precision before dropping `ciso8601`. | Keep `ciso8601` / `time.iso8601_datetime_string_to_datetime` for entity timestamp decode. |
| **V6** | D7 | Confirm msgspec C-wheel availability across CPython 3.10–3.14 including free-threaded targets before making it a hard dependency. | Constrain `requires-python`/targets or gate free-threaded support. |
| **V7** | D4/D7 | Audit that no raw `Snowflake`/`Color` int-subclass leaks into a builder dict fed to `msgspec.json.encode` (which `TypeError`s on int subclasses). | Register the global `enc_hook` and/or ensure builders lower to plain int/str (`put_snowflake` already stringifies). |
| **V8** | D1/D2 | Confirm msgspec decodes a **string** JSON object key into an **int-enum** dict-key type — `authorizing_integration_owners` / `integration_types_config` keyed on `ApplicationIntegrationType(int(k))`. | Re-key in a layer-2 transform after decode. |
| **V9** | D1 | Confirm the `msgspec.Raw` peek-then-dispatch prepass reproduces today's soft-skip (log + drop) semantics for unknown polymorphic elements and preserves wire order (components in action-rows/containers, some audit-log entries). | Keep a hand-written dispatch loop retaining the current soft-skip + ordering. |

## 5. Sub-decisions surfaced (not blocking, but presented for the maintainer)

- **D8 `*Data` layer:** keep `*Data` as mutable non-frozen carriers wrapping frozen public structs,
  **or** store frozen structs directly and move mutation to `RefCell` + `msgspec.structs.replace`.
  Recommend the least-churn path; specify `has_been_deleted` on `RefCell` and message edits via
  `structs.replace`. Owned by [../04-frozen-and-cache/01-cache-data-layer-and-mutation.md](../04-frozen-and-cache/01-cache-data-layer-and-mutation.md).
- **D2 scalar-enum caching:** whether to mirror hikari's bounded `_MAX_CACHED_MEMBERS = 4096`
  pseudo-member cache (`enums.py:39`) or accept stdlib behavior. Owned by
  [../02-enums/02-int-and-str-enums-migration.md](../02-enums/02-int-and-str-enums-migration.md).
- **D6 decode boundary:** bytes-in typed decode (fast, wide interface churn) vs dict-in via
  `msgspec.convert` (localized, slower) as the incremental bridge. Owned by
  [../01-foundations/05-decode-boundary-and-decoders.md](../01-foundations/05-decode-boundary-and-decoders.md).

## 6. Change control

Any change to D1–D11 or the OPEN items is made here first, then propagated to the owner file. A
downstream file that needs to deviate records the deviation inline and links to this log; it does not
silently override a decision.
