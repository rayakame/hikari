# Entity factory: architecture and decode strategy

The `entity_factory` is the single largest and most load-bearing subsystem in this migration.
Every Discord JSON payload (REST + gateway + interaction server) passes through it to become a
model. This file defines the target two-layer decode architecture, classifies the ~157 wire
classes into declarative-decodable vs residual-transform, and specifies the decode boundary.

Scope: `hikari/api/entity_factory.py` (interface, 2180 lines) and
`hikari/impl/entity_factory.py` (implementation, 4857 lines / 233 KB). Sibling files in this
cluster:
[`01-polymorphism-and-tagged-unions.md`](./01-polymorphism-and-tagged-unions.md),
[`02-hard-cases-and-transforms.md`](./02-hard-cases-and-transforms.md),
[`03-serialize-methods.md`](./03-serialize-methods.md).

---

## 1. Objective

Re-shape the hand-written traversal factory into the **declarative-first, transform-residual,
app-less** target of decision D1 (see [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md)),
serving all three maintainer constraints:

- **(a) no `app` injection during decode** — the factory stops injecting `self._app` into the 64
  construction sites; models lose the `app` field.
- **(b) strict enums** — the `SomeEnum | int` tolerance unions on decoded fields are removed;
  forward-compat moves into the enum design (D2).
- **(c) frozen structs** — models become immutable, which (as shown in §6 below) forces every
  transform out of `__post_init__` and into `dec_hook`s or an explicit post-decode pass.

The end-state is `msgspec.json.decode(bytes, type=WireStruct)` doing the bulk-parse in Rust, with a
**slimmed residual factory** performing only the ~13 transform categories that cannot be expressed
declaratively.

---

## 2. Current state

### 2.1 Data flow (as-is)

```
raw bytes --(orjson.loads / json.loads)--> plain dict/list --(deserialize_*)--> attrs model
```

JSON decode happens **outside** the factory. `hikari/internal/data_binding.py:107-123` sets
`default_json_loads = orjson.loads`; the REST/gateway/interaction layers decode to a dict first,
then call the factory:

| Caller | Anchor | Call |
|---|---|---|
| REST | `hikari/impl/rest.py:1012` | `body = self._loads(await response.read())` |
| REST | `hikari/impl/rest.py:1062` | `self._entity_factory.deserialize_channel(response)` |
| Gateway shard | `hikari/impl/shard.py:200` | `val = self._loads(pl)` |
| Interaction server | `hikari/impl/interaction_server.py:442` | `payload = self._loads(body)` |

Consequence: the `deserialize_*` signature is `(payload: data_binding.JSONObject) -> Model` — an
already-decoded `Mapping[str, Any]` (`data_binding.py:66`), **never bytes**. msgspec's fast path is
`msgspec.json.decode(bytes, type=Struct)` (bytes → struct in one pass); a dict-in interface forces
the slower `msgspec.convert(dict, type=Struct)`. The decode boundary is a genuine decision — see §5
and [`../01-foundations/05-decode-boundary-and-decoders.md`](../01-foundations/05-decode-boundary-and-decoders.md).

### 2.2 The factory is a giant stateful traversal layer

`EntityFactoryImpl` (`hikari/impl/entity_factory.py:456`) is **stateful**: `__init__`
(`hikari/impl/entity_factory.py:485`) builds **18 instance dispatch dictionaries** onto `__slots__`
(`464-483`), plus a 19th module-level table (`_interaction_option_type_mapping`, `81`), that map a
Discord type-int → a bound deserializer. It holds `self._app` (the `RESTAware` client), injected
into 64 model constructors.

### 2.3 Method and idiom inventory (verified counts, dossier 05 §2-3)

| Metric | Count | Source |
|---|---|---|
| Public `deserialize_*` (impl) | 91 | `grep -c "def deserialize_"` |
| Public `serialize_*` (impl) | 7 | `grep -c "def serialize_"` — see [`03-serialize-methods.md`](./03-serialize-methods.md) |
| Private `_deserialize_*` helpers | 61 | `grep -c "def _deserialize_"` |
| Private `_set_*` attribute builders | 4 | `grep -c "def _set_"` |
| Dispatch tables | 19 | 18 instance (`464-483`) + 1 module-level (`81`) |
| app-injection sites | 64 (63 `app=self._app` + 1 `app=self._entity_factory.app`) | see [`../03-app-removal-and-helpers/01-app-field-removal.md`](../03-app-removal-and-helpers/01-app-field-removal.md) |
| Wire classes constructed by the factory | 157 | dossier 03 §4.1; see [`../06-model-modules/00-README.md`](../06-model-modules/00-README.md) |

Recurring decode idioms and their frequencies (impl file):

| Idiom | Occurrences | msgspec disposition |
|---|---|---|
| `snowflakes.Snowflake(...)` | 241 | `dec_hook` on `Snowflake`-typed field (D4) |
| `payload["..."]` required key | 822 | declarative required field |
| `payload.get(...)` optional key | 386 | declarative optional / `T \| None` |
| `undefined.UNDEFINED` | 111 | field `default=UNDEFINED` (D5) |
| `in payload` membership tests | 173 | absent-key → default |
| `:= payload.get(...)` walrus | 129 | absent-key → default / transform |
| `int(...)` casts | 83 | int-from-string via hook / `str` field |
| `time.iso8601_datetime_string_to_datetime(...)` | 44 | native RFC3339 decode (D4) |
| `time.unix_epoch_to_datetime(...)` | 4 | field-specific hook (epoch numbers) |
| `datetime.timedelta(...)` | 28 | `Annotated` per-field hook (D4) |
| list/dict comprehensions & loops | 139 | array→Mapping re-keying (residual) |
| `_LOGGER.debug("Unrecognised/Unknown …")` soft-skip | 45 | Raw peek prepass (see [`01-polymorphism-and-tagged-unions.md`](./01-polymorphism-and-tagged-unions.md)) |
| `raise errors.UnrecognisedEntityError` | 11 | tagged-union raise-on-unknown-tag |
| `color_models.Color(...)` | 14 | `dec_hook` on `Color` |
| `locales.Locale(...)` | 22 | str-enum `_missing_` (D2) |
| `permission_models.Permissions(...)` | 18 | `dec_hook` `Permissions(int(obj))` |

---

## 3. Target design: the two-layer decode architecture

A single-layer `decode(bytes, type=PublicStruct)` is **not achievable** for the ~13 hard-case
categories (dossier 05 §6; enumerated in [`02-hard-cases-and-transforms.md`](./02-hard-cases-and-transforms.md)).
The target is a **two-layer** design:

```
             LAYER 1 (declarative, Rust-fast)          LAYER 2 (residual factory, Python)
bytes ──► msgspec.json.Decoder(WireStruct).decode ──► transform(wire) ──► public frozen Struct
             │                                            │
             ├─ tagged unions (polymorphism)              ├─ array → keyed Mapping re-keying
             ├─ dec_hook (Snowflake/Color/Permissions)    ├─ flattened grandchild fields
             ├─ native datetime (RFC3339)                 ├─ sibling-dependent value typing
             ├─ field(name=…) key rename                  ├─ parent→child context injection
             └─ default=UNDEFINED tri-state               ├─ computed fields / classmethods
                                                          └─ lazy GatewayGuildDefinition
```

- **Layer 1 — wire Structs.** Frozen `msgspec.Struct`s mirroring Discord JSON 1:1, decoded from
  bytes in one pass. They carry native types, `field(name=…)` renames, tagged unions, and
  `default=UNDEFINED` for tri-state fields. Custom scalars (`Snowflake`, `Color`, `Permissions`,
  `UnicodeEmoji`) decode via the single global `dec_hook` (D4;
  [`../01-foundations/02-custom-scalar-types-and-hooks.md`](../01-foundations/02-custom-scalar-types-and-hooks.md)).
- **Layer 2 — residual factory.** A much smaller `EntityFactoryImpl` whose `deserialize_*` methods
  no longer hand-parse every field; they call the layer-1 decoder, then apply only the transforms
  that msgspec cannot do. **It never injects `app`.** Where the wire shape already equals the public
  shape (see §4), the wire Struct *is* the public Struct and layer 2 is a pass-through.

The public model shape, the `UnrecognisedEntityError` / soft-skip semantics, and the
`GatewayGuildDefinition` lazy contract are all preserved by layer 2. See dossier 05 §9.

### 3.1 Illustrative split — a pure-declarative leaf vs a residual transform

```python
# LAYER 1 wire == public (VoiceRegion is app-less, all-scalar, no polymorphism):
class VoiceRegion(msgspec.Struct, frozen=True, kw_only=True, rename={"is_optimal": "optimal"}):
    id: str
    name: str
    is_optimal: bool
    is_deprecated: bool = msgspec.field(name="deprecated")
    is_custom: bool = msgspec.field(name="custom")
# deserialize_voice_region == the module-level Decoder(VoiceRegion).decode — no layer-2 body.

# LAYER 1 wire != public (guild roles arrive as a JSON array, public field is a Mapping):
class _WireGuild(msgspec.Struct, frozen=True, kw_only=True):
    id: snowflakes.Snowflake
    roles: list[_WireRole]              # Discord sends an array
    # …
def deserialize_rest_guild(data: bytes) -> RESTGuild:
    w = _guild_decoder.decode(data)
    roles = {r.id: _to_role(r, guild_id=w.id) for r in w.roles}   # re-key + context inject
    return RESTGuild(id=w.id, roles=roles, …)                     # frozen public Struct
```

---

## 4. Which of the 157 wire classes are declarative vs residual

Classification uses dossier 05 §9 and the per-class inventory in dossier 03 §4.1. The
per-module recipes live in [`../06-model-modules/`](../06-model-modules/); this table is the
factory-level summary that drives how much layer-2 code survives.

### 4.1 Declarative-decodable (layer 1 == public, or +`dec_hook`/`field(name=…)` only)

Flat leaf models with scalar / renamed / nullable fields, no `app`, no polymorphism, no re-keying,
no sibling logic. These collapse to a module-level `Decoder(Struct).decode` with an empty layer-2
body:

- `voices.VoiceRegion` (`4589`) — cleanest; already app-less, all scalars.
- `stickers.PartialSticker`, `guilds.IntegrationAccount`, `guilds.BulkBanResponse`,
  `guilds.GuildBan`, `guilds.WelcomeChannel`, `embeds.EmbedField`, `polls.PollAnswerCount`,
  `messages.ReactionCountDetails`, `components.MediaGalleryItem`, `components.TextDisplayComponent`,
  `components.SeparatorComponent`, `components.ThumbnailComponent`.
- With `field(name=…)` only: most channel field subsets, `messages.Attachment`,
  `embeds.EmbedProvider`, `invites.VanityURL` (minus app).
- With `dec_hook` only (custom scalars but otherwise flat): any leaf whose sole complication is a
  `Snowflake` / `Color` / `Permissions` / `UnicodeEmoji` field.

### 4.2 Residual-transform (need a layer-2 body)

Any class hitting one of the 13 categories. The heavy hitters:

| Category | Representative classes | Detail |
|---|---|---|
| Polymorphic dispatch | all channels, interactions, components, scheduled events, auto-mod, webhooks, commands | [`01-polymorphism-and-tagged-unions.md`](./01-polymorphism-and-tagged-unions.md) |
| Array→Mapping re-keying | `RESTGuild`/`GatewayGuild` roles/emojis/stickers, `Message` mentions, resolved interaction data, `GroupDMChannel` recipients | [`02-hard-cases-and-transforms.md`](./02-hard-cases-and-transforms.md) §2 |
| Flattened grandchild fields | `Role` (tags), `PartialIntegration` (account), `MessageSnapshot`, auto-mod triggers/actions, `ScheduledExternalEvent` (location) | [`02`](./02-hard-cases-and-transforms.md) §3 |
| Sibling-dependent typing | `CommandInteractionOption.value`, `AuditLogChange`, `ForumTag` emoji, `Role` color/colors | [`02`](./02-hard-cases-and-transforms.md) §4 |
| Context injection | `Member`/`Role`/`VoiceState`/threads (guild_id/user_id/member) — 36 `UndefinedOr` context-kwarg methods | [`02`](./02-hard-cases-and-transforms.md) §5 |
| Computed / classmethod | `StandardSticker` tags split, `Application.public_key` hex→bytes, `Embed.from_received_embed`, `ColorGradient.of` | [`02`](./02-hard-cases-and-transforms.md) §6-7 |
| Lazy guild | `GatewayGuild` via `_GatewayGuildDefinition` | [`02`](./02-hard-cases-and-transforms.md) §8 |

The two heaviest single methods — `deserialize_message` (`4032`) and `deserialize_partial_message`
(`3888`), both flagged `# noqa: C901, PLR0912, PLR0915` — hit nearly every category at once and
retain the largest layer-2 bodies.

---

## 5. Decode boundary: dict-in vs bytes-in

msgspec is fastest bytes-in. Two paths (decision, cross-linked to
[`../01-foundations/05-decode-boundary-and-decoders.md`](../01-foundations/05-decode-boundary-and-decoders.md)
and consolidated sub-decision SD3 in [`../12-appendices/01-open-questions-and-verifications.md`](../12-appendices/01-open-questions-and-verifications.md)):

1. **Incremental bridge (dict-in).** Keep the `deserialize_*(JSONObject)` signatures; inside, run
   `msgspec.convert(payload, type=WireStruct, dec_hook=…, strict=False)` instead of hand-parsing.
   Localized: no caller churn in rest.py / shard.py / interaction_server.py. Slower (double-parse:
   orjson→dict→convert), but achieves constraints (a)+(b)+(c) before the speed win.
2. **End-state (bytes-in).** Push the decode boundary down: `deserialize_*(bytes)` calling a
   module-level `msgspec.json.Decoder(WireStruct).decode`. Single-pass, full msgspec speed, but
   changes **every** abstract signature in `hikari/api/entity_factory.py` and every caller
   (`rest.py:1012,1062`, `shard.py:200`, `interaction_server.py:442`, `gateway_bot.py`).

Recommendation (D6/D7): sequence bytes-in as the end-state, use dict-in via `msgspec.convert` as the
incremental bridge so the mechanical passes land first. The `GatewayGuildDefinition` lazy path (§6)
is the one place that must keep raw bytes / `msgspec.Raw` regardless of the global choice.

---

## 6. Frozen forbids in-struct mutation (constraint (c))

msgspec **does** call `__post_init__` on a frozen struct, but assigning to a field there raises —
you must use `msgspec.structs.force_setattr` / `object.__setattr__`. Any strategy that leans on
`__post_init__` to do re-keying, enum tolerance, or flattening fights the frozen constraint. This is
the structural reason the transform work lives in layer 2 (an external function) or a `dec_hook`,
**not** in the struct. Confirmed and expanded in
[`02-hard-cases-and-transforms.md`](./02-hard-cases-and-transforms.md) §1 and
[`../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md`](../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md).

---

## 7. Step-by-step migration

1. **Freeze the interface contract.** Decide dict-in bridge vs bytes-in end-state (§5). Record in
   [`../12-appendices/01-open-questions-and-verifications.md`](../12-appendices/01-open-questions-and-verifications.md) (SD3).
   Default: dict-in bridge first.
2. **Land the foundations** first (they gate everything here): the global `dec_hook`/`enc_hook`
   ([`../01-foundations/02-custom-scalar-types-and-hooks.md`](../01-foundations/02-custom-scalar-types-and-hooks.md)),
   the `UNDEFINED` default strategy
   ([`../01-foundations/03-undefined-and-unset.md`](../01-foundations/03-undefined-and-unset.md)),
   the module `Decoder` registry
   ([`../01-foundations/05-decode-boundary-and-decoders.md`](../01-foundations/05-decode-boundary-and-decoders.md)),
   and the stdlib enum port ([`../02-enums/`](../02-enums/)).
3. **Convert leaf declarative models** (§4.1) module by module in dependency order (per
   [`../06-model-modules/00-README.md`](../06-model-modules/00-README.md)): define the frozen wire
   Struct, register a module-level `Decoder`, replace the method body with a single `decode`/
   `convert` call. Start with `VoiceRegion` as the reference conversion.
4. **Build the polymorphic layer.** For each of the 15 dispatch families, add `Literal` tag fields
   and assemble tagged unions; build the `msgspec.Raw` peek prepass for the soft-skip families. See
   [`01-polymorphism-and-tagged-unions.md`](./01-polymorphism-and-tagged-unions.md).
5. **Build the residual transform layer** for the 13 hard-case categories, method by method. See
   [`02-hard-cases-and-transforms.md`](./02-hard-cases-and-transforms.md).
6. **Remove `app` injection.** Delete all 64 app-injection sites (63 `app=self._app` + 1
   `app=self._entity_factory.app`) and drop `self._app` from `EntityFactoryImpl.__slots__` once no
   method reads it. Cross-linked to
   [`../03-app-removal-and-helpers/01-app-field-removal.md`](../03-app-removal-and-helpers/01-app-field-removal.md).
7. **Migrate the 7 serialize methods** last (they are outbound and independent). See
   [`03-serialize-methods.md`](./03-serialize-methods.md).
8. **Flip the decode boundary** to bytes-in (if chosen) once all methods are converted, updating
   rest.py / shard.py / interaction_server.py callers together.

---

## 8. Affected files and symbols

| Path | Anchor | Change |
|---|---|---|
| `hikari/impl/entity_factory.py` | class `456`, `__init__` `485` | slim to layer-2; drop `self._app`; 18 dispatch tables → tagged unions |
| `hikari/impl/entity_factory.py` | module table `81` | `_interaction_option_type_mapping` → sibling-typed transform |
| `hikari/api/entity_factory.py` | 91 `deserialize_*` + 7 `serialize_*` abstracts | signature bytes-in (end-state) or unchanged (bridge) |
| `hikari/api/entity_factory.py` | `GatewayGuildDefinition` `63` | lazy contract preserved |
| `hikari/internal/data_binding.py` | `107-123` | orjson→msgspec loads/dumps (D6) |
| `hikari/impl/rest.py` | `1012,1062` | decode-call shape (bridge: unchanged; end-state: bytes) |
| `hikari/impl/shard.py` | `200` | gateway frame decode boundary |
| `hikari/impl/interaction_server.py` | `442` | interaction decode boundary |

---

## 9. Risks and gotchas

- **Double-parse cost in the bridge.** dict-in via `msgspec.convert` parses twice (orjson→dict, then
  convert). This is temporary and must not be benchmarked as the end-state; measure bytes-in
  separately (see [`../11-rollout/02-performance-benchmarking.md`](../11-rollout/02-performance-benchmarking.md)).
- **Wire-vs-public divergence maintenance.** The two-layer split doubles some class definitions
  (`_WireRole` + `Role`). Keep wire Structs private (`_`-prefixed) and generated close to their
  public model to limit drift.
- **`GatewayGuildDefinition` laziness** must survive: a naive eager decode of `GUILD_CREATE` regresses
  memory/CPU on large guilds. Layer 2 keeps the raw payload (`msgspec.Raw`) and decodes on demand.
- **Enum strictness behavior change.** Where the factory currently returns a raw `int` on unknown
  enum values, the ported stdlib enums mint a value-preserving pseudo-member (D2). Document per
  module.
- **Soft-skip vs raise reconciliation.** msgspec tagged unions raise on unknown tag; today channels/
  interactions raise but components/audit-entries soft-skip. Preserved via the Raw peek prepass — see
  [`01-polymorphism-and-tagged-unions.md`](./01-polymorphism-and-tagged-unions.md) §4.

---

## 10. Verification

1. **Round-trip corpus test.** Capture real payloads for all 91 `deserialize_*` methods; assert the
   msgspec two-layer output equals the current attrs output field-by-field (id-based `__eq__` plus a
   deep structural compare helper).
2. **Boundary parity.** For the dict-in bridge, assert `convert(orjson.loads(b))` equals the
   end-state `Decoder.decode(b)` on the same fixtures.
3. **Unknown-value behavior.** Feed unknown enum ints/strings and unknown polymorphic tags; assert
   the pseudo-member (D2) and the preserved raise/soft-skip semantics (per family).
4. **No `app`.** `assert not hasattr(entity, "app")` across all decoded entities; grep the impl for
   residual `self._app` reads.
5. **Frozen.** `assert isinstance(struct, msgspec.Struct)` and that `setattr` raises `AttributeError`
   on every decoded model.

---

## 11. Open questions and decisions

Consolidated in the master gate
[`../12-appendices/01-open-questions-and-verifications.md`](../12-appendices/01-open-questions-and-verifications.md);
the entity-factory items map onto it as follows:

- **One-layer vs two-layer:** **resolved** — two-layer (wire Struct + residual transform), locked as
  D1. A pure single-layer decode is not achievable for the 13 hard-case categories.
- **Decode boundary:** consolidated sub-decision **SD3** — dict-in `msgspec.convert` bridge → bytes-in
  end-state. Confirm the timing of the bytes-in flip relative to the rollout phases.
- **GatewayGuildDefinition laziness:** **resolved** — preserve via `msgspec.Raw` (recommended over
  eager decode); see [`02-hard-cases-and-transforms.md`](./02-hard-cases-and-transforms.md) §8.
- **Soft-skip vs raise per union:** consolidated probe **V9** (+ decision **Q8**) — reconcile per
  polymorphic family; see [`01-polymorphism-and-tagged-unions.md`](./01-polymorphism-and-tagged-unions.md).
