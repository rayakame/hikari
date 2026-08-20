# Target Architecture

The end-state data model and decode/encode pipeline, expanding CONVENTIONS §1 (decision D1). This is
the reference every model-module and factory plan file frames itself against: each model states
whether it is "declarative-decodable" or "needs a residual transform," and why.

## 1. Objective

Define the shape the migration converges on — **declarative-first, transform-residual, app-less** —
concretely enough that per-module authors can classify each model and route it through the right
path. Serves all three constraints simultaneously: the target structs are frozen (c), app-less (a),
and strictly enum-typed (b).

## 2. The two-layer model

msgspec cannot express hikari's full deserialization declaratively for ~13 hard-case categories
(dossier 05 §6). A pure single-layer `decode(bytes, type=PublicStruct)` is **not achievable**. The
realistic shape is two layers (dossier 05 §9):

1. **Layer 1 — declarative wire decode.** `msgspec.json.decode(bytes, type=Struct)` decodes Discord
   JSON into frozen structs, using tagged unions for polymorphism, native types for scalars, a global
   `dec_hook` for custom scalars, and `field(name=…)` for key renames. Most flat leaf models decode
   fully at this layer.
2. **Layer 2 — residual transform factory.** A slimmed `entity_factory` transforms wire structs
   (or `msgspec.Raw`) into public frozen structs for the hard cases: array→keyed-`Mapping` re-keying,
   flattened grandchild fields, sibling-dependent value typing, parent→child context injection,
   computed fields, classmethod construction, and the lazy `GatewayGuildDefinition`. **It never
   injects `app`.**

Where a model is fully declarative, layers 1 and 2 collapse into a single decode call. Where it is
not, layer 2 does the minimum extra work.

## 3. Data-flow diagram

```
                        DISCORD (REST response body / gateway frame / interaction POST body)
                                                   |
                                                   |  raw bytes
                                                   v
                    +-------------------------------------------------------------+
                    |  hikari/internal/data_binding.py  (the single JSON boundary)|
                    |  untyped:  msgspec.json.decode(b)            -> dict/list    |
                    |  typed:    module-level Decoder(T).decode(b) -> T           |
                    +-------------------------------------------------------------+
                                                   |
                          +------------------------+------------------------+
                          |                                                 |
                 (declarative path)                               (residual path)
                          |                                                 |
                          v                                                 v
        msgspec.json.Decoder(PublicStruct)                 msgspec.json.Decoder(WireStruct | Raw)
                          |                                                 |
             per-field dec_hook fires for:                        wire structs / msgspec.Raw
             Snowflake, Color, Permissions,                                 |
             UnicodeEmoji (D4) + custom enums (D2)                          v
                          |                            +-----------------------------------------+
             tagged-union dispatch on the             |  slimmed entity_factory (Layer 2)       |
             `type` discriminator (D1):               |   - array -> Mapping[Snowflake, T]      |
             channels / interactions /                |   - flatten grandchild fields           |
             components / commands /                   |   - sibling-dependent value typing      |
             auto-mod / scheduled events              |   - context inject guild_id / user_id   |
                          |                            |   - computed fields, tag @everyone role |
                          |                            |   - Embed.from_received_embed           |
                          |                            |   - lazy GatewayGuildDefinition         |
                          |                            +-----------------------------------------+
                          |                                                 |
                          +------------------------+------------------------+
                                                   |
                                                   v
                             +-----------------------------------------------+
                             |  FROZEN, APP-LESS PUBLIC STRUCT               |
                             |  class X(snowflakes.Unique, msgspec.Struct,   |
                             |          frozen=True, kw_only=True, eq=False) |
                             |    id: Snowflake                             |
                             |    ...                                        |
                             |    # NO app field. NO self.app.* helpers.     |
                             +-----------------------------------------------+
                                                   |
                          +------------------------+------------------------+
                          |                                                 |
                          v                                                 v
                 returned to caller                                stored in cache
                 (rest.* / event payload)                    (shared by reference — safe
                                                              because frozen; no copy.copy;
                                                              RefCell/GuildRecord stay mutable)

         ENCODE (request bodies), unchanged first pass:
              hand-built JSONObjectBuilder dict  --(msgspec.json.encode + enc_hook)-->  bytes
              enc_hook lowers Snowflake->str, Color->int, Permissions->str  (D4/D7)
```

The **gateway event path** (decisions D12/D13) applies the same two-layer shape one level up:

```
   gateway frame -> envelope decode (op/t/s, d: msgspec.Raw) -> name-keyed dict[str, Decoder]
                 -> thin hydration layer (attach shard + cache-fed old_*, guild-vs-DM class split,
                    sibling-context threading, GUILD_CREATE laziness) -> dispatch
```

The envelope is decoded once with the `"d"` payload captured as `msgspec.Raw`, so a disabled
consumer never pays for a full parse; the per-name `Decoder` is the only full decode of `d`, and
the residual hydration layer replaces most of `impl/event_factory.py` (1216 lines → est. 400–550,
dossier 17). Events are frozen and app-less like the entities they wrap, but keep `shard` on the
event object (D13, maintainer-confirmed). Full detail in
[../07-events/00-events-migration.md](../07-events/00-events-migration.md); empirical grounding in
[../12-appendices/04-event-pipeline-feasibility.md](../12-appendices/04-event-pipeline-feasibility.md)
(dossiers 17–20).

## 4. The canonical public struct

The wire model shape locked as decision D3 (CONVENTIONS §2):

```python
class PartialChannel(snowflakes.Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    id: snowflakes.Snowflake
    name: str | None = None
    type: ChannelType = ...
    # NO app field.
```

Rules that shape the whole hierarchy (full detail in
[../01-foundations/01-base-struct-conventions.md](../01-foundations/01-base-struct-conventions.md)):

- **`frozen=True, kw_only=True`** on the hierarchy base classes; msgspec inherits struct config to
  subclasses (dossier 13 §1). `kw_only` is mandatory because hikari's deep hierarchies add required
  fields in subclasses after optional base fields, which msgspec bans unless `kw_only=True`
  (dossier 13 §4).
- **Identity stays id-only.** The `snowflakes.Unique` ABC already defines id-based
  `__eq__`/`__hash__` (`snowflakes.py:103-132`). Structs are declared **`eq=False`** so msgspec does
  not generate all-field `__eq__`/`__hash__` (which would break on unhashable list/dict fields and
  change identity semantics). This inheritance-under-`eq=False` behavior is **empirically confirmed**
  (D3, dossier 16): msgspec does not null the inherited `Unique.__hash__` under `eq=False`; residual is
  a CPython 3.10-floor re-run.
- **The `class X(snowflakes.Unique, msgspec.Struct, …)` form above (and in the §3 diagram) is a
  sketch, not literally buildable.** As written it raises `TypeError: metaclass conflict` because
  `StructMeta` is not an `abc.ABCMeta` subclass. Id-identity structs subclass the shared,
  metaclass-carrying `UniqueStruct` base (`class _StructABCMeta(abc.ABCMeta, type(msgspec.Struct))`;
  R1) and repeat `frozen=True, kw_only=True` on every level that adds fields (`kw_only` does not
  reliably inherit; R2) — see
  [../01-foundations/01-base-struct-conventions.md](../01-foundations/01-base-struct-conventions.md)
  §3–§4 for the exact recipe.
- **Slots are automatic** (msgspec structs are always slotted, no `__dict__`), matching attrs
  `slots=True` + `weakref_slot=False` (dossier 13 §1).

## 5. Declarative vs residual — the classification each author must state

| Category | Declarative? | Mechanism | Reference |
|---|---|---|---|
| Flat leaf, scalar/nullable/renamed fields, no app | Yes | `decode(bytes, type=X)` + `field(name=…)` | dossier 05 §9 |
| Custom scalar fields (`Snowflake`, `Color`, `Permissions`, `UnicodeEmoji`) | Yes | global `dec_hook` (D4) | [../01-foundations/02-custom-scalar-types-and-hooks.md](../01-foundations/02-custom-scalar-types-and-hooks.md) |
| Polymorphic by literal `type` discriminator | Yes | tagged unions (D1) | [../05-entity-factory/01-polymorphism-and-tagged-unions.md](../05-entity-factory/01-polymorphism-and-tagged-unions.md) |
| Strict enum fields | Yes | custom `Enum`/`Flag` via global `dec_hook`; #2770 pseudo-members on unknown values (D2) | [../02-enums/00-strategy-and-forward-compat.md](../02-enums/00-strategy-and-forward-compat.md) |
| Nullable / omittable fields | Yes | `T \| None`; default `None`/`UNSET`/factory | dossier 13 §15 |
| Array → keyed `Mapping[Snowflake, T]` | No | post-decode re-keying transform | [../05-entity-factory/02-hard-cases-and-transforms.md](../05-entity-factory/02-hard-cases-and-transforms.md) |
| Flattened grandchild fields (role tags, integration account, message snapshot) | No | residual transform / raw-struct intermediate | dossier 05 §3h, §6.5 |
| Sibling-dependent value typing (command-option value, audit-log change, forum-tag emoji, role color) | No | residual transform / `dec_hook` on parent | dossier 05 §3j, §6.3 |
| Context injection (`guild_id`/`user_id`/`member` threaded from parent) | No | residual transform (36 context-kwarg methods) | dossier 05 §6.11 |
| Computed fields (sticker tag split, hex→bytes key, `role_ids` @everyone append, timedelta units) | No | residual transform | dossier 05 §3i, §6.6 |
| Classmethod construction (`Embed.from_received_embed`, `ColorGradient.of`) | No | residual transform | dossier 05 §6.7 |
| Lazy `GatewayGuildDefinition` | No | preserved bespoke lazy object | dossier 05 §4 |
| Epoch-number datetimes with max/min clamping | No | field-specific hook / int field + transform | dossier 05 §6.12; [../01-foundations/02-custom-scalar-types-and-hooks.md](../01-foundations/02-custom-scalar-types-and-hooks.md) |

## 6. Polymorphic dispatch — two behaviors to preserve

msgspec tagged unions raise `ValidationError` on an unknown tag (dossier 13 §14), which **matches**
today's hard-fail dispatch (`UnrecognisedEntityError`) for channels, threads, interactions, auto-mod,
and scheduled events (dossier 02 §D.2). Where the factory instead **soft-skips** unknown types
(components in action rows/containers, some audit entries — dossier 05 §3, §6.2), a `msgspec.Raw`
peek-then-dispatch prepass (or retained hand dispatch) is needed to keep the skip semantics. This is
the one place a hook/post-pass is required for polymorphism.

## 7. Encode path

Encoding is intentionally left hand-built in the first pass (decision D7). Request-body builders emit
dicts; `msgspec.json.encode` serializes them, with the global `enc_hook` lowering int/str subclasses
(`Snowflake→str`, `Color→int`, `Permissions→str`) because **msgspec cannot encode int subclasses
natively** — the docs claim otherwise but this is empirically false in 0.21.1 (dossier 13 §11). An
audit is required for any raw `Snowflake`/`Color` leaking into builder dicts
([../01-foundations/04-json-data-binding.md](../01-foundations/04-json-data-binding.md)).

## 8. What the architecture removes

- The `app` field on every wire entity **and every event** (44 event `app` fields + 31 delegating
  properties + the `ExceptionEvent.app` proxy), plus ~156 of the 173 app-delegating helper methods
  (~114 wire-entity + 42 event; the ~17 interaction helpers await D10-interactions) — constraint (a)
  plus the D10-events decision.
- `hikari/internal/attrs_extensions.py` in full and 246 `@with_copy` decorations (constraint c).
- 104 cache `copy.copy` sites, collapsed to identity returns (constraint c).
- The ~150 `| int`/`| str` enum-tolerance unions on entity fields — dropped by #2770's strict typing;
  the fast custom enum metaclasses in `hikari/internal/enums.py` are **kept**, not removed (constraint b).
- `orjson` from the JSON boundary (D6/D7).

## 9. Open questions

The architecture's incremental path (two-layer bridge via `msgspec.convert` for dict-in, versus
bytes-in typed decode) is a sequencing decision detailed in
[../01-foundations/05-decode-boundary-and-decoders.md](../01-foundations/05-decode-boundary-and-decoders.md)
and [../11-rollout/00-phasing-and-sequencing.md](../11-rollout/00-phasing-and-sequencing.md). Of
the app decision, only the interactions half remains FLAGGED (D10-interactions): the events half is
resolved — events are app-less and follow the D12 pipeline above — while interactions either join
the app-less path too or keep a hand-constructed app-injecting path (the recommendation is to keep
`app` + response sugar). See [05-decisions-log.md](05-decisions-log.md).
