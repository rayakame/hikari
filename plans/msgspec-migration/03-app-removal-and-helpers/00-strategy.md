# App Removal and Helper Methods — Strategy

Overview of the work forced by constraint (a): frozen, JSON-decoded entity Structs cannot carry a
runtime `app`/`RESTAware` handle, so the `app` field and every `self.app.*` delegating helper are
removed from wire entities — and, by the maintainer's D10 decisions, from events and interactions
as well — and callers move to `rest.*` / `cache.*` directly (gateway handlers close over the bot).
The one survivor set: the 8 interaction builder factories, kept and reimplemented as app-free sync
constructors. This file states the philosophy, the helper taxonomy, and the three replacement
strategies that the rest of this cluster applies mechanically.

Sibling files in this cluster:
- [`01-app-field-removal.md`](./01-app-field-removal.md) — the field/property/injection-site removal
  mechanics, dead fields, `SKIP_DEEP_COPY`, `shard_id` styles, `FailedEvent.app`.
- [`02-helper-method-inventory/`](./02-helper-method-inventory/00-README.md) — the full per-module
  table of all 163 helper methods and their disposition.
- [`03-new-rest-methods-and-free-functions.md`](./03-new-rest-methods-and-free-functions.md) — the
  cluster with no 1:1 `rest.*` equivalent.
- [`04-events-and-interactions-app-decision.md`](./04-events-and-interactions-app-decision.md) — the
  D10 decision record: both halves RESOLVED — events and interactions are app-less; the interaction
  action/builder split (9 action helpers deleted, 8 builder factories kept app-free).

---

## 1. Objective

Serve **constraint (a)** ("no `app` injection during deserialization"). Concretely:

1. Delete the `app: traits.RESTAware` field from every JSON-decoded wire entity so `msgspec.json.decode`
   can construct it directly. There is no seam through which a typed decode can thread the factory's
   `self._app`, so the field must go (see [dossier 10 §6](../12-appendices/00-research-dossier-index.md)
   on the `_RESTProvider`/`app` injection mechanism).
2. Delete or re-home the **163 helper methods** that dereference `self.app` (`self.app.rest.*`,
   `self.app.cache.*`, `self.app.shard_count`, `self.app.get_me()`), across 20 modules
   (dossier 04 §0). Callers migrate to the canonical `rest.*` / `cache.*` surfaces.
3. Let the `app`-field removal cascade into the copy machinery: `app` was the one field the cache
   refused to deep-copy (`SKIP_DEEP_COPY`, 151 sites, dossier 04 §1); once it is gone and Structs are
   frozen, the whole copy layer has nothing left to special-case (feeds constraint (c);
   see [`../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md`](../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md)).

This is the single largest user-visible break in the migration. The documented, primary usage pattern
in every example is a helper (`event.message.respond(...)`, `event.interaction.create_initial_response(...)`,
`user.send(...)`); all of it changes (dossier 10 §8.1). The plan's job is to make the substitution
mechanical and to guarantee callers retain a stable path to `rest`.

---

## 2. The app-removal philosophy

Three principles govern every decision in this cluster.

### 2.1 Entities are data; clients are clients

A deserialized entity is a **snapshot of Discord JSON**. It should be constructible from bytes alone,
comparable by id, freely shared by reference, and free of live network handles. The `app` pointer
violated all of that: it made every `Message`, `Channel`, `Guild` a hidden client. Under msgspec the
entity is *only* the data. The `RESTClient` (dossier 10 §0: **zero** `.app` references in
`impl/rest.py`) is the sole action layer, and it already takes ids/builders as inputs and returns
entities — it never needs a returned entity to carry `.app`. Removing the helpers therefore requires
**no new HTTP endpoints**; the helpers were thin sugar over methods that already exist (dossier 04 §7.1,
dossier 10 §7).

### 2.2 The id the helper hid is public struct data

Every helper sourced the ids it forwarded from `self` — `self.id`, `self.channel_id`,
`self.webhook_id`, `self.application_id`, `self.token`, `self.guild_id`, `self.code`,
`self.source_guild`. All of these remain **plain public fields on the frozen Struct**. So the caller
can always reproduce the exact call the helper made; the substitution is `entity.method(args)` →
`rest.<method>(entity.<id>, args)`. Verbose, but purely mechanical (dossier 10 §8.1).

### 2.3 Symmetry vs. pragmatism is a *policy* choice — now fully decided

The forcing constraint bites *only* on JSON-decoded wire entities. Events and interactions are
constructed with runtime context in hand (dossier 08 §0, §10.1), so injecting `app` into them was
technically trivial and the constraint did not require their helpers to disappear. The maintainer has
now made the policy call **for both**: they go app-less anyway. **D10-events: RESOLVED** — the 44
`app` fields, 31 delegating properties, `ExceptionEvent` proxy, abstract `Event.app`, and all 42
event helpers are deleted; gateway handlers close over the bot object instead. **D10-interactions:
RESOLVED** — the `PartialInteraction.app` field, the `ExecutableWebhook` subclassing, and the 9
interaction *action* helpers are deleted; the 8 *builder factories* are kept and reimplemented as
app-free sync constructors, so the REST-bot return-a-builder flow is unchanged. See
[`04-events-and-interactions-app-decision.md`](./04-events-and-interactions-app-decision.md) §3–§4.
The one distinction a mechanical "remove all `self.app`" pass must respect: the 8 interaction
builder factories are *reimplemented app-free*, not deleted.

---

## 3. Helper taxonomy

Every one of the 163 `self.app` helpers falls into one of six shapes (the "Extra logic" column of the
dossier 04 §3 tables). The taxonomy determines the replacement strategy.

| Tag | Shape | Body (schematic) | Count-ish | Replacement |
|---|---|---|---|---|
| `pure` | single straight delegation, nothing else | `return await self.app.rest.X(self.some_id, **kw)` | majority (~110 rest-delegating, dossier 04 §7.1) | **Strategy 1** — delete, caller uses `rest.*` |
| `arg-default` | delegation after defaulting one argument | `guild = UNDEFINED if self.guild_id is None else self.guild_id; return await self.app.rest.X(..., guild)` | commands (5), `AuditLogEntry.fetch_user` | **Strategy 1** — caller supplies the default |
| `assert` | delegation + `assert isinstance(result, Sub)` narrowing | `c = await self.app.rest.fetch_channel(self.channel_id); assert isinstance(c, T); return c` | ~15 (webhooks, channels, audit, events) | **Strategy 1** — narrowing moves caller-side (`typing.cast`) or a typed wrapper |
| `guard` | `isinstance(self.app, traits.CacheAware/ShardAware)` gate, returns `None`/`{}` when absent | `if isinstance(self.app, traits.CacheAware): return self.app.cache.get_X(...); return {}` | the 37 `cache.*` helpers + shard helpers | **Strategy 3** — direct `cache.*`, guard collapses to "did caller pass a cache?" |
| `token` | webhook token/`use_token` tri-state resolution before the call | resolve `use_token`→`token`, raise `ValueError` if unknown, then `rest.X(..., token=token)` | webhook methods (dossier 04 §3.3) | **Strategy 2** — free function / rest-layer token param |
| `compose` | multiple calls or client-side filtering/coercion | e.g. `fetch_roles`: fetch all guild roles, filter by `self.role_ids` | `Member.fetch_roles`, `PartialUser.send`, `edit_overwrite`, `respond`, reaction dispatchers, mention getters | **Strategy 2** — free function or new `rest.*` convenience |

The precise per-method tags live in [`02-helper-method-inventory/`](./02-helper-method-inventory/00-README.md).
Everything tagged `pure`/`arg-default`/`assert` is Strategy 1 (the overwhelming majority);
`guard` is Strategy 3; `token`/`compose` is Strategy 2.

---

## 4. The three replacement strategies

### Strategy 1 — Direct `rest.*` call (delete the helper)

Applies to all `pure` / `arg-default` / `assert` rows: templates, presences, most of channels,
`PartialGuild` (22 methods), commands, audit-logs, `Message.{fetch_channel,edit,delete,add_reaction}`,
all interaction *action* methods, most event `fetch_*`. The helper is deleted; the caller writes the
`rest.*` call the helper used to make.

```python
# before
await message.edit(content="hi")
await channel.send("hi")
role = await guild.delete_channel(chan)          # + assert isinstance(chan, GuildChannel)

# after (caller has a `rest` in scope)
await rest.edit_message(message.channel_id, message.id, content="hi")
await rest.create_message(channel.id, "hi")
role = await rest.delete_channel(chan)           # rest already returns the right runtime type
```

Notes:
- The `assert isinstance(...)` narrowings (dossier 04 §8.5) are caller conveniences; drop them or move
  a `typing.cast` to the call site. `rest.fetch_channel`/`rest.delete_channel` already return the
  correct runtime types.
- `arg-default` helpers (commands' `guild = UNDEFINED if self.guild_id is None else self.guild_id`)
  push the one-line default onto the caller.

### Strategy 2 — Free function or new `rest.*` method (composition can't collapse to one call)

Applies to `token` and `compose` helpers whose logic would otherwise be orphaned. These are the
**only** places "call `rest.X` directly" is not a 1:1 substitution (dossier 10 §7.2). Enumerated with
proposed signatures in [`03-new-rest-methods-and-free-functions.md`](./03-new-rest-methods-and-free-functions.md):
`Member.fetch_roles` (client-side role filter), `PartialUser.send` (DM resolve+create), webhook
token-resolution methods, `PermissibleGuildChannel.edit_overwrite` (`target_type` inference),
`Guild.get_my_member` (needs `app.get_me()`), guild-scoped cache getters with ownership filters,
`PartialMessage.get_member_mentions`/`get_role_mentions`.

Two homes are available and the choice is per-cluster:
- **Free function** taking `rest`/`cache` explicitly, e.g. `fetch_member_roles(rest, member)`. Keeps
  the composition logic in the library without re-attaching it to the data Struct.
- **New `rest.*` convenience method**, e.g. `rest.send_dm(user, ...)`. Preserves DX for the highest-
  traffic patterns at the cost of a small public REST surface addition.

### Strategy 3 — Direct `cache.*` call (or guild-scoped free function)

Applies to the 37 `self.app.cache.*` helpers (dossier 04 §0): `Guild` getters, event `get_*`, message
mention getters. Each becomes a `cache.get_*(...)` at the call site.

```python
# before
member = guild.get_member(user_id)               # isinstance-guarded, None if not CacheAware

# after
member = cache.get_member(guild.id, user_id)     # caller holds the cache
```

Watch two things:
- **Graceful degradation.** The helpers returned `{}`/`None` when the app was not `CacheAware`
  (dossier 04 §8.6). The guard collapses to "did the caller hand us a cache?" — a free-function
  replacement must preserve "no cache → empty", not raise.
- **Ownership filters.** `Guild.get_channel`/`get_emoji`/`get_sticker`/`get_role` do a raw cache hit
  **plus** a `obj.guild_id == self.id` check (dossier 04 §3.9). These want a small free function
  `get_guild_scoped_*(cache, guild_id, id)` rather than a bare `cache.get_*`
  (see [`03-new-rest-methods-and-free-functions.md`](./03-new-rest-methods-and-free-functions.md)).

---

## 5. Where callers get `rest`/`cache` after the removal

The removal only works if callers still have an ergonomic handle. The blessed paths (dossier 10 §8.2,
gateway-handler row updated for D10-events per dossier 19 §3.3):

| Context | Path to `rest` / `cache` | Status |
|---|---|---|
| Gateway event handler | close over the bot object: `bot.rest` / `bot.cache` | **Events are app-less** (D10-events DECIDED): the entire event `app` surface is REMOVED (44 fields + 31 delegating properties + 42 helpers). Every example except `voice_message.py` already closes over `bot` (dossier 19 §3.3) — see [`04-events-and-interactions-app-decision.md`](./04-events-and-interactions-app-decision.md) §3. |
| Interaction handler (gateway) | `bot.rest.create_interaction_response(interaction.id, interaction.token, ...)` via the closed-over `bot` | **Interactions are app-less** (D10-interactions RESOLVED): the 9 action helpers are deleted; the ids/tokens they injected are public struct fields. |
| `RESTBot` / interaction server | listener still **returns a builder** (`interaction.build_response(...)`, now an app-free constructor); for explicit calls, the bot's `rest` + `interaction.id`/`interaction.token` | Unchanged — the 8 builder factories are kept app-free. |
| Standalone `RESTApp` | the `RESTApp`-acquired `rest` client | Unchanged. |

With events app-less there is no event-side `app` seam left to maintain: the 31 events that used to
*derive* `app` from their wrapped entity (e.g. `MessageCreateEvent.app → self.message.app`, dossier
08 §5.2) lose those properties outright — deleted, not converted to own fields — and the
handler-facing replacement is the closed-over `bot`. The removal recipes live in
[`02-helper-method-inventory/07-events.md`](./02-helper-method-inventory/07-events.md); sequencing
with the event pipeline in
[`04-events-and-interactions-app-decision.md`](./04-events-and-interactions-app-decision.md) §8 and
[`../07-events/00-events-migration.md`](../07-events/00-events-migration.md).

---

## 6. Step-by-step (cluster-level sequencing)

1. **Inventory freeze.** Confirm the 163-method inventory in
   [`02-helper-method-inventory/`](./02-helper-method-inventory/00-README.md) is complete and each row
   is tagged with its taxonomy class.
2. **D10 status check.** Both halves are RESOLVED — events and interactions go app-less, so the 42
   event helpers, the whole event `app` surface, and the 9 interaction action helpers all join the
   removal set alongside the wire entities. Execute the interactions subtree per the action/builder
   split: the 8 builder factories are reimplemented app-free, not deleted. See
   [`04-events-and-interactions-app-decision.md`](./04-events-and-interactions-app-decision.md) and
   the recipe in [`02-helper-method-inventory/06-interactions.md`](./02-helper-method-inventory/06-interactions.md).
3. **Remove `app` fields + injections** on wire entities (Strategy 1/2/3 do not run until the field is
   gone). Mechanics in [`01-app-field-removal.md`](./01-app-field-removal.md).
4. **Land the Strategy 2 targets first** (free functions / new `rest.*`) so callers of `compose`/`token`
   helpers have a landing pad before the helper is deleted.
5. **Delete the Strategy 1/3 helpers**, module by module, in dependency order, updating docs/examples.
6. **Drop the copy machinery** now that `app` is gone (feeds constraint (c),
   [`../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md`](../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md)).
7. **Rewrite examples & changelog.** Every `respond`/`send`/`create_initial_response` example changes;
   catalogue in [`../11-rollout/03-breaking-changes-and-changelog.md`](../11-rollout/03-breaking-changes-and-changelog.md).

---

## 7. Risks / gotchas (cluster-level)

- **DX regression is the real cost, not capability loss.** No new endpoints are mandatory (dossier 10
  §7, §9); everything is expressible with existing `rest.*`. But the highest-traffic ergonomic sugar
  (`respond`, `send`, `create_initial_response`) is what breaks — the interaction share is the
  largest single ecosystem break in the migration. Mitigate with the Strategy 2 free functions /
  convenience methods, the exact replacement table
  ([`04-events-and-interactions-app-decision.md`](./04-events-and-interactions-app-decision.md) §4.1),
  the kept app-free builder factories (`build_response` survives), and the downstream coordination in
  [`../11-rollout/03-breaking-changes-and-changelog.md`](../11-rollout/03-breaking-changes-and-changelog.md).
- **Count reconciliation.** Use **163** total `self.app` helper methods and **126** `self.app.rest.`
  reference lines (dossier 04 §0), not the task brief's earlier "~102" estimate (dossier 04 §8.9). The
  126 rest lines split ≈ 102 across data-models+interactions (dossier 10 §7: 90 methods / 102 sites)
  + 24 across events (dossier 08 §6). Grand-total accounting after the D10 resolutions: **all ~173**
  app-delegating helper sites (163 `self.app` + 10 `self.user.app`) **are removed** — ~114
  wire-entity + 42 event + the 9 interaction action helpers — and the 8 interaction builder
  factories survive as app-free sync constructors (they lose their `self.app` usage but are not
  deleted). No retained app-delegating set remains
  (see [`02-helper-method-inventory/00-README.md`](./02-helper-method-inventory/00-README.md) §2).
- **Two `shard_id` styles** and **`app`-as-abstract-property** (40 sites) are mechanical traps — a
  `grep attrs.field` misses the properties. Handled in [`01-app-field-removal.md`](./01-app-field-removal.md).
- **`isinstance(self.app, traits.*)` guards (41 sites)** exist only because a `RESTAware` app *might*
  also be Cache/Shard aware. When callers pass `cache`/`rest` explicitly, the guard collapses — but
  the "no cache → empty" semantics must be preserved by the replacement (dossier 04 §7.3, §8.6).

---

## 8. Verification

- After the field/helper removal, `grep -rnE "self\.(user\.)?app\." hikari/` must return **zero**
  hits outside tests — wire-entity modules, `hikari/events/`, AND `hikari/interactions/` (both D10
  halves RESOLVED: app-less everywhere; the 8 kept builder factories construct from
  `special_endpoints` and no longer touch `self.app`).
- `msgspec.json.decode(payload, type=Message)` (and peers) constructs without an `app` kwarg — the
  smoke test for constraint (a); see [`../05-entity-factory/00-architecture-and-decode-strategy.md`](../05-entity-factory/00-architecture-and-decode-strategy.md).
- Every removed helper's target `rest.*` method still exists on `RESTClient` (dossier 10 §5 inventory);
  no endpoint is orphaned.
- Examples (`examples/hello_world.py`, `examples/slash.py`, `examples/image_resources.py`,
  `examples/voice_message/voice_message.py`) compile and run against the rewritten `rest.*` /
  closed-over `bot.rest` forms — no `event.app.*` remains anywhere.

---

## 9. Open questions / decisions

- **D10-events — RESOLVED** by the maintainer: events are app-less (44 fields + 31 delegating
  properties + `ExceptionEvent` proxy + 42 helpers removed; zero internal readers).
  **D10-interactions — RESOLVED** by the maintainer: interactions are app-less too — 9 action
  helpers deleted, 8 builder factories kept and reimplemented app-free, `ExecutableWebhook`
  departure unconditional. No pending app decision remains. Full record in
  [`04-events-and-interactions-app-decision.md`](./04-events-and-interactions-app-decision.md);
  logged in [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md).
- **Do we ship optional `rest.*` convenience methods** (`send_dm`, reaction sugar) to soften the DX
  break, or leave callers to inline? Recommendation and signatures in
  [`03-new-rest-methods-and-free-functions.md`](./03-new-rest-methods-and-free-functions.md).
- **Keep the `assert isinstance` typed narrowing** as thin typed `rest` wrappers, or push `cast` onto
  callers? Cross-link [`../09-rest-and-gateway/00-rest-client.md`](../09-rest-and-gateway/00-rest-client.md).
