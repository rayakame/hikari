# Events migration (frozen app-less event structs, the decoder registry, and the residual hydration layer)

Scope: the 20 `hikari/events/*.py` modules, `EventFactoryImpl`
(`hikari/impl/event_factory.py`), and the seams into the event manager and shard that the
new pipeline touches. This file applies three decisions: **D10-events** (RESOLVED by the
maintainer — events lose `app`), **D12** (the event_factory is largely replaced by a
name-keyed msgspec Decoder registry + `msgspec.Raw` envelope + a thin residual hydration
layer), and **D13** (`shard` STAYS on the event object). Evidence: dossiers 17 (the 77-method
classification), 18 (the empirical decode probe), 19 (manager/cache interplay and app blast
radius), and 20 (the shard-field typing probe); the empirical results are reproduced in-plan
at [`../12-appendices/04-event-pipeline-feasibility.md`](../12-appendices/04-event-pipeline-feasibility.md).
Interaction *models* are covered by
[`../06-model-modules/11-interactions.md`](../06-model-modules/11-interactions.md); the
interaction `app` policy is likewise **RESOLVED** (**D10-interactions** — interactions are app-less:
9 action helpers deleted, 8 builder factories kept app-free) in
[`../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md`](../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md).

---

## 1. Objective

- Serve constraint (a) *directly now*: events become **frozen, app-less structs**. The 44 own
  `app` fields, 31 entity-delegating `app` properties, the abstract `Event.app`, the
  `ExceptionEvent.app` proxy, and all 42 event helper methods are deleted (D10-events).
  Gateway handlers reach the client by closing over the bot object (see
  [`../03-app-removal-and-helpers/00-strategy.md`](../03-app-removal-and-helpers/00-strategy.md)).
- Replace the decode machinery of the 1216-line `event_factory.py` with a **name-keyed
  `dict[str, msgspec.json.Decoder]` registry** fed by a `msgspec.Raw` gateway envelope
  (D12). What survives is a thin **residual hydration layer**: shard/`old_*` attachment,
  guild-vs-DM class dispatch, sibling-context threading, GUILD_CREATE laziness, and the
  synthetic events. 45 of 77 factory methods become one-or-two-liners; ~73% end trivial.
- Keep `shard` **on the event object** (D13, maintainer-confirmed), implemented with the two
  verified patterns from dossier 20 — no `Optional` leaks into the public API.
- Serve constraint (c): events freeze; the `attrs_extensions` copy scaffolding disappears.
  One pre-fix is required first: the `chunk_nonce` post-construction mutation (gate item
  **T-CN**, §4 step 0).
- Serve constraint (b): flip the 5 loose `Enum | int` fields in this subtree to strict enums.

---

## 2. Current state

### 2.1 The 1216-line hand-written factory

`EventFactoryImpl` (`hikari/impl/event_factory.py`, 1216 lines) defines **77**
`deserialize_*` methods; **73** take a live `shard`, **17** take cache-fed `old_*` params,
and **50** inject `app=self._app` (dossier 17). Every method hand-builds the event: it calls
`self._app.entity_factory.deserialize_<X>(payload)` for wrapped entities and/or plucks
scalar payload keys through `Snowflake(...)`/enum/timestamp conversions, then constructs the
mutable `attrs` event class. msgspec never sees an event class today.

The gateway path: `shard._poll_events` (`shard.py:844-895`; the envelope is parsed at
`:200`) forwards the already-materialized `"d"` dict into
`event_manager.consume_raw_event(name, shard, payload)`, whose `on_*` handlers call the
factory. The factory is the single event-construction site (`ExceptionEvent` alone is built
elsewhere, at `event_manager_base.py:656`).

Dossier 17 bins the 77 methods:

| cat | methods | shape |
|---|---|---|
| **A** — pure entity wrapper | 27 | body ≡ `EventCls(shard, entity=deserialize_X(payload)[, old_*])` |
| **B** — flat event | 18 | event's own fields map ~1:1 to payload keys |
| **C** — residual reshaping | 21 | 5 split-only, 3 split+emoji-flatten, 3 sibling `guild_id` threading, 6 heavy, 4 misc-light |
| **D** — synthetic / special | 11 | 4 lifetime, 3 no-payload shard events, shard_payload passthrough, ready, member_chunk, interaction_create (ordinary wrapper over the app-less interaction) |

### 2.2 The event-side `app` surface (all of it goes)

- **44** `app: traits.RESTAware = attrs.field(...)` declarations across `hikari/events/*.py`.
- **33** `def app` in `events/`: 1 abstract (`base_events.py:83-86`), **31**
  entity-delegating properties (`return self.<entity>.app`), and 1 `ExceptionEvent` proxy
  (`base_events.py:207-211`, delegating to `failed_event.app`).
- **42** helper methods on events using `self.app.*`: 24 `self.app.rest.*` +
  18 `self.app.cache.*` call sites.
- **0** internal readers: `grep event\.app hikari/` matches only the delegating-property
  bodies themselves (dossier 19 §3). The break is purely public API; in-tree, exactly one
  example uses `event.app` (`examples/voice_message/voice_message.py:90`).

### 2.3 Dispatch mechanics (already registry-shaped)

Dispatch is already **name-keyed**: `EventManagerBase.__init__` scans `on_*` methods into
`self._consumers` (`event_manager_base.py:339-348`) and `consume_raw_event` looks the name
up and gates on `consumer.is_enabled` *before any deserialization* (`:404-420`) — lazy
decode gating exists today. `on_guild_create`/`on_guild_update` are deliberately **not**
`filtered()` and run in always-called mode (`event_manager_base.py:348`). The factory
already does post-parse class dispatch in-file (`_INTERACTION_EVENTS_MAP`,
`event_factory.py:77-82`), and the GUILD_CREATE/GUILD_DELETE availability variants are
dispatched *outside* the factory (`event_manager.py:278-289` / `:503-504`).

### 2.4 The one event mutation in hikari (freeze blocker)

`event_manager.py:420` executes `event.chunk_nonce = nonce` on an already-constructed
`GuildAvailableEvent`/`GuildJoinEvent` (fields declared with `default=None` at
`guild_events.py:180/244`). This is the **only** post-construction event mutation in the
codebase (dossier 19 §1.3) and it breaks the moment events freeze. Gate item **T-CN**
tracks the pre-fix (§4 step 0).

### 2.5 Loose `Enum | int` fields in this subtree

Only 5 (dossier 08 §8):

```
events/auto_mod_events.py:136                 rule_trigger_type: int | AutoModTriggerType | None
interactions/base_interactions.py:406         type: InteractionType | int
interactions/command_interactions.py:85       type: commands.OptionType | int
interactions/command_interactions.py:136      command_type: commands.CommandType | int
interactions/component_interactions.py:90     component_type: components_.ComponentType | int
```

### 2.6 `attrs` machinery to strip

`@attrs_extensions.with_copy` + `SKIP_DEEP_COPY` metadata appear 216× across event files
(dossier 08 §9). `auto_mod_events.py` uses the `attr` alias (not `attrs`) — a find/replace
gotcha (dossier 08 §2). All of the event-side usage disappears with the struct conversion;
`attrs_extensions.py` itself is SLIMMED in the first pass and deleted wholesale only once all
consumers are off attrs (see
[`../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md`](../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md)).

---

## 3. Target design

### 3.1 App removal applied to events (D10-events, RESOLVED)

Delete the whole §2.2 surface: the 44 own fields, the 31 delegating properties, the
abstract `Event.app` (`base_events.py:83-86`), the `ExceptionEvent.app` proxy
(`:207-211` — its `failed_event.app` target vanishes, so the proxy cannot survive either),
and the 42 helper methods. There are zero internal readers, so nothing inside hikari
changes behavior; the replacement pattern for users is closing over the bot object, which
every example except one already does.

Plan-wide helper accounting with both D10 halves resolved: **all ~173** app-delegating helper
sites (163 `self.app.*` + 10 `self.user.app`) are removed — ~114 wire-entity + 42 event + the
interaction sites (9 action helpers deleted; the 8 builder factories survive as app-free sync
constructors, losing their `self.app` usage)
([`../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md`](../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md)).
There is no retained set and no pending app decision; this supersedes the old
"Option 2 keeps ~59 event/interaction helpers" framing.

The four lifetime events (`lifetime_events.py`) — whose *only* field is `app` — become
field-less marker classes.

### 3.2 The pipeline: Raw envelope + name-keyed Decoder registry (D12)

Events become **frozen `kw_only` msgspec structs** on an `EventStruct` base that combines
the `Event` ABC (its `__init_subclass__` bitmask/dispatch registry, `requires_intents`,
`no_recursive_throw` — all preserved verbatim) with `msgspec.Struct` via a combined
`ABCMeta`+`StructMeta` metaclass, the same mechanism verified for entities (D3,
[`../12-appendices/03-base-struct-identity-verified.md`](../12-appendices/03-base-struct-identity-verified.md)).

The shard captures `"d"` as `msgspec.Raw` — a zero-copy view; the envelope decode touches
only the skeleton — and the manager decodes it **only when the consumer is enabled**:

```python
# built ONCE at module/manager level (dossier 18 §3, verified)
class GatewayEnvelope(msgspec.Struct):
    op: int
    d: msgspec.Raw = msgspec.Raw(b"null")
    s: int | None = None
    t: str | None = None

_ENVELOPE = msgspec.json.Decoder(GatewayEnvelope)

_DECODERS: dict[str, msgspec.json.Decoder] = {
    "MESSAGE_CREATE": msgspec.json.Decoder(messages.Message, dec_hook=DEC_HOOK),          # P1: decode the ENTITY
    "THREAD_DELETE":  msgspec.json.Decoder(GuildThreadDeleteEvent, dec_hook=DEC_HOOK),    # P2: decode the EVENT itself
    # ... default skip-unknown-fields; NEVER forbid_unknown_fields (dossier 18 §2.4 —
    # verified to break on Discord's extra keys)
}
```

Today the full `"d"` dict is materialized even when the consumer is disabled and then
discarded; with Raw the disabled path becomes near-free and the enabled path parses `"d"`
exactly once — never two full parses (dossier 19 §2.3). Registry misses stay ordinary dict
misses, preserving the `LookupError`/"ignoring unknown event" contract.

The two decode shapes, both empirically verified on msgspec 0.21.1 (dossier 18):

**P1 — wrapper events (the 27 A methods, plus the split families).** The event struct is
*never decoded*; the registry decodes the entity, and the glue is a one-liner:

```python
# events/message_events.py — P1: hand-constructed, never meets a Decoder
class GuildMessageCreateEvent(EventStruct, frozen=True, kw_only=True):
    shard: gateway_shard.GatewayShard      # REAL runtime class; plain REQUIRED field (D13 pattern P1)
    message: messages.Message              # frozen app-less UniqueStruct entity

# residual glue — one line per A method; guild/DM splits add <=4 lines (§3.4)
message = _DECODERS["MESSAGE_CREATE"].decode(env.d)
cls = DMMessageCreateEvent if message.guild_id is None else GuildMessageCreateEvent
return cls(shard=shard, message=message)
```

**P2 — flat events (the 18 B methods).** The event struct **is** the decode target; wire
renames move into `msgspec.field(name=...)` declarations (`thread_id/guild_id/channel_id/
message_id ← "id"`, `event_id ← "guild_scheduled_event_id"`, `message_ids ← "ids"`,
`raw_endpoint ← "endpoint"`), scalars ride the global `dec_hook`, and `shard` is injected
post-decode (§3.3). Bench: typed decode + `dec_hook` runs at 3.20 µs/op vs 7.66 µs for the
stdlib-json→dict→hand-attrs path (~2.4×) and 4.03 µs for msgspec→dict→hand-construct
(~1.3×) — the typed path is not paying for its convenience (dossier 18 §6).

`old_*` values stay cache-fed and never decode: constructor kwargs on P1 events,
`msgspec.structs.replace(event, old_x=cached)` on P2 events — both verified to preserve the
exact cached instance (dossier 18 §4). Three scalar hooks beyond the global
Snowflake/Color/enum `dec_hook` are needed: a `UnixTimestamp` marker type for the three
unix-SECONDS fields (typing `:312`, channel_info `:993`, voice start `:1071`), hex-string
input for `Color` (`burst_colors`, `:787`), and `SnowflakeSet` (`:766`).

Collapse estimate (dossier 17 §5): 45/77 methods become one-or-two-liners outright, ~56/77
end at ≤6 lines, and the file shrinks from 1216 to an estimated **400–550 lines**
(**55–65% deleted**). All 50 `app=self._app` injections vanish; once the
`entity_factory.deserialize_*` calls are swapped for typed Decoders, the successor layer
holds decoders instead of the app and loses its `traits.RESTAware` dependency.

### 3.3 `shard` stays on the event object (D13)

`shard` is the one runtime reference events legitimately retain: unlike `app`, its
information is **irreplaceable** (which connection received the event — never derivable
from JSON), and unlike `app`, injecting it is msgspec-compatible, so there is no forcing
function to remove it. The two verified patterns (dossier 20):

- **P1 (hand-constructed events — the majority):** a plain **required** field
  `shard: gateway_shard.GatewayShard`. Constructing without it raises
  `TypeError: Missing required argument 'shard'`; the decoder never sees the field because
  these structs are never decoded. No `Optional` anywhere.
- **P2 (direct-decode flat events):** defaulted *storage* + non-optional *property*:

```python
class GuildThreadDeleteEvent(EventStruct, frozen=True, kw_only=True):
    thread_id: snowflakes.Snowflake = msgspec.field(name="id")
    guild_id: snowflakes.Snowflake
    parent_id: snowflakes.Snowflake
    type: channels.ChannelType
    _shard: gateway_shard.GatewayShard | None = msgspec.field(
        default=None, name="__hikari_runtime_shard__"
    )

    @property
    def shard(self) -> gateway_shard.GatewayShard:   # public API stays NON-optional
        assert self._shard is not None
        return self._shard
```

Injection happens via `msgspec.structs.force_setattr(event, "_shard", shard)` in the
single-owner decode→dispatch window (78 ns vs 132 ns for `structs.replace`; dossier 18
§2.3). After dispatch, frozen is a user-visible contract — never `force_setattr` a
published event.

Two details are load-bearing:

- **The `name=` rename.** Without it, a wire payload that happened to contain a literal
  `"_shard"` key would be routed into the global `dec_hook` with `t=GatewayShard` and raise;
  with the `"__hikari_runtime_shard__"` rename, such a key is just an unknown key and is
  skipped harmlessly (verified, dossier 20 §3).
- **The annotation is the REAL class.** Decoder construction is lazy in 0.21.1, so a
  runtime-class annotation never breaks `Decoder()` construction; a colliding wire key then
  fails LOUD with `ValidationError`. Never annotate runtime fields as `typing.Any` (silently
  accepts raw JSON) or `object` (0.21.1 routes it into the registered global `dec_hook`)
  — dossier 18 §2.1-2.2.

The storage+property form matches the existing abstract `ShardEvent.shard` property
(`shard_events.py:69`) exactly. Further rationale for keeping the field: the purity gain of
removing it would be marginal (only the 18 flat events would become zero-glue);
self-describing events keep their provenance when queued or forwarded to other tasks; and
`ExceptionEvent.retry()` stays simple. The considered-and-not-chosen alternative is §3.6.

### 3.4 The residual hydration layer

What msgspec cannot absorb — by design, a few mechanical lines per event instead of today's
per-field hand construction:

1. **The 9 guild-vs-DM splits**, with **three different discriminators** (dossier 17 §2):
   - `"guild_id" in payload`: pins, typing, message_delete, and the 3 reaction-removes;
   - post-decode `message.guild_id is None`: message_create, message_update;
   - **`"member" in payload`**: reaction_add (`event_factory.py:789`) — *not* `guild_id`.
   Each split is a ≤4-line post-decode dispatch (decode once, pick the class, attach shard)
   — verified as a 3-line branch in dossier 18 §5. The GUILD_CREATE/GUILD_DELETE
   availability variants stay dispatched in the event manager
   (`event_manager.py:278-289`/`:503-504`), outside this layer.
2. **Sibling `guild_id` threading** — a child entity's field comes from an *outer* payload
   key: roles (`:592-594`), known custom emojis (`:433-436`), members (typing `:316`,
   reaction_add `:791`, member_chunk `:954`), presences. msgspec cannot propagate parent
   context during decode; each site keeps a small envelope-struct + fixup (~2 lines for the
   light cases).
3. **The GUILD_CREATE family** — the hard core, migrated as a unit of its own.
   `_GatewayGuildDefinition` (`entity_factory.py:261`) is *lazy* — sub-collections parse
   only when accessed, and the handler skips construction entirely when nobody listens.
   It is also the one place where runtime context is a **decode input**:
   `shard.get_user_id()` fills the bot's own `ThreadMember.user_id`, absent from
   GUILD_CREATE thread payloads (`entity_factory.py:427/1543-1556`) — a context-free
   Decoder cannot express this. Preserving the laziness (per-section Decoders over
   `msgspec.Raw` sub-fields vs accepting eager decode) is gate item **SD5**; recommend
   preserve (§8).
4. **presence_update** — the hand-built partial user with `undefined.UNDEFINED` defaults
   for absent keys (`:503-527`) and its ">1 key" guard (`:501`) stay residual; the
   `UndefinedOr` typing strategy is an entity-side decision.
5. **Reshapers** — the list→dict joins of thread_list_sync/thread_members_update/
   member_chunk (keyed by nested ids, a genuine two-array join), the shared reaction-emoji
   flatten (`_split_reaction_emoji`, `:818-824`, with value-dependent `UnicodeEmoji`
   typing), the unix-SECONDS timestamps (§3.2), hex-string `burst_colors` (`:787`), and the
   auto_mod falsy coercions (`:1210-1215`).
6. **Synthetic events** — the 4 lifetime markers, the 3 no-payload shard events
   (connected/disconnected/resumed), `ShardPayloadEvent` (deliberately untyped
   passthrough), ready, member_chunk; interaction_create keeps its
   `_INTERACTION_EVENTS_MAP` dispatch and is an ordinary wrapper — decode/transform the
   app-less interaction ([`../06-model-modules/11-interactions.md`](../06-model-modules/11-interactions.md)),
   pick the event class, construct with `shard`; no `app` anywhere.

### 3.5 Decode-once-share-everywhere (the cache seam)

Verified end to end (dossier 19): `impl/cache.py` has **zero** raw-payload reads — every
`set_*`/`update_*` takes an entity — and the `on_*` handlers read the raw dict in exactly
**19 places**, all covered by decoded fields (old_* ID lookups, branch discriminators,
`payload.get("large")`). The migration inverts the order: **decode first**, then do the
`old_*` cache lookup with decoded fields, then construct the frozen event. The same decoded
frozen entity object goes into the cache AND the event — freezing makes the sharing safe,
and msgspec's silent unknown-key drop is invisible to the cache by construction. Dispatch
(`event.dispatches()` bitmasks, listeners, waiters, streams) is untouched.

### 3.6 Alternative considered: `shard` as a listener parameter (NOT chosen)

The design: remove the field and pass the shard as an optional second listener argument —
`async def h(event)` keeps working; `async def h(event, shard)` receives it.

Mechanically it is cheap: hikari already introspects listener signatures in `listen()`, and
`_assert_is_listener` **already permits defaulted extra parameters**, so subscribe-time
arity detection is a small change; `dispatch(event, *, shard=None)` plus 67 mechanical
call-site edits; `_invoke_callback` branches on a flag stored at subscribe time.

Why it was not chosen:

- **Dual calling convention forever** — two listener shapes in the `CallbackT` union, plus
  a permanent introspection edge policy (decorated callables, `functools.partial`, C
  callables).
- **Ecosystem churn** — command frameworks wrap listener registration and would all need to
  learn the second shape.
- **Permanent `wait_for`/`stream` asymmetry** — they return events, so the shard would not
  ride along. No *capability* is lost — the bot-level equivalents cover every shard action
  (`update_presence` `gateway_bot.py:1295`, `update_voice_state` `:1314`,
  `request_guild_members` `:1327`, `voice.connect_to` `voice.py:140` all route internally)
  — but the asymmetry is a wart the API would carry forever.
- **Provenance loss** — an event queued or forwarded to another task no longer knows which
  connection produced it.
- **`ExceptionEvent`** needs the failed event's shard anyway (`base_events.py:213-223`).

The alternative is strictly **additive**: it can be layered on later (arity detection plus
a `shard=` kwarg on `dispatch`) without removing `event.shard`. Documented here so the
option is preserved; D13 stands.

### 3.7 Strict enums

Flip the 5 fields in §2.5 to the bare strict enum type. The enums stay hikari's fast custom
`enums.Enum`/`Flag` — adopt PR hikari-py/hikari#2770, which makes the shared `_EnumMeta.__call__` mint an
`is_unknown` pseudo-member on unrecognised values (decision D2). Those pseudo-members are produced by the
shared `dec_hook` (`t(obj)`), so no `| int` widening is needed. `InteractionType`/`ResponseType` are
**kept** as custom enums (not ported to stdlib) with the rest (see
[`../02-enums/00-strategy-and-forward-compat.md`](../02-enums/00-strategy-and-forward-compat.md)).
The `MessageResponseTypesT`/`DeferredResponseTypesT`/… `Literal` unions that mix enum
members with bare ints (`base_interactions.py:238/258`, etc.) should drop the bare-int
alternatives when enums go strict.

---

## 4. Step-by-step migration

0. **Pre-fix the `chunk_nonce` mutation (T-CN).** Hoist the chunk-eligibility check in
   `on_guild_create` above event construction, compute the nonce first, and pass it as a
   constructor argument (`event_manager.py:420`; fields at `guild_events.py:180/244`).
   Land this as its own PR *before* any event freezes — it is the single freeze blocker.
1. **Land the `EventStruct` base**: combined `ABCMeta`+`StructMeta` metaclass; verify the
   `Event.__init_subclass__` bitmask/dispatch registry, `requires_intents`, and
   `no_recursive_throw` fire unchanged on Struct subclasses.
2. **Delete the app surface** (§3.1): 44 fields, 31 delegating properties, abstract
   `Event.app`, `ExceptionEvent.app` proxy, 42 helpers, the 50 factory injections; convert
   the lifetime events to field-less markers; fix `examples/voice_message/voice_message.py:90`
   to close over `bot`.
3. **Convert the P1 wrapper events** (27 A methods + the split families): required
   `shard` field, entity field(s), `old_*` as `T | None = None` constructor kwargs.
4. **Convert the P2 flat events** (18 B methods): the event struct becomes the decode
   target — `msgspec.field(name=...)` renames, `UnixTimestamp`/hex-`Color`/`SnowflakeSet`
   hooks, `_shard` storage + non-optional property (§3.3).
5. **Build the registry**: `GatewayEnvelope` + `dict[str, msgspec.json.Decoder]`, hooks
   bound once at construction, default skip-unknown-fields. Capture `"d"` as `msgspec.Raw`
   in `shard._poll_events`; decode the shard's own READY/RATE_LIMITED/INVALID_SESSION needs
   from tiny partial structs (dossier 19 §2.3). Keep `consume_raw_event` as the single
   entry point with its `is_enabled` gate; preserve always-called mode for
   `on_guild_create`/`on_guild_update`.
6. **Port the residual C methods** (§3.4): the ≤4-line splits (watch reaction_add's
   `"member"` discriminator), the sibling-threading fixups, the reshapers, presence_update.
   Migrate the **GUILD_CREATE family as its own unit**, resolving SD5 (lazy Raw
   sub-sections recommended) and keeping the `shard.get_user_id()` post-decode fixup.
7. **Port the D methods**: lifetime markers, no-payload shard events, `ShardPayloadEvent`
   passthrough, ready, member_chunk (keep its `typing.Sequence[Member]` implementation);
   interaction_create as an ordinary wrapper (decode/transform the app-less interaction,
   `_INTERACTION_EVENTS_MAP` class pick, construct with `shard`).
8. **Reshape the public adapters**: the `api/event_factory.py` 77-method ABC shrinks to the
   route-table protocol (or a deprecated façade over it); `consume_raw_event`'s payload
   type, `ShardPayloadEvent.payload`, and the inbound `loads=` params change per §6
   (coordinate with [`../09-rest-and-gateway/01-gateway-shard-and-interaction-server.md`](../09-rest-and-gateway/01-gateway-shard-and-interaction-server.md)).
9. **Strict enums** (§3.7) and the test suite: rewrite `test_event_factory.py` around the
   registry, add the per-event fixture smoke test (§7), re-run the dispatch regression
   suite.

---

## 5. Affected files & symbols

| File | Anchor(s) | Change |
|---|---|---|
| `hikari/events/base_events.py` | `:59-96`, `:83-86`, `:184-240` | Keep `Event` ABC + `__init_subclass__` dispatch registry; **delete abstract `app`** (`:83-86`) and the `ExceptionEvent.app` proxy (`:207-211`); `ExceptionEvent` stays attrs/non-msgspec (live `Exception` + coroutine), keeps `shard` (`:213-223`) |
| `hikari/events/*.py` (20 modules) | §2.2 lists | 44 `app` fields + 31 delegating properties + 42 helpers deleted; events → frozen `EventStruct` (P1 required `shard` / P2 `_shard` storage+property); drop `with_copy`/`SKIP_DEEP_COPY` |
| `hikari/events/lifetime_events.py` | whole module | 4 events become field-less marker classes |
| `hikari/events/shard_events.py` | `:69`, `:92`, `:216/259-275` | Abstract `shard` property kept (P2 pattern matches it); `ShardPayloadEvent.payload` type changes with the Raw envelope; `MemberChunkEvent` keeps its `Sequence[Member]` implementation |
| `hikari/impl/event_factory.py` | 1216 lines | Shrinks to est. 400–550 lines: registry tables + residual hydration layer (§3.4); all 50 `app=self._app` injections deleted |
| `hikari/api/event_factory.py` | 77 abstract methods | Reshaped to the route-table protocol (public break) |
| `hikari/impl/event_manager.py` | `:420`, `:278-289`, `:503-504`, 19 raw reads | `chunk_nonce` pre-fix (T-CN); decode-first reorder of every raw-payload read; availability branches move onto decoded fields |
| `hikari/impl/event_manager_base.py` | `:339-348`, `:404-420` | `_Consumer` (or a parallel route table) gains the per-name Decoder; `is_enabled` gating and always-called mode preserved |
| `hikari/api/event_manager.py` | `:168` | `consume_raw_event` payload type: `JSONObject` → bytes/`msgspec.Raw` (public break) |
| `hikari/impl/shard.py` | `:844-895`, `:200`, `:561-562` | Capture `"d"` as `msgspec.Raw`; partial-decode READY/RATE_LIMITED/INVALID_SESSION; inbound `loads=` param deprecated/replaced |
| `hikari/impl/gateway_bot.py` | `:331-332` | Same `loads=`/`dumps=` treatment |
| `hikari/events/auto_mod_events.py` | `:36`, `:136` | `attr`→`attrs` alias normalization dies with the struct conversion; strict `AutoModTriggerType` |
| `hikari/interactions/base_interactions.py` | `:406` | strict `InteractionType` (adopt #2770) |
| `hikari/interactions/command_interactions.py` | `:85`, `:136` | strict `OptionType`/`CommandType` |
| `hikari/interactions/component_interactions.py` | `:90` | strict `ComponentType` |
| `hikari/internal/attrs_extensions.py` | event-side `with_copy`/`SKIP_DEEP_COPY` usage | dropped here; the module is slimmed first, deleted wholesale in a later phase (see 04-frozen-and-cache) |
| `examples/voice_message/voice_message.py` | `:90` | the one in-tree `event.app` user → close over `bot` |

Interaction *model* field/`app`/helper changes are owned by
[`../06-model-modules/11-interactions.md`](../06-model-modules/11-interactions.md) and
[`../03-app-removal-and-helpers/02-helper-method-inventory/06-interactions.md`](../03-app-removal-and-helpers/02-helper-method-inventory/06-interactions.md);
this file only covers the interaction-create *events* (which keep the
`_INTERACTION_EVENTS_MAP` dispatch and wrap the now app-less interaction structs) and the
enum flips.

---

## 6. Risks / gotchas

- **reaction_add splits on `"member"`, not `"guild_id"`** (`event_factory.py:789`). A
  mechanical "branch on guild_id" sweep across the 9 split methods silently misroutes
  MESSAGE_REACTION_ADD; a DM reaction *can* carry no member while a guild reaction always
  does. Treat the three discriminators (§3.4) as a checklist, and cover reaction_add with
  both guild and DM fixtures.
- **Decoder construction is lazy — typos fail at first decode, not at import.** A
  mis-annotated field in a P2 event builds a Decoder fine and only raises on the first
  payload that contains that field. Mitigation: the registry fixture smoke test (§7) is
  **mandatory**, not optional.
- **GUILD_CREATE laziness (SD5).** A monolithic typed decode of the largest gateway payload
  would eagerly parse members/presences/voice_states even with those cache components
  disabled, sacrificing both laziness layers (`_GatewayGuildDefinition` +
  `_enabled_for_event` skip). Keep per-section decoders over Raw sub-fields (recommended)
  or explicitly accept eager decode — a maintainer sub-decision, not a silent default.
- **The Raw envelope is a public break** (record in
  [`../11-rollout/03-breaking-changes-and-changelog.md`](../11-rollout/03-breaking-changes-and-changelog.md)):
  `EventManager.consume_raw_event`'s payload type (`api/event_manager.py:168`),
  `ShardPayloadEvent.payload` (`shard_events.py:92`), the injectable `loads=`/`dumps=`
  params (`shard.py:561-562`, `gateway_bot.py:331-332`), and the reshaped `EventFactory`
  ABC (custom implementations are a public extension point).
- **The `name=` rename on `_shard` is load-bearing** (§3.3). Omitting it turns a
  coincidental `"_shard"` wire key into a `dec_hook` call with `t=GatewayShard`. Same
  hazard class: never annotate runtime fields `typing.Any` (silent raw-JSON smuggling) or
  `object` (routes into the global hook).
- **`force_setattr` discipline**: only in the single-owner decode→inject→dispatch window.
  After dispatch, frozen is a user-visible contract.
- **`forbid_unknown_fields` must stay OFF** for every registry decoder — Discord adds
  payload fields constantly, and the flat structs deliberately ignore keys their DM/guild
  sibling consumes (verified breakage, dossier 18 §2.4).
- **The chunk_nonce mutation is a hard freeze blocker** (T-CN, §2.4). Sequencing matters:
  the pre-fix must merge before the guild events freeze.
- **Special carriers**: `ExceptionEvent` (live `Exception` + coroutine callback) stays
  non-msgspec; `MemberChunkEvent` implements `typing.Sequence[Member]` — keep the
  implementation, whatever the base; `ShardPayloadEvent.payload` /
  `ShardRateLimitedEvent.meta` stay raw mappings by design.
- **Semantic enum change** — after strict enums, an unknown `AutoModTriggerType`/
  `InteractionType`/… decodes to an enum pseudo-member, not a bare `int`
  (`type(x) is int` becomes False); document in the changelog.

---

## 7. Verification

- **Registry smoke test (mandatory, counters the lazy-Decoder hazard):** one recorded
  fixture payload per registered gateway name, decoded through the real registry in CI;
  every decoder in `_DECODERS` must be exercised at least once.
- **App-removal greps:** `grep -rn "def app" hikari/events/` returns nothing;
  `grep -rn "app=" hikari/impl/event_factory.py` returns nothing; `grep -rn "self\.app"
  hikari/events/` returns nothing.
- **Shard checks:** constructing a P1 event without `shard` raises `TypeError`; a P2 event
  decoded from a payload containing a literal `"_shard"` key skips it harmlessly; after
  `force_setattr`, `event.shard` returns the exact shard instance and the public property
  type is non-optional.
- **Split fixtures:** all 9 guild/DM splits covered with both variants — including
  reaction_add fixtures where the member key, not guild_id, decides the class.
- **Chunk nonce:** `GuildAvailableEvent`/`GuildJoinEvent` are constructed with
  `chunk_nonce` already set when chunking applies; no post-construction assignment exists
  (grep `event.chunk_nonce =` is empty).
- **Frozen check:** setattr on any event raises; `old_*` injection via constructor/`replace`
  preserves the cached instance identity.
- **Dispatch regression:** `tests/hikari/impl/test_event_manager*.py` and
  `test_base_events` pass with the `EventStruct` base (bitmask/intents preserved);
  `is_enabled` gating still short-circuits before any decode; unknown names still surface
  as "ignoring unknown event".
- **End-to-end:** feed recorded `MESSAGE_CREATE`, `TYPING_START`, `GUILD_CREATE`,
  `MESSAGE_REACTION_ADD` envelopes through shard→manager→registry; assert class selection,
  `event.shard is shard`, cache writes receiving the same decoded object the event wraps,
  and that neither event nor entity has an `app` attribute.
- **Performance:** re-run the dossier 18 §6 bench shape in
  [`../11-rollout/02-performance-benchmarking.md`](../11-rollout/02-performance-benchmarking.md)
  against the merged pipeline (dossier 18 §6 measured ~2.4× vs the NON-speedups stdlib path — the probe venv lacked orjson/ciso8601; the binding comparison is against the orjson B0 baseline in that benchmarking file).

---

## 8. Open questions / decisions

Cross-linked to [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md)
and the tracker
[`../12-appendices/01-open-questions-and-verifications.md`](../12-appendices/01-open-questions-and-verifications.md):

1. **D10-events — RESOLVED by maintainer.** Events are app-less: 44 fields + 31 delegating
   properties + the `ExceptionEvent` proxy + 42 helpers removed; zero internal readers.
   **D10-interactions — RESOLVED by maintainer as well**: interactions are app-less — the 9
   action helpers are deleted (callers → `rest.*`) and the 8 builder factories are kept as
   app-free sync constructors, so the REST-bot return-a-builder flow is unchanged;
   `InteractionCreateEvent` wraps an app-less interaction and interaction_create is an
   ordinary wrapper (§3.4). It is the migration's largest ecosystem break, cataloged in
   [`../11-rollout/03-breaking-changes-and-changelog.md`](../11-rollout/03-breaking-changes-and-changelog.md).
   Full writeup:
   [`../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md`](../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md).
2. **D12 — LOCKED.** Name-keyed Decoder registry + `msgspec.Raw` envelope + thin residual
   hydration layer, empirically verified (dossiers 17–19;
   [`../12-appendices/04-event-pipeline-feasibility.md`](../12-appendices/04-event-pipeline-feasibility.md)).
   The Raw-related public breaks (§6) ride with it.
3. **D13 — LOCKED (maintainer-confirmed).** `shard` stays on the event object via the two
   verified patterns (dossier 20); the listener-parameter alternative is documented (§3.6),
   remains additive, and was not chosen.
4. **SD5 — GUILD_CREATE laziness.** Preserve via `msgspec.Raw`/lazy per-section decoders
   (recommended) vs accept eager decode of the largest gateway payload. Maintainer
   sub-decision before the GUILD_CREATE family unit (§4 step 6) lands.
5. **T-CN — chunk_nonce pre-fix.** Restructure `event_manager.py:420` to compute the nonce
   pre-construction; must merge before events freeze (§4 step 0).
6. **`Literal` response-type unions** — drop the bare-int arms when enums go strict, or
   keep them for input lenience on the response-builder call sites? (Ties to the
   method-parameter-union policy in [`../02-enums/03-strict-enum-field-inventory.md`](../02-enums/03-strict-enum-field-inventory.md).)
