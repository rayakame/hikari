# App Field Removal — Mechanics

The mechanical removal of the `app` reference from wire entities: the attrs field declarations, the
abstract `app` properties, the factory injection sites, the 10 "dead" fields that drop for free, the
`SKIP_DEEP_COPY` metadata that vanishes with them, and the traps (two `shard_id` styles,
`FailedEvent.app` proxy, `webhook_id` false-friend). This is the enabling step for constraint (a):
until `app` is off the Structs, `msgspec.json.decode` cannot construct them and no helper removal can
proceed.

Prerequisite reading: [`00-strategy.md`](./00-strategy.md) (philosophy + taxonomy). The helper
methods this field removal orphans are catalogued in
[`02-helper-method-inventory/`](./02-helper-method-inventory/00-README.md); the ones that need a
new home are in [`03-new-rest-methods-and-free-functions.md`](./03-new-rest-methods-and-free-functions.md).

---

## 1. Objective

Serve **constraint (a)**. Delete every runtime `app` handle from JSON-decoded wire entities so the
entity is pure data. This means removing, in lockstep:

1. The `app` **attrs field** declarations on model classes (25 fields / 22 model modules, dossier 04 §0).
2. The 40 abstract `def app` **property** declarations on mixins/ABCs (dossier 04 §0/§1).
3. The **factory injection sites** — 63 `app=self._app` in `impl/entity_factory.py`
   (dossier 04 §0, dossier 10 §3) and the `self._app` storage that feeds them.
4. The `SKIP_DEEP_COPY` metadata that only ever guarded `app`/`shard` (151 sites, dossier 04 §1).

Events (45 `app` fields, dossier 04 §0 / dossier 08 §5.1) are governed by **D10-events, RESOLVED** —
they are app-less: the 45 fields, 31 delegating properties, the abstract `Event.app`, and the
`ExceptionEvent` proxy are deleted, and all 50 `event_factory` `app=self._app` injection sites vanish
(owned by [`../07-events/00-events-migration.md`](../07-events/00-events-migration.md) and
[`04-events-and-interactions-app-decision.md`](./04-events-and-interactions-app-decision.md)).
Interactions are governed by **D10-interactions, also RESOLVED** — app-less: the
`PartialInteraction.app` field (`base_interactions.py:275`) is REMOVED and the interaction share of
the entity-factory injections goes with it (executed in the interactions pass,
[`02-helper-method-inventory/06-interactions.md`](./02-helper-method-inventory/06-interactions.md)).
This file's field-deletion scope is the wire entities only; the event and interaction surfaces are
executed in their own passes.

---

## 2. Current state — how `app` gets onto entities

The canonical model field declaration (`templates.py:151-153`):

```python
app: traits.RESTAware = attrs.field(
    repr=False, eq=False, hash=False, metadata={attrs_extensions.SKIP_DEEP_COPY: True}
)
"""Client application that models may use for procedures."""
```

Field characteristics, all migration-relevant (dossier 04 §1):
- typed `traits.RESTAware` — the **client**, never JSON data, so it can never come from a msgspec decode.
- `eq=False, hash=False` — already excluded from identity; removing it does not change equality.
- `metadata={SKIP_DEEP_COPY: True}` — tells the cache's deep-copier not to clone the live client.

Injection is factory-wide and implicit. `EntityFactoryImpl.__init__(self, app)` stores
`self._app = app` (`impl/entity_factory.py:485-486`), then every `deserialize_*` constructs its entity
with `app=self._app` — **63 sites** (dossier 04 §0, dossier 10 §3; e.g. `:681, :717, :751, :908, :926,
:936`). For REST-only clients the injected object is a `_RESTProvider` (`impl/rest.py:222`); for gateway
bots it is the `GatewayBot` itself (dossier 10 §6). Either way it is a non-serializable runtime handle
— precisely what a typed decode cannot thread in.

### 2.1 Model classes declaring the `app` field

From dossier 04 §2 (classes with the attrs field, not the abstract property):

| Module | Line | Class | Has `self.app` helpers? |
|---|---:|---|---|
| `hikari/guilds.py` | 321 | `PartialGuild` | Yes (22) |
| `hikari/guilds.py` | 1150 | `Member` | Yes (`fetch_roles`) |
| `hikari/guilds.py` | 1664 | `Guild` | Yes (21, mostly cache getters) |
| `hikari/channels.py` | 203 | `ChannelFollow` | Yes (3) |
| `hikari/channels.py` | 361 | `PartialChannel` | Yes (via subclasses, 15) |
| `hikari/messages.py` | 408 | `PartialMessage` | Yes (9) |
| `hikari/messages.py` | 599 | `Message` | inherits `PartialMessage` |
| `hikari/webhooks.py` | 475 | `PartialWebhook` | Yes (subclasses, 12) |
| `hikari/users.py` | 876 | `User`/`OwnUser` | Yes (4) |
| `hikari/commands.py` | 220 | `PartialCommand` | Yes (5) |
| `hikari/audit_logs.py` | 506 | `AuditLog` | Yes (entry-info classes, 5) |
| `hikari/audit_logs.py` | 700 | `AuditLogEntry` | Yes (`fetch_user`) |
| `hikari/presences.py` | 423 | `MemberPresence` | Yes (2) |
| `hikari/templates.py` | 151 | `Template` | Yes (4) |
| `hikari/interactions/base_interactions.py` | 275 | `PartialInteraction` | Yes (all interactions inherit) — field REMOVED (D10-interactions RESOLVED); 9 action helpers deleted, 8 builder factories reimplemented app-free ([`02-helper-method-inventory/06-interactions.md`](./02-helper-method-inventory/06-interactions.md)) |
| `hikari/applications.py` | 556 / 638 / 767 | `Application` / partial / team | **No** (dead field) |
| `hikari/invites.py` | 121 / 356 | `InviteCode`/`Invite`/`InviteWithMetadata` | **No** (dead field) |
| `hikari/emojis.py` | 343 | `KnownCustomEmoji` | **No** (dead field) |
| `hikari/stickers.py` | (via base) | `GuildSticker`/`PartialSticker` | **No** (dead field) |
| `hikari/scheduled_events.py` | 102 | `ScheduledEvent` | **No** (dead field) |
| `hikari/auto_mod.py` | 231 | `AutoModRule` | **No** (dead field) |
| `hikari/voices.py` | 47 | `VoiceState` | **No** (dead field) |
| `hikari/stage_instances.py` | 56 | `StageInstance` | **No** (dead field) |

### 2.2 `app` as an abstract property (40 sites, easy to miss)

Some ABCs/mixins expose `app` as an abstract `@property`, not a field (dossier 04 §1, §8.2). A
`grep attrs.field` misses these entirely. Known anchors:
- `webhooks.ExecutableWebhook.app` (`webhooks.py:81`)
- `events.base_events.Event.app` (`base_events.py:83-86`)
- `users.py:294`, `applications.py:440`, `guilds.py:516`
- interaction mixins satisfy `ExecutableWebhook.app` via the `PartialInteraction` field.

These abstract declarations are the contract the helper mixins call `self.app` against; concrete
subclasses satisfy them with the field. Removing `app` means removing both the field **and** the
abstract property from wire-entity ABCs.

---

## 3. The 10 "dead" `app` fields — drop free of helper fallout

Ten model modules carry an `app` field (or inherit one) but define **zero** methods that call
`self.app.*` (dossier 04 §2, verified: their only methods are properties and `make_*_url()` builders
that use `self.<hash>` + `urls`/`routes`, never the client):

| Module | Class(es) |
|---|---|
| `applications.py` | `Application` and partial/team variants |
| `invites.py` | `InviteCode` / `Invite` / `InviteWithMetadata` |
| `emojis.py` | `KnownCustomEmoji` |
| `stickers.py` | `GuildSticker` / `PartialSticker` |
| `scheduled_events.py` | `ScheduledEvent` |
| `auto_mod.py` | `AutoModRule` |
| `voices.py` | `VoiceState` |
| `stage_instances.py` | `StageInstance` |
| `monetization.py` | `Entitlement` / SKU |
| `polls.py` | poll models |

For these, deleting the `app` field is **free** — there is no helper method to re-home. The only
pre-condition is confirming nothing external reads `entity.app` on them (dossier 04 §8.4); grep the
codebase and examples for `.app` reads on these types before deletion.

---

## 4. `SKIP_DEEP_COPY` removal (151 sites)

`attrs_extensions.SKIP_DEEP_COPY` is a metadata key the cache's custom deep-copier honours to skip a
field (`internal/attrs_extensions.py`; the deep copier skips any field whose metadata carries it,
`:186`). It appears **151 times** across the codebase (dossier 04 §1), almost entirely on `app` fields
(models + events) and `shard` fields (events).

Under constraints (a) + (c) the entire construct disappears:
- `app` (the only pointer the cache refused to deep-copy) is removed from entities → its `SKIP_DEEP_COPY`
  marker goes with it.
- Structs become **frozen**, so the cache drops its copy/deepcopy machinery altogether
  (see [`../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md`](../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md)).
  `attrs_extensions.py` is slimmed in the first pass and deleted wholesale once all consumers are off
  attrs; after this pass there is nothing left for the markers to mark.

On events the `app` fields are removed outright (D10-events, RESOLVED) and events become frozen structs,
so their `SKIP_DEEP_COPY` markers go with the fields; the `shard` field stays (D13) and needs no marker
under frozen structs. Detail in [`../07-events/00-events-migration.md`](../07-events/00-events-migration.md).

---

## 5. Traps

### 5.1 Two `shard_id` styles

`shard_id` is computed two different ways, and a mechanical "remove `self.app`" pass must handle both
(dossier 04 §6, §8.1):

| Site | Expression | Passes |
|---|---|---|
| `channels.py:995` (`GuildChannel.shard_id`) | `snowflakes.calculate_shard_id(self.app, self.guild_id)` | the **whole app** object |
| `guilds.py:1692` (`PartialGuild.shard_id`) | `shard_count = self.app.shard_count; snowflakes.calculate_shard_id(shard_count, self.id)` | an **int** |

`calculate_shard_id(app_or_count: traits.ShardAware | int, guild)` (`snowflakes.py:135`) accepts both,
branching on `isinstance(app_or_count, int)` (`snowflakes.py:151`). Both call sites read the app's
`shard_count`, which is not `rest`/`cache` and has no wire equivalent (dossier 04 §6). Because
`shard_id` is inherently client-level state, it **cannot survive as a pure struct property**:
- Remove the `shard_id` property from the frozen entities.
- Re-express as a free function the caller invokes with an explicit shard count / shard-aware app:
  `snowflakes.calculate_shard_id(shard_count, entity.id)` — the function already exists and needs no
  change. Callers who have a `ShardAware` bot pass `bot`; callers who have only a count pass the int.
- Normalize the two styles while doing so (an inconsistency worth removing, dossier 04 §6).

### 5.2 `FailedEvent.app` proxies another **event**, not an entity

`ExceptionEvent.app` (`base_events.py:207-211`) returns `self.failed_event.app` — it delegates to the
inner **event**, not to a wrapped entity (dossier 04 §8.3, dossier 08 §1.3). Under the resolved
D10-events decision events are app-less, so its `failed_event.app` target vanishes and the proxy is
**removed together with the abstract `Event.app`** (see
[`../07-events/00-events-migration.md`](../07-events/00-events-migration.md) §3.1). It is called out
here so the mechanical pass treats it as part of the event surface, not as an entity-`app` proxy.

### 5.3 `webhook_id` false-friend

`PartialInteraction.webhook_id` (`base_interactions.py:352`) returns `self.application_id` — it exists
only so interactions satisfy the `ExecutableWebhook` mixin contract; it is **not** an `app` reference
(dossier 04 §8.7). It is matched by a `self.app`-adjacent grep only incidentally. Do not remove or
rewrite it as part of the `app` field pass. (Its fate is settled by the resolved D10-interactions:
`PartialInteraction` stops subclassing `ExecutableWebhook` unconditionally, so the property is
removed in the interactions pass alongside the mixin departure — still not in this file's sweep. See
[`04-events-and-interactions-app-decision.md`](./04-events-and-interactions-app-decision.md) §4.)

### 5.4 `_map_cache_maybe_discover` closes over `app`

`PartialMessage.get_member_mentions` (`messages.py:816-848`) builds a lambda closing over `app` and
`guild_id` (`messages.py:842-846`); `get_role_mentions` (`messages.py:850`) is the same shape. A
free-function rewrite must thread `cache` through, not `app` (dossier 04 §8.8). Detailed in
[`03-new-rest-methods-and-free-functions.md`](./03-new-rest-methods-and-free-functions.md).

---

## 6. Step-by-step migration

1. **Confirm no external reads** of `entity.app` on the 10 dead-field modules (§3). Grep source, tests,
   and `examples/` for `.app` on those types.
2. **Delete the dead `app` fields** (§3) first — zero helper fallout, smallest possible PR, immediate
   progress on constraint (a).
3. **Remove the shard-id properties** (§5.1) and migrate their two call styles to
   `snowflakes.calculate_shard_id(count_or_app, id)` at the (client-level) call sites.
4. **Remove the `app` field + abstract `app` property** from the remaining wire-entity modules with
   helpers (guilds, channels, messages, webhooks, users, commands, audit_logs, presences, templates).
   This orphans their helpers — land the Strategy 2 targets
   ([`03-new-rest-methods-and-free-functions.md`](./03-new-rest-methods-and-free-functions.md)) and
   delete the Strategy 1/3 helpers in the same PR sequence (see
   [`00-strategy.md`](./00-strategy.md) §6).
5. **Strip the 63 `app=self._app` injections** and the `self._app` storage in `impl/entity_factory.py`
   (`:485-486`). Verify nothing else in the factory needs `_app`
   (cross-link [`../05-entity-factory/00-architecture-and-decode-strategy.md`](../05-entity-factory/00-architecture-and-decode-strategy.md);
   cache's `build_entity(app)` collapse is in [`../04-frozen-and-cache/02-cache-app-and-views.md`](../04-frozen-and-cache/02-cache-app-and-views.md)).
6. **Delete the `SKIP_DEEP_COPY` usages**; `attrs_extensions.py` itself is SLIMMED in the same
   frozen/copy work (`with_copy` retained for the ~25 deferred non-Struct consumers) and deleted
   wholesale only in a later phase
   ([`../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md`](../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md)).
7. **Events**: remove the full event `app` surface per D10-events (RESOLVED) — 45 fields, 31
   delegating properties, abstract `Event.app`, the `ExceptionEvent` proxy, 42 helpers
   ([`../07-events/00-events-migration.md`](../07-events/00-events-migration.md)). **Interactions**:
   remove the `app` field (`base_interactions.py:275`), the 9 action helpers, the
   `ExecutableWebhook` subclassing, and the interaction `app=self._app` injections per the resolved
   D10-interactions; the 8 builder factories are reimplemented app-free
   ([`02-helper-method-inventory/06-interactions.md`](./02-helper-method-inventory/06-interactions.md)).

---

## 7. Affected files & symbols

| Path | Anchor | Change |
|---|---|---|
| `hikari/templates.py` | 151-153 | canonical `app` field decl — remove |
| `hikari/guilds.py` | 321, 516, 1150, 1664, 1683, 1692 | `app` field/property + `shard_id` (int style) |
| `hikari/channels.py` | 361, 989, 995 | `app` field + `shard_id` (app-object style) |
| `hikari/messages.py` | 408, 816-848, 850 | `app` field + mention-getter closures |
| `hikari/webhooks.py` | 81, 475 | abstract `app` property + field |
| `hikari/users.py` | 294, 876 | abstract `app` property + field |
| `hikari/commands.py` | 220 | `app` field |
| `hikari/audit_logs.py` | 506, 700 | `app` field |
| `hikari/presences.py` | 423 | `app` field |
| `hikari/applications.py` | 440, 556, 638, 767 | abstract `app` property + **dead** fields |
| `hikari/invites.py`, `emojis.py`, `stickers.py`, `scheduled_events.py`, `auto_mod.py`, `voices.py`, `stage_instances.py`, `monetization.py`, `polls.py` | §2.1/§3 anchors | **dead** `app` fields — drop free |
| `hikari/interactions/base_interactions.py` | 275, 352 | `app` field — REMOVED (D10-interactions RESOLVED; executed in the interactions pass); `webhook_id` false-friend goes with the `ExecutableWebhook` departure there, not in this sweep |
| `hikari/events/base_events.py` | 83-86, 207-211 | abstract `app` property + `FailedEvent.app` proxy — removed in the EVENTS pass (§5.2, 07-events §3.1), not in this file's wire-entity sweep |
| `hikari/impl/entity_factory.py` | 485-486 + 63 sites | `self._app` storage + `app=self._app` injections — remove |
| `hikari/internal/attrs_extensions.py` | 186 (`SKIP_DEEP_COPY`), whole file | slimmed in the frozen/copy work (`SKIP_DEEP_COPY` path deleted; `with_copy` retained for the ~25 deferred non-Struct consumers); wholesale delete rides the post-3.0 B2 step |
| `hikari/snowflakes.py` | 135-152 | `calculate_shard_id` unchanged; call sites migrate to it |

---

## 8. Risks / gotchas

- **Missing the abstract-property declarations** (40 sites) leaves an unsatisfiable abstract `app` on
  ABCs after the field is gone. Grep `def app` in addition to `attrs.field` (§2.2).
- **`shard_id` cannot be a struct property** — it is client-level state; forcing it to stay would
  reintroduce an `app`/`shard_count` dependency on a frozen entity (§5.1).
- **Do not remove `FailedEvent.app` in THIS pass** — it is deleted with the event `app` surface
  (§5.2, 07-events §3.1), not by the wire-entity sweep. `PartialInteraction.webhook_id` stays a
  false-friend of the `self.app` grep and is left alone here; it is removed in the interactions
  pass with the `ExecutableWebhook` departure (§5.3).
- **Dead-field confidence** — before dropping the 10 dead fields, verify no user-facing code path
  reads `entity.app` on them (§3, dossier 04 §8.4).
- **Ordering** — deleting the field before landing Strategy 2 replacements leaves callers of
  `compose`/`token` helpers stranded; sequence per [`00-strategy.md`](./00-strategy.md) §6.

---

## 9. Verification

- `grep -rn "attrs\.field" hikari/ | grep "app"` and `grep -rn "def app" hikari/` return **zero** hits
  on wire-entity modules AND `hikari/events/` after this pass; after the interactions pass the same
  greps return zero on `hikari/interactions/` too (D10-interactions RESOLVED — no exception remains).
- `grep -rn "SKIP_DEEP_COPY" hikari/` returns zero on converted modules; `attrs_extensions.py` is
  slimmed now, deleted wholesale in the later phase.
- `grep -rn "app=self\._app" hikari/impl/entity_factory.py` returns zero.
- `msgspec.json.decode(payload, type=Message)` and peers construct with no `app` kwarg (constraint (a)
  smoke test).
- Unit test: constructing any wire entity Struct raises `TypeError` on an unexpected `app=` kwarg
  (proves the field is gone), while equality/hash still work via the inherited `snowflakes.Unique`
  dunders (see [`../01-foundations/01-base-struct-conventions.md`](../01-foundations/01-base-struct-conventions.md)).

---

## 10. Open questions / decisions

- **D10-events (RESOLVED)** and **D10-interactions (RESOLVED)** — events and interactions are
  app-less by maintainer decision; this file's event and interaction steps reflect that. The
  interaction `app` field (`base_interactions.py:275`) is removed, with the 9 action helpers
  deleted and the 8 builder factories reimplemented app-free. Decision record in
  [`04-events-and-interactions-app-decision.md`](./04-events-and-interactions-app-decision.md) /
  [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md). No pending app
  decision remains.
- **Count reconciliation** — this file uses the dossier-verified grep figures: 25 model-field decls,
  40 abstract `app` properties, 63 entity-factory injections, 45 event fields, 50 event-factory
  injections, 151 `SKIP_DEEP_COPY` sites (dossier 04 §0). CONVENTIONS §8 summarizes these as
  "24 declarations inherited by 64 entities / 64 injection sites"; the grep counts above are
  authoritative.
