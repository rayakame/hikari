# Helper Inventory — `hikari/interactions/*.py` (D10-interactions RESOLVED — execution recipe)

Complete inventory of the interaction helper methods that reference `self.app`: 17 direct
(base 8, command 5, component 2, modal 2) + 4 inherited from `webhooks.ExecutableWebhook` = 21. The
*keep-vs-drop-app* decision for interactions is **RESOLVED** (D10-interactions, maintainer):
interactions are **app-less**. This file is now the mechanical execution recipe for that decision —
the **9 action helpers are deleted** (callers use `rest.*` directly) and the **8 builder factories
are kept and reimplemented app-free**. The decision record and rationale live in
[`../04-events-and-interactions-app-decision.md`](../04-events-and-interactions-app-decision.md) and
`../../00-overview/05-decisions-log.md`.

Sources: dossier 04 §4, dossier 08 §7. See [`00-README.md`](00-README.md) for the shared legend.

## 1. Objective

Give a full, source-anchored map of interaction `self.app.*` helpers, split into the two categories
the resolved D10-interactions treats differently: **action helpers** (genuinely need a client —
DELETED, callers move to the existing `rest.*` methods) vs. **builder factories** (need no `app` —
KEPT, reimplemented as app-free sync constructors). Serves constraint (a) / D9; executes
D10-interactions.

## 2. Why interactions were the special case (dossier 08 §0.3, §10.3)

Interactions are **not** thin data wrappers — they were entity models that were *also* clients.
`PartialInteraction` (`interactions/base_interactions.py:272`) both stores `app` and subclasses
`webhooks.ExecutableWebhook`, and the hierarchy defines ~17 helpers that call `self.app.rest.*` /
`self.app.cache.*`. They are constructed by the entity factory (not pure JSON-decoded through
msgspec), so — unlike wire entities — an `app` *could* in principle still have been injected at
construction. That was the D10-interactions question, and the maintainer has answered it:

- **Option 1 (app-less, max consistency) — CHOSEN.** Interactions become pure data; every action
  helper including `create_initial_response` moves to `rest.*`. The one refinement over a blanket
  removal: the 8 builder factories never needed `app` and are kept app-free, so the REST-bot
  return-a-builder flow is unchanged.
- **Option 2 (keep `app` + response sugar, the earlier CONVENTIONS §8 recommendation) —
  SUPERSEDED** by the maintainer's resolution.

This file executes the chosen option. The decision record is
[`../04-events-and-interactions-app-decision.md`](../04-events-and-interactions-app-decision.md).

## 3. Current state — the full helper inventory (dossier 04 §4, dossier 08 §7.3)

### 3.1 `interactions/base_interactions.py`

| Line | Class | Method | async | Delegates to | Category |
|---:|---|---|:--:|---|---|
| 356 | `PartialInteraction` | `fetch_guild` | yes | `rest.fetch_guild(self.guild_id)` | action (`None` guard) |
| 384 | `PartialInteraction` | `get_guild` | no | `cache.get_guild(self.guild_id)` | action (`guard`, cache) |
| 426 | `MessageResponseMixin` | `fetch_initial_response` | yes | `rest.fetch_interaction_response(self.application_id, self.token)` | action |
| 450 | `MessageResponseMixin` | `create_initial_response` | yes | `rest.create_interaction_response(self.id, self.token, …)` | action (huge kwargs) |
| 584 | `MessageResponseMixin` | `edit_initial_response` | yes | `rest.edit_interaction_response(self.application_id, self.token, …)` | action |
| 737 | `MessageResponseMixin` | `delete_initial_response` | yes | `rest.delete_interaction_response(self.application_id, self.token)` | action |
| 760 | `ModalResponseMixin` | `create_modal_response` | yes | `rest.create_modal_response(self.id, self.token, …)` | action |
| 789 | `ModalResponseMixin` | `build_modal_response` | no | `rest.interaction_modal_builder(title=, custom_id=)` | **builder factory** |

The 1 `cache.*` site in `base_interactions.py` is `get_guild` (`:384`).

### 3.2 `interactions/command_interactions.py`

| Line | Class | Method | async | Delegates to | Category |
|---:|---|---|:--:|---|---|
| 142 | `BaseCommandInteraction` | `fetch_command` | yes | `rest.fetch_application_command(self.application_id, self.id, self.guild_id or UNDEFINED)` | action (`arg-default`) |
| 190 | `CommandInteraction` | `build_response` | no | `rest.interaction_message_builder(ResponseType.MESSAGE_CREATE)` | **builder factory** |
| 218 | `CommandInteraction` | `build_deferred_response` | no | `rest.interaction_deferred_builder(ResponseType.DEFERRED_MESSAGE_CREATE)` | **builder factory** |
| 258 | `AutocompleteInteraction` | `build_response(choices)` | no | `rest.interaction_autocomplete_builder(choices)` | **builder factory** |
| 295 | `AutocompleteInteraction` | `create_response(choices)` | yes | `rest.create_autocomplete_response(self.id, self.token, choices)` | action |

### 3.3 `interactions/component_interactions.py` — `ComponentInteraction`

| Line | Method | async | Delegates to | Category |
|---:|---|:--:|---|---|
| 110 | `build_response(type_, /)` | no | `rest.interaction_message_builder(type_)` | **builder factory** (validates `type_ in _IMMEDIATE_TYPES`, raises `ValueError`) |
| 152 | `build_deferred_response(type_, /)` | no | `rest.interaction_deferred_builder(type_)` | **builder factory** (validates `type_ in _DEFERRED_TYPES`) |

### 3.4 `interactions/modal_interactions.py` — `ModalInteraction`

| Line | Method | async | Delegates to | Category |
|---:|---|:--:|---|---|
| 78 | `build_response` | no | `rest.interaction_message_builder(ResponseType.MESSAGE_CREATE)` | **builder factory** |
| 106 | `build_deferred_response` | no | `rest.interaction_deferred_builder(ResponseType.DEFERRED_MESSAGE_CREATE)` | **builder factory** |

## 4. Inherited from `webhooks.ExecutableWebhook` (4 methods)

`PartialInteraction` subclasses `webhooks.ExecutableWebhook` (`base_interactions.py:272`, dossier 08
§7.3), so every interaction *also* gains the four token-gated follow-up helpers `execute`
(`webhooks.py:99`), `fetch_message` (`:242`), `edit_message` (`:276`), `delete_message` (`:440`) —
with `webhook_id → application_id` (`base_interactions.py:350`) and `token →` the interaction token.
These are inventoried under [`04-users-webhooks-audit.md`](04-users-webhooks-audit.md) §2.2 and
counted there toward the 163 total; they are listed here only to complete the interaction surface.
Under the resolved decision, `PartialInteraction` **stops subclassing** the `app`-requiring base
(dossier 08 §7.3, §10.3) — unconditional: these 4 move to `rest.*` and the mixin is reduced to a
data protocol (see [`04-users-webhooks-audit.md`](04-users-webhooks-audit.md) §3.4). The
`webhook_id → application_id` shim property goes with the subclassing.

## 5. The action / builder split (the executed core of D10-interactions)

Dossier 08 §7.3–§7.4 establishes a critical distinction that the resolution preserves exactly:

### 5.1 The 9 action helpers — DELETED; callers use `rest.*` directly

`create_initial_response`, `edit_initial_response`, `delete_initial_response`,
`fetch_initial_response`, `create_modal_response`, `create_response` (autocomplete), `fetch_command`,
`fetch_guild`, `get_guild` make HTTP/cache calls — plus the inherited
`execute`/`fetch_message`/`edit_message`/`delete_message` (§4, counted under webhooks). All 9 direct
action helpers are pure delegations to **existing** rest/cache methods (no new endpoint needed):

| Deleted helper | Replacement |
|---|---|
| `PartialInteraction.fetch_guild` | `rest.fetch_guild(interaction.guild_id)` |
| `PartialInteraction.get_guild` (cache) | `cache.get_guild(interaction.guild_id)` |
| `MessageResponseMixin.fetch_initial_response` | `rest.fetch_interaction_response(interaction.application_id, interaction.token)` |
| `MessageResponseMixin.create_initial_response` | `rest.create_interaction_response(interaction.id, interaction.token, ...)` |
| `MessageResponseMixin.edit_initial_response` | `rest.edit_interaction_response(interaction.application_id, interaction.token, ...)` |
| `MessageResponseMixin.delete_initial_response` | `rest.delete_interaction_response(interaction.application_id, interaction.token)` |
| `ModalResponseMixin.create_modal_response` | `rest.create_modal_response(interaction.id, interaction.token, ...)` |
| `BaseCommandInteraction.fetch_command` | `rest.fetch_application_command(interaction.application_id, interaction.id, guild)` |
| `AutocompleteInteraction.create_response` | `rest.create_autocomplete_response(interaction.id, interaction.token, choices)` |

```python
# before: await interaction.create_initial_response(ResponseType.MESSAGE_CREATE, "hi")
# after:  await rest.create_interaction_response(interaction.id, interaction.token,
#                                                ResponseType.MESSAGE_CREATE, "hi")
```

All identity data the calls need (`id`, `token`, `application_id`, `channel.id`, `guild_id`) are
plain Struct fields that survive (dossier 08 §10.3), so every call the helpers made is exactly
reproducible caller-side. Same REST call, same wire latency — the 3-second interaction deadline is
unaffected; the loss is ergonomic only
([`../04-events-and-interactions-app-decision.md`](../04-events-and-interactions-app-decision.md) §6).

### 5.2 The 8 builder factories — KEPT, reimplemented app-free

`build_response`, `build_deferred_response`, `build_modal_response`, autocomplete `build_response`.
Dossier 08 §7.4 (verified): `rest.interaction_message_builder`/`_deferred_builder`/
`_autocomplete_builder`/`_modal_builder` (`impl/rest.py:4664-4683`) are one-line **pure sync
constructors** that capture **no** `app`; the builder classes
(`impl/special_endpoints.py:1079/1108/1155/1426`) are plain `attrs` with no `app` field and take
`entity_factory` as a `build()` *call argument*. The factory methods therefore **stay as struct
methods on the app-less interactions**, reimplemented as direct constructions with no client at all:

```python
# the executed reimplementation — no client anywhere:
builder = special_endpoints.InteractionMessageBuilder(ResponseType.MESSAGE_CREATE)
```

**Consequence: the REST-bot flow (listener RETURNS a builder) survives UNCHANGED** — a
`RESTBot`/`interaction_server` listener still ends with `return interaction.build_response(...)`.
This is the one place "remove all app helpers" is too blunt — the factories are *reimplemented*, not
deleted. The `ComponentInteraction` builder validators (`_IMMEDIATE_TYPES`/`_DEFERRED_TYPES`,
raising `ValueError`) are preserved in the reimplementation.

## 6. Strict-enum touch-points in interactions (dossier 08 §8, constraint b)

Four loose `Enum | int` unions in the interaction sub-models must become the bare strict enum. The enums
stay hikari's custom `Enum` (adopt PR hikari-py/hikari#2770); unknown Discord values decode to `is_unknown`
pseudo-members via the shared `dec_hook` (`../../02-enums/00-strategy-and-forward-compat.md`):

| Site | Field | Change |
|---|---|---|
| `base_interactions.py:406` | `PartialInteractionMetadata.type: InteractionType \| int` | → `InteractionType` |
| `command_interactions.py:85` | `CommandInteractionOption.type: commands.OptionType \| int` | → `commands.OptionType` |
| `command_interactions.py:136` | `BaseCommandInteraction.command_type: commands.CommandType \| int` | → `commands.CommandType` |
| `component_interactions.py:90` | `ComponentInteraction.component_type: components.ComponentType \| int` | → `components.ComponentType` |

`PartialInteraction.type` (`:284`), `InteractionCallback.type` (`:177`),
`InteractionCallbackResource.type` (`:203`) are already strict. `CommandInteractionOption.value`
(`command_interactions.py:88`) is a genuine polymorphic `Snowflake|str|int|float|bool|None` — **not**
an enum union; leave as-is. Details belong to `../../06-model-modules/11-interactions.md`; noted here
only because it co-occurs with the helper removal.

## 7. Support-model note (feeds `../../06-model-modules/11-interactions.md`)

`InteractionMember` (`base_interactions.py:808`, extends `guilds.Member`) and `InteractionChannel`
(`base_interactions.py:821`, extends `channels.PartialChannel`) subclass entity models and add fields
(dossier 08 §7.5). Their frozen-Struct feasibility (multiple inheritance + added fields) is governed by
the model-module plans, not this file — their parents lose `app`, so they do too.

## 8. Step-by-step migration (resolved path)

1. D10-interactions is resolved
   ([`../04-events-and-interactions-app-decision.md`](../04-events-and-interactions-app-decision.md));
   execute the steps below in order — no decision gate remains.
2. `PartialInteraction` stops subclassing `webhooks.ExecutableWebhook`
   (`base_interactions.py:272`); the 4 inherited followup helpers move to `rest.*` and the mixin is
   reduced to a data protocol (§4; [`04-users-webhooks-audit.md`](04-users-webhooks-audit.md) §3.4).
3. Reimplement the 8 builder factories app-free (§5.2) as direct `special_endpoints` constructions,
   preserving the `ComponentInteraction` type validators.
4. Apply the strict-enum change to the 4 sub-model fields (§6), coordinating with `../../02-enums/`.
5. Delete the 9 action helpers (§5.1); delete the `app` field (`base_interactions.py:275`) and the
   interaction `app=self._app` injections in `impl/entity_factory.py`; rewrite examples
   (`examples/slash.py`) to `rest.*`.
6. Catalog the user-visible surface change in
   `../../11-rollout/03-breaking-changes-and-changelog.md` — this is the headline ecosystem break of
   the migration; the §5.1 replacement table is its migration guide, and downstream frameworks
   (tanjun/lightbulb/arc/miru) are pre-announced.

## 9. Affected files & symbols

| Path | Anchor | Change |
|---|---|---|
| `hikari/interactions/base_interactions.py` | 272, 275 | DROP `ExecutableWebhook` subclassing; `app` field REMOVED |
| `hikari/interactions/base_interactions.py` | 356–789 | 7 action helpers DELETED → `rest.*`; `build_modal_response` reimplemented app-free |
| `hikari/interactions/command_interactions.py` | 142–303 | 2 action helpers DELETED (`fetch_command`, autocomplete `create_response`); 3 builder factories app-free |
| `hikari/interactions/component_interactions.py` | 110, 152 | 2 builder factories app-free (validators preserved) |
| `hikari/interactions/modal_interactions.py` | 78, 106 | 2 builder factories app-free |
| `hikari/interactions/*.py` | §6 sites | 4 strict-enum fields |
| `hikari/impl/rest.py` | 4664–4683 | `interaction_*_builder` constructors (already app-free; structs now construct directly) |
| `hikari/impl/entity_factory.py` | interaction deserialize | interaction `app=self._app` injections DELETED |

## 10. Risks / gotchas

- **`create_initial_response` is the headline ecosystem break** (dossier 08 §10.3, §6): every
  command framework's `ctx.respond` wraps it. There is **no wire-latency change** — the replacement
  is the same REST call, so the 3-second deadline is unaffected; the loss is ergonomic only.
  Mitigate with the §5.1 replacement table and the downstream coordination in
  `../../11-rollout/03-breaking-changes-and-changelog.md`.
- **Builder factories must not be lost** by an over-broad "remove all app helpers" pass (§5.2) —
  they need no `app` and are *reimplemented*, not deleted. Losing them would break the REST-bot flow
  for no constraint benefit.
- **`ExecutableWebhook` inheritance breaks** — the mixin's reduction to a data protocol is
  unconditional; sequence it with this pass ([`04-users-webhooks-audit.md`](04-users-webhooks-audit.md) §3.4).
- **`webhook_id` false friend** — `PartialInteraction.webhook_id` (`base_interactions.py:350`) returns
  `self.application_id`, not an `app` reference (dossier 04 §8.7); a naive `self.app` grep will not
  match it. It is removed with the mixin departure (step 2), not by the `app` grep pass.

## 11. Verification

1. `grep -rn "self\.app" hikari/interactions/` → **0** — the field, the 9 action helpers, and the
   factories' old `rest.interaction_*_builder` delegations are all gone.
2. Builder factories construct valid builders with no client in scope; `ComponentInteraction`
   validators still raise `ValueError` on out-of-set response types.
3. A `RESTBot` listener returning `interaction.build_response(...)` works end-to-end against
   `interaction_server` — the return-a-builder flow is unchanged.
4. The 4 strict-enum fields decode an unknown Discord value via #2770's `is_unknown` pseudo-member
   (no `TypeError`), per `../../02-enums/`.
5. A round-trip test: `rest.create_interaction_response(interaction.id, interaction.token, ...)`
   produces a request identical to the one the removed `create_initial_response` helper made.

## 12. Open questions

- **D10-interactions — RESOLVED** (maintainer): interactions are app-less (Option 1 with the
  builder-factory refinement); recorded in
  [`../04-events-and-interactions-app-decision.md`](../04-events-and-interactions-app-decision.md)
  and `../../00-overview/05-decisions-log.md`. No FLAGGED items remain.
- **Builder factory home — RESOLVED** with the decision: they stay struct methods on the app-less
  interactions, constructing `special_endpoints` builders directly
  (`../03-new-rest-methods-and-free-functions.md` §9).
- **`ExecutableWebhook` fate — RESOLVED**: reduced to a data protocol, unconditional —
  [`04-users-webhooks-audit.md`](04-users-webhooks-audit.md) §3.4.
