# Gateway shard and interaction server (the JSON decode boundary)

Scope: `hikari/impl/shard.py` (`GatewayShardImpl`, `_GatewayTransport` family) and
`hikari/impl/interaction_server.py`. How the gateway op/`d` frame and the interaction
webhook body are decoded (`self._loads`), how compression sits below the decoder, the
type-dispatch on `payload["type"]`, and how `msgspec.Raw` + tagged unions slot in for a
gradual then declarative decode. From dossiers 01 and 08; the D12 event-pipeline design and its
empirical verification are dossiers 18 and 19.

---

## 1. Objective

- Route the two remaining `self._loads` boundaries (shard `receive_json`, interaction
  webhook body) through the swapped msgspec decoder without disturbing compression.
- Preserve the gateway `{op, d, s, t}` framing and the interaction `type`-dispatch,
  including the current unknown-type soft-skip behavior.
- Set up the `msgspec.Raw` + tagged-union path so the envelope can be typed while the inner
  payload is decoded (or re-dispatched) once, avoiding double parsing.
- Feed the decided event pipeline (D12): the envelope's `d` is captured as `msgspec.Raw` and
  handed to the name-keyed Decoder registry behind `consume_raw_event`, so typed decode runs only
  for enabled consumers. The event struct/hydration design lives in
  [`../07-events/00-events-migration.md`](../07-events/00-events-migration.md); this file owns the
  envelope capture and the dispatch seam. Interactions stay factory-constructed and are app-less
  per the resolved D10-interactions; `InteractionServer` listeners still return builders — the 8
  `build_*` factories are kept as app-free sync constructors on the app-less interaction structs,
  so the return-a-builder flow is unchanged
  ([`../03-app-removal-and-helpers/02-helper-method-inventory/06-interactions.md`](../03-app-removal-and-helpers/02-helper-method-inventory/06-interactions.md)).

---

## 2. Current state

### 2.1 Shard JSON boundary and compression (dossier 01 §2.2/§5.4)

`_GatewayTransport.receive_json` (`shard.py:193-202`):

```python
pl = await self._receive_and_check()      # already-DECOMPRESSED bytes
val = self._loads(pl)                      # :200  -> dict
assert isinstance(val, dict)               # :201
return val
```

`send_json` (`:204-210`): `pl = self._dumps(data)` then `ws.send_bytes(pl)` — **outbound is
never compressed** (Discord accepts uncompressed frames); requires `bytes`.

Compression is entirely in the `_GatewayTransport` subclasses and sits **below** the JSON
decoder — the decoder always receives decompressed bytes (dossier 01 §5.4):
- transport selection `shard.py:290-298`
  (`_GatewayZstdStreamTransport`/`_GatewayZlibStreamTransport`/`_GatewayZlibMessageTransport`/
  `_GatewayBasicTransport`);
- zlib stream `:336-370` (`zlib.decompressobj()` + `_ZLIB_SYNC_FLUSH` framing);
- zstd stream `:375-401` (`compression.zstd` 3.14+ or `backports.zstd`);
- payload zlib `:404-418` (per-message `zlib.decompress`).
There is **no gzip layer** in hikari (aiohttp handles HTTP content-encoding transparently).

`_dumps`/`_loads` are constructor-injected on `_GatewayTransport` and `GatewayShardImpl`
(defaults `default_json_dumps`/`default_json_loads`; `shard.py:526/541/561-562/616-617`,
forwarded to the transport at `:954-955`).

### 2.2 Gateway op/`d`/`s`/`t` framing (dossier 01 §6.3)

`GatewayShardImpl._poll_events` (`shard.py:844-919`) consumes the decoded dict:

```python
payload = await self._ws.receive_json()       # :849  the full frame dict
op = payload[_OP]                              # :851  _OP = intern("op"), shard.py:85
if op == _DISPATCH:
    name = payload[_T]                         # :854  event name
    data = payload[_D]                         # :855  event payload dict
    self._seq = payload[_S]                    # :856
    ...
    self._event_manager.consume_raw_event(name, self, data)   # :893  (dict passed on)
elif op == _HEARTBEAT_ACK: ...
elif op == _INVALID_SESSION:
    can_reconnect = payload[_D]                # :912  _D may be a bare bool here
```

Outbound frames are built inline as dicts and sent via `_send_json` → transport `send_json`
→ `self._dumps`: `{_OP: _HEARTBEAT, _D: self._seq}` (`:822`), IDENTIFY (`:1000-1021`),
RESUME (`:1020`), REQUEST_GUILD_MEMBERS (`:751`), etc. Four `JSONObjectBuilder` sites build
the `d` sub-dicts (`:743-751/759-763/812-818/1155-1162`).

The decoded `data` dict is passed intact to `event_manager.consume_raw_event`, whose `on_*`
handlers (`event_manager.py:127/149/…`) forward it as `payload` into
`event_factory.deserialize_*_event(shard, payload)`, which finally calls
`entity_factory.deserialize_*(payload)`. So the shard's decode boundary produces a plain
dict and never sees a Struct today.

### 2.3 Interaction server type-dispatch (dossier 08 §7.4, and source)

`InteractionServer._on_interaction` (`interaction_server.py:441-508`):

```python
payload = self._loads(body)                        # :442  -> dict
assert isinstance(payload, dict)                   # :443
interaction_type = int(payload["type"])            # :444  peek discriminator
# ... except (ValueError, TypeError) -> 400 ; KeyError -> 400 (missing 'type')
if interaction_type == _PING_INTERACTION_TYPE:     # :454
    return _PONG_RESPONSE
try:
    interaction = self._entity_factory.deserialize_interaction(payload)   # :459
except errors.UnrecognisedEntityError:             # :461  UNKNOWN TYPE -> 501 soft-skip
    return _Response(_NOT_IMPLEMENTED, ...)
...
raw_payload, files = result.build(self._entity_factory)    # :494  builder -> (dict, files)
payload = self._dumps(raw_payload)                          # :495
```

Response encode also at `interaction_server.py:145` (`_PONG_RESPONSE` = `default_json_dumps
({"type": 1})` built at import) and `:495` (listener result). File-bearing responses switch
to `multipart/form-data` with the JSON under `payload_json` (`:350-365`). `_dumps`/`_loads`
injected at `:215/220/231-234/251/256`.

`deserialize_interaction` currently peeks `payload["type"]` and dispatches to the concrete
interaction deserializer, **raising `UnrecognisedEntityError` on an unknown type** — the
server catches it and returns 501 (soft-skip). This raise-then-catch is the tolerance
mechanism to preserve.

### 2.4 The other decode/encode sites (dossier 01 §9)

Decoder call sites total 6: `net.py:47` (error body, `try/except ValueError`),
`ux.py:494` (PyPI version check), `rest.py:895/1012` (REST — sibling file
[`00-rest-client.md`](00-rest-client.md)), `shard.py:200`, `interaction_server.py:442`.
Encoder call sites total 14 (dossier 01 §9). Components carrying `_dumps`/`_loads`: 6
(`RESTClientImpl`, `RESTApp`, `GatewayShardImpl`, `GatewayBot`, `InteractionServer`,
`_GatewayTransport`).

---

## 3. Target design

### 3.1 First pass: swap the decoder, keep the dict boundary

`shard.receive_json` and `interaction_server._on_interaction` keep returning/consuming a
plain `dict`; only `self._loads` changes from `orjson.loads` to `msgspec.json.decode`
(untyped, returns dict/list — drop-in). `msgspec.DecodeError` subclasses `ValueError`, so
the existing `try/except (ValueError, TypeError)` guards (`interaction_server.py:446`;
`net.py:52`) still catch malformed input (dossier 01 §8.1). Compression is untouched — the
decoder still receives decompressed bytes (dossier 01 §5.4). Outbound `_dumps` becomes
`msgspec.json.encode` (bytes-out matches `ws.send_bytes` / `aiohttp.BytesPayload` /
`payload_json`).

### 3.2 Gateway envelope: `Raw` for `d`, typed `op/s/t` (D12 — decided, empirically verified)

This is no longer an optional end-state: the `Raw` envelope + name-keyed Decoder registry is the
locked event-pipeline design (D12; verified end to end on msgspec 0.21.1 — dossiers 18/19,
appendix [`../12-appendices/04-event-pipeline-feasibility.md`](../12-appendices/04-event-pipeline-feasibility.md)).
The envelope Struct replaces the full-frame dict parse at `shard.py:200`:

```python
class GatewayFrame(msgspec.Struct):
    op: int
    d: msgspec.Raw = msgspec.Raw(b"null")   # zero-copy view; skipped, never materialized here
    s: int | None = None
    t: str | None = None

frame = _frame_decoder.decode(pl)            # single skeleton parse
if frame.op == _DISPATCH:
    self._event_manager.consume_raw_event(frame.t, self, frame.d)   # Raw bytes on
```

`_poll_events` (`shard.py:844-895`) keeps its branch structure; the deltas:

- **Dispatch + the `is_enabled` win.** `consume_raw_event(name, self, raw_d)` passes the `Raw`
  view instead of a dict (`api/event_manager.py:168` retypes — a recorded public break,
  [`../11-rollout/03-breaking-changes-and-changelog.md`](../11-rollout/03-breaking-changes-and-changelog.md) §3.10).
  The per-name `Decoder.decode(raw_d)` in the registry is the **only** parse of `d`, and it runs
  only when the consumer's `is_enabled` gate passes (`event_manager_base.py:404-420`). Today the
  full `d` dict is materialized by orjson even when the consumer is disabled and then discarded —
  under `Raw` the disabled path is near-free. Net parses per event: today 1 full; after, 1
  skeleton + at most 1 typed — never 2 full. The unknown-event `LookupError` contract
  (`shard.py:892-895` logs "ignoring unknown event") is preserved verbatim by the registry dict
  miss.
- **READY:** the shard needs `session_id`/`resume_gateway_url`/`user{...}`/`v`/guild count
  (`shard.py:860-878`) before and independently of the event manager — decode a tiny `_ReadyMeta`
  struct from the `Raw`; one extra partial parse per connection lifecycle, negligible.
- **RATE_LIMITED logging** (`shard.py:883-890`): small partial decode of `opcode`/`retry_after`/
  `meta`, or move the log line into the consumer.
- **INVALID_SESSION:** decode `d` as `bool` for that opcode only (`shard.py:912`). Heartbeat `d`
  is an int-or-null. `Raw` tolerates all of this by deferring typing — keep `Raw` for `d`, never
  a `bool | int | Struct` union.
- **ShardPayloadEvent:** the raw-passthrough event's `payload` (`shard_events.py:92`) becomes raw
  bytes or a lazily-decoded mapping, materialized only at the
  `_enabled_for_event(ShardPayloadEvent)` gate (`event_manager_base.py:407-409`) — a recorded
  break.
- **Inbound `loads=`:** a user-supplied generic `loads` cannot produce the typed envelope or
  structs; the inbound halves of the `loads=`/`dumps=` params (`shard.py:561-562`,
  `gateway_bot.py:331-332`) are deprecated/replaced — a recorded break (see §3.5).
- **Per-route transition:** routes not yet on a typed Decoder decode `frame.d` untyped into a
  dict and run the residual hand path; converted routes decode typed. Each gateway `t` name
  migrates independently, and the heavy residuals (GUILD_CREATE family, presence_update, thread
  joins, member_chunk) stay on the hydration layer by design
  ([`../07-events/00-events-migration.md`](../07-events/00-events-migration.md)).

### 3.3 Interaction server: `Raw` peek + tagged-union, preserving soft-skip

Replace the `int(payload["type"])` peek + `deserialize_interaction` dispatch with either
(a) a `{type: int, data: msgspec.Raw, …}` envelope Struct that peeks `type`, PONGs on `1`,
then decodes the remainder into the concrete interaction Struct; or (b) a msgspec **tagged
union** keyed `tag_field="type"` over the interaction Structs (dossier 01 §8.4/§8.5):

```python
class _InteractionEnvelope(msgspec.Struct, frozen=True):
    type: int
    # peek only; full decode via a tagged union of interaction Structs

_env = _env_decoder.decode(body)
if _env.type == _PING_INTERACTION_TYPE:
    return _PONG_RESPONSE
try:
    interaction = _interaction_decoder.decode(body)   # tagged union over interaction types
except msgspec.ValidationError:                        # unknown tag -> raises (see below)
    return _Response(_NOT_IMPLEMENTED, ...)
```

**Soft-skip preservation is the critical subtlety.** msgspec tagged unions **raise
`msgspec.ValidationError` on an unknown tag** (dossier 01 §8.5, verified in dossier 13). The
current behavior raises `UnrecognisedEntityError` and the server returns 501. To keep "ignore
unknown interaction type → 501":

1. peek `type` via the `Raw`/envelope prepass and map unknown types to the 501 response
   **before** the union decode, or
2. catch `msgspec.ValidationError` from the union decode and return 501, or
3. add a catch-all variant to the union.

Option 1 (peek-then-decide) mirrors today's flow most closely and is recommended. Keep the
`KeyError`→400 (missing `type`) and `(ValueError, TypeError)`→400 (bad JSON) branches; under
msgspec a missing `type` is a `ValidationError`/`DecodeError` (both `ValueError`
subclasses), so the 400 mapping still holds but the exact exception type changes — adjust the
`except` clauses accordingly.

### 3.4 Keep the response-builder path unchanged

`result.build(self._entity_factory)` returning `(dict, files)` is unchanged — the builders
stay dict-emitters (see
[`../08-builders/00-special-endpoints-builders.md`](../08-builders/00-special-endpoints-builders.md)),
and `self._dumps(raw_payload)` uses the swapped encoder. The `_PONG_RESPONSE` import-time
const rebuilds fine under msgspec. The listener side is equally unchanged under the resolved
D10-interactions: the interaction structs handed to listeners are app-less, but their `build_*`
factory methods (`build_response`, `build_deferred_response`, `build_modal_response`, autocomplete
`build_response`) are kept as app-free sync constructors — they construct the builder directly
from `special_endpoints` with no client — so a listener that returns a builder works exactly as
before. Only the 9 interaction *action* helpers are gone, and a gateway-side handler that used
them calls `rest.*` with `interaction.id`/`.token` instead (see
[`00-rest-client.md`](00-rest-client.md) §3.4).

### 3.5 Pluggable-json decision touches these components

`GatewayShardImpl`, `_GatewayTransport`, and `InteractionServer` are 3 of the 6 components
exposing `dumps`/`loads` overrides. Keep the encode override + default-swap; a
Struct-producing typed decode cannot honor a user-supplied generic `loads`, so the decode
override becomes meaningless for typed paths (dossier 01 §8.6) — coordinate the public-API
decision with [`00-rest-client.md`](00-rest-client.md) §8 and the decisions log.

---

## 4. Step-by-step migration

1. **Swap `self._loads`/`self._dumps` defaults** to msgspec via `data_binding` (single
   point; owned by [`../01-foundations/04-json-data-binding.md`](../01-foundations/04-json-data-binding.md)).
   Confirm the shard-transport forward (`shard.py:954-955`) and interaction-server injection
   (`:231-234`) inherit it.
2. **Adjust interaction-server `except` clauses** for msgspec exception types: bad JSON /
   missing `type` now surface as `msgspec.DecodeError`/`ValidationError` (both `ValueError`
   subclasses) — keep the 400 mapping, and add explicit handling if the `KeyError` branch no
   longer fires.
3. **(Incremental) leave the dict boundary as-is** — `receive_json` and `_on_interaction`
   still produce dicts; nothing else in shard/dispatch changes. For the gateway this state is
   transitional only: D12 replaces it inside the `3.0.0` train.
4. **(D12, `3.0.0` train) introduce the gateway envelope Struct** with `d: msgspec.Raw`; retype
   `consume_raw_event` to take the `Raw` payload; wire the name-keyed Decoder registry behind the
   `is_enabled` gate; add the READY/RATE_LIMITED partial decodes and the INVALID_SESSION bool
   decode; keep `Raw` for `d` to tolerate the bool/int/object polymorphism at
   `op == INVALID_SESSION`/heartbeat. Convert routes incrementally (untyped decode-to-dict
   fallback per unconverted route, §3.2); land the per-name fixture smoke test with the registry
   ([`../10-testing/00-test-strategy.md`](../10-testing/00-test-strategy.md)).
5. **(Declarative) introduce the interaction envelope + tagged union**; implement the
   peek-then-decide soft-skip (§3.3 option 1) so unknown interaction types still return 501,
   PING still returns PONG, and known types decode into interaction Structs.
6. **Verify compression is untouched** — the four transports still hand decompressed bytes to
   the decoder; no zstd/zlib code changes.
7. **Decide the decode-override public-API fate** and document any break.

---

## 5. Affected files & symbols

| File | Anchor(s) | Change |
|---|---|---|
| `hikari/internal/data_binding.py` | `:106-123` | decoder/encoder swap (single point) |
| `hikari/impl/shard.py` | `:193-202` `receive_json`, `:204-210` `send_json` | `_loads`/`_dumps` via msgspec; `Raw` envelope replaces the full-frame parse at `:200` (D12) |
| `hikari/impl/shard.py` | `:844-919` `_poll_events`, `:851/854-856/893/912` | keep op/`d`/`s`/`t` framing; `d` captured as `Raw`; READY/RATE_LIMITED partial decodes; INVALID_SESSION bool decode |
| `hikari/impl/shard.py` | `:290-418` transports | **unchanged** (compression below the decoder) |
| `hikari/impl/shard.py` | `:526/541/561-562/616-617/954-955` | `_dumps`/`_loads` wiring inherits msgspec default; inbound `loads=` override deprecated/replaced (break) |
| `hikari/api/event_manager.py` | `:167-168` `consume_raw_event` ABC | payload retyped dict → bytes/`Raw` (public break) |
| `hikari/impl/event_manager_base.py` | `:339-348` `_Consumer` build, `:404-431` consume | registry seam; the `is_enabled` gate now guards the only full decode of `d` |
| `hikari/events/shard_events.py` | `:92` `ShardPayloadEvent.payload` | raw bytes / lazily-decoded mapping (public break) |
| `hikari/impl/gateway_bot.py` | `:331-332` `loads=`/`dumps=` | inbound override deprecated/replaced (break) |
| `hikari/impl/interaction_server.py` | `:441-508` `_on_interaction` | envelope/tagged-union dispatch; preserve PING/501/400 |
| `hikari/impl/interaction_server.py` | `:145` `_PONG_RESPONSE`, `:495` | encode via msgspec; unchanged shape |
| `hikari/impl/interaction_server.py` | `:215/220/231-234/251/256` | `_dumps`/`_loads` wiring |
| `hikari/impl/event_manager.py` | `:127/149/…` `on_*` | decode-first reordering + registry build fns per route ([`../07-events/00-events-migration.md`](../07-events/00-events-migration.md)) |

Related: event/interaction *construction* is
[`../07-events/00-events-migration.md`](../07-events/00-events-migration.md); the interaction
tagged-union type design is in
[`../05-entity-factory/01-polymorphism-and-tagged-unions.md`](../05-entity-factory/01-polymorphism-and-tagged-unions.md);
the REST boundary is the sibling [`00-rest-client.md`](00-rest-client.md).

---

## 6. Risks / gotchas

- **Unknown-tag soft-skip.** msgspec tagged unions **raise** on unknown tag, whereas the
  interaction server today soft-skips to 501. Miss the peek-then-decide (or the
  `ValidationError` catch) and every new Discord interaction type 500s/400s instead of
  returning 501. This is the highest-risk item in this file.
- **Exception-type drift.** Malformed JSON and missing `type` become
  `msgspec.DecodeError`/`ValidationError` (both `ValueError` subclasses). The current
  `except (ValueError, TypeError)` still catches bad JSON, but the `except KeyError` for
  missing `type` may never fire under msgspec — re-map explicitly to keep the 400.
- **`d` polymorphism.** At `op == INVALID_SESSION` `d` is a bare bool (`shard.py:912`) and
  heartbeat `d` is an int/null — a fully-typed `d` union is fragile; keep `msgspec.Raw` for
  `d` to defer typing.
- **Assertion `isinstance(val, dict)`** (`shard.py:201`, `interaction_server.py:443`) — a
  typed decode returns a Struct, not a dict; these asserts must be dropped/relaxed when the
  boundary moves off dict-in.
- **Outbound never compressed** — do not accidentally route `send_json` through a
  compression path; it must stay raw `bytes` to `ws.send_bytes`.
- **Pluggable decode override** loses meaning for typed decode — a user's custom `loads`
  cannot produce Structs; a recorded public break for the inbound gateway path
  ([`../11-rollout/03-breaking-changes-and-changelog.md`](../11-rollout/03-breaking-changes-and-changelog.md) §3.10).
- **Decoder construction is lazy** (dossier 18): a bad field annotation in a registry decode
  target fails on the *first decode* of a matching payload, not at import or registry build —
  hence the per-name fixture smoke test in CI.
- **`_PONG_RESPONSE` import-time encode** must still succeed under msgspec (trivial dict —
  low risk, but it runs at import).

---

## 7. Verification

- **Compression matrix:** replay recorded zlib-stream, zstd-stream, and payload-zlib gateway
  sessions; assert `receive_json` yields identical dicts under msgspec vs orjson.
- **Frame dispatch:** a `DISPATCH` frame routes `name`/`d`/`s` to `consume_raw_event`
  unchanged; `HEARTBEAT_ACK`/`RECONNECT`/`INVALID_SESSION(bool d)`/`HEARTBEAT` branches all
  still fire.
- **Disabled-consumer path:** with no listener/waiter/cache interest in a gateway name, assert
  `d` is never fully decoded (the registry Decoder is not invoked) — the `is_enabled` gating win
  of §3.2 is observable, not incidental.
- **Registry smoke test:** decode one recorded fixture payload per registry entry — Decoder
  construction is lazy, so annotation errors surface only on first decode (dossier 18;
  [`../10-testing/00-test-strategy.md`](../10-testing/00-test-strategy.md)).
- **Interaction PING:** a `type=1` body returns `_PONG_RESPONSE` (200, `{"type":1}`).
- **Interaction known type:** a recorded slash-command interaction decodes to the correct
  interaction Struct and dispatches to its listener.
- **Interaction unknown type:** a body with an unmodeled `type` returns **501**
  (`_NOT_IMPLEMENTED`), not 400/500 — the soft-skip regression guard.
- **Interaction bad input:** malformed JSON and a body missing `type` each return **400**.
- **Signature verify unchanged:** the ed25519 verify (`:432-439`) still precedes decode.
- **Outbound frames:** IDENTIFY/RESUME/heartbeat/REQUEST_GUILD_MEMBERS encode to identical
  bytes under msgspec vs orjson and are accepted by the gateway.

---

## 8. Open questions / decisions

Cross-linked to [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md):

1. **Soft-skip strategy for unknown interaction types** — peek-then-decide (recommended) vs
   catch `ValidationError` vs catch-all union variant. Must preserve the 501 behavior. Ties
   to [`../05-entity-factory/01-polymorphism-and-tagged-unions.md`](../05-entity-factory/01-polymorphism-and-tagged-unions.md).
2. **When to move the boundary off dict-in** — DECIDED for the gateway (D12): the `Raw` envelope
   + name-keyed registry lands in the `3.0.0` train, with per-route typed conversion allowed to
   trail into P5 ([`../11-rollout/00-phasing-and-sequencing.md`](../11-rollout/00-phasing-and-sequencing.md) §3 P2).
   The REST and interaction-server boundaries keep the incremental dict-in pass first
   ([`../01-foundations/05-decode-boundary-and-decoders.md`](../01-foundations/05-decode-boundary-and-decoders.md)).
3. **Pluggable-json decode override** — RESOLVED for the inbound gateway path: a documented
   break (deprecated/replaced, §3.2). The outbound encode override and the REST-side story are
   still coordinated with [`00-rest-client.md`](00-rest-client.md) §8.
4. **Typing `d`** — RESOLVED: `msgspec.Raw` permanently (D12); a `bool | int | Struct` union is
   rejected — `Raw` preserves op-dependent polymorphism.
