# Decode Boundary and Decoders

Where typed decoding happens: the dict-in vs bytes-in boundary decision, a module-level
`Decoder` registry keyed by top-level entity type, `msgspec.Raw` for deferred/polymorphic
payloads, and `msgspec.convert` as the incremental bridge from today's dict-based factory.
Serves the declarative-decode end-state (D1) and sequences it behind an incremental path.

## 1. Objective

- Choose the decode boundary (dict-in vs bytes-in) for the end-state and the incremental path.
- Define how reusable typed `Decoder`s are held and where `Raw`/`convert` fit.
- Give the entity-factory cluster ([`../05-entity-factory/`](../05-entity-factory/00-architecture-and-decode-strategy.md))
  a concrete seam to migrate against without a big-bang rewrite.

## 2. Current state (file:line)

Decode is **two-stage** today (dossier 01 §8.4): `_loads(bytes) -> dict`, then
`entity_factory.deserialize_*(dict) -> attrs model`. The `deserialize_*(JSONObject)` interface is
**dict-in** everywhere.

Decode call sites (dossier 01 §2.2, all `bytes`-in from `response.read()`/ws frame/webhook body):

| File:line | Call | Notes |
|-----------|------|-------|
| `rest.py:895` | `self._loads(await response.read())` | main REST success path (content-type gated `:893`) |
| `rest.py:1012` | `self._loads(await response.read())` | 429 ratelimit body |
| `shard.py:200` | `self._loads(pl)` | gateway frame; asserts dict `:201` |
| `interaction_server.py:442` | `self._loads(body)` | webhook body; `except (ValueError, TypeError)` → 400 |
| `net.py:47`, `ux.py:494` | error-body / PyPI decode | untyped |

Dispatch/peek patterns that decode wants to preserve:

- Interaction dispatch reads `payload["type"]` then picks a deserializer
  (`interaction_server.py:442-459`), tolerating unknown top-level types by catching
  `UnrecognisedEntityError` (`:461-463`).
- Gateway dispatch reads `op`/`d`/`s`/`t` (`shard.py:985,998-1021,1155`).
- 19 hand-rolled dispatch tables in the factory (dossier 13 §14): channels
  (`entity_factory.py:1761-1779`), interactions (`:3182-3190`), components (`:3413-3657`), commands
  (`:2822`), interaction metadata (`:3817`), auto-mod, scheduled events — most **raise**
  `UnrecognisedEntityError` on unknown type; some **soft-skip**.

msgspec facts (dossier 13 §7, §11, §14):

- Typed decode `msgspec.json.Decoder(SomeStruct).decode(bytes) -> Struct` collapses the two stages
  into one; typed decode into a struct is often **faster than into an untyped dict**.
- `msgspec.Raw(bytes)` captures a sub-document undecoded for later/peek-then-dispatch decoding.
- `msgspec.convert(obj, Type, *, from_attributes=False, dec_hook=...)` builds a struct from an
  **already-parsed** dict/list (or object attributes) — the bridge from dict-in to Structs without
  re-parsing bytes.
- Tagged unions route polymorphic decode by a discriminator and **raise on unknown tag** (matches the
  factory's raising tables); soft-skip needs a `Raw`-peek pre-pass. Detail in
  [`../05-entity-factory/01-polymorphism-and-tagged-unions.md`](../05-entity-factory/01-polymorphism-and-tagged-unions.md).

## 3. Target design

### 3.1 dict-in vs bytes-in

| Axis | dict-in (`convert`) | bytes-in (typed `Decoder`) |
|------|---------------------|----------------------------|
| Parse passes | two (bytes→dict, then convert) | one (bytes→Struct) |
| Speed | slower (double handling) | faster (msgspec's main win) |
| Signature churn | **none** — `deserialize_*(JSONObject)` keeps its shape; body becomes `msgspec.convert(payload, T, dec_hook=…)` | **high** — every abstract `deserialize_*` signature + callers (rest/shard/interaction_server) shift to `bytes`/`Raw` |
| Migration risk | low — incremental, per-method | higher — touches the API boundary |
| app injection | still impossible on decode (constraint a holds either way) | same |

**Recommendation (decision D6):** target **bytes-in typed `Decoder`s for the declarative end-state**,
but reach it via **dict-in `msgspec.convert` as the incremental bridge**. The first mechanical passes
keep the dict-in `deserialize_*` interface and swap the hand-construction body for `convert(payload,
T, dec_hook=…)`; later passes push the boundary out to `bytes`/`Raw` where the top-level type is known
at the call site (REST success path, gateway frames), deleting the intermediate dict.

### 3.2 Module-level Decoder registry

Hold one reusable `Decoder` per top-level decoded type (dossier 13 §11 — build once, bind
type+hook+config to the instance):

```python
# hikari/impl/entity_factory.py (or a dedicated decoders module)
import msgspec
from hikari.internal.msgspec_hooks import dec_hook       # see 02-custom-scalar-types-and-hooks.md

_MESSAGE_DECODER = msgspec.json.Decoder(messages.Message, dec_hook=dec_hook)
_USER_DECODER    = msgspec.json.Decoder(users.User, dec_hook=dec_hook)
_GUILD_DECODER   = msgspec.json.Decoder(guilds.RESTGuild, dec_hook=dec_hook)
# ... one per top-level entity the REST/gateway boundary decodes.

def decode_message(buf: bytes) -> messages.Message:      # bytes-in end-state
    return _MESSAGE_DECODER.decode(buf)
```

For the incremental (dict-in) phase, a single untyped `Decoder` feeds `convert`:

```python
def deserialize_message(self, payload: data_binding.JSONObject) -> messages.Message:
    return msgspec.convert(payload, messages.Message, dec_hook=dec_hook)   # no re-parse
```

Registry placement: co-locate with the residual factory so hooks/config are defined once. `strict=True`
(default) everywhere; do **not** flip global `strict=False` (a blunt instrument — the custom scalars
need hooks regardless, dossier 13 §9).

### 3.3 msgspec.Raw for deferred and polymorphic decode

`Raw` is the escape hatch for peek-then-dispatch and incremental rollout (dossier 01 §8.4):

```python
class _InteractionEnvelope(msgspec.Struct):
    type: int
    data: msgspec.Raw = msgspec.Raw()      # captured undecoded

env = msgspec.json.Decoder(_InteractionEnvelope).decode(body)
concrete = _INTERACTION_DECODERS[env.type].decode(env.data)   # single-parse dispatch
```

Uses:

- **Interaction dispatch** (`interaction_server.py:442-459`): peek `type`, decode the remainder into
  the concrete struct — no double parse, and the `except UnrecognisedEntityError` soft-tolerance is
  reproduced by dispatching an unknown `type` to a fallback (or re-raising to match a raising table).
- **Gateway envelope** (`shard.py:985,998-1021`): `{op, d: Raw, s, t}` struct mirrors the current
  dict-peek without materializing unknown event payloads.
- **Incremental seam:** a parent struct can hold `child: msgspec.Raw` so the residual factory keeps
  owning that child's deserialization while msgspec owns the envelope — a clean per-type rollout knob.
- **Soft-skip arrays** (today's `cast_variants_array`, `data_binding.py:411-438`): decode a
  `list[msgspec.Raw]`, then convert each element under `try/except` to drop unrecognized variants.

### 3.4 msgspec.convert as the incremental bridge

`convert` is the low-churn path (dossier 13 §7):

- `convert(payload_dict, T, dec_hook=dec_hook)` — build `T` from an already-parsed dict; keeps the
  dict-in `deserialize_*` signatures, so callers (rest/shard/interaction_server) are untouched during
  the transition.
- `convert(src_obj, T, from_attributes=True)` — build a struct by reading attributes off an arbitrary
  object; useful for cache interop and constructing Structs from non-dict sources
  ([`../04-frozen-and-cache/01-cache-data-layer-and-mutation.md`](../04-frozen-and-cache/01-cache-data-layer-and-mutation.md)).
- `convert` runs the same `dec_hook`, tagged-union dispatch, and validation as `json.decode`, so a
  method migrated to `convert` behaves identically to its future bytes-in form — de-risking the later
  boundary push.

### 3.5 Residual factory and the 13 hard cases

Not everything decodes declaratively. The residual factory (decision D1) still owns the ~13 categories
that cannot be expressed as a typed `Decoder` — array→keyed-`Mapping` re-keying, flattened grandchild
fields, sibling-dependent typing, parent→child context injection (`guild_id`/`user_id` threading), the
lazy `GatewayGuildDefinition`, computed fields, and classmethod-constructed types
(`Embed.from_received_embed`). These transform wire Structs (or `Raw`) into public Structs and **never
inject `app`**. Enumerated in [`../05-entity-factory/02-hard-cases-and-transforms.md`](../05-entity-factory/02-hard-cases-and-transforms.md).

## 4. Step-by-step migration

1. Create the `dec_hook` (see [`02-custom-scalar-types-and-hooks.md`](02-custom-scalar-types-and-hooks.md))
   and a decoders module holding untyped + per-type `Decoder`s.
2. Phase 1 (dict-in bridge): rewrite `deserialize_*` bodies to `msgspec.convert(payload, T,
   dec_hook=…)` where `T` is declarative-decodable; keep signatures. Leave hard cases hand-written.
3. Phase 2 (Raw dispatch): replace interaction/gateway dict-peek dispatch with `Raw`-envelope structs +
   the per-type decoder registry; reproduce raise-vs-soft-skip per table.
4. Phase 3 (bytes-in): at call sites where the top-level type is known (REST success `rest.py:892-895`,
   gateway `receive_json` `shard.py:193-202`), decode `bytes` directly into the top-level Struct,
   deleting the intermediate dict; push the boundary out method-by-method.
5. Retire `cast_variants_array` in favor of `list[Raw]` + per-element `convert` under `try/except`
   (coordinate with [`../02-enums/00-strategy-and-forward-compat.md`](../02-enums/00-strategy-and-forward-compat.md)).
6. Decide the pluggable-decode public API fate (bytes-in typed decode makes a user `loads` override
   meaningless on typed paths — see [`04-json-data-binding.md`](04-json-data-binding.md) §3.5).

## 5. Affected files and symbols

| Path | Anchor | Change |
|------|--------|--------|
| `hikari/impl/entity_factory.py` | `deserialize_*`, dispatch tables `:1761-1779,3182-3190,3413-3657,2822,3817` | bodies → `convert`; tables → tagged unions / Raw dispatch |
| `hikari/impl/rest.py` | `:892-895`, `:1000-1019` | phase-3 bytes-in typed decode |
| `hikari/impl/shard.py` | `:193-202`, `:985,998-1021` | Raw envelope + typed decode |
| `hikari/impl/interaction_server.py` | `:442-459` | Raw peek-then-dispatch |
| `hikari/internal/data_binding.py` | `:411-438` | `cast_variants_array` → `list[Raw]` + convert |
| new decoders module | — | per-type `Decoder` registry + `dec_hook` binding |

## 6. Risks and gotchas

1. **Signature churn is the cost of speed.** bytes-in changes every abstract `deserialize_*` signature
   and its callers; stage it behind `convert` so the behavior is proven before the boundary moves.
2. **Unknown-tag semantics must be reproduced per table.** Tagged unions raise on unknown tag (matches
   the raising tables) but there is no declarative default variant; soft-skip tables need a `Raw`-peek
   pre-pass. Get the raise-vs-skip mapping right per dispatch site.
3. **`convert` still needs the `dec_hook`.** Omitting it makes custom-scalar fields fail exactly as a
   typed `decode` would; pass `dec_hook` everywhere.
4. **Double parse during phase 1.** dict-in + `convert` is two passes — a temporary regression vs the
   bytes-in target; acceptable for de-risking, but do not ship phase 1 as the end-state.
5. **Registry lifetime.** Build `Decoder`s once at module import; constructing them per call throws
   away msgspec's amortized setup and the perf win.
6. **app removal is orthogonal but concurrent.** No decode path injects `app` (constraint a); ensure
   the residual transforms thread `guild_id`/`user_id` context without reintroducing an `app` handle
   ([`../03-app-removal-and-helpers/00-strategy.md`](../03-app-removal-and-helpers/00-strategy.md)).

## 7. Verification

- Equivalence: for a representative payload per top-level type, assert
  `convert(loads(buf), T, dec_hook=…) == Decoder(T, dec_hook=…).decode(buf)` — proves phase-1 and
  phase-3 agree before moving the boundary.
- Dispatch: interaction/gateway `Raw` dispatch produces the same concrete types as the current tables;
  unknown types raise or soft-skip exactly as before (per table).
- Perf: benchmark bytes-in typed decode vs today's `loads`+factory on a large guild-create payload
  ([`../11-rollout/02-performance-benchmarking.md`](../11-rollout/02-performance-benchmarking.md)).
- Malformed input still raises `ValueError` at each boundary call site.

## 8. Open questions / decisions

Cross-link [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md):

- Q-DECODE-1: end-state boundary — bytes-in (recommended) vs staying dict-in via `convert`? Confirms
  how far the boundary push goes.
- Q-DECODE-2: keep the pluggable `loads` override once typed decode lands (it cannot produce Structs on
  typed paths)?
- Q-DECODE-3: per dispatch table, reproduce raise (channels/interactions/…) vs soft-skip
  (components/some audit) — enumerated with [`../05-entity-factory/01-polymorphism-and-tagged-unions.md`](../05-entity-factory/01-polymorphism-and-tagged-unions.md).
- Q-DECODE-4: where does the `Decoder` registry live — inside `entity_factory` or a dedicated module?
