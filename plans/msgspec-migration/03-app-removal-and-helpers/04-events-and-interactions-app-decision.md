# Events and Interactions — the App Decision (D10, FLAGGED)

The one maintainer-level policy call in the app-removal cluster. Constraint (a) forces `app` off
JSON-decoded wire entities, but **events and interactions are hand-constructed, not msgspec-decoded**
(dossier 08 §0, §10.1), so the "can't inject on decode" constraint does not technically bite them.
Whether they *also* go app-less "for symmetry" is a genuine choice with a large ergonomics/latency
cost. This file lays out both options in full and recommends **option 2**. It does not silently pick
the most-breaking path.

This is decision **D10** in [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md).
Applies alongside [`../07-events/00-events-migration.md`](../07-events/00-events-migration.md) and
[`../06-model-modules/11-interactions.md`](../06-model-modules/11-interactions.md).

---

## 1. Objective

Decide, explicitly, whether:
- **Events** keep their `app` field + `self.app.rest.*` / `self.app.cache.*` helpers, or lose them.
- **Interactions** keep their response sugar (`create_initial_response`, `build_response`, …) via an
  app-injecting construction path, or become pure app-less data like wire entities.

The decision changes how many of the 163 helpers are removed vs. retained, and it determines the
blessed path callers use to reach `rest` after wire entities lose `.app` (dossier 10 §8.2).

---

## 2. Why the constraint does not force this

Constraint (a) is about **decode-time injection**: `msgspec.json.decode(bytes, type=Struct)` has no
seam to attach `self._app`. Events and interactions are not on that path:

- **Events** are built by `EventFactoryImpl` (`impl/event_factory.py:85`). Each `deserialize_*_event`
  first builds the wrapped **entity** via `self._app.entity_factory.deserialize_*`, then constructs the
  event `attrs` class, passing the entity plus `shard` and (for some events) `app=self._app`
  (dossier 08 §0, §4). msgspec never sees an event class. Events legitimately hold non-serializable
  runtime references (`app`, `shard`, `Exception`, coroutine callbacks) — a poor fit for a Struct
  anyway (dossier 08 §10.1). **Events can and probably should stay `attrs`** (frozen), and an attrs
  field can hold a frozen msgspec entity with no structural problem.

- **Interactions** are built by the entity factory too, but they are unusual: `PartialInteraction`
  (`base_interactions.py:272`) is *both* an entity model *and* a client — it stores `app`, subclasses
  `webhooks.ExecutableWebhook`, and defines ~17 direct + 4 inherited `self.app.*` helpers
  (dossier 08 §7.3). Because they are hand-constructed by the factory, injecting `app` into them is as
  trivial as it is for events. The constraint only *technically* applies if interactions are put on the
  declarative-decode path.

So the decision is about **consistency vs. ergonomics**, not about what msgspec allows.

---

## 3. What actually breaks regardless of the decision

Independent of D10, one thing is a hard blocker and must be fixed either way (dossier 08 §5.2, §10.2):

**31 events derive `app` from their wrapped entity via a `@property`** (`return self.<entity>.app`) —
e.g. `GuildMessageCreateEvent.app → self.message.app` (`message_events.py:87-89`),
`GuildChannelCreateEvent.app → self.channel.app`, `InteractionCreateEvent.app → self.interaction.app`.
The moment the wrapped entity is an app-less msgspec Struct, **every one of these 31 properties fails**
(dossier 08 §5.2 lists all of them). The event has no other way to reach the client.

Required fix (both options): every delegating event gets its **own** `app: traits.RESTAware` field
(mirroring the 44 events that already store one, dossier 04 §0 / dossier 08 §5.1), and `event_factory`
passes `app=self._app` at the ~30 currently app-less construction sites (message `:709/:711`, channel
`:118/:132/:142/…`, voice `:1054`, interaction-create `:547-552`, role, scheduled, stage, typing,
reaction-add, member, guild-available/join/update, presence, audit-log, auto-mod-rule, own-user,
shard-ready — dossier 08 §10.2). This is mechanical but touches ~30 methods. `ExceptionEvent.app →
self.failed_event.app` (`base_events.py:207-211`) is the one delegating property that stays — it reads
another **event's** `app`, which survives (dossier 08 §1.3; see [`01-app-field-removal.md`](./01-app-field-removal.md) §5.2).

Pure-data forwards on events (`.id`, `.channel_id`, `.guild_id`, `.author`, `.member`, `.webhook_id`,
`.is_bot`) keep working — they read real Struct fields, not `app` (dossier 08 §4, §10.2).

---

## 4. Option 1 — events and interactions ALSO go app-less + helper-less

**Maximally consistent, maximally breaking.**

Events lose `app`; the 24 event `self.app.rest.*` helpers (dossier 08 §6) and 19 event `cache`
getters are deleted. Interactions lose `app`, stop subclassing `ExecutableWebhook`, and lose all ~21
`self.app.*` helpers — including `create_initial_response`, `edit_initial_response`,
`fetch_initial_response`, `create_modal_response`, `create_autocomplete_response`, and the inherited
`execute`/`fetch_message`/`edit_message`/`delete_message` (dossier 08 §7.3, §10.3). Callers do
everything via `rest.*`.

What callers write instead:
```python
# event helper → rest
await event.fetch_channel()            → await rest.fetch_channel(event.channel_id)
event.get_guild()                      → cache.get_guild(event.guild_id)
# interaction sugar → rest
await interaction.create_initial_response(ResponseType.MESSAGE_CREATE, "hi")
    → await rest.create_interaction_response(interaction.id, interaction.token,
                                             ResponseType.MESSAGE_CREATE, "hi")
build = interaction.build_response()   → build = rest.interaction_message_builder(ResponseType.MESSAGE_CREATE)
```

But note: even under option 1, **events must still store `app`** to fix the §3 blocker — otherwise
`event.app.rest.*` (the recommended replacement path, dossier 10 §8.2) does not exist and callers have
*no* stable handle to `rest` from a gateway event. So option 1's "events lose `app`" is in tension
with the very migration path it depends on. In practice option 1 keeps the `app` field on events but
deletes the *helpers* — a half-measure that removes ergonomics while retaining the field.

| Pros | Cons |
|---|---|
| One rule everywhere: "entities/events/interactions are data; use `rest.*`." | Kills the primary documented pattern (`interaction.create_initial_response`, `event.message.respond`) — every example and most user code breaks (dossier 10 §8.1). |
| Smallest conceptual surface; nothing special about interactions. | Interaction response latency ergonomics regress hardest (see §6). |
| Interactions become trivially freezable pure data. | `build_response`/`build_deferred_response`/`build_modal_response` are **app-free already** (dossier 08 §7.4) — deleting them discards ergonomics for *zero* constraint benefit. |
| | Still must store `app` on events for the `rest` handle (§3), so it does not even achieve full symmetry. |

---

## 5. Option 2 — events keep app+helpers; interactions keep response sugar (RECOMMENDED)

**Pragmatic; honours the constraint exactly where it bites and nowhere else.**

- **Events keep their own `app` field and their `self.app.rest.*` / `self.app.cache.*` helpers.** They
  are hand-constructed, so app injection is trivial (dossier 08 §10.1). The §3 fix (give the 31
  delegating events their own `app` field + inject it in `event_factory`) is done, which *also* makes
  `event.app.rest.*` the stable blessed path (dossier 10 §8.2). Event helpers (`event.fetch_guild()`,
  `event.get_channel()`) survive.

- **Interactions are constructed via a non-declarative, app-injecting path** (they already are —
  the entity factory builds them, dossier 08 §7), so they **keep `app`** and keep their latency-
  critical response sugar: `create_initial_response`, `edit_initial_response`,
  `delete_initial_response`, `fetch_initial_response`, `create_modal_response`, followups via
  `ExecutableWebhook`, and the app-free builder factories (`build_response`,
  `build_deferred_response`, `build_modal_response`).

- **Interaction response methods are ALSO available on `rest.*`** for those who prefer the explicit
  form — they already exist (`rest.create_interaction_response`, etc., dossier 10 §5), so this is free.

This means interactions do **not** go on the declarative msgspec-decode path; they stay a
hand-constructed model (entity factory injects `app`). That is a deliberate carve-out: interactions
are the one entity family where the "entity is also a client" design is load-bearing for DX and
latency, and where the constraint does not force otherwise.

| Pros | Cons |
|---|---|
| Preserves the primary documented DX (`interaction.create_initial_response(...)`, `event.message.respond`-style via `event.app.rest`). | Interactions remain a special case — not pure declarative-decoded data (they keep an app-injecting construction path). |
| No ergonomic/latency regression on interaction responses (§6). | Two mental models: wire entities are app-less; events/interactions carry `app`. |
| Keeps app-free builder factories that cost nothing to retain (dossier 08 §7.4). | Slightly more construction code in the factories (inject `app` — but that code already exists). |
| Events already needed their `app` field for the `rest` handle anyway (§3). | `InteractionMember`/`InteractionChannel` still subclass entity models and must satisfy frozen-Struct rules (dossier 08 §7.5). |

### 5.1 The action/builder split within interactions

Even under option 2, distinguish two helper categories (dossier 08 §7.3, §10.3):
- **Action helpers** (need a live client): `create_initial_response`, `edit/delete/fetch_initial_response`,
  `create_modal_response`, `create_response` (autocomplete), `fetch_command`, `fetch_guild`,
  `get_guild`, inherited `execute`/`*_message`. These keep working because interactions keep `app`.
- **Builder-factory helpers** (app-free): `build_response`, `build_deferred_response`,
  `build_modal_response`, autocomplete `build_response`. These construct an app-free builder
  (`rest.interaction_*_builder` captures no `app`; builders take `entity_factory` at `build()` time —
  dossier 08 §7.4). They can be retained even if a maintainer later wants interactions app-less,
  because they never needed `app`.

---

## 6. The interaction stakes: ergonomics and latency

Why interactions get a carve-out that wire entities do not:

1. **The primary documented pattern is the sugar.** `examples/slash.py:42,47,52` all use
   `await event.interaction.create_initial_response(...)` (dossier 10 §8.1). Removing it rewrites every
   slash-command example and most bot code to the verbose
   `rest.create_interaction_response(interaction.id, interaction.token, response_type, ...)`.

2. **Discord's 3-second initial-response deadline.** Interaction responses are latency-critical: an
   initial response must reach Discord within 3 seconds or the interaction token is invalidated. The
   ergonomic method (`interaction.create_initial_response(...)`) minimizes the code between receiving
   the event and responding. Forcing every handler to thread `interaction.id` + `interaction.token`
   through a `rest.*` call adds friction exactly on the hot path where friction causes missed
   deadlines. Keeping the sugar is a reliability argument, not only a taste one.

3. **The data the sugar needs is trivial to inject.** `id`, `token`, `application_id` are plain fields
   that survive on the model regardless (dossier 08 §10.3). The *only* thing removed by app-less
   interactions is the `app` handle that lets the method reach `rest` — and since interactions are
   hand-constructed, injecting that handle is free.

4. **Builders cost nothing to keep** (§5.1) — deleting them under option 1 discards ergonomics for no
   constraint benefit.

Net: the ergonomic and latency downside of app-less interactions is concentrated and severe; the cost
of keeping `app` on a hand-constructed model is negligible. Hence the option 2 carve-out.

---

## 7. Recommendation

**Adopt option 2.**
- Events keep `app` + helpers; fix the 31 delegating-`app` events to own-field + inject in
  `event_factory` (mandatory regardless — §3).
- Interactions keep `app` (hand-constructed, app-injecting path) and keep response sugar; the same
  actions remain available on `rest.*` for callers who prefer explicitness.
- Preserve builder factories app-free either way (§5.1).

This honours constraint (a) precisely where it applies (JSON-decoded wire entities) and preserves DX
and latency-critical ergonomics where the constraint does not force a change. It is a maintainer call;
option 1 is documented above so the trade-off is explicit.

Consistency note for the whole plan: constraint (a)'s "remove helpers" scope is **wire entities**.
Events/interactions are governed by D10, and under the recommended option they are *exempt* from the
blanket helper removal. Do not let a mechanical `grep self.app` pass delete event/interaction helpers.

---

## 8. Step-by-step migration (under option 2)

1. **Fix the 31 delegating-`app` events** (§3): add an `app: traits.RESTAware` field to each, and add
   `app=self._app` at the ~30 app-less construction sites in `event_factory`. Checklist keyed to
   dossier 08 §5.2 / §10.2. Detail in [`../07-events/00-events-migration.md`](../07-events/00-events-migration.md).
2. **Leave `ExceptionEvent.app` as a delegating property** (`base_events.py:207-211`) — it proxies an
   event, not an entity, and survives (§3).
3. **Keep interaction `app` + action helpers.** Ensure the factory continues to inject `app` into
   `PartialInteraction` and subclasses. Retain `ExecutableWebhook` subclassing (interactions keep
   `webhook_id → application_id`, `token` → interaction token). Detail in
   [`../06-model-modules/11-interactions.md`](../06-model-modules/11-interactions.md).
4. **Keep builder factories app-free** — no change needed; they already capture no `app` (dossier 08 §7.4).
5. **Apply constraint (b)** to the 5 loose `Enum | int` fields in this subtree (dossier 08 §8):
   `PartialInteractionMetadata.type`, `CommandInteractionOption.type`, `BaseCommandInteraction.command_type`,
   `ComponentInteraction.component_type`, `AutoModActionExecutionEvent.rule_trigger_type` — all become
   the strict enum (unknown-value strategy per [`../02-enums/00-strategy-and-forward-compat.md`](../02-enums/00-strategy-and-forward-compat.md)).
6. **Apply constraint (c)** — freeze events/interactions and drop `@attrs_extensions.with_copy` +
   `SKIP_DEEP_COPY`; nothing mutates a built event/interaction (dossier 08 §9, §10.5). See
   [`../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md`](../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md).

---

## 9. Affected files & symbols

| Path | Anchor | Change (option 2) |
|---|---|---|
| `hikari/events/base_events.py` | 83-86 (`Event.app` abstract), 207-211 (`ExceptionEvent.app`) | keep abstract `app`; leave `ExceptionEvent` proxy |
| `hikari/events/*_events.py` | 31 delegating `app` properties (dossier 08 §5.2) | replace each with an own `app` field |
| `hikari/impl/event_factory.py` | ~30 app-less construction sites (`:118/:709/:711/:1054/:547-552/…`) | add `app=self._app` |
| `hikari/interactions/base_interactions.py` | 272-343 (`PartialInteraction`), 421/755 mixins | keep `app` field + action/builder helpers |
| `hikari/interactions/command_interactions.py`, `component_interactions.py`, `modal_interactions.py` | build_*/create_*/fetch_* | keep (action helpers use `app`; builders app-free) |
| `hikari/interactions/base_interactions.py` | 406; `command_interactions.py:85,136`; `component_interactions.py:90`; `events/auto_mod_events.py:136` | strict-enum (constraint b) |
| `hikari/webhooks.py` | 73-81 (`ExecutableWebhook`) | interactions keep subclassing it (they keep `app`) |

---

## 10. Risks / gotchas

- **The 31-property fix is mandatory under BOTH options** (§3) — it is not optional to option 2. Skipping
  it leaves gateway handlers with no path to `rest`.
- **`auto_mod_events.py` uses the `attr` alias**, not `attrs` (dossier 08 §2) — a find/replace gotcha
  when adding `app` fields / freezing.
- **`ExceptionEvent` holds an `Exception` + coroutine callback** — keep it non-msgspec (attrs), frozen
  or not (dossier 08 §10.6).
- **`MemberChunkEvent` is a `Sequence`** (`shard_events.py:216`, `__getitem__/__iter__/__len__`) and
  `ShardPayloadEvent.payload` is raw `Mapping[str, Any]` — awkward for Structs; keep attrs (dossier 08 §10.6).
- **`InteractionMember`/`InteractionChannel` subclass entity models and add fields** — their frozen-
  Struct feasibility is governed by the entity dossiers, not this file (dossier 08 §7.5); cross-link
  [`../06-model-modules/11-interactions.md`](../06-model-modules/11-interactions.md).
- **Do not delete the app-free builder factories** under any option (§5.1) — pure ergonomic loss for
  no constraint benefit.

---

## 11. Verification

- After the event fix, every concrete event exposes a working `.app` (own field or the `ExceptionEvent`
  proxy); `grep` for `return self\.<x>\.app` on entity-wrapping events returns zero (only the
  `failed_event.app` proxy remains).
- `event.app.rest.fetch_channel(...)` and `event.app.cache.get_guild(...)` work on a constructed event
  whose wrapped entity is an app-less Struct.
- `interaction.create_initial_response(...)` works end-to-end (interaction retains `app`), and the
  equivalent `rest.create_interaction_response(interaction.id, interaction.token, ...)` produces an
  identical request.
- `interaction.build_response()` constructs the correct builder with no `app` present.
- Latency probe (optional): measure handler-receipt → initial-response wall time under both the sugar
  and the raw `rest.*` form to quantify the ergonomic argument (§6).

---

## 12. Open questions / decisions

- **D10 itself** — recommend option 2. Log the maintainer's final choice in
  [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md).
- **Should event `fetch_*`/`get_*` helpers ALSO move to `rest.*` for symmetry** even under option 2?
  They share the exact `self.app.*` shape but are not covered by constraint (a) (dossier 08 §6, §10.6).
  Recommend: keep them (they are the same low-risk category as the retained interaction sugar). This is
  a sub-decision of D10.
- **Do the `MessageResponseTypesT`/`DeferredResponseTypesT`/… `Literal` unions drop their bare-int
  alternatives** under strict enums (dossier 08 §8)? Cross-link
  [`../02-enums/03-strict-enum-field-inventory.md`](../02-enums/03-strict-enum-field-inventory.md).
