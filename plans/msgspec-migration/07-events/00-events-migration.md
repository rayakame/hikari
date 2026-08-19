# Events migration (event classes, `event_factory`, and the `app` decision applied)

Scope: the 20 `hikari/events/*.py` modules and the `EventFactoryImpl`
(`hikari/impl/event_factory.py`) that constructs them. This file states why events
stay `attrs`/frozen and are *not* JSON-decoded Structs, applies decision **D10**
(events keep `app` + helpers), and enumerates the exact `event_factory` changes forced
by wire entities becoming app-less. Interaction *models* are covered by
[`../06-model-modules/11-interactions.md`](../06-model-modules/11-interactions.md);
the interaction/event `app` policy is decided in
[`../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md`](../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md).

---

## 1. Objective

- Serve constraint (c): freeze the event/interaction classes and delete their
  `attrs_extensions` copy scaffolding, which is vestigial for events.
- Serve constraint (a) *indirectly*: wire entities lose `.app`, so the ~31 events that
  reach the client through `self.<entity>.app` must gain their own `app` field and be
  constructed with `app=self._app`.
- Serve constraint (b): flip the 5 loose `Enum | int` fields in this subtree to strict
  enums.
- Keep event ergonomics intact: `event.app.rest.*` remains the blessed way to reach the
  REST client after entities go app-less (see
  [`../09-rest-and-gateway/00-rest-client.md`](../09-rest-and-gateway/00-rest-client.md) §8).

---

## 2. Current state

### 2.1 Events are hand-constructed, never decoded

`EventFactoryImpl` (`event_factory.py:85`), `__slots__ = ("_app",)`, stores
`self._app = app` (`:90-91`). Every `deserialize_*_event` method:

1. builds the wrapped *entity* via `self._app.entity_factory.deserialize_<X>(payload)`
   (e.g. `:101`, `:114`), and
2. constructs the event `attrs` class, passing the entity plus `shard`, and — only for
   some events — `app=self._app`.

msgspec never sees an event class. The event managers never `deepcopy` an event and no
internal code reassigns an event field, so events are effectively immutable already
(dossier 08 §9).

The gateway path that reaches these methods: `shard._poll_events` reads
`payload[_D]` (a dict) and calls `event_manager.consume_raw_event(name, shard, data)`
(`shard.py:855/893`), whose `on_*` handlers (e.g. `event_manager.py:127/149`) forward the
dict as `payload` into `event_factory.deserialize_*_event(shard, payload)`. The event
factory is the single construction site.

### 2.2 `Event` root and `app` contract

- `Event` (`base_events.py:59-96`) is a pure ABC (`__slots__ = ()`, not `attrs`). Its
  `__init_subclass__` (`:67-81`) builds the `__dispatches`/`__bitmask` dispatch registry
  used by the event manager — orthogonal to attrs/msgspec, must be preserved verbatim.
- **`app` is an abstract property** (`base_events.py:83-86`, `@property @abc.abstractmethod`
  returning `traits.RESTAware`). Every concrete event supplies it, today two ways:
  - **own field** — `app: traits.RESTAware = attrs.field(metadata={SKIP_DEEP_COPY: True})`
    (44 declarations across 13 files, dossier 08 §5.1); or
  - **delegated** — `@property def app(self): return self.<entity>.app`
    (32 properties, dossier 08 §5.2).

### 2.3 The 31 delegating `app` properties that break

Each reads a wrapped **entity's** `.app` and fails once that entity is an app-less Struct
(constraint a). Full list (dossier 08 §5.2):

```
auto_mod_events.py:74/93/112     -> self.rule.app
channel_events.py:274/311/342    -> self.channel.app
channel_events.py:562            -> self.invite.app
channel_events.py:758/793/830    -> self.thread.app
guild_events.py:193/257/343      -> self.guild.app
guild_events.py:362              -> self.user.app
guild_events.py:669              -> self.presence.app
guild_events.py:721              -> self.entry.app
interaction_events.py:65         -> self.interaction.app   (exception: under the recommended D10 Option 2 interactions KEEP app, so this one does NOT break; it breaks only under Option 1)
member_events.py:56              -> self.user.app
message_events.py:89/267         -> self.message.app
reaction_events.py:299           -> self.member.app
role_events.py:78/115            -> self.role.app
scheduled_events.py:80/105/130   -> self.event.app
shard_events.py:166              -> self.my_user.app
stage_events.py:52               -> self.stage_instance.app
typing_events.py:155             -> self.member.app
user_events.py:62                -> self.user.app
voice_events.py:91               -> self.state.app
```

`base_events.py:211` (`ExceptionEvent.app -> self.failed_event.app`) delegates to another
**event** (which still has `app`) — safe, keep as-is.

### 2.4 Construction sites currently missing `app`

Delegating events are built without `app=` today, e.g. `event_factory.py`:
`GuildChannelCreateEvent(shard=shard, channel=channel)` (`:118`),
`GuildMessageCreateEvent(shard=shard, message=message)` (`:709/:711`),
`VoiceStateUpdateEvent(shard=shard, state=state, old_state=old_state)` (`:1054`),
interaction-create events (`:543-552`), plus role/scheduled/stage/typing/reaction-add/
member/guild-available-join-update/presence/audit-log/auto-mod-rule/own-user/shard-ready
sites (dossier 08 §4). Own-`app` events already pass it, e.g.
`ApplicationCommandPermissionsUpdateEvent(app=self._app, …)` (`:102`),
`GuildLeaveEvent(app=self._app, …)` (`:393`).

### 2.5 Event-side helper methods (D10: keep)

Events themselves define `fetch_*`/`get_*`/`trigger_*` helpers using `self.app.rest.*`
(24 sites) and `self.app.cache.*` (19 sites) — dossier 08 §6. These are the event-side
analogue of the entity helpers removed by constraint (a). Because events legitimately hold
`app` (runtime object, not decoded), D10 keeps them.

### 2.6 Loose `Enum | int` fields in this subtree

Only 5 (dossier 08 §8):

```
events/auto_mod_events.py:136                 rule_trigger_type: int | AutoModTriggerType | None
interactions/base_interactions.py:406         type: InteractionType | int
interactions/command_interactions.py:85       type: commands.OptionType | int
interactions/command_interactions.py:136      command_type: commands.CommandType | int
interactions/component_interactions.py:90     component_type: components_.ComponentType | int
```

### 2.7 `attrs` machinery to strip

`@attrs_extensions.with_copy` + `SKIP_DEEP_COPY` metadata appear 216× across event files
(dossier 08 §9). `auto_mod_events.py` uses the `attr` alias (not `attrs`) — a find/replace
gotcha (dossier 08 §2).

---

## 3. Target design

### 3.1 Events stay `attrs`, become frozen — NOT msgspec Structs

Events wrap runtime, non-serializable references (`app`, `shard`, and `ExceptionEvent`
holds a live `Exception` + coroutine callback). msgspec Structs are a poor fit and buy
nothing here (events are never decoded). Recommendation: keep events as **frozen `attrs`**
(`@attrs.define(frozen=True, kw_only=True, weakref_slot=False)`) or plain frozen
dataclasses; an `attrs` field can freely hold a frozen msgspec entity Struct.

```python
# events/message_events.py — target shape
@base_events.requires_intents(intents.Intents.GUILD_MESSAGES)
@attrs.define(frozen=True, kw_only=True, weakref_slot=False)
class GuildMessageCreateEvent(GuildMessageEvent):
    app: traits.RESTAware = attrs.field(repr=False)     # now an OWN field
    shard: gateway_shard.GatewayShard = attrs.field()
    message: messages.Message = attrs.field()           # a frozen msgspec Struct, app-less
    # channel_id/author/guild_id remain pure-data forwards to message.* (survive)
```

Notes:
- Drop `@attrs_extensions.with_copy` and all `SKIP_DEEP_COPY` metadata from events — the
  copy machinery is vestigial (dossier 08 §9) and `attrs_extensions.py` is deleted whole
  (see [`../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md`](../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md)).
- Preserve `Event.__init_subclass__` bitmask/dispatch registry and the
  `requires_intents`/`no_recursive_throw` decorators unchanged.

### 3.2 Every delegating event gains an own `app` field

Convert the 31 delegating `app` properties (§2.3) to real fields, mirroring the ~44 events
that already store `app`:

```python
# was:  @property
#       def app(self) -> traits.RESTAware: return self.channel.app
# now:  app: traits.RESTAware = attrs.field(repr=False)
```

`Event.app` stays an abstract property on the base; concrete events satisfy it with the
field (attrs generates the attribute; the abstract property is fulfilled). Keep
`ExceptionEvent.app -> self.failed_event.app` as a delegating property (safe).

### 3.3 `event_factory` threads `app=self._app` everywhere

Every previously-appless construction site adds `app=self._app`. The wrapped-entity
`deserialize_*` calls are unchanged — event_factory keeps owning entity construction and
becomes the "hydrate runtime context (`app`/`shard`) + cache-lookup `old_*`" layer even if
entities later gain a declarative decode path.

### 3.4 Strict enums

Flip the 5 fields in §2.6 to the bare strict enum type. The enums stay hikari's fast custom
`enums.Enum`/`Flag` — adopt PR hikari-py/hikari#2770, which makes the shared `_EnumMeta.__call__` mint an
`is_unknown` pseudo-member on unrecognised values (decision D2). Those pseudo-members are produced by the
shared `dec_hook` (`t(obj)`), so no `| int` widening is needed. `InteractionType`/`ResponseType` are
**kept** as custom enums (not ported to stdlib) with the rest (see
[`../02-enums/00-strategy-and-forward-compat.md`](../02-enums/00-strategy-and-forward-compat.md)).
The `MessageResponseTypesT`/`DeferredResponseTypesT`/… `Literal` unions that mix enum
members with bare ints (`base_interactions.py:238/258`, etc.) should drop the bare-int
alternatives when enums go strict.

### 3.5 Event-side helpers: D10 keeps them

Because events keep `app`, the 24 `self.app.rest.*` + 19 `self.app.cache.*` event helpers
(§2.5) stay. This is the recommended (option-2) end-state; the alternative (symmetry with
entity-helper removal) is presented in the decisions log — flag, do not silently pick it.

---

## 4. Step-by-step migration

1. **Normalize `auto_mod_events.py`** to the `attrs`/`attrs.field` alias used by every
   other event module (dossier 08 §2) to make the subsequent passes uniform.
2. **Add `app` fields.** For each of the 31 delegating events (§2.3, excluding
   `ExceptionEvent`), replace the `@property def app` with
   `app: traits.RESTAware = attrs.field(repr=False)`.
3. **Thread `app=self._app`** into every appless `event_factory` construction site
   (dossier 08 §4/§10.2 checklist). Grep guard: after this pass, every
   `return <SomeEvent>(` in `event_factory.py` that is a concrete event either passes
   `app=self._app` or is an event whose `app` genuinely delegates to another event.
4. **Freeze events.** Change `@attrs.define(...)` to add `frozen=True`; drop
   `@attrs_extensions.with_copy`; delete `SKIP_DEEP_COPY` metadata from `app`/`shard`
   fields. Confirm no event field is reassigned anywhere (grep `event.<field> = `).
5. **Strict enums.** Flip the 5 loose fields (§2.6); prune bare-int arms from the
   `*ResponseTypesT` `Literal` unions.
6. **Preserve dispatch machinery.** Re-run the event-manager routing tests to confirm
   `__init_subclass__` bitmasks and `requires_intents` still resolve after the base/config
   changes (msgspec is not involved; this guards the frozen/attrs-config change).
7. **Special-case carriers:** keep `ExceptionEvent` non-frozen-if-needed or frozen holding
   the `Exception`/callback as plain fields; keep `ShardPayloadEvent.payload` /
   `ShardRateLimitedEvent.meta` as raw `Mapping[str, Any]`; keep `MemberChunkEvent` as the
   `Sequence[Member]`-implementing attrs class (§6).

---

## 5. Affected files & symbols

| File | Anchor(s) | Change |
|---|---|---|
| `hikari/events/base_events.py` | `:59-96`, `:83-86`, `:184-240` | Keep `Event` ABC + abstract `app` + dispatch registry; freeze `ExceptionEvent`; keep its delegating `app` (`:211`) |
| `hikari/events/*.py` (20 modules) | dossier 08 §5.2 list | 31 delegating `app` properties → own fields; add `frozen=True`; drop `with_copy`/`SKIP_DEEP_COPY` |
| `hikari/events/auto_mod_events.py` | `:36`, `:136` | `attr`→`attrs` alias; strict `AutoModTriggerType` |
| `hikari/impl/event_factory.py` | appless sites in dossier 08 §4 (`:118`, `:709/:711`, `:1054`, `:543-552`, …) | add `app=self._app` |
| `hikari/interactions/base_interactions.py` | `:74`, `:93`, `:406` | strict `InteractionType`; adopt #2770 strict custom enums |
| `hikari/interactions/command_interactions.py` | `:85`, `:136` | strict `OptionType`/`CommandType` |
| `hikari/interactions/component_interactions.py` | `:90` | strict `ComponentType` |
| `hikari/internal/attrs_extensions.py` | whole file | deleted (see 04-frozen-and-cache) |

Interaction *model* field/`app`/helper changes are owned by
[`../06-model-modules/11-interactions.md`](../06-model-modules/11-interactions.md) and
[`../03-app-removal-and-helpers/02-helper-method-inventory/06-interactions.md`](../03-app-removal-and-helpers/02-helper-method-inventory/06-interactions.md);
this file only covers the interaction-create *events* and the enum flips.

---

## 6. Risks / gotchas

- **The 31-property → field conversion is the single hard blocker.** Miss one and that
  event's `app` raises `AttributeError` at runtime the first time it wraps an app-less
  entity. The step-3 grep guard is mandatory.
- **Interaction-create events.** `InteractionCreateEvent.app -> self.interaction.app`.
  Under the **recommended D10 Option 2** interactions KEEP `app`, so this delegation still
  works and does not break; the plan still converts it to a stored `app` field for uniformity
  with the other 30 events (and to decouple the event from the interaction's app handling).
  Only under **Option 1** (interactions also app-less) would this delegation break, in which
  case the five interaction-create events (`interaction_events.py:52/70/79/88/97`) must take
  `app` explicitly and `event_factory` must pass it at the `:543-552` sites — which it already
  does for events regardless.
- **`ExceptionEvent`** carries a live `Exception` + coroutine `failed_callback` and calls
  it in `retry()` — never a msgspec Struct; freezing must not interfere with the stored
  callback.
- **`MemberChunkEvent`** implements `typing.Sequence[guilds.Member]` with
  `__getitem__/__iter__/__len__` (`shard_events.py:216/259-275`) — keep it attrs; a
  Struct-as-Sequence is awkward.
- **`ShardPayloadEvent.payload` / `ShardRateLimitedEvent.meta`** are untyped
  `Mapping[str, Any]` (raw JSON) — fine for attrs, keep as-is.
- **`attr` vs `attrs` alias** in `auto_mod_events.py` — a blind find/replace across events
  will miss it; normalize first (step 1).
- **Semantic enum change** — after strict enums, an unknown `AutoModTriggerType`/
  `InteractionType`/… decodes to an enum pseudo-member, not a bare `int`
  (`type(x) is int` becomes False); document in the changelog
  ([`../11-rollout/03-breaking-changes-and-changelog.md`](../11-rollout/03-breaking-changes-and-changelog.md)).

---

## 7. Verification

- **Grep guard (step 3):** no concrete event is constructed without `app=` except those
  whose `app` delegates to another event.
- **Property-removal check:** `grep -n "def app" hikari/events/` returns only
  `base_events.py` (abstract) + `ExceptionEvent` (delegating to `failed_event`); all others
  are fields.
- **Frozen check:** attempting `event.message = other` raises
  `attrs.exceptions.FrozenInstanceError`; `copy.deepcopy(event)` still returns an equal
  event without invoking the deleted `with_copy` codegen.
- **Dispatch regression:** existing `tests/hikari/impl/test_event_manager*.py` and
  `test_base_events` pass unchanged (bitmask/intents preserved).
- **End-to-end:** feed a recorded `MESSAGE_CREATE`, `GUILD_CREATE`, `INTERACTION_CREATE`
  gateway payload through `event_factory`; assert `event.app is bot` and
  `event.app.rest` is reachable, and that the wrapped entity has no `.app` attribute.
- **Enum decode:** a payload with an unknown `AutoModTriggerType` int yields an enum
  pseudo-member equal to that int (see [`../02-enums/00-strategy-and-forward-compat.md`](../02-enums/00-strategy-and-forward-compat.md)).

---

## 8. Open questions / decisions

Cross-linked to [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md):

1. **D10 — events keep `app` + helpers (recommended, option 2).** Confirm events retain
   the 24 `rest.*` + 19 `cache.*` helper methods rather than being stripped for symmetry
   with the entity-helper removal. Full both-options writeup:
   [`../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md`](../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md).
2. **Frozen `attrs` vs plain frozen dataclass** for events — either satisfies (c);
   `attrs` is lower-churn (existing decorators/validators). Maintainer call.
3. **`Literal` response-type unions** — drop the bare-int arms when enums go strict, or
   keep them for input lenience on the response-builder call sites? (Ties to the
   method-parameter-union policy in [`../02-enums/03-strict-enum-field-inventory.md`](../02-enums/03-strict-enum-field-inventory.md).)
