# Helper Inventory — `hikari/events/*.py` (REMOVED — D10-events DECIDED)

Complete inventory of the **42 event helper methods** that reference `self.app` (24 `rest.*` + 18
`cache.*` call-site lines, dossier 08 §6; per dossier 04 §0 the cache lines split
message 10 / typing 3 / guild 2 / channel 2 / member 1). Only 5 of the 20 event modules define such
helpers. **All 42 are now definitively REMOVED**: the maintainer has resolved the events half of D10
— events go app-less
([`../04-events-and-interactions-app-decision.md`](../04-events-and-interactions-app-decision.md) §3;
`../../00-overview/05-decisions-log.md`, D10-events). This file enumerates every helper and its
removal recipe; the recipes in §5 are the migration path, no longer a contingency.

Sources: dossier 04 §5, dossier 08 §5–§6, dossiers 17/19 (removal counts). See
[`00-README.md`](00-README.md) for the shared legend.

## 1. Objective

Map every event `self.app.rest.*`/`self.app.cache.*` helper to its replacement, and record the
event-specific structural outcome: the **31 events that compute `app` via a `@property` returning
`self.<wrapped_entity>.app` lose those properties outright** — deleted along with the 44 own `app`
fields, the abstract `Event.app`, and the `ExceptionEvent.app` proxy; nothing converts to an
own-`app` field. Serves constraint (a) / D9 plus the resolved D10-events.

## 2. Why events were a separate decision — and how it resolved

Events are hand-constructed today: `EventFactoryImpl` (`impl/event_factory.py:85`) deserializes the
wrapped entity via `self._app.entity_factory.deserialize_*`, then constructs the event, passing the
entity plus `shard` and (for some events) `app=self._app` (dossier 08 §0.1, §10.1). msgspec never
sees an event class today, and even under the target event pipeline — where the 18 flat events *do*
become direct decode targets
([`../../12-appendices/04-event-pipeline-feasibility.md`](../../12-appendices/04-event-pipeline-feasibility.md))
— runtime injection stays msgspec-compatible (that is exactly how `shard` survives, dossiers 18/20).
So constraint (a) never technically forced the event helpers away; keeping them was a live option
(the old D10 Option 2). The maintainer decided the other way: **events are app-less**. Two
consequences for this file:

1. The 42 helpers below are **removed** — apply the §5 recipes; callers reach the client by closing
   over the bot object (`bot.rest` / `bot.cache`).
2. The **31 `app`-delegating `@property` events are deleted, not converted** — see §4; the 44 own
   `app` fields, the abstract `Event.app`, and the `ExceptionEvent.app` proxy go with them.

The interactions half of D10 is NOT decided by this — see [`06-interactions.md`](06-interactions.md)
and D10-interactions.

## 3. The full event-helper inventory — all 42 REMOVED (dossier 04 §5)

### 3.1 `events/channel_events.py` (12 methods; 10 rest + 2 cache)

| Line | Class | Method | async | Delegates to | Extra logic |
|---:|---|---|:--:|---|---|
| 129 | `GuildChannelEvent` | `get_guild` | no | `cache.get_available_guild or get_unavailable_guild` | `guard` |
| 145 | `GuildChannelEvent` | `fetch_guild` | yes | `rest.fetch_guild(self.guild_id)` | pure |
| 169 | `GuildChannelEvent` | `get_channel` | no | `cache.get_guild_channel(self.channel_id)` | `guard` |
| 186 | `GuildChannelEvent` | `fetch_channel` | yes | `rest.fetch_channel(self.channel_id)` | `assert` |
| 225 | `DMChannelEvent` | `fetch_channel` | yes | `rest.fetch_channel(self.channel_id)` | `assert` |
| 390 | `PinsUpdateEvent` | `fetch_pins` | no | `rest.fetch_pins(self.channel_id)` | pure |
| 439 | `GuildPinsUpdateEvent` | `fetch_channel` | yes | `rest.fetch_channel(self.channel_id)` | `assert` |
| 487 | `DMPinsUpdateEvent` | `fetch_channel` | yes | `rest.fetch_channel(self.channel_id)` | `assert` |
| 523 | `InviteEvent` | `fetch_invite` | yes | `rest.fetch_invite(self.code)` | pure |
| 644 | `WebhookUpdateEvent` | `fetch_channel_webhooks` | yes | `rest.fetch_channel_webhooks(self.channel_id)` | pure |
| 668 | `WebhookUpdateEvent` | `fetch_guild_webhooks` | yes | `rest.fetch_guild_webhooks(self.guild_id)` | pure |
| 709 | `GuildThreadEvent` | `fetch_channel` | yes | `rest.fetch_channel(self.thread_id)` | `assert` |

### 3.2 `events/guild_events.py` (10 methods; 8 rest + 2 cache)

| Line | Class | Method | async | Delegates to | Extra logic |
|---:|---|---|:--:|---|---|
| 87 | `GuildEvent` | `fetch_guild` | yes | `rest.fetch_guild(self.guild_id)` | pure |
| 97 | `GuildEvent` | `fetch_guild_preview` | yes | `rest.fetch_guild_preview(self.guild_id)` | pure |
| 107 | `GuildEvent` | `get_guild` | no | `cache.get_available_guild or get_unavailable_guild` | `guard` |
| 374 | `BanEvent` | `fetch_user` | yes | `rest.fetch_user(self.user)` | pure |
| 400 | `BanCreateEvent` | `fetch_ban` | yes | `rest.fetch_ban(self.guild_id, self.user)` | pure |
| 454 | `EmojisUpdateEvent` | `fetch_emojis` | yes | `rest.fetch_guild_emojis(self.guild_id)` | pure |
| 489 | `StickersUpdateEvent` | `fetch_stickers` | yes | `rest.fetch_guild_stickers(self.guild_id)` | pure |
| 516 | `IntegrationEvent` | `fetch_integrations` | yes | `rest.fetch_integrations(self.guild_id)` | pure |
| 681 | `PresenceUpdateEvent` | `get_user` | no | `cache.get_user(self.user_id)` | `guard` |
| 694 | `PresenceUpdateEvent` | `fetch_user` | yes | `rest.fetch_user(self.user_id)` | pure |

### 3.3 `events/member_events.py` — `MemberEvent` (1 method; 1 cache)

| Line | Method | async | Delegates to | Extra logic |
|---:|---|:--:|---|---|
| 73 | `get_guild` | no | `cache.get_available_guild or get_unavailable_guild` | `guard` |

### 3.4 `events/message_events.py` (10 methods; all cache, all `guard`ed)

| Line | Class | Method | async | Delegates to | Extra logic |
|---:|---|---|:--:|---|---|
| 185 | `GuildMessageCreateEvent` | `get_channel` | no | `cache.get_guild_channel(self.channel_id)` | `guard` + `assert` |
| 203 | `GuildMessageCreateEvent` | `get_guild` | no | `cache.get_guild(self.guild_id)` | `guard` |
| 221 | `GuildMessageCreateEvent` | `get_member` | no | `cache.get_member(self.guild_id, self.message.author.id)` | `guard` |
| 405 | `GuildMessageUpdateEvent` | `get_member` | no | `cache.get_member(...)` | `guard` + author UNDEFINED check |
| 426 | `GuildMessageUpdateEvent` | `get_channel` | no | `cache.get_guild_channel(...)` | `guard` + `assert` |
| 444 | `GuildMessageUpdateEvent` | `get_guild` | no | `cache.get_guild(...)` | `guard` |
| 542 | `GuildMessageDeleteEvent` | `get_channel` | no | `cache.get_guild_channel(...)` | `guard` + `assert` |
| 560 | `GuildMessageDeleteEvent` | `get_guild` | no | `cache.get_guild(...)` | `guard` |
| 638 | `GuildBulkMessageDeleteEvent` | `get_channel` | no | `cache.get_guild_channel(...)` | `guard` + `assert` |
| 656 | `GuildBulkMessageDeleteEvent` | `get_guild` | no | `cache.get_guild(...)` | `guard` |

### 3.5 `events/typing_events.py` (9 methods; 6 rest + 3 cache)

| Line | Class | Method | async | Delegates to | Extra logic |
|---:|---|---|:--:|---|---|
| 71 | `TypingEvent` | `fetch_channel` | yes | `rest.fetch_channel(self.channel_id)` | `assert` |
| 83 | `TypingEvent` | `get_user` | no | `cache.get_user(self.user_id)` | `guard` |
| 96 | `TypingEvent` | `fetch_user` | yes | `rest.fetch_user(self.user_id)` | pure |
| 118 | `TypingEvent` | `trigger_typing` | no | `rest.trigger_typing(self.channel_id)` | pure |
| 178 | `GuildTypingEvent` | `fetch_guild` | yes | `rest.fetch_guild(self.guild_id)` | pure |
| 188 | `GuildTypingEvent` | `fetch_guild_preview` | yes | `rest.fetch_guild_preview(self.guild_id)` | pure |
| 198 | `GuildTypingEvent` | `fetch_member` | yes | `rest.fetch_member(self.guild_id, self.user_id)` | pure |
| 208 | `GuildTypingEvent` | `get_channel` | no | `cache.get_guild_channel(self.channel_id)` | `guard` + `assert` |
| 225 | `GuildTypingEvent` | `get_guild` | no | `cache.get_available_guild or get_unavailable_guild` | `guard` |

The other 15 event modules (`reaction_events`, `voice_events`, `role_events`, `scheduled_events`,
`shard_events`, `poll_events`, `monetization_events`, `application_events`, `auto_mod_events`,
`lifetime_events`, `stage_events`, `interaction_events`, `user_events`, `base_events`) carry an
`app` field/property but define **no** `self.app.*` helpers (dossier 04 §5) — their `app` surface is
removed all the same (§4).

## 4. The delegating properties and `app` fields — DELETED, not converted (dossier 08 §5.2)

**55% of concrete events do not store `app`** — they expose it as `@property` returning
`self.<wrapped_entity>.app` (32 sites total; 31 read an *entity's* `.app`, 1 reads another
*event's*). Examples:

```
message_events.py:89/267 -> self.message.app     channel_events.py:274/311/342 -> self.channel.app
guild_events.py:193/257/343 -> self.guild.app     interaction_events.py:65 -> self.interaction.app
reaction_events.py:299 -> self.member.app         typing_events.py:155 -> self.member.app
role_events.py:78/115 -> self.role.app            voice_events.py:91 -> self.state.app
... (full list dossier 08 §5.2)
```

When the wrapped entity becomes an app-less Struct, **each of these 31 properties fails** — which is
why they must be deleted in the same change that strips entity `app`, not left as latent
AttributeErrors. An earlier revision of this section framed them as a mandatory convert-to-own-field
fix "under both D10 options". **Superseded** — with D10-events decided as app-less, the fix is
deletion across the board:

- the **31** entity-delegating `app` properties are deleted;
- the **44** own `app: traits.RESTAware` field declarations are deleted (grep-verified count,
  dossier 08 §5.1; with their `SKIP_DEEP_COPY` metadata);
- the abstract `Event.app` (`base_events.py:83-86`) is deleted;
- the `ExceptionEvent.app` proxy (`base_events.py:207-211`) is deleted too — it was the one
  "safe" delegator (it reads another *event's* `app`), but its `failed_event.app` target vanishes
  with concrete-event `app`; `ExceptionEvent.shard` stays (events keep `shard`, D13);
- the **50** `app=self._app` injection sites in `impl/event_factory.py` are deleted (dossier 17 §0);
  no new injection sites are written anywhere;
- the lifetime events (`StartingEvent`/`StartedEvent`/`StoppingEvent`/`StoppedEvent`), whose *only*
  field was `app`, become field-less marker classes (dossier 19 §3.3).

The blast radius is purely public API: **zero** hikari-internal readers of `event.app` (dossier 19
§3.2), 1 example (`examples/voice_message/voice_message.py:90`), ~120 test references.

## 5. Replacements — the definitive removal recipes

These recipes are now the migration path for every caller: the helpers are gone, and the `rest` /
`cache` handle is the closed-over bot object (`bot.rest` / `bot.cache` — dossier 19 §3.3).

### 5.1 Pure / assert rest helpers → direct `rest.*` (Strategy 1)

| Removed helper (examples) | Caller now writes |
|---|---|
| `event.fetch_guild()` | `await rest.fetch_guild(event.guild_id)` |
| `event.fetch_channel()` | `await rest.fetch_channel(event.channel_id)` (cast to narrow) |
| `channel_event.fetch_pins()` | `rest.fetch_pins(event.channel_id)` |
| `invite_event.fetch_invite()` | `await rest.fetch_invite(event.code)` |
| `webhook_event.fetch_channel_webhooks()` | `await rest.fetch_channel_webhooks(event.channel_id)` |
| `ban_event.fetch_user()` | `await rest.fetch_user(event.user)` |
| `ban_create_event.fetch_ban()` | `await rest.fetch_ban(event.guild_id, event.user)` |
| `typing_event.trigger_typing()` | `rest.trigger_typing(event.channel_id)` |
| `guild_typing_event.fetch_member()` | `await rest.fetch_member(event.guild_id, event.user_id)` |

The `assert isinstance(...)` narrowings on the `fetch_channel` variants (channel/typing/thread) are
lost on direct calls — apply the cluster narrowing policy ([`00-README.md`](00-README.md) §9).

### 5.2 Cache getters → direct `cache.*` with `{}`/`None` degradation (Strategy 3)

All 18 cache getters gate on `isinstance(self.app, traits.CacheAware)` and return `None` (or `{}`)
when there is no cache — this graceful degradation must survive (dossier 04 §8.6):

```python
# before: event.get_guild()  -> GatewayGuild | None, None if no cache
# after:
guild = (cache.get_available_guild(event.guild_id)
         or cache.get_unavailable_guild(event.guild_id)) if cache is not None else None
```

Watch the two enriched cases:
- `GuildMessageCreateEvent.get_member` (`message_events.py:221`) reads
  `self.message.author.id` — the author id is plain Struct data and survives.
- `GuildMessageUpdateEvent.get_member` (`message_events.py:405`) additionally checks the author is not
  UNDEFINED (partial update payload) before the cache hit — preserve that guard.

## 6. Step-by-step migration

1. **Delete the `app` surface** (§4): the 31 delegating properties, the 44 own `app` fields, the
   abstract `Event.app`, and the `ExceptionEvent.app` proxy — in the same change that strips entity
   `app`. Mind the `attr` alias in `auto_mod_events.py`.
2. **Delete the 42 helpers** per the §5 recipes; rewrite doc examples to the closed-over
   `bot.rest`/`bot.cache` (only `examples/voice_message/voice_message.py:90` reads `event.app`
   today; every other example already closes over `bot` — dossier 19 §3.3).
3. **Delete the 50 `app=self._app` injections** in `impl/event_factory.py`; the four lifetime-event
   factory methods collapse to `EventCls()` (field-less markers).
4. Freeze events (constraint c) and drop `@attrs_extensions.with_copy`/`SKIP_DEEP_COPY` — safe once
   the one `event.chunk_nonce` mutation (`event_manager.py:420`) is restructured first (dossier 19
   §1.3; gate item in the decisions log).
5. Catalog the surface change in `../../11-rollout/03-breaking-changes-and-changelog.md`: 42 methods
   plus the `app` attribute (44 fields + 33 properties) across the concrete events.

## 7. Affected files & symbols

| Path | Anchor | Change |
|---|---|---|
| `hikari/events/channel_events.py` | 129–709 | DELETE 12 helpers + delegating `app` props (274/311/342/562/758/793/830) + own `app` fields |
| `hikari/events/guild_events.py` | 87–694 | DELETE 10 helpers + delegating props (193/257/343/362/669/721) + own fields |
| `hikari/events/member_events.py` | 56, 73 | DELETE 1 helper + delegating prop |
| `hikari/events/message_events.py` | 89/267, 185–656 | DELETE 10 helpers + delegating props + own fields |
| `hikari/events/typing_events.py` | 71–225, 155 | DELETE 9 helpers + delegating prop + own fields |
| `hikari/events/*.py` | dossier 08 §5.1–§5.2 | DELETE the remaining delegating props / own-`app` fields (44 fields + 31 props total) |
| `hikari/events/base_events.py` | 83-86, 207-211 | DELETE abstract `Event.app` + `ExceptionEvent.app` proxy |
| `hikari/events/lifetime_events.py` | 44/67/84/109 | `app` was the only field — become field-less markers |
| `hikari/impl/event_factory.py` | 50 sites | DELETE the `app=self._app` injections |

## 8. Risks / gotchas

- **The 31 delegating properties are the single biggest event-side hazard** (dossier 08 §0.2) — they
  break silently (AttributeError at access time) as soon as any wrapped entity loses `.app`. Delete
  them in the same change that strips entity `app` (§4); do not leave them behind.
- **`InteractionCreateEvent.app → self.interaction.app` (`interaction_events.py:65`) is deleted with
  the other 31** — this does not depend on D10-interactions. Interaction *objects* keep their `app`
  under the recommendation, so `event.interaction.app` remains reachable if genuinely needed
  (dossier 19 §3.4).
- **`auto_mod_events.py` uses the `attr` alias, not `attrs`** (dossier 08 §2) — a find/replace gotcha
  during the field-deletion/freeze pass.
- **Cache-getter callers must preserve degradation to `None`/`{}`**, never raise (dossier 04 §8.6) —
  the replacement code in §5.2 keeps the "no cache → empty" semantics.
- **`ShardPayloadEvent.payload` / `MemberChunkEvent` as a `Sequence`** are structural oddities
  (dossier 08 §10.6) — orthogonal to helper removal; handled by the event pipeline cluster
  ([`../../12-appendices/04-event-pipeline-feasibility.md`](../../12-appendices/04-event-pipeline-feasibility.md)).
- The event-side `fetch_*`/`get_*` symmetry with entity helpers was a *policy* call, not forced by
  (a) (dossier 08 §6) — D10-events has now made it: removal.

## 9. Verification

1. `grep -rn "def app" hikari/events/` returns **0** — all 33 `app` members gone (1 abstract + 31
   delegating + 1 `ExceptionEvent` proxy) — and no `app: traits.RESTAware` field declaration remains
   (44 deleted; `grep -rn "return self\..*\.app" hikari/events/` is also empty).
2. `grep -rnE "self\.app\.(rest|cache)" hikari/events/` returns **0** (42 helpers deleted).
3. No event constructor accepts an `app` kwarg; `StartingEvent()` constructs with zero arguments.
4. `grep -n "app=self\._app" hikari/impl/event_factory.py` returns **0** (50 injections deleted).
5. Replacement call sites preserve cache degradation: with no cache in scope the §5.2 forms yield
   `None`/`{}`, never raise.

## 10. Open questions

- **D10-events: RESOLVED** — events are app-less; the 42 helpers are removed
  ([`../04-events-and-interactions-app-decision.md`](../04-events-and-interactions-app-decision.md),
  `../../00-overview/05-decisions-log.md`). **D10-interactions remains FLAGGED** — see
  [`06-interactions.md`](06-interactions.md).
- The former sub-decision (move event `fetch_*`/`get_*` helpers to `rest.*` for symmetry even if
  events kept `app`) is **moot** — the helpers are removed with D10-events.
- Assert-narrowing policy for the ex-`fetch_channel` call sites (callers lose the helper's
  `assert isinstance` narrowing) — `../../00-overview/05-decisions-log.md`.
