# Helper Method Inventory — Overview and Index

This subfolder is the per-module removal recipe book for the app-delegating entity/event/interaction
helper methods. The `self\.app.(rest|cache)` grep finds **163**; that is a floor. `guilds.Member`
reaches the client through the **wrapped user's** app on 10 more helpers — `self.user.app.(rest|cache)`
(`Member.app` is a property returning `self.user.app`) — which a `self\.app` grep never sees. The
**true grand total is 173** (163 `self.app` + 10 `self.user.app`, all 10 on `Member`; see
[`03-guilds.md`](03-guilds.md) §2.2). This book turns the audit in dossier 04 into an actionable
checklist: for every helper, its exact `self.app.rest.*` / `self.app.cache.*` (or
`self.user.app.*`) delegation, the extra logic it carries, and the concrete replacement a caller must
switch to.

Read `../00-strategy.md` first (the app-removal philosophy and the three replacement strategies),
then `../01-app-field-removal.md` (how the `app` field itself is removed). This inventory operates on
the assumption established there: under constraint (a) the `app` field disappears from every
JSON-decoded Struct, so `self.app` is gone and every method built on it must be deleted or re-homed.

## 1. Objective

Provide a mechanical, file-by-file map from "helper that calls `self.app.*`" to "what the caller does
instead." Each per-module file reproduces dossier 04's helper tables verbatim and appends a
**Replacement** column plus per-cluster gotchas (assert-narrowing loss, cache degradation semantics,
token/compose special cases). This directly serves constraint (a) — "no `app` injection during
deserialization" (`../../00-overview/05-decisions-log.md`, D9).

## 2. Counts (from dossier 04 §0)

| Metric | Count |
|---|---:|
| Distinct helper methods referencing `self.app` (the grep floor) | **163** |
| `self.app.rest.*` call-site lines | **126** |
| `self.app.cache.*` call-site lines | **37** |
| `self.user.app.(rest\|cache)` helpers (all on `guilds.Member`) | **10** |
| **True grand total app-delegating helpers** | **173** |
| Other `self.app.*` (`shard_count`, `get_me()`) | 2 |
| `calculate_shard_id(self.app, …)` (passes the app object) | 1 |
| `isinstance(self.app, traits.CacheAware)` narrowing checks | 38 |
| `isinstance(self.app, traits.ShardAware)` narrowing checks | 3 |

The gap between "126 rest call-site lines" and "163 distinct methods" is explained in dossier 04 §0:
several methods issue two `rest.*` calls (branching), and 37 methods delegate to cache rather than
rest. Counting *distinct helper methods* gives 163; counting *`self.app.rest.` reference lines* gives
126; counting *`self.app.cache.` reference lines* gives 37. The task brief's "~102" estimate is an
undercount — **plans must size the work at 126/37/163, not 102** (dossier 04 §0 note, §8.9).

**The 163 is a `self\.app`-only floor, not the total.** `guilds.Member` delegates 10 helpers through
`self.user.app.(rest|cache)` (the wrapped user's app; `guilds.py:641/658/673/862/925/954/981/1011/
1041/1120`) — invisible to a `self\.app` grep. Adding them gives the **true grand total of 173**
(163 + 10). File [`03-guilds.md`](03-guilds.md) §2.2 carries the full `Member` table; every
verification grep in this folder uses the broadened `self\.(user\.)?app\.(rest|cache)` regex so these
sites are detectable (§8). Disposition after the D10 resolutions (events AND interactions go
app-less —
[`../04-events-and-interactions-app-decision.md`](../04-events-and-interactions-app-decision.md)):
**all ~173 app-delegating helper sites are removed** — ~114 wire-entity helpers + the **42** event
helpers ([`07-events.md`](07-events.md)) + the **9** interaction action helpers
([`06-interactions.md`](06-interactions.md)), while the **8** interaction builder factories are kept
and reimplemented as app-free sync constructors (they lose their `self.app` usage but are not
deleted). There is **no retained app-delegating set and no pending app decision**. The old
"Option 2 keeps ≈59 event/interaction helpers" and "~156 removed / ~17 retained" framings are both
superseded.

## 3. Per-file distribution of `self.app.rest.` sites (dossier 04 §0)

```
29  hikari/guilds.py                        7  hikari/interactions/base_interactions.py
16  hikari/channels.py                      6  hikari/events/typing_events.py
12  hikari/webhooks.py                      5  hikari/interactions/command_interactions.py
10  hikari/events/channel_events.py         5  hikari/commands.py
 9  hikari/messages.py                      5  hikari/audit_logs.py
 8  hikari/events/guild_events.py           4  hikari/users.py
                                            4  hikari/templates.py
                                            2  hikari/presences.py
                                            2  hikari/interactions/modal_interactions.py
                                            2  hikari/interactions/component_interactions.py
```

Both §3 and §4 count `self.app.*` only. `guilds.Member`'s 10 `self.user.app.(rest|cache)` helpers are
**additional** (7 rest: `fetch_self`/`ban`/`unban`/`kick`/`add_role`/`remove_role`/`edit`; 3 cache:
`get_guild`/`get_presence`/`get_roles`) — do not read these two tables as the full guilds surface
(that is 55, per §5 and [`03-guilds.md`](03-guilds.md) §2.2).

## 4. Per-file distribution of `self.app.cache.` sites (dossier 04 §0)

```
14  hikari/guilds.py                        2  hikari/events/channel_events.py
10  hikari/events/message_events.py         1  hikari/users.py
 3  hikari/events/typing_events.py          1  hikari/messages.py
 2  hikari/events/guild_events.py           1  hikari/interactions/base_interactions.py
 2  hikari/channels.py                      1  hikari/events/member_events.py
```

## 5. How the 173 methods split across this subfolder

Each file below is scoped to its module(s). The distinct-method counts sum to the true grand total of
173 (the 163 `self.app` floor + `Member`'s 10 `self.user.app` helpers, counted in the guilds row).

| File | Modules | Distinct helper methods |
|---|---|---:|
| [`01-channels.md`](01-channels.md) | `hikari/channels.py` | 18 |
| [`02-messages.md`](02-messages.md) | `hikari/messages.py` | 9 |
| [`03-guilds.md`](03-guilds.md) | `hikari/guilds.py` (`PartialGuild`, `Guild`, `Member`, `GuildWidget`) | 55 |
| [`04-users-webhooks-audit.md`](04-users-webhooks-audit.md) | `hikari/users.py`, `hikari/webhooks.py`, `hikari/audit_logs.py` | 21 |
| [`05-templates-presences-commands.md`](05-templates-presences-commands.md) | `hikari/templates.py`, `hikari/presences.py`, `hikari/commands.py` | 11 |
| [`06-interactions.md`](06-interactions.md) | `hikari/interactions/*.py` | 21 (17 direct + 4 inherited) |
| [`07-events.md`](07-events.md) | `hikari/events/*.py` | 42 |
| | **Total** | **177\*** |

The guilds row is **55**, not 45: `Member` contributes 11 app-delegating helpers (1 `self.app`
+ 10 `self.user.app`), not 1 — see [`03-guilds.md`](03-guilds.md) §2.2.

\* The raw column sum is 177 because the interactions row counts 4 helpers that interactions
*inherit* from `webhooks.ExecutableWebhook` (`execute`, `fetch_message`, `edit_message`,
`delete_message`) — those 4 are already counted once against `webhooks.py` in file `04`. Net distinct
methods = **173** (177 − 4 inherited duplicates). See [`06-interactions.md`](06-interactions.md) §4
for the inheritance detail.

Disposition: **every row is now REMOVED, interactions included** (both D10 halves resolved). The
interactions row splits: its **9 action helpers are deleted** (callers → `rest.*`), its **8 builder
factories are kept and reimplemented app-free** (no longer app-delegating), and its 4 inherited
`ExecutableWebhook` helpers are removed with the webhooks row. Totals: **all ~173 app-delegating
sites removed; no retained set** (§2).

## 6. Legend (shared by every file, from dossier 04 §3)

| Tag | Meaning |
|---|---|
| `pure` | single straight delegation, no other statements → **Strategy 1: direct `rest.*`** |
| `assert` | delegation + `assert isinstance(...)` narrowing on the result |
| `guard` | `isinstance(self.app, traits.*)` gate; returns `None`/`{}` when app is not Cache/Shard-aware |
| `token` | webhook token-resolution branch before the call |
| `compose` | multiple calls / client-side composition or filtering → **Strategy 2: free function / new rest method** |
| `arg-default` | converts/defaults an argument (e.g. `undefined.UNDEFINED if guild_id is None`) |

The three replacement strategies (`../00-strategy.md` §4):
1. **Direct `rest.*` call** — delete the helper; caller invokes `rest.<method>(entity.<id>, …)`. The
   target rest method already exists; these helpers are thin sugar, no new endpoint needed.
2. **Free function / new `rest.*` method** — for `compose`/`token` logic that cannot collapse to one
   call. Enumerated in [`../03-new-rest-methods-and-free-functions.md`](../03-new-rest-methods-and-free-functions.md).
3. **Direct `cache.*` call (or guild-scoped free function)** — for the 37 cache getters; preserve the
   `{}`/`None` degradation semantics.

## 7. Two cross-cluster deferrals

- **The D10 split — both halves RESOLVED.** Events ([`07-events.md`](07-events.md)): the maintainer
  resolved **D10-events** — events go app-less, all 42 event helpers are removed, and the 31
  delegating `app` properties are deleted rather than converted to fields (removal recipes in
  file 07). Interactions ([`06-interactions.md`](06-interactions.md)): the maintainer resolved
  **D10-interactions** — interactions go app-less too; the 9 action helpers are deleted (every one a
  pure delegation to an existing `rest.*` method) and the 8 builder factories are kept and
  reimplemented app-free, so the REST-bot return-a-builder flow is unchanged. File 06 is the
  mechanical execution recipe for that split; both decisions are recorded in
  [`../04-events-and-interactions-app-decision.md`](../04-events-and-interactions-app-decision.md)
  and `../../00-overview/05-decisions-log.md`.
- The **no-1:1-rest cluster** (composition/token/ownership-filter helpers that cannot become a single
  `rest.*`/`cache.*` call) is inventoried in each module file but its *target design* (free-function
  signatures, new `rest.send_dm`, token resolution) lives in
  [`../03-new-rest-methods-and-free-functions.md`](../03-new-rest-methods-and-free-functions.md). Each
  module file cross-links the relevant section rather than re-specifying it.

## 8. Verification (applies to every file in this folder)

1. After removing all helpers, `grep -rnE "self\.(user\.)?app\.(rest|cache)" hikari/` returns **0**
   hits everywhere — model modules, `hikari/events/`, **and `hikari/interactions/`** (both D10
   halves resolved: app-less; the kept builder factories construct from `special_endpoints` and no
   longer touch `self.app`). The `(user\.)?` arm is mandatory: a bare
   `self\.app\.rest\.`/`self\.app\.cache\.` grep misses `guilds.Member`'s 10
   `self.user.app.(rest|cache)` sites and undercounts the work at 163 instead of 173.
2. `grep -rnE "self\.(user\.)?app" hikari/` returns **0** hits outside tests — there is no
   legitimately-retained `app` site anywhere.
3. Every removed method that appeared in `__all__` or docs is listed in the breaking-changes catalog
   (`../../11-rollout/03-breaking-changes-and-changelog.md`).
4. The doc examples that call `message.respond(...)`, `channel.send(...)`, `guild.get_member(...)`,
   `interaction.create_initial_response(...)` are rewritten to the `rest.*`/`cache.*` form.

## 9. Open questions

Consolidated in `../../00-overview/05-decisions-log.md`:
- **D9** — app removal is LOCKED for JSON-decoded entities.
- **D10-events — RESOLVED**: events are app-less; all 42 event helpers removed (file 07).
  **D10-interactions — RESOLVED**: interactions are app-less; 9 action helpers removed, 8 builder
  factories kept app-free (file 06 and
  [`../04-events-and-interactions-app-decision.md`](../04-events-and-interactions-app-decision.md)).
  No pending app decision remains.
- Per-cluster: whether the ~15 `assert isinstance(...)` narrowings are preserved as typed
  convenience wrappers or pushed onto callers as `typing.cast` (raised in files 01, 04, 07).
