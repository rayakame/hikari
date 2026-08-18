# Helper Removal — `hikari/users.py`, `hikari/webhooks.py`, `hikari/audit_logs.py`

Removal recipe for 21 helper methods across three modules: `users.py` (4 helpers; 4 `rest.*` + 1
`cache.*`), `webhooks.py` (12 helpers, all `rest.*`, all token-gated), and `audit_logs.py`
(5 helpers, `rest.*`, entry-info classes). Webhooks and `PartialUser.send` are the heaviest
`token`/`compose` cases in the whole cluster.

See [`00-README.md`](00-README.md) for the shared legend and
[`../03-new-rest-methods-and-free-functions.md`](../03-new-rest-methods-and-free-functions.md) §4–§5
for the `send_dm` and webhook-token targets.

## 1. Objective

Delete these three modules' `app`-delegating helpers, mapping the pure ones to direct `rest.*` and
re-homing `PartialUser.send` (DM resolve+create) and the webhook token-resolution methods. Serves
constraint (a) / D9.

## 2. Current state

### 2.1 `hikari/users.py` (dossier 04 §3.5)

`PartialUser` (`users.py:387` area) and `OwnUser` (`users.py:876`/`1027`).

| Line | Class | Method | async | Delegates to | Extra logic |
|---:|---|---|:--:|---|---|
| 387 | `PartialUser` | `fetch_dm_channel` | yes | `rest.create_dm_channel(self.id)` | pure |
| 409 | `PartialUser` | `fetch_self` | yes | `rest.fetch_user(user=self.id)` | pure |
| 429 | `PartialUser` | `send` (huge sig) | yes | `cache.get_dm_channel_id(self.id)` → `rest.create_message(...)` | `compose` |
| 1027 | `OwnUser` | `fetch_self` | yes | `rest.fetch_my_user()` | pure |

`send` (`users.py:429`) is the only cache-touching user helper (the 1 `users.py` cache site): it looks
up the DM channel id in the cache, falls back to `self.fetch_dm_channel()` (create), then
`rest.create_message` (dossier 04 §3.5, §7.2).

### 2.2 `hikari/webhooks.py` (dossier 04 §3.3)

`ExecutableWebhook` (`webhooks.py:73`) is a **mixin ABC** with abstract `app`, `webhook_id`, `token`;
all four of its methods gate on `self.token`. `IncomingWebhook` (`webhooks.py:611`+) and
`ChannelFollowerWebhook` (`webhooks.py:823`+) add token-resolution and `assert` narrowing.

| Line | Class | Method | async | Delegates to | Extra logic |
|---:|---|---|:--:|---|---|
| 99 | `ExecutableWebhook` | `execute` | yes | `rest.execute_webhook(self.webhook_id, token=self.token, …)` | `token` (raises `ValueError` if no token) |
| 242 | `ExecutableWebhook` | `fetch_message` | yes | `rest.fetch_webhook_message(self.webhook_id, token=self.token, message=)` | `token` |
| 276 | `ExecutableWebhook` | `edit_message` | yes | `rest.edit_webhook_message(self.webhook_id, token=self.token, …)` | `token` |
| 440 | `ExecutableWebhook` | `delete_message` | yes | `rest.delete_webhook_message(self.webhook_id, token=self.token, message=)` | `token` |
| 611 | `IncomingWebhook` | `delete(*, use_token=UNDEFINED)` | yes | `rest.delete_webhook(self.id, token=token)` | `token` (resolves `use_token`) |
| 645 | `IncomingWebhook` | `edit(...)` | yes | `rest.edit_webhook(self.id, token=token, …)` | `token` + `assert isinstance(..., IncomingWebhook)` |
| 717 | `IncomingWebhook` | `fetch_channel` | yes | `rest.fetch_channel(self.channel_id)` | `assert` |
| 743 | `IncomingWebhook` | `fetch_self(*, use_token)` | yes | `rest.fetch_webhook(self.id, token=token)` | `token` + `assert` |
| 823 | `ChannelFollowerWebhook` | `delete` | yes | `rest.delete_webhook(self.id)` | pure |
| 836 | `ChannelFollowerWebhook` | `edit(...)` | yes | `rest.edit_webhook(self.id, …)` | `assert isinstance(..., ChannelFollowerWebhook)` |
| 888 | `ChannelFollowerWebhook` | `fetch_channel` | yes | `rest.fetch_channel(self.channel_id)` | `assert` |
| 914 | `ChannelFollowerWebhook` | `fetch_self` | yes | `rest.fetch_webhook(self.id)` | `assert` |

Verified `execute` token gate (`webhooks.py:218-220`):
```python
if not self.token:
    msg = "Cannot send a message using a webhook where we don't know the token"
    raise ValueError(msg)
```

> **Inheritance note (feeds [`06-interactions.md`](06-interactions.md) and
> [`00-README.md`](00-README.md) §5):** the four `ExecutableWebhook` methods (`execute`,
> `fetch_message`, `edit_message`, `delete_message`) are inherited by `PartialInteraction`
> (`interactions/base_interactions.py:272` subclasses `ExecutableWebhook`). They are counted once here
> under `webhooks.py`; file 06 references them but does not double-count them toward the 163 total.

### 2.3 `hikari/audit_logs.py` (dossier 04 §3.6)

Entry-info classes on `AuditLog` (`audit_logs.py:506`) and `AuditLogEntry` (`audit_logs.py:700`).

| Line | Class | Method | async | Delegates to | Extra logic |
|---:|---|---|:--:|---|---|
| 543 | `MessagePinEntryInfo` | `fetch_channel` | yes | `rest.fetch_channel(self.channel_id)` | `assert` |
| 569 | `MessagePinEntryInfo` | `fetch_message` | yes | `rest.fetch_message(self.channel_id, self.message_id)` | pure |
| 624 | `MessageDeleteEntryInfo` | `fetch_channel` | yes | `rest.fetch_channel(self.channel_id)` | `assert` |
| 668 | `MemberMoveEntryInfo` | `fetch_channel` | yes | `rest.fetch_channel(self.channel_id)` | `assert` |
| 729 | `AuditLogEntry` | `fetch_user` | yes | `rest.fetch_user(self.user_id)` | `arg-default` (`None` if `user_id is None`) |

## 3. Target design — replacements

### 3.1 Pure / assert / arg-default → direct `rest.*` (Strategy 1)

| Removed helper | Caller now writes |
|---|---|
| `user.fetch_dm_channel()` | `await rest.create_dm_channel(user.id)` |
| `user.fetch_self()` | `await rest.fetch_user(user.id)` |
| `own_user.fetch_self()` | `await rest.fetch_my_user()` |
| `wh.fetch_channel()` (Incoming/Follower) | `await rest.fetch_channel(wh.channel_id)` (cast to narrow) |
| `follower_wh.delete()` | `await rest.delete_webhook(follower_wh.id)` |
| `follower_wh.edit(...)` | `await rest.edit_webhook(follower_wh.id, ...)` (cast) |
| `follower_wh.fetch_self()` | `await rest.fetch_webhook(follower_wh.id)` (cast) |
| `entry_info.fetch_channel()` | `await rest.fetch_channel(entry_info.channel_id)` (cast) |
| `entry_info.fetch_message()` | `await rest.fetch_message(entry_info.channel_id, entry_info.message_id)` |
| `entry.fetch_user()` | `await rest.fetch_user(entry.user_id) if entry.user_id is not None else None` |

The `assert isinstance(...)` narrowings (webhook `fetch_channel`/`edit`/`fetch_self`, audit
`fetch_channel`) are lost on direct calls — apply the cluster narrowing policy
([`00-README.md`](00-README.md) §9). `AuditLogEntry.fetch_user` keeps the `user_id is None → None`
guard inline.

### 3.2 `PartialUser.send` — DM resolve + create (no-1:1)

`PartialUser.send` (`users.py:429`) composes: cache DM-channel-id lookup → `fetch_dm_channel()`
fallback (create) → `rest.create_message`. It needs both `cache` and `rest`. Target: a new REST
convenience method `rest.send_dm(user, ...)` (recommended) per
[`../03-new-rest-methods-and-free-functions.md`](../03-new-rest-methods-and-free-functions.md) §4,
which folds the resolve-or-create step into the REST layer so callers keep a one-call ergonomic
without an `app`:

```python
# before: await user.send("hi")
# after:  await rest.send_dm(user, "hi")
```

### 3.3 Webhook token resolution — the `token` cluster (no-1:1)

The eight token-gated webhook methods carry logic that cannot collapse to a single `rest.*` call:
- `ExecutableWebhook.{execute,fetch_message,edit_message,delete_message}` raise `ValueError` when
  `self.token` is `None` before delegating.
- `IncomingWebhook.{delete,edit,fetch_self}` resolve a `use_token` tri-state
  (`UNDEFINED`/`bool`/explicit) into the actual token, raising when the token is unknown.

Target: the token-resolution design in
[`../03-new-rest-methods-and-free-functions.md`](../03-new-rest-methods-and-free-functions.md) §5 —
either free functions `execute_webhook_for(rest, webhook, …)` that carry the token gate, or push the
token parameter into the `rest` layer so `rest.execute_webhook(webhook, token=..., ...)` performs the
`ValueError` gate itself. Whichever is chosen, the `ValueError`/`use_token` semantics must be
preserved (they are documented `Raises` in the public API).

### 3.4 `ExecutableWebhook` mixin fate

`ExecutableWebhook` (`webhooks.py:73`) exists only to attach these four methods via abstract
`app`/`webhook_id`/`token`. With the methods gone and `app` removed, the mixin either disappears or
becomes a pure data protocol (id + token) with no behavior. Because `PartialInteraction` currently
subclasses it (see [`06-interactions.md`](06-interactions.md) §4), coordinate the mixin's removal with
the interactions decision (D10) — under app removal `PartialInteraction` can no longer inherit an
`app`-requiring base regardless.

## 4. Step-by-step migration

1. Remove `app` fields/abstract properties: `users.User`/`OwnUser` (`users.py:876`), `webhooks`
   mixins (`webhooks.py:81` abstract), `AuditLog`/`AuditLogEntry` (`audit_logs.py:506/700`) per
   [`../01-app-field-removal.md`](../01-app-field-removal.md).
2. Delete the pure/assert/arg-default helpers (§3.1); rewrite docs.
3. Add `rest.send_dm(user, ...)` and delete `PartialUser.send` (§3.2).
4. Implement the webhook token-resolution target (§3.3) and delete the 8 token-gated methods.
5. Retire or reduce `ExecutableWebhook` to a data protocol (§3.4); coordinate with D10.
6. Apply the assert-narrowing policy across webhook/audit `fetch_channel`.
7. Catalog all 21 removed public methods in `../../11-rollout/03-breaking-changes-and-changelog.md`.

## 5. Affected files & symbols

| Path | Anchor | Change |
|---|---|---|
| `hikari/users.py` | 387, 409, 429, 1027 | remove `PartialUser`/`OwnUser` helpers; `send`→`rest.send_dm` |
| `hikari/webhooks.py` | 73, 81 | reduce/remove `ExecutableWebhook` mixin + abstract `app` |
| `hikari/webhooks.py` | 99–914 | remove 12 helpers; re-home token resolution |
| `hikari/audit_logs.py` | 543–729 | remove 5 entry helpers |
| `hikari/api/rest.py`, `hikari/impl/rest.py` | new | add `send_dm` (+ optional token-aware webhook params) |
| `hikari/impl/entity_factory.py` | user/webhook/audit deserialize | drop `app=self._app` |

## 6. Risks / gotchas

- **Token gates are documented `Raises: ValueError`.** Dropping them silently (e.g. letting a
  `token=None` reach `rest.execute_webhook`) would change error behavior. The gate must move
  somewhere, not vanish (dossier 04 §7.2).
- **`use_token` tri-state** (`IncomingWebhook.delete/edit/fetch_self`) is subtle — `UNDEFINED` vs. a
  bool vs. an explicit token. Reproduce exactly in the token-resolution target.
- **`send_dm` must preserve the cache-first, create-fallback order** (`users.py:429`) so it does not
  create a redundant DM channel when one is already cached.
- **Narrowing loss** on webhook/audit `fetch_channel` and `IncomingWebhook.edit`/`ChannelFollowerWebhook.edit`
  (subtype `assert`s) — cluster policy.
- **`ExecutableWebhook` is a shared base with interactions** — its fate is entangled with D10
  ([`06-interactions.md`](06-interactions.md) §4).

## 7. Verification

1. `grep -n "self\.app" hikari/{users,webhooks,audit_logs}.py` → 0 after the pass.
2. `rest.send_dm` uses the cached DM channel when present, creates one otherwise (mock cache/rest).
3. Token-resolution target still raises `ValueError` on a tokenless webhook execute, and resolves
   `use_token` correctly for all three tri-state inputs.
4. `AuditLogEntry.fetch_user` replacement returns `None` when `user_id is None`.

## 8. Open questions

- Webhook token resolution: free functions vs. `rest`-layer token param —
  `../03-new-rest-methods-and-free-functions.md` §5, `../../00-overview/05-decisions-log.md`.
- `send_dm` as a first-class `rest` method vs. a free function — same refs (§4).
- Fate of `ExecutableWebhook` as a data protocol — coordinate with D10
  (`../04-events-and-interactions-app-decision.md`).
