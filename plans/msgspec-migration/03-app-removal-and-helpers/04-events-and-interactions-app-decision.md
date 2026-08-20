# Events and Interactions — the App Decision (D10: events DECIDED, interactions FLAGGED)

The one maintainer-level policy call in the app-removal cluster — now half-resolved. Constraint (a)
forces `app` off JSON-decoded wire entities, but events and interactions are constructed with runtime
context in hand (dossier 08 §0, §10.1), so the "can't inject on decode" constraint did not technically
bite them and going app-less there was a genuine choice. The maintainer has made that choice **for
events**: **events lose `app`** — Option 1 (§4) applied to the events half (**D10-events: DECIDED**).
The **interactions half remains FLAGGED** (**D10-interactions**), with the unchanged recommendation
that interactions keep `app` + response sugar (§5–§7). This file records the decided events outcome
and lays out the still-open interactions choice in full.

Logged as **D10-events** (resolved) and **D10-interactions** (flagged) in
[`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md). Applies alongside
[`../07-events/00-events-migration.md`](../07-events/00-events-migration.md),
[`../06-model-modules/11-interactions.md`](../06-model-modules/11-interactions.md), and the event
pipeline appendix
[`../12-appendices/04-event-pipeline-feasibility.md`](../12-appendices/04-event-pipeline-feasibility.md)
(dossiers 17–19).

---

## 1. Objective

Record both halves of D10 explicitly:

- **Events — DECIDED (D10-events).** Events lose `app` entirely. Removed: the **44** own
  `app: traits.RESTAware` field declarations, the **31** entity-delegating `app` properties, the
  abstract `Event.app` (`base_events.py:83-86`), the `ExceptionEvent.app` proxy
  (`base_events.py:207-211`), all **42** event helper methods (24 `self.app.rest.*` + 18
  `self.app.cache.*`), and the **50** `app=self._app` injection sites in `impl/event_factory.py`.
  The lifetime events become field-less markers. Gateway handlers reach the client by closing over
  the bot object. Full surface in §3.
- **Interactions — FLAGGED (D10-interactions).** Whether interactions keep their response sugar
  (`create_initial_response`, `build_response`, …) via an app-injecting construction path, or become
  pure app-less data like wire entities. Recommendation unchanged: **keep `app`** (§5–§7); removing
  it would be the single largest ecosystem break in the migration (§6). Do not infer this half from
  the events answer (dossier 19 §3.4).

Together the halves fix the helper accounting: of the **173** app-delegating helpers, **~156 are now
removed** (~114 wire-entity + 42 event) and **~17 interaction helpers are retained** pending
D10-interactions ([`02-helper-method-inventory/00-README.md`](./02-helper-method-inventory/00-README.md) §2).

---

## 2. Why the constraint did not force this — and what decided the events half

Constraint (a) is about **decode-time injection**: `msgspec.json.decode(bytes, type=Struct)` has no
seam to attach `self._app`. Events and interactions were not fully on that path:

- **Events** are built by `EventFactoryImpl` (`impl/event_factory.py:85`) from already-deserialized
  entities plus runtime `shard` (dossier 08 §0, §4). Under the target event pipeline the 18 flat
  events *do* become direct decode targets — but even there, runtime injection stays
  msgspec-compatible (`force_setattr` post-decode, the exact mechanism that keeps `shard` on events
  under D13 — dossiers 18/20). So the constraint alone never forced app-less events. What decided it
  (maintainer call, on design grounds):
  1. **Events are data snapshots**; the client handle is redundant context — the bot is always in
     scope in a gateway handler.
  2. **Zero internal readers.** No hikari-internal code reads `event.app`; the grep matches only the
     delegating-property bodies themselves (dossier 19 §3.2). The field existed solely to power
     public helper sugar.
  3. **Pipeline simplification.** App-less events leave `shard` as the only runtime field to inject,
     delete all 50 factory injections, and help 45 of the 77 factory methods collapse to
     one-or-two-liners (dossier 17 §5).

- **Interactions** are built by the entity factory too, but they are unusual: `PartialInteraction`
  (`base_interactions.py:272`) is *both* an entity model *and* a client — it stores `app`, subclasses
  `webhooks.ExecutableWebhook`, and defines ~17 direct + 4 inherited `self.app.*` helpers
  (dossier 08 §7.3). Because they are hand-constructed by the factory, injecting `app` into them is
  trivial. The constraint only *technically* applies if interactions are put on the
  declarative-decode path — which the §5 recommendation deliberately avoids.

So the events half was settled by explicit maintainer decision; the interactions half remains a
**consistency vs. ergonomics** choice, not something msgspec dictates.

---

## 3. The events half — what is removed (DECIDED)

An earlier revision of this section framed the 31 entity-delegating `app` properties as a fix to
apply "regardless of D10": convert each to an own `app` field and add `app=self._app` at ~30 factory
construction sites. **That framing is superseded.** With D10-events decided as app-less, the
delegating properties are **deleted outright, not converted to fields**; nothing gains an `app`, and
the ~30 would-be injection sites are never written. The full removal surface (grep-verified counts):

| Removed surface | Count | Anchor |
|---|---:|---|
| Own `app: traits.RESTAware` field declarations | **44** | dossier 08 §5.1 — 13 files, incl. `AutoModActionExecutionEvent` via the `attr` alias |
| Entity-delegating `app` properties (`return self.<entity>.app`) | **31** | dossier 08 §5.2 (full list) |
| `ExceptionEvent.app` proxy (`return self.failed_event.app`) | 1 | `base_events.py:207-211` — its target vanishes with concrete-event `app` |
| Abstract `Event.app` property | 1 | `base_events.py:83-86` |
| Event helper methods (24 rest + 18 cache) | **42** | [`02-helper-method-inventory/07-events.md`](./02-helper-method-inventory/07-events.md) |
| `app=self._app` injections in `impl/event_factory.py` | **50** | dossier 17 §0 — all vanish |

Consequences:

- **Lifetime events become field-less marker classes.** `app` is the *only* field of
  `StartingEvent`/`StartedEvent`/`StoppingEvent`/`StoppedEvent` (`lifetime_events.py`, the one
  events module with no `shard`); their four factory methods (`event_factory.py:683-696`) collapse
  to `EventCls()` (dossier 19 §3.3).
- **The break is purely public API.** Zero hikari-internal readers of `event.app` (dossier 19 §3.2);
  externally, 1 example (`examples/voice_message/voice_message.py:90`) and ~120 test references.
- **The blessed handler path changes.** With no `event.app`, gateway handlers reach the client by
  **closing over the bot object** (`bot.rest` / `bot.cache`) — the pattern every example except
  `voice_message.py` already uses (dossier 19 §3.3). The pattern table in
  [`00-strategy.md`](./00-strategy.md) §5 is updated accordingly.
- **`shard` is unaffected.** Events keep `shard` (D13, dossier 20): it is irreplaceable provenance —
  *which connection received this* — whereas the client handle is always reachable another way.
- **Pure-data forwards keep working** (`.id`, `.channel_id`, `.guild_id`, `.author`, `.member`,
  `.webhook_id`, `.is_bot`) — they read real Struct fields, not `app` (dossier 08 §4, §10.2).

---

## 4. Option 1 — app-less + helper-less (APPLIED TO EVENTS)

**Maximally consistent, maximally breaking.** The maintainer has applied this option to the events
half only; the description below records what it means for each subtree.

Events lose `app`; the 24 event `self.app.rest.*` helpers (dossier 08 §6) and 18 event `cache`
getters are deleted. Applied to interactions, the option would also strip `app`, stop the
`ExecutableWebhook` subclassing, and delete all ~21 interaction `self.app.*` helpers — including
`create_initial_response`, `edit_initial_response`, `fetch_initial_response`,
`create_modal_response`, `create_autocomplete_response`, and the inherited
`execute`/`fetch_message`/`edit_message`/`delete_message` (dossier 08 §7.3, §10.3). **That
interactions half is NOT decided — see §5–§7.**

What callers write instead:
```python
# event helper → rest/cache via the closed-over bot
await event.fetch_channel()            → await bot.rest.fetch_channel(event.channel_id)
event.get_guild()                      → bot.cache.get_guild(event.guild_id)
# interaction sugar → rest (ONLY if D10-interactions ever chose removal — not recommended)
await interaction.create_initial_response(ResponseType.MESSAGE_CREATE, "hi")
    → await rest.create_interaction_response(interaction.id, interaction.token,
                                             ResponseType.MESSAGE_CREATE, "hi")
```

An earlier draft objected that option 1 was internally inconsistent for events — "events must still
store `app` or gateway handlers have no stable `rest` handle." **That tension is resolved by
maintainer fiat: the handle is the bot in scope, full stop** (dossier 19 §3.3 — every example except
one already closes over `bot`). Option 1 on events is therefore a clean removal, not the
field-keeping half-measure the earlier draft feared.

| Pros | Cons |
|---|---|
| One rule everywhere: "entities/events are data; use `rest.*`/`cache.*` via the client you hold." | Kills the documented event sugar (`event.fetch_channel()`, `event.get_guild()`); examples and user code migrate to the closed-over bot. |
| Deletes an event-side `app` surface with zero internal readers (44 fields + 33 properties + 42 helpers). | Applied to interactions it would kill `interaction.create_initial_response(...)` — the primary documented pattern — and regress the 3-second-deadline hot path (§6). Not decided; not recommended. |
| Events become pure frozen shard+data(+old_*) wrappers — the exact shape the typed-decode pipeline wants (dossiers 17–19). | `build_response`/`build_deferred_response`/`build_modal_response` are **app-free already** (dossier 08 §7.4) — deleting those would discard ergonomics for *zero* constraint benefit. |

---

## 5. Option 2 — keep app + helpers (SUPERSEDED for events; RECOMMENDED for interactions)

**Pragmatic; honours the constraint exactly where it bites and nowhere else.** This was the original
recommendation for both halves. The maintainer has **overridden it for events** (§3–§4); it remains
the live recommendation **for interactions**.

- **Events (superseded).** The original bullet — events keep their own `app` field and their
  `self.app.rest.*`/`self.app.cache.*` helpers, with the 31 delegating events upgraded to own
  fields — is void. D10-events resolved the other way: everything in §3 is removed.

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

| Pros (interactions) | Cons (interactions) |
|---|---|
| Preserves the primary documented DX (`interaction.create_initial_response(...)`). | Interactions remain a special case — not pure declarative-decoded data (they keep an app-injecting construction path). |
| No ergonomic/latency regression on interaction responses (§6). | Two mental models: wire entities **and events** are app-less; interactions carry `app`. |
| Keeps app-free builder factories that cost nothing to retain (dossier 08 §7.4). | Slightly more construction code in the factory (inject `app` — but that code already exists). |
| | `InteractionMember`/`InteractionChannel` still subclass entity models and must satisfy frozen-Struct rules (dossier 08 §7.5). |

### 5.1 The action/builder split within interactions

Even under the keep-`app` recommendation, distinguish two helper categories (dossier 08 §7.3, §10.3):
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

Why interactions get a carve-out that wire entities and events did not:

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

4. **Builders cost nothing to keep** (§5.1) — deleting them would discard ergonomics for no
   constraint benefit.

Net: the ergonomic and latency downside of app-less interactions is concentrated and severe; the cost
of keeping `app` on a hand-constructed model is negligible. Hence the recommended carve-out.

---

## 7. Decision and recommendation

- **Events: DECIDED — app-less.** Delete the 44 fields, 31 delegating properties, abstract
  `Event.app`, `ExceptionEvent.app` proxy, 42 helpers, and 50 factory injections (§3); lifetime
  events become field-less markers; handlers close over the bot. Removal recipes in
  [`02-helper-method-inventory/07-events.md`](./02-helper-method-inventory/07-events.md); sequencing
  with the event pipeline in [`../07-events/00-events-migration.md`](../07-events/00-events-migration.md).
- **Interactions: RECOMMEND keep `app`** (D10-interactions, still a maintainer call). Interactions
  keep `app` (hand-constructed, app-injecting path) and keep response sugar; the same actions remain
  available on `rest.*` for callers who prefer explicitness. Preserve builder factories app-free
  either way (§5.1). Removing interaction `app` would be the largest single ecosystem break in the
  migration (§6), and nothing in the events decision implies it (dossier 19 §3.4).

Consistency note for the whole plan: the "remove helpers" scope is now **wire entities + events**.
Interactions are governed by D10-interactions, and under the recommendation they are *exempt* from
the blanket helper removal. Do not let a mechanical `grep self.app` pass delete interaction helpers.

---

## 8. Step-by-step migration

**Events (decided path):**

1. **Delete the `app` surface across `hikari/events/*.py`**: the 31 delegating properties and the
   44 own `app` fields (with their `SKIP_DEEP_COPY` metadata). Mind the `attr` alias in
   `auto_mod_events.py` (dossier 08 §2).
2. **Delete the abstract `Event.app`** (`base_events.py:83-86`) and the **`ExceptionEvent.app`
   proxy** (`:207-211`). `ExceptionEvent.shard` (`:213-223`) stays — events keep `shard` (D13).
3. **Reduce the lifetime events to field-less markers**; their factory methods become `EventCls()`
   (`event_factory.py:683-696`).
4. **Delete the 42 event helpers** per the recipes in
   [`02-helper-method-inventory/07-events.md`](./02-helper-method-inventory/07-events.md) §5.
5. **Delete the 50 `app=self._app` injections** in `impl/event_factory.py`. The factory's `_app`
   slot survives only until entity deserialization moves to typed Decoders, after which it loses its
   `traits.RESTAware` dependency entirely (dossier 17 §5).
6. **Rewrite the one example** (`examples/voice_message/voice_message.py:90`) and the handler-pattern
   docs to close over `bot`; update the ~120 test references.

**Interactions (under the §7 recommendation, once D10-interactions is confirmed):**

7. **Keep interaction `app` + action helpers.** Ensure the factory continues to inject `app` into
   `PartialInteraction` and subclasses. Retain `ExecutableWebhook` subclassing (interactions keep
   `webhook_id → application_id`, `token` → interaction token). Detail in
   [`../06-model-modules/11-interactions.md`](../06-model-modules/11-interactions.md).
8. **Keep builder factories app-free** — no change needed; they already capture no `app` (dossier 08 §7.4).

**Both halves:**

9. **Apply constraint (b)** to the 5 loose `Enum | int` fields in this subtree (dossier 08 §8):
   `PartialInteractionMetadata.type`, `CommandInteractionOption.type`, `BaseCommandInteraction.command_type`,
   `ComponentInteraction.component_type`, `AutoModActionExecutionEvent.rule_trigger_type` — all become
   the strict enum (unknown-value strategy per [`../02-enums/00-strategy-and-forward-compat.md`](../02-enums/00-strategy-and-forward-compat.md)).
10. **Apply constraint (c)** — freeze events/interactions and drop `@attrs_extensions.with_copy` +
    `SKIP_DEEP_COPY`. One pre-condition: the `event.chunk_nonce` mutation (`event_manager.py:420`)
    must be restructured before events freeze (dossier 19 §1.3; gate item in the decisions log). See
    [`../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md`](../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md).

---

## 9. Affected files & symbols

| Path | Anchor | Change |
|---|---|---|
| `hikari/events/base_events.py` | 83-86 (`Event.app` abstract), 207-211 (`ExceptionEvent.app`) | DELETE both (`ExceptionEvent.shard` at 213-223 stays) |
| `hikari/events/*_events.py` | 31 delegating `app` properties + 44 own `app` fields (dossier 08 §5.1–§5.2) | DELETE all — no conversions to fields |
| `hikari/events/lifetime_events.py` | 44/67/84/109 | `app` was the only field — become field-less markers |
| `hikari/impl/event_factory.py` | 50 `app=self._app` sites | DELETE injections; lifetime methods → `EventCls()` |
| `hikari/interactions/base_interactions.py` | 272-343 (`PartialInteraction`), 421/755 mixins | keep `app` field + action/builder helpers (D10-interactions recommendation) |
| `hikari/interactions/command_interactions.py`, `component_interactions.py`, `modal_interactions.py` | build_*/create_*/fetch_* | keep (action helpers use `app`; builders app-free) |
| `hikari/interactions/base_interactions.py` | 406; `command_interactions.py:85,136`; `component_interactions.py:90`; `events/auto_mod_events.py:136` | strict-enum (constraint b) |
| `hikari/webhooks.py` | 73-81 (`ExecutableWebhook`) | interactions keep subclassing it (they keep `app`) |
| `examples/voice_message/voice_message.py` | 90 | rewrite `event.app.rest.*` → closed-over `bot.rest.*` |

---

## 10. Risks / gotchas

- **Delete the 31 delegating properties in the same change that strips entity `app`.** They break
  silently (AttributeError at access time, not import time) the moment any wrapped entity loses
  `.app`; a lagging property is a latent runtime failure, not a type error.
- **`InteractionCreateEvent.app` (`interaction_events.py:65`) is deleted with the other 31** — this
  does not depend on D10-interactions. Interaction *objects* keep their `app` under the
  recommendation, so `event.interaction.app` remains reachable if genuinely needed (dossier 19 §3.4).
- **`auto_mod_events.py` uses the `attr` alias**, not `attrs` (dossier 08 §2) — a find/replace gotcha
  during the field-deletion/freeze pass.
- **`ExceptionEvent` holds an `Exception` + coroutine callback** — keep it non-msgspec (attrs); its
  `app` proxy goes, its `shard` property stays (dossier 19 §3.1).
- **`MemberChunkEvent` is a `Sequence`** (`shard_events.py:216`) and `ShardPayloadEvent.payload` is
  raw `Mapping[str, Any]` — structural oddities for the event pipeline cluster
  ([`../12-appendices/04-event-pipeline-feasibility.md`](../12-appendices/04-event-pipeline-feasibility.md)),
  orthogonal to the app removal.
- **`InteractionMember`/`InteractionChannel` subclass entity models and add fields** — their frozen-
  Struct feasibility is governed by the entity dossiers, not this file (dossier 08 §7.5); cross-link
  [`../06-model-modules/11-interactions.md`](../06-model-modules/11-interactions.md).
- **Do not delete the app-free builder factories** under any outcome (§5.1) — pure ergonomic loss for
  no constraint benefit.

---

## 11. Verification

- `grep -rn "def app" hikari/events/` returns **0** — all 33 `app` members are gone (1 abstract +
  31 delegating + 1 `ExceptionEvent` proxy) — and no `app: traits.RESTAware` field declaration
  remains in `hikari/events/` (44 deleted).
- `grep -rnE "self\.app\.(rest|cache)" hikari/events/` returns **0** (42 helpers deleted).
- `grep -n "app=self\._app" hikari/impl/event_factory.py` returns **0** (50 injections deleted).
- No event constructor accepts an `app` kwarg; `StartingEvent()` constructs with zero arguments.
- `interaction.create_initial_response(...)` works end-to-end (interaction retains `app` under the
  recommendation), and the equivalent `rest.create_interaction_response(interaction.id,
  interaction.token, ...)` produces an identical request.
- `interaction.build_response()` constructs the correct builder with no `app` present.
- `examples/voice_message/voice_message.py` runs against the closed-over `bot.rest` form.

---

## 12. Open questions / decisions

- **D10-events — RESOLVED** (maintainer): events are app-less; recorded in
  [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md).
- **D10-interactions — FLAGGED**: recommend keep `app` + response sugar (§7). Log the maintainer's
  final choice in the decisions log.
- The former sub-decision "should event `fetch_*`/`get_*` helpers ALSO move to `rest.*` for symmetry
  even under option 2" is **moot** — the helpers are removed with D10-events.
- **Do the `MessageResponseTypesT`/`DeferredResponseTypesT`/… `Literal` unions drop their bare-int
  alternatives** under strict enums (dossier 08 §8)? Cross-link
  [`../02-enums/03-strict-enum-field-inventory.md`](../02-enums/03-strict-enum-field-inventory.md).
