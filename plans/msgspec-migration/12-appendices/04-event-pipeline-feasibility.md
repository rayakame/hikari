# Event-pipeline feasibility under msgspec (in-plan evidence)

The plan of record replaces **most — not all — of `hikari/impl/event_factory.py`** with a name-keyed
`dict[str, msgspec.json.Decoder]` registry fed by a `msgspec.Raw` gateway envelope, plus a thin
residual hydration layer (decision **D12**); events lose `app` (**D10-events**) and keep `shard` on
the event object via two verified field patterns (**D13**). This appendix is the plan's own,
self-contained evidence for those decisions — dossiers 17 (the 77-method classification,
source-verified), 18 (the decode probe, EMPIRICAL against msgspec 0.21.1 / CPython 3.11), 19 (the
manager/cache interplay, source-verified), and 20 (the shard-typing probe, EMPIRICAL) — so a reviewer
need not reach the out-of-tree research notes: the verdict, the classification, the empirical
results, the shard recipe, the consumer-side facts, and the considered-and-not-chosen alternative.

It underpins D10-events, D12, and D13
([`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md)) and is referenced from
[`../07-events/00-events-migration.md`](../07-events/00-events-migration.md),
[`../09-rest-and-gateway/01-gateway-shard-and-interaction-server.md`](../09-rest-and-gateway/01-gateway-shard-and-interaction-server.md),
and [`../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md`](../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md).
The probe environment reused the plan's own building blocks: the real PR hikari-py/hikari#2770 enums
(appendix [`02-custom-enum-feasibility.md`](02-custom-enum-feasibility.md)), `Snowflake` via the
global `dec_hook`, and the `UniqueStruct` base exactly per appendix
[`03-base-struct-identity-verified.md`](03-base-struct-identity-verified.md).

---

## 1. Verdict — MOST of the factory is replaceable (empirically proven)

- **45 of 77** `deserialize_*` methods become one-or-two-liners outright, and **~73%** (≈56/77) end
  trivial (≤6 lines). The 1216-line file shrinks to an estimated **400–550 lines** — roughly
  **55–65% of the code is deleted**.
- Every tested decode pattern **PASSES** on msgspec 0.21.1: two-step wrapper events (P1),
  direct-decode flat events (P2), the name-keyed Decoder registry over a `msgspec.Raw` envelope,
  cache-fed `old_*` injection, and the guild-vs-DM post-decode split (§3).
- What survives is a **thin residual hydration layer**, by design: `shard`/`old_*` attachment,
  guild-vs-DM class dispatch, sibling-context threading (`guild_id` → Member/Role/emoji),
  GUILD_CREATE laziness, and the synthetic events.
- The consumer side imposes **no blocker** (§5): the cache is entity-typed end-to-end, every
  raw-dict read in the handlers is covered by decoded fields, and dispatch is already name-keyed
  with lazy gating that `msgspec.Raw` capture strictly improves. One pre-fix is mandatory: the
  `chunk_nonce` post-construction mutation (gate task **T-CN**, §8).

---

## 2. The 77-method classification (dossier 17, source-verified)

Baseline counts, grep-verified: `hikari/impl/event_factory.py` = **1216 lines**, **77**
`deserialize_*` methods; **73** take a live `shard`, **17** take cache-fed `old_*` params, **50**
inject `app=self._app` — all 50 vanish under D10-events.

| Cat | Definition | Methods | % of 77 | ~lines today | % of file |
|---|---|---|---|---|---|
| **A** | Pure entity wrapper → one-liner `EventCls(shard=shard, entity=DECODER.decode(d))` | **27** | 35% | ~209 | ~17% |
| **B** | Flat event: the event struct ITSELF decodes (renames via `msgspec.field(name=...)`); `shard`/`old_*` attached after | **18** | 23% | ~214 | ~18% |
| **C** | Residual reshaping/logic: 5 split-only, 3 split+emoji-flatten, 3 sibling `guild_id` threading, 6 heavy, 4 misc-light | **21** | 27% | ~473 (incl. shared helper) | ~39% |
| **D** | Synthetic/special: 4 lifetime, 3 no-payload shard events, `shard_payload` passthrough, ready, member_chunk, interaction_create (ordinary wrapper — decode/transform the app-less interaction, pick the event class; no app anywhere) | **11** | 14% | ~86 | ~7% |
| — | Module frame (header, `_INTERACTION_EVENTS_MAP`, class frame, banners) | — | — | ~234 | ~19% |

**Guild-vs-DM split census.** Exactly **9** methods produce a Guild*/DM* class pair, on **three
different discriminators**: `"guild_id" in payload` (pins, typing, message_delete, and the 3
reaction-removes), post-decode `message.guild_id is None` (message_create/update), and
`"member" in payload` (reaction_add, `event_factory.py:789`) — the last is a migration hazard: the
discriminator must be carried into the dispatch table **verbatim** (gate note N-EV, §8). Each split
is a ≤4-line post-decode dispatch: decode once, pick the class, attach shard. The GUILD_CREATE /
GUILD_DELETE availability variants dispatch in `event_manager.py:278-289`/`:503-504`, outside the
factory, and stay there.

**The hard residual cores** (what genuinely cannot become a declarative decode):

- **GUILD_CREATE family**: the lazy `_GatewayGuildDefinition` (`entity_factory.py:261`) parses
  sub-entity payloads only on accessor call, and `shard.get_user_id()` is consumed as **decode
  input** to fill the bot's own `ThreadMember.user_id` (`entity_factory.py:427`/`1543-1556`) — a
  context-free `Decoder` cannot express either; this family is a migration unit of its own (§5, SD5).
- **presence_update**: the hand-built UNDEFINED-partial user (`event_factory.py:503-527`).
- **thread_list_sync / thread_members_update / member_chunk**: list→dict joins keyed by ids.
- The shared **reaction-emoji flatten** (`_split_reaction_emoji`, `event_factory.py:818-824`).
- **unix-SECONDS timestamps** (typing `:312`, channel_info `:993`, voice start `:1071`) — msgspec's
  native datetime decode is RFC3339-string-only, so these need a marker type through the dec_hook.
- **hex-string `burst_colors`** (`:787`) — the Color dec_hook must accept hex strings too.
- **auto_mod falsy coercions** (`:1210-1215`).

---

## 3. Empirical decode results (dossier 18, msgspec 0.21.1)

The probe ran against the real hikari code from the PR #2770 head checkout (`Snowflake`, `Unique`,
`MessageType`, `MessageFlag`), the `UniqueStruct` base per appendix 03, and the global `dec_hook`
per appendix 02; real-code anchors were `event_factory.py:307-324` (typing start), `:703-711`
(message create), and `:713-726` (message update, cache-fed `old_message`).

| Pattern | Shape | Result |
|---|---|---|
| **P1** two-step | Decode the frozen entity, hand-construct the frozen event wrapping it (`shard` a required, never-decoded field) | **PASS** — enum decode returns the **canonical member by identity**; `rename=`/`msgspec.field(name=...)` works; unknown wire fields skipped; event immutable + hashable |
| **P2** one-step | Decode the flat EVENT struct directly; inject `shard` after | **PASS** — unix-seconds epoch via marker type + dec_hook; runtime field defaulted |
| Registry + Raw | Decode the envelope ONCE (`op`/`t`/`s`/`d` with `d: msgspec.Raw`), dispatch `d` through `dict[str, msgspec.json.Decoder]` | **PASS** — decoders are singletons, hook bound once at construction; unknown `t` is an ordinary dict miss (unknown-event policy stays pure Python) |
| `old_*` | Cache-fed, never decoded: constructor kwarg (P1) or `structs.replace` (P2) | **PASS** both ways — the exact cached instance rides through (identity preserved) |
| Guild/DM split | Decode once, 3-line post-decode branch, wrap | **PASS** |
| `forbid_unknown_fields` | — | **Verified BREAKING** on Discord's extra fields — registry decoders must keep the default skip-unknown |

**Injection on frozen structs**: `msgspec.structs.force_setattr` costs **78 ns/op** vs
`msgspec.structs.replace` at **132 ns/op**. Recommendation: `force_setattr` in the hot dispatch path
— injection happens in the single-owner decode→dispatch window, before the event is published,
hashed, or shared; never after dispatch (frozen is a user-visible contract). `replace` is the
pure-functional alternative anywhere the original may already be visible.

**Microbenchmark** (informal; one message-like payload, 11 fields incl. 6 snowflakes + 2 enums + an
ISO timestamp):

| Path | µs/op |
|---|---|
| A — stdlib `json.loads` → dict → hand-built attrs | 7.66 |
| B — msgspec → dict → hand-built attrs | 4.03 |
| C — msgspec typed decode + dec_hook | **3.20** |

Speedup **C vs A: ~2.4×**, C vs B: ~1.3×. Caveat, stated honestly: the probe venv had no
orjson/ciso8601, so paths A/B used hikari's fallback parsers (what hikari runs without the
`speedups` extra); with orjson+ciso8601 the decode/parse halves shrink, but the per-field Python
construction cost (`Snowflake()`/enum calls, dict lookups, attrs `__init__`) remains.
Characterization only, not a gate — the direction is that the typed path is not paying for its
convenience; it is faster.

**Gotcha — Decoder construction is LAZY** in 0.21.1. `msgspec.json.Decoder(X)` builds for every
tested annotation of a runtime field; errors surface only at decode time, and only if the field is
actually involved. Two consequences:

1. Annotate `shard` as the **REAL runtime class** — never `typing.Any` (silently accepts raw JSON
   into the field on a wire-name collision) and never `object` (0.21.1 routes `object`-typed fields
   into the registered **global** dec_hook with `t=object`). With the real-class annotation, a
   colliding wire key fails **loud** (`ValidationError: Expected 'GatewayShard', got 'dict'`).
2. Laziness cuts both ways: a typo'd/undecodable field type does NOT fail at import or
   registry-build time — it fails on the first decode of a payload containing that field. Hence the
   CI requirement: a registry **smoke test** decoding one fixture per event name (gate note N-EV, §8).

---

## 4. The shard-field typing recipe (dossier 20, EMPIRICAL)

`shard` stays on the event object (D13) with **no `Optional` leaking into the public API**:

- **P1 — hand-constructed events** (wrappers, splits, `old_*` events — the majority): a plain
  required field, `shard: GatewayShard`. Constructing without it raises
  `TypeError: Missing required argument 'shard'`; these structs never meet a Decoder.
- **P2 — direct-decode flat events**: defaulted **storage** field + non-optional **property**:

  ```python
  class GuildTypingEvent(EventStruct, frozen=True, kw_only=True):
      channel_id: Snowflake
      guild_id: Snowflake
      _shard: GatewayShard | None = msgspec.field(default=None, name="__hikari_runtime_shard__")

      @property
      def shard(self) -> GatewayShard:      # public API: NON-optional
          assert self._shard is not None
          return self._shard
  ```

  Verified behaviors: decodes with `_shard=None`; `msgspec.structs.force_setattr(ev, "_shard",
  shard)` injects pre-dispatch on the frozen struct (~78 ns; `structs.replace` at ~132 ns is the
  copy-based alternative); the property returns the non-optional type; the struct stays frozen;
  unknown wire keys are skipped.

- **The `name=` rename is load-bearing.** Verified with a `{"_shard": {...}}` key planted in the
  payload: WITHOUT the rename, that wire key routes the raw JSON into the global dec_hook with
  `t=GatewayShard` and raises (a loud `NotImplementedError` from the hook — not silent, but an
  avoidable failure). WITH `msgspec.field(name="__hikari_runtime_shard__")`, the same `"_shard"`
  wire key is just an unknown key and is skipped harmlessly.
- The storage+property form matches the **existing** abstract `ShardEvent.shard` property
  (`shard_events.py:69`) exactly — concrete events merely change how they satisfy it.
- Alternatives that work but are weaker: a public `shard: GatewayShard | None = None` field with
  user-side narrowing (Optional leaks into public typing), or a `.pyi` stub declaring the field
  non-optional (hikari has stub-masquerade precedent in `enums.pyi`/`undefined.pyi`).

---

## 5. Manager and cache interplay (dossier 19, source-verified)

- **Decode-once-share-everywhere works.** `impl/cache.py` contains **zero** raw-payload reads —
  every `set_*`/`update_*` takes an entity (`set_thread` cache.py:726, `set_guild_channel` :855,
  `set_invite` :1040, `set_member` :1249, `set_presence` :1413, `set_role` :1534, `set_message`
  :1943). msgspec's silent unknown-key drop is invisible to the cache by construction; the same
  decoded entity object can go into the cache AND the event, safely, once structs freeze.
- **Handlers read the raw dict in exactly 19 places, all covered by decoded fields** — pre-decode
  ID extraction for `old_*` cache lookups (e.g. `on_channel_update` event_manager.py:161,
  `on_voice_state_update` :823-824), event-class branch discriminators (`unavailable`,
  `newly_created`, `guild_id` presence), and `payload.get("large")` for member chunking (:406). The
  migration inverts the order — decode first, then do the `old_*` lookup with decoded fields — and
  the reordering is semantics-preserving (dispatch always happens after cache ops today).
- **Dispatch is already name-keyed with lazy gating.** `EventManagerBase.__init__` builds
  `_consumers` from the `on_*` methods (`event_manager_base.py:339-348`); `consume_raw_event`
  (`:404-420`) short-circuits on `is_enabled` **before any deserialization**. Capturing `"d"` as
  `msgspec.Raw` in `shard._poll_events` (`shard.py:844-895`; the envelope is parsed at `:200`) is a
  **strict win**: today the full `"d"` dict is materialized even when the consumer is disabled and
  discarded; with Raw, the disabled path is near-free — one skeleton parse plus at most one typed
  parse, never two full parses. `on_guild_create`/`on_guild_update` are deliberately NOT
  `filtered()` (always-called, `event_manager_base.py:348`) — the registry must preserve that mode.
- **Public breaks from the Raw envelope** (recorded in D12): the `consume_raw_event` payload type
  (`api/event_manager.py:168`), `ShardPayloadEvent.payload` (`shard_events.py:92`), the injectable
  `loads=`/`dumps=` params (`shard.py:561-562`, `gateway_bot.py:331-332`), and the `EventFactory`
  ABC (77 abstract methods) reshaped.
- **BUG/BLOCKER for frozen events**: `event_manager.py:420` mutates a constructed event —
  `event.chunk_nonce = nonce` (fields declared at `guild_events.py:180/244`). This is the **only**
  event mutation anywhere in hikari; it must be restructured (hoist the chunk-eligibility check,
  compute the nonce pre-construction, pass `chunk_nonce=` to the constructor) before events freeze
  — gate task **T-CN** (§8).
- **GUILD_CREATE laziness** (sub-decision **SD5**): today there are two decode paths for the same
  payload — with a listener, the factory builds the event; cache-only, the lazy
  `_GatewayGuildDefinition` accessors ensure disabled cache components are *never deserialized*,
  and the factory is skipped entirely when nobody listens. A monolithic typed decode loses both
  layers; the recommendation is to preserve them via `msgspec.Raw`/lazy sub-sections with
  per-section Decoders. On top sits the **decode-context gotcha**: `deserialize_gateway_guild(payload,
  user_id=shard.get_user_id())` (`event_manager.py:308`/`:453`; `event_factory.py:334/:352/:374`)
  threads a live-shard value into thread-member decode (`entity_factory.py:427` →
  `deserialize_thread_member(..., user_id=...)`, `:1543-1556`) and the voice-state member join
  (`:448`) — a decode **input** that a context-free `Decoder.decode(raw)` cannot express; it stays
  a small post-decode fixup, the strongest single argument that a thin per-name glue layer survives.
- `ExceptionEvent` stays non-msgspec (it holds a live `Exception` + a coroutine callback; built at
  `event_manager_base.py:656`, outside the 77). Its `app` property (`base_events.py:207-211`,
  proxies `failed_event.app`) is removed with event app-removal; its `shard` property (`:213-223`)
  survives under D13.

---

## 6. app blast radius on events — purely public API

Grep-verified counts (canonical; they supersede any dossier-internal drift):

| Surface | Count |
|---|---|
| Own `app: traits.RESTAware = attrs.field` declarations in `hikari/events/*.py` | **44** |
| `def app` in events/: 1 abstract (`base_events.py:83-86`) + 31 entity-delegating properties + 1 `ExceptionEvent` proxy (`:207-211`) | **33** |
| Event helper call sites using `self.app` (24 rest + 18 cache) | **42** |
| hikari-internal readers of `event.app` | **0** — grep matches only the delegating-property bodies |
| examples/ readers | 1 (`examples/voice_message/voice_message.py:90`; every other example closes over `bot`) |

Plan-wide helper accounting with both D10 halves resolved: **173** total app-delegating sites = 163
`self.app` + 10 `self.user.app`; **all ~173 removed** — ~114 wire-entity + 42 event + the
interaction sites (9 action helpers deleted; the 8 builder factories survive as app-free sync
constructors, losing their `self.app` usage). No retained set and no pending app decision remain.
Because zero internal readers exist, removing `event.app`
costs hikari's own pipeline nothing — the break is entirely in the public surface catalogued in
[`../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md`](../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md).

---

## 7. The alternative not chosen — shard as a listener parameter

Why `shard` stays on the event (D13): unlike `app`, there is **no forcing function** — shard
injection is msgspec-compatible (§3, §4) and the information is irreplaceable (which connection
received the event). The purity gain of removing it is marginal (only the 18 flat B events would
become zero-glue); self-describing events keep provenance when queued or forwarded; and
`ExceptionEvent.retry` stays simple.

The documented alternative — **shard as an optional second listener parameter** — was considered
and NOT chosen: `async def h(event)` keeps working; `async def h(event, shard)` receives it. The
mechanics are cheap: arity detection once at `subscribe()` (hikari already introspects listener
signatures in `listen()`, and `_assert_is_listener` ALREADY permits defaulted extra params);
`dispatch(event, *, shard=None)` plus 67 mechanical call-site edits; `_invoke_callback` branches on
a stored flag. The costs that decided against it:

- a **dual calling convention forever** (the `CallbackT` union typing + an introspection edge-case
  policy);
- **ecosystem churn** — frameworks wrap listener registration;
- a **permanent `wait_for`/`stream` asymmetry** (they return events; though NO capability is lost —
  bot-level `update_presence` `gateway_bot.py:1295`, `update_voice_state` `:1314`,
  `request_guild_members` `:1327`, and `voice.connect_to` `voice.py:140` all route internally);
- **provenance loss** on queued/forwarded events;
- `ExceptionEvent` needing a shard anyway.

It is **ADDITIVE**: it can be layered on later without removing `event.shard`. The full record is
D13's rejected-alternative column in the decisions log.

---

## 8. Gate items this evidence feeds

Tracked in [`01-open-questions-and-verifications.md`](01-open-questions-and-verifications.md):

- **T-CN (TASK, BLOCKING)** — restructure the `chunk_nonce` post-construction mutation
  (`event_manager.py:420`; §5) before events freeze: compute the nonce pre-construction and pass it
  to the constructor.
- **SD5 (SUB-DECISION)** — GUILD_CREATE laziness under typed decode: preserve via `msgspec.Raw`/lazy
  sub-section accessors (recommended) vs accept eager decode (§5).
- **N-EV (NOTE, non-gating)** — the registry fixture smoke test (lazy Decoder construction fails on
  first decode, not at build; §3), and the reaction_add discriminator hazard: it splits on
  `"member" in payload`, NOT `"guild_id"` (`event_factory.py:789`; §2) — carry it into the dispatch
  table verbatim.
