# Interactions

Purpose: migrate `hikari/interactions/` — `base_interactions.py` plus `command_interactions.py`,
`component_interactions.py`, `modal_interactions.py` (19 `@attrs.define` classes, 2 enums). Unlike the
pure data modules, interactions are today **entity models that are also clients**: `PartialInteraction`
stores `app`, subclasses `webhooks.ExecutableWebhook`, and the hierarchy defines ~17 direct + 4
inherited `self.app.*` response/followup helpers (dossier 08 §7.3). That surface is now **RESOLVED
(D10-interactions, maintainer): interactions are app-less** — the `app` field and the 9 action helpers
go (callers use `rest.*` directly), the 8 builder factories are kept and reimplemented app-free. The
decision record is `../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md`; the
mechanical recipe is `../03-app-removal-and-helpers/02-helper-method-inventory/06-interactions.md`.
This file details the **data-side** migration (frozen, strict enums, re-keying, polymorphism,
sibling-typed value) and applies that resolution in §4.

--------------------------------------------------------------------------------------------------

## 1. Objective

- Freeze the 19 classes (`frozen=True, kw_only=True`); id-only identity where `Unique`
  (`PartialInteraction`, `InteractionCallback`).
- Keep `InteractionType`/`ResponseType` as hikari's custom int enums (adopt #2770); strict-type the
  **5 loose `Enum | int`** fields (dossier 08 §8) and the `str | Locale` fields, decoded via the shared
  `dec_hook`.
- Preserve the residual transforms: `ResolvedOptionData` 6-map re-keying, member-vs-user branching,
  `authorizing_integration_owners` enum-int keys, polymorphic `interaction_metadata`, and the
  sibling-typed `CommandInteractionOption.value`.
- Model the interaction and interaction-metadata unions (`type`-tagged, raise on unknown).
- **Apply the resolved D10-interactions decision** (`../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md`):
  drop the `app` field and the `webhooks.ExecutableWebhook` base (unconditional), delete the 9 action
  helpers (callers move to `rest.*`), keep the 8 builder factories as app-free sync constructors (§4).

Decode classification: **P/T** throughout — interactions are built non-declaratively (context
injection, re-keying, sibling-typing), never `msgspec.json.decode`d straight into the public Struct.

--------------------------------------------------------------------------------------------------

## 2. Current state (file:line anchors)

### 2.1 Enums (`base_interactions.py`)
- `InteractionType` — `:74-91` (`APPLICATION_COMMAND=2`, `MESSAGE_COMPONENT=3`, `AUTOCOMPLETE=4`,
  `MODAL_SUBMIT=5`); already `int, enums.Enum`.
- `ResponseType` — `:93-157` (`MESSAGE_CREATE=4`..`LAUNCH_ACTIVITY=12`).

### 2.2 Callback + support models (`base_interactions.py`)
- `InteractionCallbackResponse` — `:159-167`; `interaction: InteractionCallback`, `resource:
  UndefinedOr[InteractionCallbackResource]`.
- `InteractionCallback(Unique)` — `:170-197`; `id` (hash), `type: InteractionType` (strict),
  `activity_instance_id`/`response_message_id` (`UndefinedOr`), two bools.
- `InteractionCallbackResource` — `:199-217`; `type: ResponseType`, `activity_instance`/`message`
  (`UndefinedOr`).
- `InteractionCallbackActivityInstance` — `:219-224`; `id: str`.
- `InteractionMember(guilds.Member)` — `:807-816`; adds `permissions: Permissions` to `Member`.
- `InteractionChannel(channels.PartialChannel)` — `:819-834`; adds `permissions`, `parent_id`,
  `thread_metadata: ThreadMetadata | None`.
- `ResolvedOptionData` — `:837-858`; **6 re-keyed Mappings** (`attachments`, `channels`, `members`,
  `messages`, `roles`, `users`), built by `_deserialize_resolved_option_data` (`entity_factory.py:2958`).

### 2.3 `PartialInteraction` and metadata (`base_interactions.py`)
- `PartialInteraction(snowflakes.Unique, webhooks.ExecutableWebhook)` — `:270-395`; **`app` field**
  (`:275`, `eq=False`, `SKIP_DEEP_COPY`). `id` (hash), `application_id`, `type: InteractionType`
  (strict), `token`, `version: int`, `app_permissions: Permissions | None`, `user: User`, `member:
  InteractionMember | None`, `channel: InteractionChannel`, `guild_id`, `guild_locale: str | Locale |
  None`, `locale: str | Locale`, `authorizing_integration_owners: Mapping[ApplicationIntegrationType,
  Snowflake]` (enum-keyed), `context: ApplicationContextType`, `entitlements: Sequence[Entitlement]`,
  `attachment_size_limit`. Properties `channel_id` (`:345`→`channel.id`), `webhook_id`
  (`:350`→`application_id`). Helpers `fetch_guild` (`:356`, rest), `get_guild` (`:384`, cache).
- `PartialInteractionMetadata` — `:398-418`; `interaction_id` (hash), **`type: InteractionType | int`**
  (`:406`, LOOSE), `user`, `authorizing_integration_owners` (enum-keyed), `original_response_message_id`.
- `MessageResponseMixin(PartialInteraction, Generic)` — `:421`; `fetch_initial_response` (`:426`),
  `create_initial_response` (`:450`), `edit_initial_response`, `delete_initial_response` — all
  `app.rest`.
- `ModalResponseMixin(PartialInteraction)` — `:755-804`; `create_modal_response` (`:760`, rest),
  `build_modal_response` (`:789`, builder factory).

### 2.4 Command interactions (`command_interactions.py`)
- `CommandInteractionOption` — `:77-106`; `name`, **`type: OptionType | int`** (`:85`, LOOSE),
  **`value: Snowflake | str | int | float | bool | None`** (`:88`, sibling-typed), `options:
  Sequence[Self] | None` (recursive).
- `AutocompleteInteractionOption(CommandInteractionOption)` — `:109-119`; `is_focused` (default False).
- `BaseCommandInteraction(PartialInteraction)` — `:122-166`; `command_id`, `command_name`,
  **`command_type: CommandType | int`** (`:136`, LOOSE), `registered_guild_id`; `fetch_command`
  (`:142`, rest).
- `CommandInteraction(BaseCommandInteraction, MessageResponseMixin, ModalResponseMixin)` — `:169-247`;
  `app_permissions`, `options`, `resolved: ResolvedOptionData | None`, `target_id`; `build_response`
  (`:190`, builder factory), `build_deferred_response` (`:218`, builder factory).
- `AutocompleteInteraction(BaseCommandInteraction)` — `:250-303`; `options`; `build_response` (`:258`,
  builder factory), `create_response` (`:295`, rest).
- `CommandInteractionMetadata(PartialInteractionMetadata)` — `:306-315`; `target_user`,
  `target_message_id`.

### 2.5 Component + modal interactions
- `ComponentInteraction(MessageResponseMixin, ModalResponseMixin)` — `component_interactions.py:84-185`;
  **positional (`@attrs.define(unsafe_hash=True, weakref_slot=False)` — NOT `kw_only`)**.
  **`component_type: ComponentType | int`** (`:90`, LOOSE), `custom_id`, `values`, `resolved`,
  `message: Message`; `build_response` (`:110`), `build_deferred_response` (`:152`).
- `ComponentInteractionMetadata(PartialInteractionMetadata)` — `:187-195`; `original_response_message_id`,
  `interacted_message_id`.
- `ModalInteraction(MessageResponseMixin)` — `modal_interactions.py:61-124`; `custom_id`, `message:
  Message | None`, `components: Sequence[ModalActionRowComponent]`; `build_response` (`:78`),
  `build_deferred_response` (`:106`).
- `ModalInteractionMetadata(PartialInteractionMetadata)` — `:127-137`; `original_response_message_id`,
  **`triggering_interaction_metadata: PartialInteractionMetadata`** (`:134`, recursive metadata).

Factory: `deserialize_interaction` (`entity_factory.py:3182`, dispatch `_interaction_type_mapping`
`:505-512`, raises on unknown `:3188-3190`); `deserialize_command_interaction` (`:3007`),
`deserialize_autocomplete_interaction` (`:3074`), `deserialize_component_interaction` (`:3275`),
`deserialize_modal_interaction` (`:3129`); `_deserialize_interaction_command_option` (`:2853`),
`_deserialize_resolved_option_data` (`:2958`), `_deserialize_interaction_metadata` (`:3813`, dispatch
`_interaction_metadata_mapping` `:513-519`, raises `:3819-3821`). `app=self._app` injected at
`:2947`/`:3047`/`:3104`/`:3159`/`:3307`.

--------------------------------------------------------------------------------------------------

## 3. Target design (data side)

### 3.1 Enums + strict fields
`InteractionType`/`ResponseType` stay custom int enums (adopt #2770;
`../02-enums/00-strategy-and-forward-compat.md`). Strict-type the 5 loose fields:
`PartialInteractionMetadata.type`→`InteractionType`, `CommandInteractionOption.type`→`OptionType`,
`BaseCommandInteraction.command_type`→`CommandType`, `ComponentInteraction.component_type`→
`ComponentType`; and `PartialInteraction.guild_locale`→`Locale | None`, `.locale`→`Locale` (drop the
`str |` arm). `CommandInteractionOption.value` stays the polymorphic `Snowflake | str | int | float |
bool | None` (not an enum union — leave it; see §3.3).

### 3.2 `ResolvedOptionData` re-keying + `InteractionMember`/`InteractionChannel`
```python
class ResolvedOptionData(msgspec.Struct, frozen=True, kw_only=True):     # T: 6 array->dict re-keys
    attachments: typing.Mapping[snowflakes.Snowflake, messages.Attachment]
    channels: typing.Mapping[snowflakes.Snowflake, InteractionChannel]
    members: typing.Mapping[snowflakes.Snowflake, InteractionMember]
    messages: typing.Mapping[snowflakes.Snowflake, messages.Message]
    roles: typing.Mapping[snowflakes.Snowflake, guilds.Role]
    users: typing.Mapping[snowflakes.Snowflake, users.User]
```
All 6 maps are re-keyed from Discord objects/arrays in `_deserialize_resolved_option_data` (dossier 05
§3f; `../05-entity-factory/02-hard-cases-and-transforms.md`). `InteractionMember(guilds.Member)` and
`InteractionChannel(channels.PartialChannel)` subclass entity Structs and add fields — feasibility is
governed by the entity dossiers (`05-guilds-members-roles.md`, `04-channels.md`); the
added-field + frozen-subclass pattern must be validated there.

### 3.3 Sibling-typed `CommandInteractionOption.value`
`value`'s runtime type is chosen by the sibling `type` (`_deserialize_interaction_command_option`
`entity_factory.py:2853-2870`): `USER`/`CHANNEL`/`ROLE`/`MENTIONABLE`/`ATTACHMENT` cast the raw value
to `Snowflake` via the module-level `_interaction_option_type_mapping` (`entity_factory.py:78-84`); the
autocomplete variant casts only when `is_focused`. msgspec has no field-typing-by-sibling mechanism, so
the field stays the broad union and the Snowflake cast stays a residual transform (dossier 05 §3j,
`../05-entity-factory/02-hard-cases-and-transforms.md`). `options` is recursive (`Sequence[Self]`) —
native.

### 3.4 `authorizing_integration_owners` enum-int keys
`Mapping[ApplicationIntegrationType, Snowflake]` keyed on `ApplicationIntegrationType(int(k))` from
**string** JSON keys (dossier 05 §6.13) — same shape as `applications.Application.
integration_types_config` (`09-applications-and-oauth.md` §3.4). Either rely on msgspec coercing the
stringified-int enum key (VERIFY) or re-key in the transform.

### 3.5 Interaction + metadata unions
- `deserialize_interaction` dispatches on `InteractionType` → `CommandInteraction`/
  `AutocompleteInteraction`/`ComponentInteraction`/`ModalInteraction`, **raises** on unknown — a
  `type`-tagged union that raises (matches `entity_factory.py:3188-3190`).
- `interaction_metadata` dispatches on `InteractionType` → `CommandInteractionMetadata`/
  `ComponentInteractionMetadata`/`ModalInteractionMetadata`, **raises** on unknown
  (`entity_factory.py:3819-3821`). `ModalInteractionMetadata.triggering_interaction_metadata` recurses
  into the same union (dossier 05 §4 interaction). Both in
  `../05-entity-factory/01-polymorphism-and-tagged-unions.md`.
- **member-vs-user branching**: `deserialize_command_interaction` reuses `member.user` as `user`
  (discord-api-docs#2568) — context resolution kept in the transform.

### 3.6 `ComponentInteraction` positional → kw_only
Convert `ComponentInteraction` from positional to `kw_only=True` (conventions §2; it is one of the 2
non-kw_only model classes, dossier 03 §2).

### 3.7 Frozen + copy machinery
Interactions are currently mutable `attrs.define` + `with_copy`; nothing mutates them post-construction
and the event/interaction managers never deep-copy them (dossier 08 §9/§10.5), so freeze freely and
drop `with_copy`/`SKIP_DEEP_COPY`.

--------------------------------------------------------------------------------------------------

## 4. The `app` / helper / builder outcome (D10-interactions — RESOLVED: app-less)

`PartialInteraction` carries `app` (`:275`) and subclasses `webhooks.ExecutableWebhook` (base requires
`app`); the hierarchy exposes ~17 direct + 4 inherited (`execute`/`fetch_message`/`edit_message`/
`delete_message`) `self.app.*` methods (dossier 08 §7.3). The maintainer has **RESOLVED**
D10-interactions: **interactions are app-less**, with the two categories treated differently (decision
record: `../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md`; mechanical recipe:
`../03-app-removal-and-helpers/02-helper-method-inventory/06-interactions.md`):

- **9 action helpers — DELETED** (`create_initial_response`, `edit/delete/fetch_initial_response`,
  `create_modal_response`, `create_response`, `fetch_command`, `fetch_guild`, `get_guild`). Every one
  is a pure delegation to an **existing** rest/cache method, and all the ids/tokens they injected
  (`id`, `token`, `application_id`, `guild_id`) are public Struct fields, so callers reproduce each
  call via `rest.*`/`cache.*` directly — same REST call, same wire latency; the 3-second interaction
  deadline is unaffected. The 4 inherited webhook helpers go with the `ExecutableWebhook` departure
  (unconditional; the mixin reduces to a data protocol, and the `webhook_id → application_id` shim
  property goes with it).
- **8 builder factories — KEPT, reimplemented app-free** (`build_response`, `build_deferred_response`,
  `build_modal_response`, autocomplete `build_response`). They only construct an **app-free** builder
  (`impl/rest.py:4664-4683` are one-line pure sync constructors; `impl/special_endpoints.py` builders
  hold no `app`, dossier 08 §7.4), so they stay struct methods that construct the `special_endpoints`
  builder directly with no client, preserving the `ComponentInteraction` type validators.
  **Consequence: the REST-bot flow (listener RETURNS a builder) survives UNCHANGED.**

Effects on this module: the `app` field (`:275`) is removed; `PartialInteraction` stops subclassing
`ExecutableWebhook`; the entity factory stops injecting `app` into interactions
(`entity_factory.py:2947/3047/3104/3159/3307`). This is the migration's largest ecosystem break
(every command framework's `ctx.respond` wraps `create_initial_response`) — the loss is ergonomic
only, cataloged with its replacement table in `../11-rollout/03-breaking-changes-and-changelog.md`.

--------------------------------------------------------------------------------------------------

## 5. Step-by-step migration

1. Adopt #2770 for `InteractionType`/`ResponseType` — keep them custom int enums; strict-type the 5
   loose fields + the `locale`/`guild_locale` `str |` arms.
2. Convert the callback/support models (`InteractionCallback*`, `InteractionMember`,
   `InteractionChannel`, `ResolvedOptionData`) to frozen Structs; keep the 6-map re-keying transform.
3. Convert `PartialInteraction` + metadata (frozen; enum-keyed `authorizing_integration_owners`);
   `ComponentInteraction` → kw_only.
4. Convert the command/component/modal interaction classes; keep the sibling-typed `value` transform
   and member-vs-user branching.
5. Model the interaction and interaction-metadata `type`-tagged unions (raise on unknown); keep the
   recursive `triggering_interaction_metadata`.
6. Execute the resolved D10-interactions removal (§4): delete the `app` field and the
   `ExecutableWebhook` base, delete the 9 action helpers (callers → `rest.*`), reimplement the 8
   builder factories app-free; drop `with_copy`/`SKIP_DEEP_COPY`.
7. Slim the factory: keep re-keying/context/sibling transforms; delete the interaction
   `app=self._app` injections (`entity_factory.py:2947/3047/3104/3159/3307`).

--------------------------------------------------------------------------------------------------

## 6. Affected files & symbols

| Path / anchor | Change |
|---|---|
| `interactions/base_interactions.py:74-157` | `InteractionType`/`ResponseType` stay custom; adopt #2770 |
| `interactions/base_interactions.py:159-224` | callback models → frozen Structs |
| `interactions/base_interactions.py:270-418` | `PartialInteraction`/metadata → frozen Structs; strict fields; enum-keyed map; `app` field REMOVED + `ExecutableWebhook` base dropped + action helpers deleted (D10-interactions resolved) |
| `interactions/base_interactions.py:807-858` | `InteractionMember`/`InteractionChannel`/`ResolvedOptionData` → Structs; 6-map re-keying |
| `interactions/command_interactions.py:77-315` | option/command interactions → Structs; sibling-typed `value`; strict enums |
| `interactions/component_interactions.py:84-195` | `ComponentInteraction`→kw_only Struct; strict `component_type` |
| `interactions/modal_interactions.py:61-137` | `ModalInteraction`/metadata → Structs; recursive metadata |
| `hikari/impl/entity_factory.py:2853-3319,3813-3821` | interaction/option/resolved/metadata transforms; interaction `app=self._app` injections REMOVED |
| `../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md` | D10-interactions decision record (RESOLVED: app-less; the action/factory split) |

--------------------------------------------------------------------------------------------------

## 7. Risks / gotchas

1. **The action-helper removal is the migration's largest ecosystem break** — every command
   framework's `ctx.respond` wraps `create_initial_response`. There is no wire-latency change (same
   REST call; the 3-second deadline is unaffected — the loss is ergonomic only); mitigate with the
   replacement table and downstream coordination in
   `../11-rollout/03-breaking-changes-and-changelog.md`.
2. **Builder factories must not be lost** by an over-broad "remove all app helpers" pass — they are
   app-free and are *reimplemented*, not deleted (dossier 08 §7.4); losing them would break the
   REST-bot return-a-builder flow for no constraint benefit.
3. **Sibling-typed `value`** — cannot be typed declaratively; the `Snowflake` cast for
   USER/CHANNEL/ROLE/MENTIONABLE/ATTACHMENT (and autocomplete's `is_focused` guard) stays a transform.
4. **`InteractionMember`/`InteractionChannel` subclass entity Structs and add fields** — frozen-Struct
   subclassing + extra fields must be validated in the entity dossiers; identity for `InteractionMember`
   rides on `guilds.Member`→`users.User` (`02-users.md`/`05-guilds-members-roles.md`).
5. **Enum-keyed `authorizing_integration_owners`** — string→IntEnum key coercion (shared with
   applications §3.4); VERIFY or re-key.
6. **Interaction + metadata unions raise on unknown** — preserve; also keep the recursive
   `triggering_interaction_metadata` in the metadata union.
7. **`ComponentInteraction` positional** — must become `kw_only`.

--------------------------------------------------------------------------------------------------

## 8. Verification

- Decode each interaction type → correct concrete class; unknown `type` → `UnrecognisedEntityError`.
- Decode a command interaction with a USER option → `value` is a `Snowflake`; a STRING option → `str`;
  an autocomplete non-focused option keeps the raw value.
- `ResolvedOptionData` maps are keyed by `Snowflake`; `member`/`user` reuse holds (`member.user is
  user` where applicable).
- `authorizing_integration_owners` keyed by `ApplicationIntegrationType`.
- Decode an interaction with modal metadata → `triggering_interaction_metadata` is the nested metadata
  Struct.
- App-less checks: `grep -rn "self\.app" hikari/interactions/` → 0; the builder factories still
  produce a valid `InteractionMessageBuilder` with no client in scope; the deleted action helpers'
  calls resolve via `rest.*` (e.g. `rest.create_interaction_response(interaction.id,
  interaction.token, ...)`); a `RESTBot` listener returning `interaction.build_response(...)` works
  unchanged.

--------------------------------------------------------------------------------------------------

## 9. Open questions / decisions

Cross-link `../00-overview/05-decisions-log.md`:

- **D10-interactions — RESOLVED (maintainer):** interactions are app-less; the 9 action helpers are
  deleted (callers → `rest.*`), the 8 builder factories are kept app-free, and the
  `ExecutableWebhook` departure is unconditional — recorded in
  `../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md`.
- **Enum-keyed dict coercion** — VERIFY stringified-int `IntEnum` keys (shared with applications).
- **Sibling-typed `value`** — kept as a transform (`../05-entity-factory/02-hard-cases-and-transforms.md`).
- **Frozen-subclass + added fields** for `InteractionMember`/`InteractionChannel` — VERIFY in the
  channels/guilds dossiers.
- **D5:** `UndefinedOr` on the callback models — keep `undefined.UNDEFINED` defaults.
