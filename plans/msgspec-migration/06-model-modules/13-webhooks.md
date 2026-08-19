# Webhooks

Purpose: migrate `hikari/webhooks.py` — 1 enum, the `ExecutableWebhook` mixin, the `PartialWebhook`
base and its 3 concrete subtypes (`IncomingWebhook`, `ChannelFollowerWebhook`, `ApplicationWebhook`)
dispatched polymorphically by the `type` int. This module is app-heavy: **12 `self.app.rest.*` helper
methods** (4 on the `ExecutableWebhook` mixin, 4 on `IncomingWebhook`, 4 on `ChannelFollowerWebhook`),
all with token-resolution logic that must be re-homed under constraint (a).

--------------------------------------------------------------------------------------------------

## 1. Objective

- Freeze the 4 webhook Structs; drop the `PartialWebhook.app` field (`webhooks.py:475`, inherited by all
  3 subtypes) and re-home the 12 `self.app.rest.*` helpers
  (`../03-app-removal-and-helpers/02-helper-method-inventory/04-users-webhooks-audit.md`,
  `../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md`).
- Express the `PartialWebhook` → {`IncomingWebhook`, `ChannelFollowerWebhook`, `ApplicationWebhook`}
  polymorphism as a msgspec tagged union on `type` (or a retained peek-then-dispatch), preserving the
  current **raise-on-unknown-type** semantics (`entity_factory.py:4677` `UnrecognisedEntityError`).
- Keep `WebhookType` as hikari's custom `Enum` (adopt #2770 strict typing) and drop `WebhookType | int`
  (`PartialWebhook.type`).
- Resolve the fate of the `ExecutableWebhook` mixin whose whole body is `self.app.rest.*` sugar.

Decode classification: `IncomingWebhook`/`ApplicationWebhook` are near-**D** (renamed `avatar`→`avatar_hash`,
`user`→`author`, tagged by `type`) once `app` is gone. `ChannelFollowerWebhook` is **T** (the
`source_channel` `setdefault("type", GUILD_NEWS)` computed default and the inline `source_guild`
partial-guild build).

--------------------------------------------------------------------------------------------------

## 2. Current state (file:line anchors)

### 2.1 Enum
`WebhookType(int, enums.Enum)` `webhooks.py:60` — INCOMING=1, CHANNEL_FOLLOWER=2, APPLICATION=3.

### 2.2 ExecutableWebhook mixin (`webhooks.py:73`)
An `abc.ABC`, `__slots__=()`, with abstract properties `app` `:79`, `webhook_id` `:84`, `token` `:89`,
and 4 async helpers, each of which resolves `self.token` (raising `ValueError` if `None`) then delegates
to `self.app.rest.*`:
- `execute` `:99` → `self.app.rest.execute_webhook(...)` `:222`.
- `fetch_message` `:242` → `self.app.rest.fetch_webhook_message(...)` `:274`.
- `edit_message` `:276` → `self.app.rest.edit_webhook_message(...)` `:424`.
- `delete_message` `:440` → `self.app.rest.delete_webhook_message(...)` `:467`.

### 2.3 PartialWebhook base (`webhooks.py:472`)
`@attrs.define(unsafe_hash=True, kw_only=True)`, subclasses `snowflakes.Unique`. Fields: `app` `:475`,
`id` (hash) `:480`, `type: WebhookType | int` `:483`, `name` `:486`, `avatar_hash` `:489`,
`application_id` `:492`. Non-app helpers: `__str__` `:495`, `mention` `:499`, `default_avatar_url` `:517`,
`make_avatar_url` `:522` (all `routes.*`, no `app`).

### 2.4 Concrete subtypes
- `IncomingWebhook(PartialWebhook, ExecutableWebhook)` `webhooks.py:575` — `channel_id`, `guild_id`,
  `author: User | None`, `token: str | None`; `webhook_id` property → `self.id` `:605`; helpers
  `delete` `:611`, `edit` `:645`, `fetch_channel` `:717`, `fetch_self` `:743` (all `self.app.rest.*`,
  with `use_token` resolution logic `:633-641`).
- `ChannelFollowerWebhook(PartialWebhook)` `webhooks.py:793` — `channel_id`, `guild_id`,
  `author: User | None`, `source_channel: PartialChannel | None`, `source_guild: PartialGuild | None`;
  helpers `delete` `:823`, `edit` `:836`, `fetch_channel` `:888`, `fetch_self` `:914`.
- `ApplicationWebhook(PartialWebhook)` `webhooks.py:943` — `application_id` (required override) `:949`;
  no extra helpers.

### 2.5 Factory
- `deserialize_incoming_webhook` `entity_factory.py:4603`, `deserialize_channel_follower_webhook`
  `:4622` (the `source_channel.setdefault("type", GUILD_NEWS)` at `:4633`, inline `source_guild` at
  `:4638`), `deserialize_application_webhook` `:4660`.
- `deserialize_webhook` `entity_factory.py:4671` routes on `WebhookType` via `_webhook_type_mapping`
  (built `:644`), raising `UnrecognisedEntityError` on unknown type `:4677`.

--------------------------------------------------------------------------------------------------

## 3. Target design

### 3.1 Enum → strict custom (adopt #2770)
`class WebhookType(int, enums.Enum)` stays hikari's custom `Enum` (unchanged); PR #2770's
`_EnumMeta.__call__` mints an `is_unknown` pseudo-member on unrecognised values
(`../02-enums/00-strategy-and-forward-compat.md`). Here `type` is the tagged-union discriminator (§3.2),
so it dispatches on the raw wire int; drop `WebhookType | int` on the field.

### 3.2 Tagged-union polymorphism on `type`
Discord's `type` int is a clean per-object discriminator (1/2/3 map 1:1 to the three concrete classes),
so this is a textbook msgspec tagged union — the recommended end-state
(`../05-entity-factory/01-polymorphism-and-tagged-unions.md`):
```python
class PartialWebhook(
    snowflakes.Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False,
    tag_field="type",
):
    id: snowflakes.Snowflake
    name: str
    avatar_hash: str | None = msgspec.field(name="avatar")
    application_id: snowflakes.Snowflake | None = None
    # NO app; mention / default_avatar_url / make_avatar_url verbatim (routes.*)

class IncomingWebhook(PartialWebhook, ExecutableWebhook, frozen=True, kw_only=True, eq=False, tag=1):
    channel_id: snowflakes.Snowflake
    guild_id: snowflakes.Snowflake
    author: users.User | None = None                # field(name="user")
    token: str | None = None
    @property
    def webhook_id(self) -> snowflakes.Snowflake: return self.id

class ChannelFollowerWebhook(PartialWebhook, frozen=True, kw_only=True, eq=False, tag=2):
    channel_id: snowflakes.Snowflake
    guild_id: snowflakes.Snowflake
    author: users.User | None = None                # field(name="user")
    source_channel: channels.PartialChannel | None = None   # T: default type=GUILD_NEWS
    source_guild: guilds.PartialGuild | None = None         # T: inline partial build

class ApplicationWebhook(PartialWebhook, frozen=True, kw_only=True, eq=False, tag=3):
    application_id: snowflakes.Snowflake

AnyWebhook = typing.Union[IncomingWebhook, ChannelFollowerWebhook, ApplicationWebhook]
```
- **Behaviour parity:** msgspec tagged unions **raise** on an unknown tag — matching today's
  `UnrecognisedEntityError` at `entity_factory.py:4677`. No soft-skip is needed here.
- The old `type: WebhookType | int` field becomes the tag discriminator. `entity.type` still reads back
  as the tag value; if a stored `WebhookType` attribute is required for public-API parity, expose a
  trivial `@property type` mapping the tag to the enum. Settle in
  `../05-entity-factory/01-polymorphism-and-tagged-unions.md`.
- Incremental fallback: keep `deserialize_webhook` as a `msgspec.Raw` peek on `type` dispatching to the
  concrete decoders, until the tagged union lands.
- `ChannelFollowerWebhook` stays **T**: `source_channel` needs `type` defaulted to `GUILD_NEWS`
  (`entity_factory.py:4633`) and `source_guild` is an inline `PartialGuild` — both residual transforms.

### 3.3 ExecutableWebhook — the mixin decision (constraint a)
Every method of `ExecutableWebhook` is `self.app.rest.*` sugar plus token-resolution/`ValueError`. Under
constraint (a) the abstract `app` property and the 4 delegating helpers cannot survive on a decoded,
app-less Struct. Two options (recommend Option A):

- **Option A — strip the mixin to a marker, move logic to rest/free functions (recommended).** Remove the
  abstract `app`, drop `execute`/`fetch_message`/`edit_message`/`delete_message`; keep `ExecutableWebhook`
  only as a typing marker carrying abstract `webhook_id`/`token` (so `IncomingWebhook` still advertises
  "executable"). Callers use `rest.execute_webhook(wh.webhook_id, token=wh.token, …)` directly. The
  token-resolution convenience (raise if `token is None`; the `use_token` UNDEFINED→token-else-bot-auth
  logic in `IncomingWebhook.delete/edit/fetch_self`, `webhooks.py:633-641`) is re-homed as **free
  functions** or **new rest helpers** — enumerate in
  `../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md`.
- **Option B — delete `ExecutableWebhook` entirely.** Fewer moving parts, but loses the "executable"
  marker used for typing `execute_webhook`'s accepted objects.

The 12-helper re-homing table (all delegate to an existing `rest.*` method, so none is a genuinely new
endpoint — they are token-resolution wrappers):

| Helper | Location | Re-home target |
|---|---|---|
| `ExecutableWebhook.execute` | `:99` | `rest.execute_webhook(id, token=…, …)` (+ token-None guard as free fn) |
| `ExecutableWebhook.fetch_message` | `:242` | `rest.fetch_webhook_message(id, token, message)` |
| `ExecutableWebhook.edit_message` | `:276` | `rest.edit_webhook_message(id, token, message, …)` |
| `ExecutableWebhook.delete_message` | `:440` | `rest.delete_webhook_message(id, token, message)` |
| `IncomingWebhook.delete` | `:611` | `rest.delete_webhook(id, token=…)` (+ `use_token` resolver) |
| `IncomingWebhook.edit` | `:645` | `rest.edit_webhook(id, token=…, …)` |
| `IncomingWebhook.fetch_channel` | `:717` | `rest.fetch_channel(channel_id)` |
| `IncomingWebhook.fetch_self` | `:743` | `rest.fetch_webhook(id, token=…)` |
| `ChannelFollowerWebhook.delete` | `:823` | `rest.delete_webhook(id)` |
| `ChannelFollowerWebhook.edit` | `:836` | `rest.edit_webhook(id, …)` |
| `ChannelFollowerWebhook.fetch_channel` | `:888` | `rest.fetch_channel(channel_id)` |
| `ChannelFollowerWebhook.fetch_self` | `:914` | `rest.fetch_webhook(id)` |

--------------------------------------------------------------------------------------------------

## 4. Step-by-step migration

1. Adopt #2770's strict custom `WebhookType` (kept, not ported); drop `WebhookType | int`.
2. Convert `PartialWebhook` to a frozen Struct base with `tag_field="type"`; drop the `app` field;
   keep `mention`/`default_avatar_url`/`make_avatar_url`.
3. Convert the 3 subtypes to tagged Structs (`tag=1/2/3`); rename `avatar`→`avatar_hash`,
   `user`→`author` via `field(name=…)`; keep `IncomingWebhook.webhook_id`.
4. Apply the `ExecutableWebhook` decision (Option A): strip helpers + abstract `app`, keep the marker;
   move token-resolution/`use_token` logic to free functions/rest helpers.
5. Re-home the 12 helpers per the table; delete `self.app.rest.*` bodies.
6. Keep `ChannelFollowerWebhook`'s residual transforms (`source_channel` default type, inline
   `source_guild`); update the 3 concrete decoders + `deserialize_webhook` to stop injecting `app` and to
   feed the tagged union (or the interim `Raw` dispatch).

--------------------------------------------------------------------------------------------------

## 5. Affected files & symbols

| Path / anchor | Change |
|---|---|
| `hikari/webhooks.py:60` (`WebhookType`) | stays custom (#2770 strict typing); strict field |
| `hikari/webhooks.py:73-467` (`ExecutableWebhook`) | strip helpers + abstract `app`; keep marker (Option A) |
| `hikari/webhooks.py:472-571` (`PartialWebhook`) | frozen Struct base, `tag_field="type"`; drop `app`; keep url helpers |
| `hikari/webhooks.py:575-789` (`IncomingWebhook`) | tag=1; rename `avatar`/`user`; re-home 4 helpers |
| `hikari/webhooks.py:793-939` (`ChannelFollowerWebhook`) | tag=2; **T** `source_channel`/`source_guild`; re-home 4 helpers |
| `hikari/webhooks.py:943-950` (`ApplicationWebhook`) | tag=3; required `application_id` |
| `hikari/impl/entity_factory.py:4603-4679` | drop `app`; feed tagged union / `Raw` dispatch; keep `GUILD_NEWS` default + inline `source_guild` |
| `../03-app-removal-and-helpers/02-helper-method-inventory/04-users-webhooks-audit.md` | the 12-helper inventory |
| `../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md` | token-resolution / `use_token` free fns |
| `../05-entity-factory/01-polymorphism-and-tagged-unions.md` | webhook tagged union, raise-on-unknown |
| `04-channels.md`, `05-guilds-members-roles.md`, `02-users.md` | base/reference types |

--------------------------------------------------------------------------------------------------

## 6. Risks / gotchas

1. **Tag field vs stored `type`.** Moving `type` to the tag discriminator may change how `entity.type`
   reads back (tag int vs `WebhookType`); add a `@property type` for API parity if needed.
2. **`ExecutableWebhook` is pure app sugar.** Its 4 helpers, plus 8 more on the subtypes, must be
   re-homed; the `use_token` UNDEFINED→token-else-bot-auth resolver (`webhooks.py:633-641`, 3 sites) is
   bespoke and needs a free-function home, not a mechanical delete.
3. **`ChannelFollowerWebhook` residuals** — `source_channel` needs `type` defaulted to `GUILD_NEWS`
   (`entity_factory.py:4633`) and `source_guild` is built inline; both stay residual transforms.
4. **Token secrecy in repr.** `IncomingWebhook.token` is secret; msgspec's default all-field repr would
   expose it. Hand-write a `__repr__` that omits `token` (conventions §2 repr guidance).
5. **Raise-on-unknown preserved** — tagged unions raise on unknown tag, matching
   `entity_factory.py:4677`; do not add a soft-skip.

--------------------------------------------------------------------------------------------------

## 7. Verification

- Decode each of the 3 webhook types → correct concrete class; an unknown `type` int → decode error
  (parity with today's `UnrecognisedEntityError`).
- `IncomingWebhook.webhook_id == id`; `avatar`→`avatar_hash`, `user`→`author` map correctly;
  `ChannelFollowerWebhook.source_channel.type == GUILD_NEWS` when the payload omits it; `source_guild`
  is a `PartialGuild`.
- `repr(incoming_webhook)` does not contain the token string.
- Grep: no `self.app` in `webhooks.py`; the 12 helpers resolve to `rest.*`/free functions.
- Strict enum: unknown `WebhookType` int surfaces as a decode error via the union (tagged), not a silent
  `int`.

--------------------------------------------------------------------------------------------------

## 8. Open questions / decisions

Cross-link `../00-overview/05-decisions-log.md`:
- **`ExecutableWebhook` fate** — Option A (marker + free-function helpers, recommended) vs Option B
  (delete). Confirm with the maintainer; the `execute_webhook` typing surface depends on the marker.
- **Tagged union vs retained hand dispatch** for webhooks — recommend the tagged union
  (`../05-entity-factory/01-polymorphism-and-tagged-unions.md`); interim `Raw` peek is the bridge.
- **`type` property parity** — whether a read-only `WebhookType` property is needed once `type` is the tag.
- **D9 token-resolution free functions** (`execute`, `use_token` resolver) — signatures in
  `../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md`.
