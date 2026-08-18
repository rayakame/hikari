# Gateway shard and interaction server (the JSON decode boundary)

Scope: `hikari/impl/shard.py` (`GatewayShardImpl`, `_GatewayTransport` family) and
`hikari/impl/interaction_server.py`. How the gateway op/`d` frame and the interaction
webhook body are decoded (`self._loads`), how compression sits below the decoder, the
type-dispatch on `payload["type"]`, and how `msgspec.Raw` + tagged unions slot in for a
gradual then declarative decode. From dossiers 01 and 08.

---

## 1. Objective

- Route the two remaining `self._loads` boundaries (shard `receive_json`, interaction
  webhook body) through the swapped msgspec decoder without disturbing compression.
- Preserve the gateway `{op, d, s, t}` framing and the interaction `type`-dispatch,
  including the current unknown-type soft-skip behavior.
- Set up the `msgspec.Raw` + tagged-union path so the envelope can be typed while the inner
  payload is decoded (or re-dispatched) once, avoiding double parsing.
- Keep events/interactions constructed by the factories (constraints a/c handled in
  [`../07-events/00-events-migration.md`](../07-events/00-events-migration.md)); this file
  is only the JSON boundary and dispatch.

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

### 3.2 Gateway envelope: `Raw` for `d`, typed `op/s/t`

The idiomatic msgspec shape is an envelope Struct with `d` left as `msgspec.Raw` so the
op/name peek happens without materializing the event payload, and `d` is decoded once — into
a Struct for ported event types, or handed to `entity_factory` as before (dossier 01 §8.4):

```python
class GatewayFrame(msgspec.Struct, frozen=True):
    op: int
    d: msgspec.Raw = msgspec.Raw()      # deferred; decode after peeking op/t
    s: int | None = None
    t: str | None = None

frame = _frame_decoder.decode(pl)       # single parse of the envelope
if frame.op == _DISPATCH:
    # decode frame.d into the concrete event payload Struct, or pass raw bytes/dict on
    ...
```

Caveat: `op == _INVALID_SESSION` puts a bare **bool** in `d` (`shard.py:912`), and heartbeat
sends `d = self._seq` (an int-or-null). `Raw` tolerates both (it defers typing); a fully
typed `d: bool | int | SomeStruct` union would need care. Keep `Raw` for `d` to preserve the
current polymorphic tolerance.

The dispatch keeps calling `consume_raw_event(name, self, <d>)`. In the incremental pass
`<d>` stays a dict (decode `frame.d` untyped); in the declarative end-state `<d>` can be a
decoded Struct once the event_factory/entity_factory path accepts Structs — but note
event_factory still runs afterward to attach `shard`/`app` and do cache lookups for `old_*`
(events do not collapse into msgspec —
[`../07-events/00-events-migration.md`](../07-events/00-events-migration.md) §2.1).

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
const rebuilds fine under msgspec.

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
   still produce dicts; nothing else in shard/dispatch changes.
4. **(Declarative) introduce the gateway envelope Struct** with `d: msgspec.Raw`; peek
   `op`/`t`, decode `d` once, preserve `consume_raw_event(name, self, <d>)`. Keep `Raw` for
   `d` to tolerate the bool/int/object polymorphism at `op == INVALID_SESSION`/heartbeat.
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
| `hikari/impl/shard.py` | `:193-202` `receive_json`, `:204-210` `send_json` | `_loads`/`_dumps` via msgspec; optional `Raw` envelope |
| `hikari/impl/shard.py` | `:844-919` `_poll_events`, `:851/854-856/893/912` | keep op/`d`/`s`/`t` framing; typed envelope in end-state |
| `hikari/impl/shard.py` | `:290-418` transports | **unchanged** (compression below the decoder) |
| `hikari/impl/shard.py` | `:526/541/561-562/616-617/954-955` | `_dumps`/`_loads` wiring inherits msgspec default |
| `hikari/impl/interaction_server.py` | `:441-508` `_on_interaction` | envelope/tagged-union dispatch; preserve PING/501/400 |
| `hikari/impl/interaction_server.py` | `:145` `_PONG_RESPONSE`, `:495` | encode via msgspec; unchanged shape |
| `hikari/impl/interaction_server.py` | `:215/220/231-234/251/256` | `_dumps`/`_loads` wiring |
| `hikari/impl/event_manager.py` | `:127/149/…` `on_*` | consume the (still-dict) `d`; unchanged in incremental pass |

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
  cannot produce Structs; flag as a possible public-API break.
- **`_PONG_RESPONSE` import-time encode** must still succeed under msgspec (trivial dict —
  low risk, but it runs at import).

---

## 7. Verification

- **Compression matrix:** replay recorded zlib-stream, zstd-stream, and payload-zlib gateway
  sessions; assert `receive_json` yields identical dicts under msgspec vs orjson.
- **Frame dispatch:** a `DISPATCH` frame routes `name`/`d`/`s` to `consume_raw_event`
  unchanged; `HEARTBEAT_ACK`/`RECONNECT`/`INVALID_SESSION(bool d)`/`HEARTBEAT` branches all
  still fire.
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
2. **When to move the boundary off dict-in** — keep dict-in (`msgspec.json.decode` untyped)
   in the first pass; adopt the `Raw` envelope + typed `d`/tagged-union decode in the
   declarative end-state, sequenced after model Structs land
   ([`../01-foundations/05-decode-boundary-and-decoders.md`](../01-foundations/05-decode-boundary-and-decoders.md)).
3. **Pluggable-json decode override** — keep for untyped paths, drop for Struct-typed decode?
   Coordinate with [`00-rest-client.md`](00-rest-client.md) §8; likely a documented break.
4. **Typing `d`** — leave as `msgspec.Raw` permanently vs a `bool | int | Struct` union.
   Recommend `Raw` to preserve op-dependent polymorphism.
