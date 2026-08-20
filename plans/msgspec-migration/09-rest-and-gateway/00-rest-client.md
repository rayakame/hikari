# REST client surface (deserialize/serialize plumbing under msgspec)

Scope: `hikari/api/rest.py` (interface) + `hikari/impl/rest.py` (`RESTClientImpl`,
`RESTApp`, `_RESTProvider`). How the REST surface deserializes via `entity_factory` and
serializes via builders/`serialize_*`, why removing the entity helper methods shifts all
usage onto `rest.*` with **zero new endpoints**, and how the response-decode plumbing
changes from `self._loads → dict → deserialize_*` toward typed `Decoder`s. From dossier 10.

---

## 1. Objective

- Confirm the REST client is **structurally unaffected** by constraints (a)/(b)/(c) — it
  never reads `entity.app`, builds requests from dicts, and holds no entity state.
- Redirect the ~90 removed entity helper methods onto `rest.*` (they all wrap methods that
  already exist), and record the DX cost.
- Change the response-decode plumbing (`self._loads`) to route toward typed
  `msgspec.json.Decoder`s while keeping `entity_factory` as the deserialize owner.
- Route request encoding through the swapped `self._dumps` (msgspec) without touching the
  ~318 `put*` call sites.

---

## 2. Current state

### 2.1 Canonical method shape (dossier 10 §2)

`impl/rest.py` methods follow one pattern (`edit_channel` `:1069-1161`, `fetch_channel`
`:1055-1067`):

```python
route = routes.PATCH_CHANNEL.compile(channel=channel)             # 1. compile route
body = data_binding.JSONObjectBuilder()                           # 2. build request dict
body.put("name", name)
body.put_snowflake("parent_id", parent_category)
body.put_array("permission_overwrites", permission_overwrites,
               conversion=self._entity_factory.serialize_permission_overwrite)
response = await self._request(route, json=body, reason=reason)   # 3. transport (loads/dumps)
assert isinstance(response, dict)
return self._entity_factory.deserialize_channel(response)         # 4. deserialize -> entity
```

`impl/rest.py` contains **zero** `.app` references (dossier 10 §0) — REST never relies on a
returned entity carrying `.app`. `fetch_channel` reads `result.recipient.id`/`result.id`
for a cache write (`:1064-1065`), never `result.app`.

### 2.2 Transport `_request` and the JSON boundary (dossier 10 §2.1)

- **Encode** request body: `data = data_binding.JSONPayload(json, dumps=self._dumps)`
  (`:795`); `self._dumps` defaults to `data_binding.default_json_dumps`.
- **Decode** response: `return self._loads(await response.read())` (`:895`) for
  `200-299` + `application/json`; `204` → `return None` (`:888`); also `:1012`
  (429 ratelimit body). `self._loads` defaults to `default_json_loads`.
- **11 multipart `payload_json` encode sinks** at `:1706/1738/1831/2128/2189/2264/3569/
  4746/4775/4827/4849` (`self._dumps(body)` into a form field).
- Injection wiring: `RESTClientImpl.__init__` params `:593-594`, stored `:620-621`;
  `RESTApp` mirror `:319-320/328-329`, forwarded `:450-451`.

### 2.3 How `app` is injected into entities (the seam constraint (a) severs)

`app` is **never** a deserialize parameter (dossier 10 §3;
`grep 'def deserialize_[a-z_]+\(self, .*\bapp\b'` = 0). Instead
`EntityFactoryImpl.__init__(self, app)` stores `self._app` (`entity_factory.py:485-486`),
and every entity is built with `app=self._app` (63 sites). For `RESTApp`, the injected
`app` is a `_RESTProvider` (`impl/rest.py:222`) holding `_rest`/`_entity_factory`/
`_executor`; wired in `RESTApp.acquire` (`:435/445/461`). For gateway bots the `GatewayBot`
itself is the `app`. This runtime handle is exactly what msgspec's typed decode cannot
thread into a Struct → entities lose `.app` → every `entity.<helper>()` that used
`self.app.rest.*`/`self.app.cache.*` stops working.

### 2.4 Deserialize/serialize call inventory (dossier 10 §3.1/§4)

- `_entity_factory.deserialize_*` is called **143×** in `impl/rest.py` (top targets:
  `deserialize_message` 14, `deserialize_known_custom_emoji` 8, `deserialize_template` 6,
  `deserialize_member` 6). `api/entity_factory.py` declares 98 `deserialize_*`/`serialize_*`
  total.
- Request serialization: **58** `JSONObjectBuilder`, **19** `StringMapBuilder`, **7**
  `URLEncodedFormBuilder`, **318** `put*`, **11** builder `.build()`. Only **7** of the
  `serialize_*` methods are exercised from REST (`serialize_permission_overwrite`,
  `serialize_forum_tag`, `serialize_embed`, `serialize_command_option`,
  `serialize_welcome_channel`, `serialize_command_permission`,
  `serialize_application_connection_metadata_record` — dossier 10 §4.1).

### 2.5 The removed helper surface (dossier 10 §7)

**90 distinct entity helper methods** across the data models call `self.app.rest.*`
(**102** call sites). **Every target already exists on `RESTClient`** — removing the helpers
needs **no new endpoints**, only that callers call `rest.*` and pass the ids the helper
sourced from `self`. Additionally **19** `self.app.cache.*` sites (and `get_me`/
`shard_count`) back cache accessors that have **no REST equivalent** (dossier 10 §7.1) — a
separate work-stream (drop, or take an explicit `cache` arg). The full helper inventory and
per-module tables live in
[`../03-app-removal-and-helpers/02-helper-method-inventory/00-README.md`](../03-app-removal-and-helpers/02-helper-method-inventory/00-README.md).

The only helpers doing more than a thin forward (dossier 10 §7.2), i.e. candidate optional
`rest.*` conveniences (owned by
[`../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md`](../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md)):

1. `User.send` (`users.py:429/588-614`) — cache DM lookup → `create_dm_channel` →
   `create_message`. Strongest candidate for `rest.send_dm(user, …)`.
2. `Message.remove_reaction` (`messages.py:1390`) — branch `delete_my_reaction` vs
   `delete_reaction`.
3. `Message.remove_all_reactions` (`messages.py:1472`) — branch `delete_all_reactions` vs
   `delete_all_reactions_for_emoji`.
4. Webhook helpers (`webhooks.py:217-221`, …) — resolve `webhook_id`+`token`, raise on
   missing token, then forward.
5. Interaction `build_*_response` — select the `ResponseType` constant and call the
   (app-free) builder factory (`command_interactions.py:214/246`).

---

## 3. Target design

### 3.1 REST stays the sole action API; only `_dumps`/`_loads` change underneath

`RESTClient` is essentially unchanged and becomes the *only* action layer. The encode side
is swapped by making `default_json_dumps` a `msgspec.json.encode`/module-`Encoder`
(single point in `data_binding.py`, owned by
[`../01-foundations/04-json-data-binding.md`](../01-foundations/04-json-data-binding.md));
`self._dumps` inherits it. All 58 `JSONObjectBuilder` bodies + 11 `payload_json` sinks flow
through unchanged (dicts encode natively). Audit for `Snowflake`/`Color` int-subclasses
reaching the encoder without lowering (dossier 10 §9; see the builder plan
[`../08-builders/00-special-endpoints-builders.md`](../08-builders/00-special-endpoints-builders.md) §3.3).

### 3.2 Response decode: `self._loads → dict → deserialize_*` today; typed `Decoder` end-state

Two staged options (align with
[`../01-foundations/05-decode-boundary-and-decoders.md`](../01-foundations/05-decode-boundary-and-decoders.md)):

- **Incremental (first pass):** keep `self._loads(bytes) -> dict` (now
  `msgspec.json.decode` untyped) then `entity_factory.deserialize_*(dict)`. `entity_factory`
  stops injecting `app` (drop `app=self._app`, `entity_factory.py:485-486` + 63 sites) and
  constructs app-less Structs, or bridges via `msgspec.convert(dict, type=Struct)`. Zero
  change to the 143 `deserialize_*` call sites in `rest.py`.
- **Declarative end-state:** replace `self._loads(response) -> dict` +
  `deserialize_X(dict)` with a single typed decode `msgspec.json.Decoder(X).decode(bytes)`
  per top-level entity type, bypassing the dict stage for covered types. This changes the
  `_request` decode contract (bytes-in vs dict-in) and is sequenced after the model Structs
  land. `entity_factory` retains ownership of the ~13 residual hard cases (re-keying,
  flatten, context injection) — see
  [`../05-entity-factory/00-architecture-and-decode-strategy.md`](../05-entity-factory/00-architecture-and-decode-strategy.md).

Recommendation: bytes-in typed decode for the end-state, dict-in via `msgspec.convert` as
the incremental bridge, so the risky model migration is decoupled from the low-risk
encoder/decoder swap.

```python
# _request success path — end-state sketch (per-type typed decode)
raw = await response.read()
if response.status == 204:
    return None
# caller passes the expected top-level type; the client holds a Decoder cache
return self._entity_factory.decode(raw, expected_type)   # -> frozen app-less Struct
```

### 3.3 Removed helpers → `rest.*` (mechanical, verbose, no new endpoints)

Callers rewrite (dossier 10 §8.1):

| Was (helper) | Now (`rest.*`) |
|---|---|
| `event.message.respond("hi")` | `rest.create_message(event.message.channel_id, "hi")` |
| `event.interaction.create_initial_response(t, …)` | `rest.create_interaction_response(event.interaction.id, event.interaction.token, t, …)` |
| `message.add_reaction("👌")` | `rest.add_reaction(message.channel_id, message.id, "👌")` |
| `user.send("hi")` | manual DM resolve + `rest.create_message(dm.id, "hi")` (or `rest.send_dm`) |

The ids the helpers hid (`channel_id`, `interaction.id`/`.token`, `webhook_id`/`token`) all
remain plain Struct fields, so substitution is mechanical.

### 3.4 The blessed path to `rest` is the closed-over bot object

After entities lose `.app` — and events too, per the resolved D10-events — gateway handlers reach
`rest` by **closing over the bot object** (`bot.rest`), which every shipped example but one already
does. The former `event.app.rest` path does not survive: the 31 entity-delegating `app` properties
(e.g. `message_events.py:87-89` `return self.message.app`) are **deleted outright, not converted to
stored fields** ([`00-events-migration.md`](../07-events/00-events-migration.md) §3.1). Interactions
use `rest.*` like everything else (D10-interactions, RESOLVED: interactions are app-less):
`event.interaction.create_initial_response(...)` becomes
`rest.create_interaction_response(interaction.id, interaction.token, ...)` — same REST call, so the
3-second interaction deadline is unaffected. For `RESTBot`, the listener flow is unchanged: the
handler already has the bot's `rest`, passes `interaction.id`/`.token` explicitly, and still
returns a builder — the 8 `build_*` factories are kept as app-free sync constructors
([`../03-app-removal-and-helpers/02-helper-method-inventory/06-interactions.md`](../03-app-removal-and-helpers/02-helper-method-inventory/06-interactions.md)).

---

## 4. Step-by-step migration

1. **Swap the encoder/decoder** in `data_binding.py:106-123` (owned by 04-json-data-binding);
   confirm `RESTClientImpl._dumps`/`_loads` defaults and the `RESTApp` forwards
   (`:319-320/328-329/450-451`) flow through.
2. **Audit request-body leaves:** ensure no raw `Snowflake`/`Color`/custom-enum reaches the
   encoder un-lowered across the 318 `put*` + 11 `payload_json` sinks; register the global
   `enc_hook` or rely on `put_snowflake`/`serialize_*` stringification.
3. **Confirm `OPT_NON_STR_KEYS` parity** for localization-map query/body keys after the
   `Locale` enum port (dossier 10 §2 note).
4. **De-`app` `entity_factory`:** drop `app=self._app` from the 63 construction sites
   (`entity_factory.py`); the 143 `deserialize_*` calls in `rest.py` stay unchanged in the
   incremental pass.
5. **(End-state) introduce typed `Decoder`s:** add a per-type `Decoder` cache and switch the
   `_request` success path to bytes-in typed decode for covered types; keep the dict path
   for residual hard-case types.
6. **Rewrite callers** of the 90 removed helpers to `rest.*` across examples, docs, and
   internal usage (dossier 10 §8.1). Add optional `rest.send_dm` and inline the reaction/
   webhook-token branches or replicate as small sugar (owned by 03-new-rest-methods).
7. **Cache accessors** (`Guild.get_channels()`, `Message.role_mentions`, …) — resolve
   separately (drop or explicit `cache` arg); REST cannot replace them (dossier 10 §7.1).
8. **Decide pluggable-json fate** — keep the `dumps`/`loads` overrides (change only the
   default) vs drop the decode override for Struct-typed paths (dossier 01 §8.6). A
   Struct-producing decode cannot honor a user-supplied generic `loads` — flag as a possible
   public API break.

---

## 5. Affected files & symbols

| File | Anchor(s) | Change |
|---|---|---|
| `hikari/internal/data_binding.py` | `:106-123` | encoder/decoder swap (single point) |
| `hikari/impl/rest.py` | `:754/795/895/1012`, 11 `payload_json` sinks | route through swapped `_dumps`/`_loads`; end-state typed decode at `:892-895` |
| `hikari/impl/rest.py` | `:593-594/620-621`, `:319-320/328-329/450-451` | `_dumps`/`_loads` injection wiring (keep or narrow) |
| `hikari/impl/rest.py` | `:222` `_RESTProvider`, `:435/445/461` | app-provider wiring (unaffected; still the `app` for cache accessors, not entities) |
| `hikari/impl/entity_factory.py` | `:485-486` + 63 `app=self._app` sites | stop injecting `app` |
| model modules (channels/messages/guilds/users/webhooks/templates/commands/presences/audit_logs/interactions) | dossier 10 §7 tables | remove 90 `self.app.rest.*` helpers; callers use `rest.*` |
| examples/docs | `examples/hello_world.py:28`, `image_resources.py:49`, `slash.py:42` | rewrite helper calls to `rest.*` |

Helper-removal details: the per-module files under
[`../03-app-removal-and-helpers/02-helper-method-inventory/`](../03-app-removal-and-helpers/02-helper-method-inventory/00-README.md).
The gateway/interaction-server JSON boundary is in the sibling
[`01-gateway-shard-and-interaction-server.md`](01-gateway-shard-and-interaction-server.md).

---

## 6. Risks / gotchas

- **REST itself is low-risk** — 0 `.app` refs, no entity storage, no copy/deepcopy; frozen
  Structs (c) need no REST change. The risk is entirely in the encoder swap and the caller
  rewrites.
- **int-subclass encode gap** — a `Snowflake`/`Color` reaching `msgspec.json.encode`
  un-lowered raises `TypeError` (the builders mostly stringify, but audit the 318 `put*`
  and `serialize_forum_tag`).
- **`OPT_NON_STR_KEYS`** — losing non-str-key tolerance breaks localization maps; verify
  after the `Locale` port.
- **DX regression is the headline break** — `message.respond` / `create_initial_response` /
  `user.send` are the primary documented patterns; every example and most user code changes
  (`interaction.create_initial_response` is the single largest ecosystem break — every command
  framework's `ctx.respond` wraps it). The exception: `*.build_response` survives — the builder
  factories are kept app-free, so REST-bot listeners are unchanged. Sequence loud changelog +
  migration-guide work
  ([`../11-rollout/03-breaking-changes-and-changelog.md`](../11-rollout/03-breaking-changes-and-changelog.md) §3.11).
- **Handler migration surface** — every handler using `event.app.rest` moves to the closed-over
  `bot.rest` (§3.4); the one in-tree example is `examples/voice_message/voice_message.py:90`.
- **Pluggable-json decode override** becomes semantically empty for Struct-typed decode; a
  user relying on a custom `loads` to shape output loses it — public API break to flag.
- **Cache accessors have no REST answer** — do not let them silently vanish into "use
  `rest.*`"; they read in-memory cache.

---

## 7. Verification

- **`grep -c '\.app' hikari/impl/rest.py` == 0** stays true after the migration.
- **Round-trip fixtures:** for each of the top `deserialize_*` targets, decode a recorded
  Discord response into an app-less Struct and assert field equality with the pre-migration
  entity (minus `.app`).
- **Encode parity:** every `JSONObjectBuilder` body and `payload_json` field encodes
  byte-identically under msgspec vs orjson for representative fixtures.
- **204 path:** an endpoint returning `204` still returns `None` (no decode attempted).
- **429 path:** the ratelimit body decode (`:1012`) still parses under msgspec.
- **Helper-removal grep:** `grep -rn 'self\.app\.rest' hikari/{channels,messages,guilds,
  users,webhooks,templates,commands,presences,audit_logs}.py hikari/interactions/` returns
  0 after the caller rewrites.
- **Example smoke:** the rewritten `hello_world`/`slash` examples run against a live token
  and post a message / respond to an interaction via `rest.*`.

---

## 8. Open questions / decisions

Cross-linked to [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md):

1. **Decode boundary — dict-in vs bytes-in** (D6/D7). Recommend bytes-in typed `Decoder`
   end-state, dict-in via `msgspec.convert` bridge; confirm timing relative to the model
   Struct migration. Detail:
   [`../01-foundations/05-decode-boundary-and-decoders.md`](../01-foundations/05-decode-boundary-and-decoders.md).
2. **Keep pluggable `dumps`/`loads`?** Keep encode override + default swap; decide whether
   the decode override survives for Struct-typed paths (likely a documented break).
3. **Optional convenience endpoints** — add `rest.send_dm` (covers `User.send`); decide
   whether reaction/`remove_all` dispatch and webhook token-guard sugar become `rest.*`
   methods or are inlined at call sites (owned by 03-new-rest-methods).
4. **Cache accessor fate** — drop vs explicit-`cache`-arg free functions for the 19
   `self.app.cache.*` accessors (owned by the cache and helper-inventory plans).
