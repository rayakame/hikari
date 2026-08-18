# Helper Inventory — `hikari/interactions/*.py` (D10-FLAGGED)

Complete inventory of the interaction helper methods that reference `self.app`: 17 direct
(base 8, command 5, component 2, modal 2) + 4 inherited from `webhooks.ExecutableWebhook` = 21. This
file **enumerates every helper and its replacement**, but the *keep-vs-drop-app* decision for
interactions is FLAGGED (D10) and made in
[`../04-events-and-interactions-app-decision.md`](../04-events-and-interactions-app-decision.md) and
`../../00-overview/05-decisions-log.md`. Nothing here silently picks the most-breaking option.

Sources: dossier 04 §4, dossier 08 §7. See [`00-README.md`](00-README.md) for the shared legend.

## 1. Objective

Give a full, source-anchored map of interaction `self.app.*` helpers, split into two categories that
matter for D10: **action helpers** (genuinely need a client — removed or app-injected) vs. **builder
factories** (need no `app` and can survive app-free regardless of D10). Serves constraint (a) / D9,
with the interaction-specific policy deferred to D10.

## 2. Why interactions are the special case (dossier 08 §0.3, §10.3)

Interactions are **not** thin data wrappers — they are entity models that are *also* clients.
`PartialInteraction` (`interactions/base_interactions.py:272`) both stores `app` and subclasses
`webhooks.ExecutableWebhook`, and the hierarchy defines ~17 helpers that call `self.app.rest.*` /
`self.app.cache.*`. They are constructed by the entity factory (not pure JSON-decoded through
msgspec), so — unlike wire entities — an `app` *could* in principle still be injected at construction.
That is exactly the D10 question:

- **Option 1 (app-less, max consistency):** interactions become pure data; every helper including
  `create_initial_response` moves to `rest.*`. Maximally breaking.
- **Option 2 (recommended in CONVENTIONS §8):** interactions are built via a non-declarative path
  that injects `app`, so latency-critical response sugar (`build_response`, `create_initial_response`)
  survives; the same methods are ALSO exposed on `rest.*`.

This file inventories the helpers for **both** options. The choice is in
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
Under app removal, `PartialInteraction` can **no longer** subclass an `app`-requiring base (dossier 08
§7.3, §10.3) — these 4 move to `rest.*` regardless of D10, or the mixin is reduced to a data protocol
(see [`04-users-webhooks-audit.md`](04-users-webhooks-audit.md) §3.4).

## 5. The action / builder split (the crux of D10 for interactions)

Dossier 08 §7.3–§7.4 establishes a critical distinction that neither option should blur:

### 5.1 Action helpers — genuinely need a client
`create_initial_response`, `edit_initial_response`, `delete_initial_response`,
`fetch_initial_response`, `create_modal_response`, `create_response` (autocomplete), `fetch_command`,
`fetch_guild`, `get_guild`, plus inherited `execute`/`fetch_message`/`edit_message`/`delete_message`.
These make HTTP/cache calls. Under **Option 1** they are removed; callers use e.g.:

```python
# before: await interaction.create_initial_response(ResponseType.MESSAGE_CREATE, "hi")
# after:  await rest.create_interaction_response(interaction.id, interaction.token,
#                                                ResponseType.MESSAGE_CREATE, "hi")
```
All identity data the call needs (`id`, `token`, `application_id`, `channel.id`, `guild_id`) are plain
Struct fields that survive (dossier 08 §10.3). Under **Option 2** these stay as methods on an
`app`-carrying interaction *and* are mirrored on `rest.*`.

### 5.2 Builder factories — need no `app`, survive app-free either way
`build_response`, `build_deferred_response`, `build_modal_response`, autocomplete `build_response`.
Dossier 08 §7.4 (verified): `rest.interaction_message_builder`/`_deferred_builder`/
`_autocomplete_builder`/`_modal_builder` (`impl/rest.py:4664-4683`) are one-line constructors that
capture **no** `app`; the builder classes (`impl/special_endpoints.py:1079/1108/1155/1426`) are plain
`attrs` with no `app` field and take `entity_factory` as a `build()` *call argument*. So these can be
reimplemented as direct constructor calls or module-level factories with **no client at all**:

```python
# app-free replacement (valid under BOTH options):
builder = special_endpoints.InteractionMessageBuilder(ResponseType.MESSAGE_CREATE)
```

This is the one place "remove all app helpers" is too blunt — keep the builder factories app-free so
ergonomics survive even if interactions go fully app-less. The `ComponentInteraction` builder
validators (`_IMMEDIATE_TYPES`/`_DEFERRED_TYPES`, raising `ValueError`) must be preserved in whatever
factory replaces them.

## 6. Strict-enum touch-points in interactions (dossier 08 §8, constraint b)

Four loose `Enum | int` unions in the interaction sub-models must become the bare strict enum
(unknown-value handling via the enum `_missing_` design, `../../02-enums/`):

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
the model-module plans, not this file — but note that if their parents lose `app`, so do they.

## 8. Step-by-step migration (both options)

1. Resolve D10 in [`../04-events-and-interactions-app-decision.md`](../04-events-and-interactions-app-decision.md)
   **before** touching interaction code.
2. **Regardless of D10:** `PartialInteraction` stops subclassing `webhooks.ExecutableWebhook`
   (`base_interactions.py:272`); the 4 inherited followup helpers move to `rest.*` or a data protocol
   (§4).
3. **Regardless of D10:** reimplement the 8 builder factories app-free (§5.2), preserving the
   `ComponentInteraction` type validators.
4. Apply the strict-enum change to the 4 sub-model fields (§6), coordinating with `../../02-enums/`.
5. **Option 1 path:** remove all action helpers (§5.1); rewrite examples to `rest.*`; delete the
   `app` field (`base_interactions.py:275`).
6. **Option 2 path:** keep action helpers on an `app`-carrying interaction; ensure the construction
   path injects `app`; mirror the response methods on `rest.*` for parity.
7. Catalog the user-visible surface change in
   `../../11-rollout/03-breaking-changes-and-changelog.md` (magnitude depends on the option chosen).

## 9. Affected files & symbols

| Path | Anchor | Change |
|---|---|---|
| `hikari/interactions/base_interactions.py` | 272, 275 | mixin/`app` field (option-dependent) |
| `hikari/interactions/base_interactions.py` | 356–789 | 8 direct helpers (action + `build_modal_response`) |
| `hikari/interactions/command_interactions.py` | 142–303 | 5 helpers (3 builder factories) |
| `hikari/interactions/component_interactions.py` | 110, 152 | 2 builder factories (+ validators) |
| `hikari/interactions/modal_interactions.py` | 78, 106 | 2 builder factories |
| `hikari/interactions/*.py` | §6 sites | 4 strict-enum fields |
| `hikari/impl/rest.py` | 4664–4683 | app-free builder factories (already app-free) |
| `hikari/impl/entity_factory.py` | interaction deserialize | `app=` injection depends on D10 |

## 10. Risks / gotchas

- **`create_initial_response` is latency-critical** for interaction acks (dossier 08 §10.3, §6). Its
  ergonomics/latency stakes are the core argument for Option 2 — do not remove it without the D10
  decision explicitly choosing Option 1.
- **Builder factories must not be lost** by an over-broad "remove all app helpers" pass (§5.2) — they
  need no `app`.
- **`ExecutableWebhook` inheritance breaks regardless** — plan the mixin's reduction to a data
  protocol before the interaction pass.
- **`webhook_id` false friend** — `PartialInteraction.webhook_id` (`base_interactions.py:350`) returns
  `self.application_id`, not an `app` reference (dossier 04 §8.7); a naive `self.app` grep will not
  match it, but a reviewer might mistake it.

## 11. Verification

1. If Option 1: `grep -n "self\.app" hikari/interactions/` → 0. If Option 2: only the injected `app`
   field + retained action helpers remain; response methods also reachable via `rest.*`.
2. Builder factories construct valid builders with no client in scope; `ComponentInteraction`
   validators still raise `ValueError` on out-of-set response types.
3. The 4 strict-enum fields decode an unknown Discord value via the enum `_missing_` pseudo-member
   (no `TypeError`), per `../../02-enums/`.
4. A round-trip test: `rest.create_interaction_response(interaction.id, interaction.token, ...)`
   reproduces `interaction.create_initial_response(...)` behavior.

## 12. Open questions

- **D10 (FLAGGED):** interactions app-less (Option 1) vs. app-injected with response sugar
  (Option 2) — [`../04-events-and-interactions-app-decision.md`](../04-events-and-interactions-app-decision.md),
  `../../00-overview/05-decisions-log.md`. Recommendation on record: Option 2 with `rest.*` parity.
- Whether the builder factories become interaction methods, module functions, or `special_endpoints`
  constructors — `../03-new-rest-methods-and-free-functions.md` §9.
- Fate of `ExecutableWebhook` as a data protocol — [`04-users-webhooks-audit.md`](04-users-webhooks-audit.md) §3.4.
