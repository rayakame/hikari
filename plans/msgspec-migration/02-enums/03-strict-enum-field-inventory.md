# Strict-Enum Field Inventory — Every `| int` / `| str` to Remove

Purpose: the master checklist for constraint (b). Every entity field, cache view model, entity_factory
`_Fields` helper, and localization map that carries a `SomeEnum | int` / `SomeEnum | str` tolerance
union, transcribed in module order from dossier 02 Part C, so a developer can tick them off. Also
separates the orthogonal method-parameter `| int` lenience (which does **not** touch msgspec decode)
and flags two pre-existing typing bugs to fix during the sweep.

Once the enum types carry forward-compat themselves — the custom `Flag` already mints a pseudo-member,
and PR hikari-py/hikari#2770 makes the custom `Enum` do the same (`01-flags-migration.md`,
`02-int-and-str-enums-migration.md`) — these unions are redundant **and** illegal under msgspec (an
`Enum | int` union is a hard `TypeError` — dossier 13 §15). This file is the removal manifest. PR
#2770 lands this exact typing sweep upstream (`changes/2770.breaking.md`: "model fields and REST
parameters are now typed with only the enum/flag type instead of a union with its raw type"), so the
migration adopts #2770 rather than re-deriving the tables below; they remain the authoritative
site-by-site checklist for reviewing that sweep.

Totals (dossier 02 Part C): ~150 `SomeEnum | int|str` occurrences overall; **67 on entity fields**.
Dossier 13 §10 counts **114** `X | int` field occurrences across models by a broader grep — the
delta is str-enum unions and cache/factory mirrors; treat the tables below as the authoritative
site-by-site list.

--------------------------------------------------------------------------------------------------

## 1. Objective

- Enumerate every deserialization-output union to convert to a bare strict enum.
- Keep method-parameter unions (input lenience) as a **separate, deferred** decision.
- Fix `entity_factory.py:152` (wrong enum, copy-paste) and `:166` (reversed union order) while here.

--------------------------------------------------------------------------------------------------

## 2. Entity fields typed `SomeEnum | int` / `| str` (dossier 02 §C.1)

These are the true deserialization targets — drop the union to the bare enum. Grouped by module, in
file order.

### 2.1 Channels / components / interactions

| file:line | field | current annotation | target |
|---|---|---|---|
| `channels.py:333` | `type` | `PermissionOverwriteType \| int` (attrs `converter=PermissionOverwriteType`) | `PermissionOverwriteType` |
| `channels.py:372` | `type` | `ChannelType \| int` | `ChannelType` |
| `channels.py:1406` | `video_quality_mode` | `VideoQualityMode \| int` | `VideoQualityMode` |
| `channels.py:1439` | `video_quality_mode` | `VideoQualityMode \| int` | `VideoQualityMode` |
| `components.py:267` | `type` | `ComponentType \| int` | `ComponentType` |
| `components.py:304` | `style` | `ButtonStyle \| int` | `ButtonStyle` |
| `interactions/component_interactions.py:90` | `component_type` | `ComponentType \| int` | `ComponentType` |
| `interactions/command_interactions.py:85` | `type` | `OptionType \| int` | `OptionType` |
| `interactions/command_interactions.py:136` | `command_type` | `CommandType \| int` | `CommandType` |
| `interactions/base_interactions.py:406` | `type` | `InteractionType \| int` | `InteractionType` |

### 2.2 Messages

| file:line | field | current annotation | target |
|---|---|---|---|
| `messages.py:392` | `type` | `MessageActivityType \| int` | `MessageActivityType` |
| `messages.py:413` | `type` | `MessageReferenceType \| int` | `MessageReferenceType` |
| `messages.py:531` | `type` | `MessageType \| int` | `MessageType` |
| `messages.py:720` | `type` | `undefined.UndefinedOr[MessageType \| int]` | `undefined.UndefinedOr[MessageType]` |
| `messages.py:1567` | `type` | `MessageType \| int` | `MessageType` |

Note `messages.py:720` keeps its `UndefinedOr[...]` wrapper (an omitted-key sentinel, orthogonal to
enum strictness — see `../01-foundations/03-undefined-and-unset.md`); only the inner `| int` drops.

### 2.3 Guilds / templates / integrations

| file:line | field | current annotation | target |
|---|---|---|---|
| `guilds.py:511` | `guild_flags` | `GuildMemberFlags \| int` Flag | `GuildMemberFlags` (dead union, §6) |
| `guilds.py:1458` | `type` | `IntegrationType \| str` | `IntegrationType` |
| `guilds.py:1473` | `expire_behavior` | `IntegrationExpireBehaviour \| int \| None` | `IntegrationExpireBehaviour \| None` |
| `guilds.py:2979` | `default_message_notifications` | `GuildMessageNotificationsLevel \| int` | `GuildMessageNotificationsLevel` |
| `guilds.py:2992` | `explicit_content_filter` | `GuildExplicitContentFilterLevel \| int` | `GuildExplicitContentFilterLevel` |
| `guilds.py:3007` | `mfa_level` | `GuildMFALevel \| int` | `GuildMFALevel` |
| `guilds.py:3026` | `premium_tier` | `GuildPremiumTier \| int` | `GuildPremiumTier` |
| `guilds.py:3064` | `verification_level` | `GuildVerificationLevel \| int` | `GuildVerificationLevel` |
| `templates.py:82` | `verification_level` | `GuildVerificationLevel \| int` | `GuildVerificationLevel` |
| `templates.py:85` | `default_message_notifications` | `GuildMessageNotificationsLevel \| int` | `GuildMessageNotificationsLevel` |
| `templates.py:90` | `explicit_content_filter` | `GuildExplicitContentFilterLevel \| int` | `GuildExplicitContentFilterLevel` |

### 2.4 Invites / stickers / errors / users

| file:line | field | current annotation | target |
|---|---|---|---|
| `invites.py:153` | `verification_level` | `GuildVerificationLevel \| int` | `GuildVerificationLevel` |
| `invites.py:364` | `type` | `InviteType \| int` | `InviteType` |
| `invites.py:402` | `target_type` | `TargetType \| int \| None` | `TargetType \| None` |
| `stickers.py:163` | `format_type` | `StickerFormatType \| int` | `StickerFormatType` |
| `errors.py:250` | `code` | `ShardCloseCode \| int \| None` | `ShardCloseCode \| None` |
| `errors.py:282` | `status` | `http.HTTPStatus \| int` (stdlib enum) | `http.HTTPStatus` (already msgspec-native) |
| `users.py:1020` | `premium_type` | `PremiumType \| int \| None` | `PremiumType \| None` |

### 2.5 Applications / OAuth / monetization

| file:line | field | current annotation | target |
|---|---|---|---|
| `applications.py:358` | `visibility` | `ConnectionVisibility \| int` | `ConnectionVisibility` |
| `applications.py:422` | `membership_state` | `TeamMembershipState \| int` | `TeamMembershipState` |
| `applications.py:719` | `kind` | `ActivityLocationKind \| str` | `ActivityLocationKind` |
| `applications.py:831` | `event_webhooks_status` | `ApplicationEventWebhookStatus \| int` | `ApplicationEventWebhookStatus` |
| `applications.py:834` | `event_webhooks_types` | `Sequence[ApplicationEventWebhookType \| str]` | `Sequence[ApplicationEventWebhookType]` |
| `applications.py:928` | `scopes` | `Sequence[OAuth2Scope \| str]` | `Sequence[OAuth2Scope]` |
| `applications.py:951` | `token_type` | `TokenType \| str` | `TokenType` |
| `applications.py:957` | `scopes` | `Sequence[OAuth2Scope \| str]` | `Sequence[OAuth2Scope]` |
| `applications.py:1044` | `type` | `ApplicationRoleConnectionMetadataRecordType \| int` | `ApplicationRoleConnectionMetadataRecordType` |
| `monetization.py:129` | `type` | `SKUType \| int` | `SKUType` |
| `monetization.py:161` | `type` | `EntitlementType \| int` | `EntitlementType` |

### 2.6 Commands / audit logs / auto-mod / presences

| file:line | field | current annotation | target |
|---|---|---|---|
| `commands.py:135` | `type` | `OptionType \| int` | `OptionType` |
| `commands.py:167` | `channel_types` | `Sequence[channels.ChannelType \| int] \| None` | `Sequence[channels.ChannelType] \| None` |
| `commands.py:493` | `type` | `CommandPermissionType \| int` (attrs `converter=CommandPermissionType`) | `CommandPermissionType` |
| `audit_logs.py:295` | `key` | `AuditLogChangeKey \| str` | `AuditLogChangeKey` |
| `audit_logs.py:522` | `type` | `PermissionOverwriteType \| int` | `PermissionOverwriteType` |
| `audit_logs.py:720` | `action_type` | `AuditLogEventType \| int` | `AuditLogEventType` |
| `auto_mod.py:193` | `presets` | `Sequence[AutoModKeywordPresetType \| int]` | `Sequence[AutoModKeywordPresetType]` |
| `presences.py:340` | `type` | `ActivityType \| int` (attrs `converter=ActivityType`) | `ActivityType` |
| `presences.py:408` | `desktop` | `Status \| str` | `Status` |
| `presences.py:411` | `mobile` | `Status \| str` | `Status` |
| `presences.py:414` | `web` | `Status \| str` | `Status` |
| `presences.py:434` | `visible_status` | `Status \| str` | `Status` |
| `webhooks.py:483` | `type` | `WebhookType \| int` | `WebhookType` |

--------------------------------------------------------------------------------------------------

## 3. Cache view models — `hikari/internal/cache.py` (dossier 02 §C.1)

Mirror the entity fields in the cache layer; drop identically.

| file:line | field | current annotation | target |
|---|---|---|---|
| `internal/cache.py:342` | `type` | `invites.InviteType \| int` | `invites.InviteType` |
| `internal/cache.py:346` | `target_type` | `invites.TargetType \| int \| None` | `invites.TargetType \| None` |
| `internal/cache.py:442` | `guild_flags` | `guilds.GuildMemberFlags \| int` Flag | `guilds.GuildMemberFlags` (§6) |
| `internal/cache.py:553` | `format_type` | `stickers_.StickerFormatType \| int` | `stickers_.StickerFormatType` |
| `internal/cache.py:598` | `type` | `presences.ActivityType \| int` | `presences.ActivityType` |
| `internal/cache.py:683` | `visible_status` | `presences.Status \| str` | `presences.Status` |
| `internal/cache.py:755` | `type` | `messages.MessageType \| int` | `messages.MessageType` |

--------------------------------------------------------------------------------------------------

## 4. entity_factory `_Fields` helpers — `hikari/impl/entity_factory.py` (dossier 02 §C.1)

Internal deserialization scratch structs; they carry the union too. In the declarative end-state these
become wire structs (`../05-entity-factory/00-architecture-and-decode-strategy.md`); in the
incremental phase they are attrs helpers whose annotations should still be tightened.

| file:line | field | current annotation | target |
|---|---|---|---|
| `entity_factory.py:122` | `_GuildChannelFields.type` | `ChannelType \| int` | `ChannelType` |
| `entity_factory.py:134` | `_IntegrationFields.type` | `IntegrationType \| str` | `IntegrationType` |
| `entity_factory.py:144` | `_GuildFields.features` | `list[GuildFeature \| str]` | `list[GuildFeature]` |
| `entity_factory.py:150` | `_GuildFields.verification_level` | `GuildVerificationLevel \| int` | `GuildVerificationLevel` |
| `entity_factory.py:151` | `_GuildFields.default_message_notifications` | `GuildMessageNotificationsLevel \| int` | `GuildMessageNotificationsLevel` |
| `entity_factory.py:152` | `_GuildFields.explicit_content_filter` | `GuildVerificationLevel \| int` **BUG** | `GuildExplicitContentFilterLevel` (see §4.1) |
| `entity_factory.py:153` | `_GuildFields.mfa_level` | `GuildMFALevel \| int` | `GuildMFALevel` |
| `entity_factory.py:164` | `_GuildFields.premium_tier` | `GuildPremiumTier \| int` | `GuildPremiumTier` |
| `entity_factory.py:166` | `_GuildFields.preferred_locale` | `str \| locales.Locale` **reversed** | `locales.Locale` (see §4.2) |
| `entity_factory.py:226` | `_InviteFields.type` | `InviteType \| int` | `InviteType` |
| `entity_factory.py:234` | `_InviteFields.target_type` | `TargetType \| int \| None` | `TargetType \| None` |

### 4.1 Bug: `entity_factory.py:152` wrong enum (copy-paste)

`_GuildFields.explicit_content_filter` is annotated `GuildVerificationLevel | int` but the field holds
an **explicit-content-filter** level. Confirmed in source (line 152, adjacent to
`verification_level` at 150 and `mfa_level` at 153). Correct type is `GuildExplicitContentFilterLevel`
(`guilds.py:89`). The runtime deserialization uses the right enum
(`GuildExplicitContentFilterLevel(payload[...])` in `_GuildFields.from_payload`), so this is a typing
bug only — but under msgspec the annotation drives decode, so it **must** be fixed or the field would
decode against the wrong value set. Fix as part of this sweep; note it in the changelog as a
type-annotation correction.

### 4.2 Reversed union: `entity_factory.py:166`

`_GuildFields.preferred_locale` is `str | locales.Locale` (value type first) rather than the
conventional `locales.Locale | str`. Cosmetic today; under msgspec the whole union is dropped to
`locales.Locale` regardless of order, so this normalizes away.

--------------------------------------------------------------------------------------------------

## 5. Localization enum-keyed maps — `Mapping[Locale | str, str]` (dossier 02 §C.2)

`Locale` is used as a **dict key**. Unknown-locale tolerance is on the KEY type; the hook decodes the
key through `Locale(raw)`, and #2770's pseudo-member `__call__` covers unknown keys (verified for
`dict[...]` keys, dossier 15 §3). Drop the key union to bare `Locale`.

| file:line | field |
|---|---|
| `applications.py:1056` | `name_localizations: Mapping[locales.Locale \| str, str]` → `Mapping[Locale, str]` |
| `applications.py:1061` | `description_localizations: Mapping[locales.Locale \| str, str]` → `Mapping[Locale, str]` |
| `commands.py:121` | `name_localizations` → `Mapping[Locale, str]` |
| `commands.py:190` | `name_localizations` → `Mapping[Locale, str]` |
| `commands.py:195` | `description_localizations` → `Mapping[Locale, str]` |
| `commands.py:258` | `name_localizations` → `Mapping[Locale, str]` |
| `commands.py:453` | `description_localizations` → `Mapping[Locale, str]` |

Builder mirrors (`impl/special_endpoints.py:1496,1610`) and REST method-param mirrors
(`api/rest.py`, `impl/rest.py`, `api/special_endpoints.py`) are input-side — treat with §7
(input-param lenience), not here. On **encode**, the shared `enc_hook` emits the key `.value` not
`.name`; verify and pin (`02-int-and-str-enums-migration.md` §6 risk 4).

--------------------------------------------------------------------------------------------------

## 6. Dead Flag `| int` unions (dossier 02 §C.5)

`GuildMemberFlags` is a Flag; `GuildMemberFlags(raw)` always returns a Flag pseudo-member (never a bare
int), so the `| int` is dead/defensive. Drop it — the custom `Flag` is kept, so unknown bits stay
inside the flag pseudo-member exactly as today, and the reasoning holds (`01-flags-migration.md`
§2.3). PR #2770 drops this union in its typing sweep.

| file:line | field | action |
|---|---|---|
| `guilds.py:511` | `guild_flags: GuildMemberFlags \| int` | → `GuildMemberFlags` |
| `internal/cache.py:442` | `guild_flags: guilds.GuildMemberFlags \| int` | → `GuildMemberFlags` |

Before removing, grep callers for a branch on the int arm (dossier 02 §C.5 says none exists). No other
Flag-with-`| int` was found (`MessageFlag`, `Permissions`, `ChannelFlag`, `GuildSystemChannelFlag`,
`GuildNSFWLevel` are already strict — §8).

--------------------------------------------------------------------------------------------------

## 7. Method-parameter `| int` lenience — ORTHOGONAL, keep by default (dossier 02 §C.3)

These are **input** unions in REST/builder signatures that let a caller pass a raw int/str where an
enum is expected. They are **not decoded by msgspec** (they are function parameters, not struct
fields), so constraint (b) does not touch them. Decision D2 recommends **keeping** them for API
ergonomics; tighten later only if desired (a separate, non-blocking decision).

Representative surface (~80 sites, non-exhaustive; dossier 02 §C.3):

- `hikari/api/rest.py`, `hikari/impl/rest.py`: e.g. `video_quality_mode: UndefinedOr[VideoQualityMode
  | int]` (`api/rest.py:199`, `impl/rest.py:1081`), `default_forum_layout: UndefinedOr[ForumLayoutType
  | int]`, `default_sort_order: UndefinedOr[ForumSortOrderType | int]`, `flags: UndefinedType | int |
  MessageFlag`, `default_member_permissions: UndefinedType | int | Permissions`, `type: ChannelType |
  int`, `type_: ResponseType | int`, `event_type: AutoModEventType | int`, `scopes: Sequence[OAuth2Scope
  | str]`, `token_type: TokenType | str | None`, `type: CommandType | int`, `event_type:
  UndefinedOr[AuditLogEventType | int]`.
- `hikari/api/special_endpoints.py`, `hikari/impl/special_endpoints.py`: builder fields/getters —
  `_flags: UndefinedType | int | messages.MessageFlag` (`impl:1124`), `_default_member_permissions:
  UndefinedType | int | permissions_.Permissions` (`impl:1490`), `_type: ComponentType | int`
  (`impl:2006`), `set_style(style: TextInputStyle | int)`, `_assert_can_add_type(type_: ComponentType |
  int)`.
- Model-level convenience methods: `webhooks.py:104,120`, `channels.py:542,1044,1207`,
  `users.py:449,1073`, `messages.py:1129`, `guilds.py:2482-2483,2580`.
- entity_factory local params/casts: `entity_factory.py:989` (`key: AuditLogChangeKey | str`), `:1012`
  (`action_type: AuditLogEventType | int`), `:2289` (`expire_behavior: IntegrationExpireBehaviour | int
  | None`), `:2665` (`channel_types: Sequence[ChannelType | int] | None`).

Action: leave unchanged in the enum PRs. If the maintainer later tightens them, do it as a separate
API-ergonomics change (`../11-rollout/03-breaking-changes-and-changelog.md`).

--------------------------------------------------------------------------------------------------

## 8. Already-strict fields — the target shape (dossier 02 §C.4)

No change; listed so the sweep does not touch them. These are already bare enums because they are
Flags (pseudo-member on miss) or the maintainer already chose strictness:

- `messages.py:1589` `flags: MessageFlag`.
- `permissions_.Permissions` fields: `templates.py:52`, `command_interactions.py:178`,
  `base_interactions.py:293,815,824`, `channels.py:336,341` (`allow`/`deny`), `applications.py:372,758,
  1084`, `guilds.py:1209`, `commands.py:240`.
- `errors.py:525` `intents: intents_.Intents`; `intents_.Intents` params elsewhere.
- entity_factory strict helpers: `_GuildChannelFields.flags: ChannelFlag` (`entity_factory.py:126`),
  `_GuildFields.system_channel_flags: GuildSystemChannelFlag` (`:158`), `_GuildFields.nsfw_level:
  GuildNSFWLevel` (`:168`).

--------------------------------------------------------------------------------------------------

## 9. Step-by-step

1. Adopt PR #2770 first (`01-flags-migration.md`, `02-int-and-str-enums-migration.md`) — the fields
   cannot become bare enums until the custom `Enum` mints a pseudo-member on a miss (the custom `Flag`
   already does). #2770 lands both the pseudo-member behavior and this union-drop sweep together.
2. Sweep §2 (entity fields), §3 (cache view models), §4 (factory helpers), §5 (localization keys), §6
   (dead Flag unions): remove the `| int` / `| str` arm, keeping any `| None` and `UndefinedOr[...]`
   wrappers.
3. Fix `entity_factory.py:152` (§4.1) and normalize `:166` (§4.2).
4. Delete the now-redundant attrs `converter=` casts (`channels.py:333`, `presences.py:340`,
   `commands.py:493`) and manual `EnumType(raw)` casts in the factory where msgspec decode takes over
   (declarative phase; keep them in the incremental phase).
5. Leave §7 (input-param unions) and §8 (already-strict) untouched.
6. Run mypy/pyright: because `enums.pyi` already presents these as stdlib enums, type-checker churn is
   expected to be small (`04-enums-module-and-machinery.md` §3).

--------------------------------------------------------------------------------------------------

## 10. Affected files & symbols

| Path | Rows here | Category |
|---|---|---|
| model modules (`channels.py`, `messages.py`, `guilds.py`, `invites.py`, `stickers.py`, `errors.py`, `users.py`, `applications.py`, `monetization.py`, `commands.py`, `audit_logs.py`, `auto_mod.py`, `presences.py`, `webhooks.py`, `templates.py`, `components.py`, `interactions/*`) | §2 | entity fields |
| `hikari/internal/cache.py` | §3 | cache view models |
| `hikari/impl/entity_factory.py` | §4 (incl. 2 bugs) | `_Fields` helpers |
| `applications.py`, `commands.py` | §5 | localization key maps |
| `guilds.py`, `internal/cache.py` | §6 | dead Flag unions |
| `api/rest.py`, `impl/rest.py`, `api/special_endpoints.py`, `impl/special_endpoints.py`, model convenience methods | §7 | input params (deferred) |

--------------------------------------------------------------------------------------------------

## 11. Risks / gotchas

1. **Order dependency.** Removing a field union before #2770's pseudo-member `__call__` lands (custom
   `Enum`) would make the field raise on unknown values through the hook. Do §9 step 1 first. (Flags
   already mint a pseudo-member, so flag-field drops are order-independent.)
2. **`converter=` removal changes construction.** Fields with attrs `converter=` (e.g.
   `channels.py:333`) currently coerce on manual construction too; removing the converter means
   hand-constructed instances must pass an already-cast enum. Affects tests/fixtures
   (`../10-testing/`).
3. **The two bugs are behavior-adjacent.** Fixing `entity_factory.py:152` narrows the annotation to the
   correct enum; if any downstream code relied on the (wrong) `GuildVerificationLevel` typing it will
   now mismatch — but runtime already used the right enum, so the fix is safe. Call it out in the
   changelog.
4. **`http.HTTPStatus`** at `errors.py:282` / `net.py:65` is a genuine stdlib `enum.IntEnum` and is
   msgspec-native (no hook needed); dropping `| int` is safe and needs no pseudo-member handling
   (unknown HTTP statuses are rare, and `HTTPStatus` has its own tolerance).

--------------------------------------------------------------------------------------------------

## 12. Open questions / decisions

Cross-linked to `../00-overview/05-decisions-log.md` (D2):

1. Tighten input-param unions (§7) or keep lenient? Recommendation: keep lenient (orthogonal).
2. `entity_factory.py:152` fix — land in the enum PR (recommended) or separately as a standalone bugfix
   first? Recommendation: standalone bugfix first, so the enum PR is a pure refactor.
3. Should `errors.py:250` `code: ShardCloseCode | None` also gain unknown-value tolerance (close codes
   are a custom int enum)? Yes — it is in the 55 int-enum set and inherits #2770's pseudo-member
   `__call__` automatically.
