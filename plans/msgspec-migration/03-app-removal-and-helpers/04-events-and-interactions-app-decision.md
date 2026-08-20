# Events and Interactions — the App Decision (D10: RESOLVED, both halves)

The one maintainer-level policy call in the app-removal cluster — now fully resolved. Constraint (a)
forces `app` off JSON-decoded wire entities, but events and interactions are constructed with runtime
context in hand (dossier 08 §0, §10.1), so the "can't inject on decode" constraint did not technically
bite them and going app-less there was a genuine choice. The maintainer has made that choice for
**both halves**: **events lose `app`** (**D10-events: RESOLVED**) and **interactions lose `app`**
(**D10-interactions: RESOLVED**) — Option 1 (§5) applied across the board. The interactions
resolution carries a verified split: the **9 action helpers** (real I/O) are deleted in favour of
`rest.*`, while the **8 builder factories** are kept and reimplemented app-free — so the REST-bot
return-a-builder flow survives **unchanged** (§4, §6). This file is the record of both decisions.

Logged as **D10-events** and **D10-interactions** (both RESOLVED) in
[`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md). Applies alongside
[`../07-events/00-events-migration.md`](../07-events/00-events-migration.md),
[`../06-model-modules/11-interactions.md`](../06-model-modules/11-interactions.md), and the event
pipeline appendix
[`../12-appendices/04-event-pipeline-feasibility.md`](../12-appendices/04-event-pipeline-feasibility.md)
(dossiers 17–19). The mechanical recipe for the interactions half is
[`02-helper-method-inventory/06-interactions.md`](./02-helper-method-inventory/06-interactions.md).

---

## 1. Objective

Record both halves of D10 explicitly:

- **Events — RESOLVED (D10-events).** Events lose `app` entirely. Removed: the **45** own
  `app: traits.RESTAware` field declarations, the **31** entity-delegating `app` properties, the
  abstract `Event.app` (`base_events.py:83-86`), the `ExceptionEvent.app` proxy
  (`base_events.py:207-211`), all **42** event helper methods (24 `self.app.rest.*` + 18
  `self.app.cache.*`), and the **50** `app=self._app` injection sites in `impl/event_factory.py`.
  The lifetime events become field-less markers. Gateway handlers reach the client by closing over
  the bot object. Full surface in §3.
- **Interactions — RESOLVED (D10-interactions).** Interactions become app-less data like everything
  else. Deleted: the `PartialInteraction.app` field (`base_interactions.py:275`), the
  `webhooks.ExecutableWebhook` subclassing (with the 4 inherited followup helpers moving to
  `rest.*`), and the **9 action helpers** — every one a pure delegation to an *existing*
  `rest.*`/`cache.*` method, so no new endpoint is needed (§4.1). Kept: the **8 builder factories**
  (`build_response`/`build_deferred_response` in their command/component/modal variants,
  autocomplete `build_response`, `build_modal_response`), reimplemented as app-free sync
  constructors over `special_endpoints` (§4.2). A construction step survives in the response flow
  regardless, so app-lessness costs only ergonomics on the action path — rationale in §6.

Together the halves finish the helper accounting: **all ~173 app-delegating helper sites are
removed** — ~114 wire-entity + 42 event + the 9 interaction action helpers (with the 4
`ExecutableWebhook` followups counted under webhooks) — while the 8 interaction builder factories
are not removed but lose their `self.app` usage entirely, so
`grep -rnE "self\.(user\.)?app\." hikari/` goes to zero outside tests. There is **no retained set
and no pending app decision**
([`02-helper-method-inventory/00-README.md`](./02-helper-method-inventory/00-README.md) §2).

---

## 2. Why the constraint did not force this — and what decided both halves

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

- **Interactions** are built by the entity factory too, but they were unusual: `PartialInteraction`
  (`base_interactions.py:272`) was *both* an entity model *and* a client — it stored `app`,
  subclassed `webhooks.ExecutableWebhook`, and defined ~17 direct + 4 inherited `self.app.*`
  helpers (dossier 08 §7.3). Because they are hand-constructed by the factory, injecting `app` into
  them was trivial, and the earlier draft of this file recommended exactly that. The maintainer
  resolved the other way (design grounds, not msgspec):
  1. **A construction step survives regardless.** The response flow always contains a
     build-the-response step, and the 8 builder factories that embody it never needed `app` —
     `rest.interaction_message_builder` is a pure sync constructor (`impl/rest.py:4676-4679`).
     Keeping them app-free means app-lessness costs **only ergonomics** on the 9 action helpers,
     not capability, and not the REST-bot flow (§4.2).
  2. **Every action helper is a pure delegation** to an *existing* `rest.*`/`cache.*` method, and
     all the ids/tokens it injected (`id`, `token`, `application_id`, `guild_id`) are public struct
     fields — callers can reproduce every call exactly (§4.1).
  3. **One rule everywhere.** With wire entities and events already app-less, retaining an
     app-injecting construction path for one entity family would preserve the dual mental model the
     migration is eliminating.

So both halves were settled by explicit maintainer decision; msgspec dictated neither. Consistency
won over ergonomics — with the builder-factory carve-out ensuring the loss stays ergonomic-only.

---

## 3. The events half — what is removed (RESOLVED)

An earlier revision of this section framed the 31 entity-delegating `app` properties as a fix to
apply "regardless of D10": convert each to an own `app` field and add `app=self._app` at ~30 factory
construction sites. **That framing is superseded.** With D10-events resolved as app-less, the
delegating properties are **deleted outright, not converted to fields**; nothing gains an `app`, and
the ~30 would-be injection sites are never written. The full removal surface (grep-verified counts):

| Removed surface | Count | Anchor |
|---|---:|---|
| Own `app: traits.RESTAware` field declarations | **45** | dossier 08 §5.1 — 14 files; the dossier's 44 was the `attrs.field`-only count, and the `attr`-alias site in `auto_mod_events.py` (`AutoModActionExecutionEvent`) is the +1 — greps must match both spellings |
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

## 4. The interactions half — the action/builder split (RESOLVED)

The 17 direct interaction `self.app.*` helpers split into two categories with opposite fates
(dossier 08 §7.3–§7.4; full source-anchored tables in
[`02-helper-method-inventory/06-interactions.md`](./02-helper-method-inventory/06-interactions.md)):

### 4.1 The 9 action helpers — DELETED; callers use `rest.*` directly

Every one is a pure delegation to an **existing** rest/cache method — no new endpoint is needed —
and all ids/tokens the helpers injected are public struct data, so callers can reproduce every call:

| Deleted helper | Replacement |
|---|---|
| `PartialInteraction.fetch_guild` | `rest.fetch_guild(interaction.guild_id)` |
| `PartialInteraction.get_guild` (cache) | `cache.get_guild(interaction.guild_id)` |
| `MessageResponseMixin.fetch_initial_response` | `rest.fetch_interaction_response(interaction.application_id, interaction.token)` |
| `MessageResponseMixin.create_initial_response` | `rest.create_interaction_response(interaction.id, interaction.token, ...)` |
| `MessageResponseMixin.edit_initial_response` | `rest.edit_interaction_response(interaction.application_id, interaction.token, ...)` |
| `MessageResponseMixin.delete_initial_response` | `rest.delete_interaction_response(interaction.application_id, interaction.token)` |
| `ModalResponseMixin.create_modal_response` | `rest.create_modal_response(interaction.id, interaction.token, ...)` |
| `BaseCommandInteraction.fetch_command` | `rest.fetch_application_command(interaction.application_id, interaction.id, guild)` |
| `AutocompleteInteraction.create_response` | `rest.create_autocomplete_response(interaction.id, interaction.token, choices)` |

One caveat on the `fetch_command` row: the replacement reproduces the current helper's argument
verbatim — `command_interactions.py:164-166` passes `command=self.id`, the *interaction's own*
snowflake — even though `BaseCommandInteraction.command_id` (`command_interactions.py:130`) exists
and is the semantically intended command id. The migration must not silently change the argument;
resolving (or confirming) that discrepancy is an upstream change of its own.

The 4 followup helpers interactions inherited from `ExecutableWebhook`
(`execute`/`fetch_message`/`edit_message`/`delete_message`) go with the subclassing — also to
`rest.*` (counted under webhooks;
[`02-helper-method-inventory/04-users-webhooks-audit.md`](./02-helper-method-inventory/04-users-webhooks-audit.md)
§3.4). `ExecutableWebhook` itself reduces to a data protocol, unconditionally.

### 4.2 The 8 builder factories — KEPT, reimplemented app-free

They currently call `self.app.rest.interaction_*_builder(...)`, but those rest methods are **pure
sync constructors** (verified: `rest.interaction_message_builder` is literally
`return special_endpoints_impl.InteractionMessageBuilder(type=type_)`, `impl/rest.py:4676-4679`;
same for deferred/autocomplete/modal at `:4664/:4670/:4682`). The struct methods are reimplemented
to construct the builder directly from `special_endpoints` with **no client**: `build_response` and
`build_deferred_response` (command/component/modal variants, keeping the `ComponentInteraction`
component-type validation logic), `AutocompleteInteraction.build_response`, and
`ModalResponseMixin.build_modal_response`.

**Consequence: the REST-bot flow (listener RETURNS a builder) survives UNCHANGED** — the
load-bearing fact that makes app-less interactions safe for `RESTBot`/`interaction_server`. A
listener still ends with `return interaction.build_response(...)`; nothing in that path ever needed
`app`. See [`../09-rest-and-gateway/01-gateway-shard-and-interaction-server.md`](../09-rest-and-gateway/01-gateway-shard-and-interaction-server.md).

---

## 5. Option history — Option 1 applied to both halves; Option 2 superseded

**Option 1 — app-less + helper-less** (maximally consistent, maximally breaking) is the applied
outcome for both halves, with one refinement for interactions: the 8 builder factories are not
"helpers over `app`" at all (dossier 08 §7.4), so they are kept app-free rather than deleted —
deleting them would discard ergonomics for zero constraint benefit.

What callers write instead:
```python
# event helper → rest/cache via the closed-over bot
await event.fetch_channel()            → await bot.rest.fetch_channel(event.channel_id)
event.get_guild()                      → bot.cache.get_guild(event.guild_id)
# interaction action sugar → rest (D10-interactions RESOLVED)
await interaction.create_initial_response(ResponseType.MESSAGE_CREATE, "hi")
    → await rest.create_interaction_response(interaction.id, interaction.token,
                                             ResponseType.MESSAGE_CREATE, "hi")
# builder factories — unchanged for callers
return interaction.build_response(...)  # still valid; now constructs app-free
```

An earlier draft objected that option 1 was internally inconsistent for events — "events must still
store `app` or gateway handlers have no stable `rest` handle." **That tension is resolved by
maintainer fiat: the handle is the bot in scope, full stop** (dossier 19 §3.3 — every example except
one already closes over `bot`). The parallel objection for interactions — that deleting the sugar
regresses the 3-second-deadline hot path — is answered in §6: the replacement issues the same wire
call with the same latency; the loss is ergonomic only.

| Gains (applied) | Accepted costs |
|---|---|
| One rule everywhere: "entities/events/interactions are data; use `rest.*`/`cache.*` via the client you hold." | Kills the documented event sugar and `interaction.create_initial_response(...)` — the largest single ecosystem break in the migration; every command framework's `ctx.respond` wraps it (§6). |
| Deletes the event `app` surface (45 fields + 33 properties + 42 helpers, zero internal readers) and the interaction `app` surface (field + mixin + 9 action helpers). | Examples, docs, and downstream frameworks (tanjun/lightbulb/arc/miru) migrate to `rest.*`; pre-announced coordination required ([`../11-rollout/03-breaking-changes-and-changelog.md`](../11-rollout/03-breaking-changes-and-changelog.md)). |
| Events and interactions become pure frozen data — the exact shape the typed-decode pipeline wants (dossiers 17–19). | None on the builder path: the 8 factories are kept app-free, so the REST-bot flow is unchanged (§4.2). |

**Option 2 — keep `app` + helpers** was the original recommendation for both halves (events keep
their helpers; interactions keep an app-injecting construction path with response sugar, mirrored on
`rest.*`). It is **superseded in full**: the maintainer overrode it for events first, and has now
overridden it for interactions as well. Its one durable insight is preserved as the §4 split — the
builder factories it wanted to protect are kept, precisely because they never needed `app` in the
first place.

---

## 6. The interaction stakes: what the break costs — and why it is acceptable

The interactions half was the last FLAGGED item in the plan because its stakes are the highest.
Recording the cost analysis the maintainer accepted:

1. **The primary documented pattern is the sugar.** `examples/slash.py:42,47,52` all use
   `await event.interaction.create_initial_response(...)` (dossier 10 §8.1), and every command
   framework's `ctx.respond` wraps `create_initial_response`. Removing it rewrites every
   slash-command example and most bot code to
   `rest.create_interaction_response(interaction.id, interaction.token, response_type, ...)`. This
   is **the largest single ecosystem break in the migration** — the rollout treats it as the
   headline item, with the §4.1 replacement table and downstream pre-announcement
   (tanjun/lightbulb/arc/miru) in
   [`../11-rollout/03-breaking-changes-and-changelog.md`](../11-rollout/03-breaking-changes-and-changelog.md).

2. **There is NO wire-latency change.** Discord's 3-second initial-response deadline is unaffected:
   the replacement issues the *same REST call* the helper made — same endpoint, same request, same
   latency. What is lost is keystrokes (threading `interaction.id` + `interaction.token`
   explicitly), not time on the wire. The earlier draft's reliability worry — friction on the hot
   path causing missed deadlines — is mitigated by documentation: the replacement table makes the
   substitution one mechanical line.

3. **The data the sugar needs is public struct data.** `id`, `token`, `application_id` survive as
   plain fields (dossier 08 §10.3), so every deleted action helper is exactly reproducible by its
   caller — no capability is lost.

4. **The construction step survives.** The builder factories cost nothing to keep app-free (§4.2)
   and they carry the REST-bot return-a-builder flow unchanged — the one flow where the sugar is
   structural rather than convenience.

Net: the downside is concentrated, ergonomic-only, and mitigable with docs plus ecosystem
coordination; the upside is one model everywhere and zero app seams. That is the trade the
maintainer accepted in resolving D10-interactions.

---

## 7. Decision record

- **Events: RESOLVED — app-less.** Delete the 45 fields, 31 delegating properties, abstract
  `Event.app`, `ExceptionEvent.app` proxy, 42 helpers, and 50 factory injections (§3); lifetime
  events become field-less markers; handlers close over the bot. Removal recipes in
  [`02-helper-method-inventory/07-events.md`](./02-helper-method-inventory/07-events.md); sequencing
  with the event pipeline in [`../07-events/00-events-migration.md`](../07-events/00-events-migration.md).
- **Interactions: RESOLVED — app-less** (D10-interactions, maintainer). Delete the `app` field, the
  `ExecutableWebhook` subclassing, and the 9 action helpers; callers use the existing `rest.*`
  methods per the §4.1 table. The 8 builder factories are kept and reimplemented app-free (§4.2);
  the REST-bot return-a-builder flow is unchanged. Removal recipes in
  [`02-helper-method-inventory/06-interactions.md`](./02-helper-method-inventory/06-interactions.md);
  model detail in [`../06-model-modules/11-interactions.md`](../06-model-modules/11-interactions.md).

Consistency note for the whole plan: the "remove helpers" scope is now **wire entities + events +
interactions** — there is no exempt subtree and no pending app decision anywhere. The one nuance a
mechanical `grep self.app` pass must respect: the 8 interaction builder factories are
*reimplemented*, not deleted (§4.2).

---

## 8. Step-by-step migration

**Events (resolved path):**

1. **Delete the `app` surface across `hikari/events/*.py`**: the 31 delegating properties and the
   45 own `app` fields (with their `SKIP_DEEP_COPY` metadata). Mind the `attr` alias in
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

**Interactions (resolved path):**

7. **Delete the interaction `app` surface**: the `app` field (`base_interactions.py:275`), the
   `ExecutableWebhook` subclassing (`base_interactions.py:272` — the mixin reduces to a data
   protocol per
   [`02-helper-method-inventory/04-users-webhooks-audit.md`](./02-helper-method-inventory/04-users-webhooks-audit.md)
   §3.4), the 9 action helpers (§4.1), and the interaction share of the `app=self._app` injections
   in `impl/entity_factory.py`. Detail in
   [`../06-model-modules/11-interactions.md`](../06-model-modules/11-interactions.md).
8. **Reimplement the 8 builder factories app-free** (§4.2): direct `special_endpoints`
   constructions on the app-less structs, preserving the `ComponentInteraction` type validators;
   verify the REST-bot listener flow end-to-end.

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
| `hikari/events/*_events.py` | 31 delegating `app` properties + 45 own `app` fields (dossier 08 §5.1–§5.2) | DELETE all — no conversions to fields |
| `hikari/events/lifetime_events.py` | 44/67/84/109 | `app` was the only field — become field-less markers |
| `hikari/impl/event_factory.py` | 50 `app=self._app` sites | DELETE injections; lifetime methods → `EventCls()` |
| `hikari/interactions/base_interactions.py` | 272 (mixin), 275 (`app` field), 356-789 helpers | DELETE `app` field + `ExecutableWebhook` subclassing + 7 action helpers; `build_modal_response` reimplemented app-free |
| `hikari/interactions/command_interactions.py`, `component_interactions.py`, `modal_interactions.py` | build_*/create_*/fetch_* | action helpers (`fetch_command`, autocomplete `create_response`) DELETED → `rest.*`; builder factories reimplemented app-free (validators preserved) |
| `hikari/impl/entity_factory.py` | interaction `deserialize_*` | DELETE the interaction `app=self._app` injections |
| `hikari/interactions/base_interactions.py` | 406; `command_interactions.py:85,136`; `component_interactions.py:90`; `events/auto_mod_events.py:136` | strict-enum (constraint b) |
| `hikari/webhooks.py` | 73-81 (`ExecutableWebhook`) | interactions stop subclassing it; the mixin reduces to a data protocol — unconditional |
| `examples/voice_message/voice_message.py` | 90 | rewrite `event.app.rest.*` → closed-over `bot.rest.*` |
| `examples/slash.py` | 42/47/52 | rewrite `interaction.create_initial_response(...)` → `rest.create_interaction_response(...)` |

---

## 10. Risks / gotchas

- **Delete the 31 delegating properties in the same change that strips entity `app`.** They break
  silently (AttributeError at access time, not import time) the moment any wrapped entity loses
  `.app`; a lagging property is a latent runtime failure, not a type error.
- **`InteractionCreateEvent.app` (`interaction_events.py:65`) is deleted with the other 31** — and
  with D10-interactions resolved, the old fallback (`event.interaction.app`) is gone too: there is
  no `app` anywhere on the interaction path. Handlers use the closed-over bot (gateway) or the
  server's `rest` client (REST bot).
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
- **Do not delete the app-free builder factories** (§4.2) — they are kept and *reimplemented*, not
  removed. An over-broad "remove all app helpers" pass is the main execution risk on the
  interactions half.
- **The interactions break is the headline ecosystem item** — sequence the changelog entry and the
  downstream pre-announcement (tanjun/lightbulb/arc/miru) before the release
  ([`../11-rollout/03-breaking-changes-and-changelog.md`](../11-rollout/03-breaking-changes-and-changelog.md)).

---

## 11. Verification

- `grep -rn "def app" hikari/events/` returns **0** — all 33 `app` members are gone (1 abstract +
  31 delegating + 1 `ExceptionEvent` proxy) — and no `app: traits.RESTAware` field declaration
  remains in `hikari/events/` (45 deleted).
- `grep -rnE "self\.app\.(rest|cache)" hikari/events/` returns **0** (42 helpers deleted).
- `grep -n "app=self\._app" hikari/impl/event_factory.py` returns **0** (50 injections deleted).
- No event constructor accepts an `app` kwarg; `StartingEvent()` constructs with zero arguments.
- `grep -rn "self\.app" hikari/interactions/` returns **0** — the field, the 9 action helpers, and
  the factories' old `rest.interaction_*_builder` delegations are all gone.
- `rest.create_interaction_response(interaction.id, interaction.token, ...)` produces a request
  identical to the one the removed `create_initial_response` helper made.
- `interaction.build_response()` constructs the correct builder with no `app` present;
  `ComponentInteraction` validators still raise `ValueError` on out-of-set response types.
- A `RESTBot` listener returning `interaction.build_response(...)` works end-to-end against
  `interaction_server` — the return-a-builder flow is unchanged.
- `examples/voice_message/voice_message.py` runs against the closed-over `bot.rest` form;
  `examples/slash.py` runs against the `rest.create_interaction_response(...)` form.

---

## 12. Open questions / decisions

- **D10-events — RESOLVED** (maintainer): events are app-less; recorded in
  [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md).
- **D10-interactions — RESOLVED** (maintainer): interactions are app-less; the 9 action helpers are
  deleted (callers → `rest.*`), the 8 builder factories are kept and reimplemented app-free, and
  the `ExecutableWebhook` departure is unconditional. Recorded in the decisions log. No FLAGGED
  items remain in the plan.
- The former sub-decision "should event `fetch_*`/`get_*` helpers ALSO move to `rest.*` for symmetry
  even under option 2" is **moot** — the helpers are removed with D10-events.
- **Do the `MessageResponseTypesT`/`DeferredResponseTypesT`/… `Literal` unions drop their bare-int
  alternatives** under strict enums (dossier 08 §8)? Cross-link
  [`../02-enums/03-strict-enum-field-inventory.md`](../02-enums/03-strict-enum-field-inventory.md).
