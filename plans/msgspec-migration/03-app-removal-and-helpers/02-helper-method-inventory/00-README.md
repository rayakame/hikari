# Helper Method Inventory — Overview and Index

This subfolder is the per-module removal recipe book for the **163 entity/event/interaction helper
methods that reference `self.app`**. It turns the audit in dossier 04 into an actionable checklist:
for every helper, its exact `self.app.rest.*` / `self.app.cache.*` delegation, the extra logic it
carries, and the concrete replacement a caller must switch to.

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
| Distinct helper methods referencing `self.app` | **163** |
| `self.app.rest.*` call-site lines | **126** |
| `self.app.cache.*` call-site lines | **37** |
| Other `self.app.*` (`shard_count`, `get_me()`) | 2 |
| `calculate_shard_id(self.app, …)` (passes the app object) | 1 |
| `isinstance(self.app, traits.CacheAware)` narrowing checks | 38 |
| `isinstance(self.app, traits.ShardAware)` narrowing checks | 3 |

The gap between "126 rest call-site lines" and "163 distinct methods" is explained in dossier 04 §0:
several methods issue two `rest.*` calls (branching), and 37 methods delegate to cache rather than
rest. Counting *distinct helper methods* gives 163; counting *`self.app.rest.` reference lines* gives
126; counting *`self.app.cache.` reference lines* gives 37. The task brief's "~102" estimate is an
undercount — **plans must size the work at 126/37/163, not 102** (dossier 04 §0 note, §8.9).

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

## 4. Per-file distribution of `self.app.cache.` sites (dossier 04 §0)

```
14  hikari/guilds.py                        2  hikari/events/channel_events.py
10  hikari/events/message_events.py         1  hikari/users.py
 3  hikari/events/typing_events.py          1  hikari/messages.py
 2  hikari/events/guild_events.py           1  hikari/interactions/base_interactions.py
 2  hikari/channels.py                      1  hikari/events/member_events.py
```

## 5. How the 163 methods split across this subfolder

Each file below is scoped to its module(s). The distinct-method counts sum exactly to 163.

| File | Modules | Distinct helper methods |
|---|---|---:|
| [`01-channels.md`](01-channels.md) | `hikari/channels.py` | 18 |
| [`02-messages.md`](02-messages.md) | `hikari/messages.py` | 9 |
| [`03-guilds.md`](03-guilds.md) | `hikari/guilds.py` (`PartialGuild`, `Guild`, `Member`, `GuildWidget`) | 45 |
| [`04-users-webhooks-audit.md`](04-users-webhooks-audit.md) | `hikari/users.py`, `hikari/webhooks.py`, `hikari/audit_logs.py` | 21 |
| [`05-templates-presences-commands.md`](05-templates-presences-commands.md) | `hikari/templates.py`, `hikari/presences.py`, `hikari/commands.py` | 11 |
| [`06-interactions.md`](06-interactions.md) | `hikari/interactions/*.py` | 21 (17 direct + 4 inherited) |
| [`07-events.md`](07-events.md) | `hikari/events/*.py` | 42 |
| | **Total** | **167\*** |

\* The raw column sum is 167 because the interactions row counts 4 helpers that interactions
*inherit* from `webhooks.ExecutableWebhook` (`execute`, `fetch_message`, `edit_message`,
`delete_message`) — those 4 are already counted once against `webhooks.py` in file `04`. Net distinct
methods = **163** (167 − 4 inherited duplicates). See [`06-interactions.md`](06-interactions.md) §4
for the inheritance detail.

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

- **Interactions ([`06-interactions.md`](06-interactions.md)) and events
  ([`07-events.md`](07-events.md)) are FLAGGED under decision D10.** This inventory enumerates every
  one of their helpers, but the *keep-vs-drop* question (do events/interactions also go app-less, or
  do they keep `app` because they are hand-constructed, not JSON-decoded?) is a maintainer call made
  in [`../04-events-and-interactions-app-decision.md`](../04-events-and-interactions-app-decision.md).
  Files 06 and 07 present the full removal recipe *and* the "keep but require every event to carry its
  own `app`" alternative, and defer the decision to that file and to
  `../../00-overview/05-decisions-log.md` (D10).
- The **no-1:1-rest cluster** (composition/token/ownership-filter helpers that cannot become a single
  `rest.*`/`cache.*` call) is inventoried in each module file but its *target design* (free-function
  signatures, new `rest.send_dm`, token resolution) lives in
  [`../03-new-rest-methods-and-free-functions.md`](../03-new-rest-methods-and-free-functions.md). Each
  module file cross-links the relevant section rather than re-specifying it.

## 8. Verification (applies to every file in this folder)

1. After removing all helpers, `grep -rn "self\.app\.rest\." hikari/` and
   `grep -rn "self\.app\.cache\." hikari/` return **0** hits in model modules (and in
   events/interactions if D10 chooses the app-less option).
2. `grep -rn "self\.app" hikari/` returns only the legitimately-retained sites (events/interactions
   under D10 option 2, and none under option 1).
3. Every removed method that appeared in `__all__` or docs is listed in the breaking-changes catalog
   (`../../11-rollout/03-breaking-changes-and-changelog.md`).
4. The doc examples that call `message.respond(...)`, `channel.send(...)`, `guild.get_member(...)`,
   `interaction.create_initial_response(...)` are rewritten to the `rest.*`/`cache.*` form.

## 9. Open questions

Consolidated in `../../00-overview/05-decisions-log.md`:
- **D9** — app removal is LOCKED for JSON-decoded entities.
- **D10 (FLAGGED)** — events/interactions keep-vs-drop app; see files 06, 07, and
  [`../04-events-and-interactions-app-decision.md`](../04-events-and-interactions-app-decision.md).
- Per-cluster: whether the ~15 `assert isinstance(...)` narrowings are preserved as typed
  convenience wrappers or pushed onto callers as `typing.cast` (raised in files 01, 04, 07).
