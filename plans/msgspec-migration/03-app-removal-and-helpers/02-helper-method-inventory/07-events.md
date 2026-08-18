# Helper Inventory — `hikari/events/*.py` (D10-FLAGGED)

Complete inventory of the **42 event helper methods** that reference `self.app` (24 `rest.*` + 18
`cache.*` call-site lines, dossier 08 §6; per dossier 04 §0 the cache lines split
message 10 / typing 3 / guild 2 / channel 2 / member 1). Only 5 of the 20 event modules define such
helpers. This file enumerates every one and its replacement, but whether events **keep `app`** (they
are hand-constructed, not JSON-decoded) or **also go app-less** is FLAGGED (D10) and decided in
[`../04-events-and-interactions-app-decision.md`](../04-events-and-interactions-app-decision.md) and
`../../00-overview/05-decisions-log.md`.

Sources: dossier 04 §5, dossier 08 §5–§6. See [`00-README.md`](00-README.md) for the shared legend.

## 1. Objective

Map every event `self.app.rest.*`/`self.app.cache.*` helper to its replacement, and surface the
event-specific structural fact that dominates the decision: **31 events do not store `app` at all —
they compute it via a `@property` returning `self.<wrapped_entity>.app`**, which breaks the instant the
wrapped entity is an app-less msgspec Struct. Serves constraint (a) / D9, with the event policy
deferred to D10.

## 2. Why events are different from wire entities (dossier 08 §0.1, §10.1)

Events are **hand-constructed `attrs` classes, never JSON-decoded.** `EventFactoryImpl`
(`impl/event_factory.py:85`) deserializes the wrapped entity via
`self._app.entity_factory.deserialize_*`, then constructs the event, passing the entity plus `shard`
and (for some events) `app=self._app`. msgspec never sees an event class. So making entities msgspec
does **not** force events to msgspec, and events may legitimately keep a live `app`/`shard` (they are
runtime objects, not decoded data). Two consequences:

1. The event `fetch_*`/`get_*` helpers below are **not** forced away by constraint (a) — they can stay
   if events keep `app` (D10 Option 2). This is a *policy* choice about API symmetry, not a technical
   requirement (dossier 08 §6, §10.1).
2. But the **31 `app`-delegating `@property` events must change regardless** — see §4.

## 3. Current state — the full event-helper inventory (dossier 04 §5)

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
`app` field/property but define **no** `self.app.*` helpers (dossier 04 §5).

## 4. The hard blocker regardless of D10 — 31 `app`-delegating properties (dossier 08 §5.2, §10.2)

Independent of whether the helpers above stay or go, **55% of concrete events do not store `app`** —
they expose it as `@property` returning `self.<wrapped_entity>.app` (32 sites total; 31 read an
*entity's* `.app`, 1 reads another *event's*). Examples:

```
message_events.py:89/267 -> self.message.app     channel_events.py:274/311/342 -> self.channel.app
guild_events.py:193/257/343 -> self.guild.app     interaction_events.py:65 -> self.interaction.app
reaction_events.py:299 -> self.member.app         typing_events.py:155 -> self.member.app
role_events.py:78/115 -> self.role.app            voice_events.py:91 -> self.state.app
... (full list dossier 08 §5.2)
```

When the wrapped entity becomes an app-less Struct, **each of these 31 properties fails** — the event
has no other route to the client. The 1 safe exception is `ExceptionEvent.app → self.failed_event.app`
(`base_events.py:211`), which delegates to another *event* (still has `app`), and
`FailedEvent.app` (dossier 04 §8.3).

**Required fix (both D10 options):** every delegating event gets its **own** `app: traits.RESTAware`
field (mirroring the 44 events that already do — dossier 08 §5.1), and `event_factory` must pass
`app=self._app` at the ~30 currently-appless construction sites (dossier 08 §10.2: message
`event_factory.py:709/711`, channel, voice `:1054`, role, scheduled, stage, typing, reaction-add,
member, guild-available/join/update, presence, audit-log, auto-mod-rule, own-user, shard-ready,
interaction-create `:547-552`). This is mechanical but touches ~30 event-factory methods — provide a
checklist keyed to dossier 08 §5.2.

> Under **Option 1** (events also app-less), the delegating properties are removed entirely and the
> helpers below go with them. Under **Option 2** (events keep `app`), the delegating properties are
> replaced by own-`app` fields and the helpers stay. Either way the 31 properties cannot survive
> unchanged.

## 5. Replacements (if D10 chooses app-less events / for any caller that prefers `rest.*`)

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

1. Resolve D10 in [`../04-events-and-interactions-app-decision.md`](../04-events-and-interactions-app-decision.md)
   **before** touching event code.
2. **Regardless of D10 — the mandatory fix:** convert the 31 `app`-delegating properties (§4) to
   own-`app` fields and thread `app=self._app` through the ~30 appless `event_factory` construction
   sites (dossier 08 §5.2 checklist). `ExceptionEvent`/`FailedEvent` stay as-is (delegate to an event).
3. **Option 1 path:** remove the 42 helpers (§5); rewrite doc examples to `rest.*`/`cache.*`; drop the
   `app` field once callers migrate.
4. **Option 2 path:** keep the 42 helpers on own-`app` events; they now work uniformly because every
   event carries `app`.
5. Freeze events (constraint c) and drop `@attrs_extensions.with_copy`/`SKIP_DEEP_COPY` — safe, events
   are never mutated or deep-copied (dossier 08 §9, §10.5).
6. Catalog the surface change in `../../11-rollout/03-breaking-changes-and-changelog.md` (magnitude is
   option-dependent).

## 7. Affected files & symbols

| Path | Anchor | Change |
|---|---|---|
| `hikari/events/channel_events.py` | 129–709 | 12 helpers + delegating `app` props (274/311/342/562/758/793/830) |
| `hikari/events/guild_events.py` | 87–694 | 10 helpers + delegating props (193/257/343/362/669/721) |
| `hikari/events/member_events.py` | 56, 73 | 1 helper + delegating prop |
| `hikari/events/message_events.py` | 89/267, 185–656 | 10 helpers + delegating props |
| `hikari/events/typing_events.py` | 71–225, 155 | 9 helpers + delegating prop |
| `hikari/events/*.py` | dossier 08 §5.2 | remaining 24 delegating props / own-`app` fields |
| `hikari/impl/event_factory.py` | ~30 sites | thread `app=self._app` into appless constructions |

## 8. Risks / gotchas

- **The 31 delegating properties are the single biggest event-side hazard** (dossier 08 §0.2) — they
  break silently as soon as any wrapped entity loses `.app`, even if no helper is touched. Fix them
  first (§4).
- **`InteractionCreateEvent.app → self.interaction.app` breaks** because interactions lose `app` under
  (a) (dossier 08 §10.2) — the interaction-create events must take `app` explicitly.
- **`auto_mod_events.py` uses the `attr` alias, not `attrs`** (dossier 08 §2) — a find/replace gotcha
  during the freeze/own-`app` pass.
- **Cache getters must degrade to `None`/`{}`**, never raise (dossier 04 §8.6).
- **`ShardPayloadEvent.payload` / `MemberChunkEvent` as a `Sequence`** are structural oddities
  (dossier 08 §10.6) — orthogonal to helper removal but relevant if events are ever moved off `attrs`.
- The event-side `fetch_*`/`get_*` symmetry with entity helpers is a *policy* call, not forced by (a)
  (dossier 08 §6) — the plan must state it explicitly, which is exactly what D10 does.

## 9. Verification

1. After the §4 fix, every concrete event exposes `app` from its own field; `grep -n "return self\..*\.app"`
   over `hikari/events/` returns only `base_events.py:211` (`ExceptionEvent`).
2. Constructing any event without a cache and calling a `get_*` helper returns `None`/`{}`.
3. If Option 1: `grep -n "self\.app\.\(rest\|cache\)" hikari/events/` → 0. If Option 2: the helpers
   remain and resolve against the injected `app`.
4. `event_factory` passes `app=self._app` at all ~30 previously-appless sites (test each event has a
   non-None `app`).

## 10. Open questions

- **D10 (FLAGGED):** events app-less (Option 1) vs. events keep `app`+helpers (Option 2, recommended
  in CONVENTIONS §8) — [`../04-events-and-interactions-app-decision.md`](../04-events-and-interactions-app-decision.md),
  `../../00-overview/05-decisions-log.md`.
- Whether the event-side `fetch_*`/`get_*` helpers move to `rest.*` for symmetry even under Option 2
  (dossier 08 §6) — decision-log item.
- Assert-narrowing policy for event `fetch_channel` variants — `../../00-overview/05-decisions-log.md`.
