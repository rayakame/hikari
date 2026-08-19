# Applications and OAuth2

Purpose: migrate `hikari/applications.py` — 18 model classes spanning the OAuth2 token hierarchy, the
`Application`/`Team`/`TeamMember` graph, activity instances, and role-connection metadata, plus 11
enums. This module is one of the **10 "dead app field"** modules (conventions §8): it carries 3 `app`
fields that no helper method reads, so they drop free of helper fallout.

--------------------------------------------------------------------------------------------------

## 1. Objective

- Freeze all 18 classes (`frozen=True, kw_only=True`); id-only identity where `Unique`.
- Drop the 3 **dead** `app` fields (`Team`, `InviteApplication`, `Application`) and the delegating
  `TeamMember.app` property; confirm nothing external reads `entity.app`.
- Keep the 11 enums as hikari's custom enums (adopt #2770): `ApplicationFlags` stays the custom `Flag`;
  the 6 int and 4 str enums stay custom `Enum`. Strict-type every enum field and the localization
  enum-keyed maps, decoded via the shared `dec_hook`.
- Preserve the residual transforms: hex→bytes `public_key`, enum-keyed `integration_types_config`,
  re-keyed `Team.members`, and the `expires_in` timedelta.
- Handle `TeamMember(users.User, eq=False)` identity delegation (shared shape with `guilds.Member`,
  `05-guilds-members-roles.md`).

Decode classification: the leaf records are **D**; `Application`/`Team`/the token family are **T**.

--------------------------------------------------------------------------------------------------

## 2. Current state (file:line anchors)

### 2.1 Enums
| Enum | Anchor | Kind (kept custom) |
|---|---|---|
| `ApplicationFlags` | `applications.py:83-113` | custom `enums.Flag` |
| `ApplicationEventWebhookStatus` | `applications.py:115-127` | int enum |
| `ApplicationEventWebhookType` | `applications.py:129-167` | **str** enum |
| `OAuth2Scope` | `applications.py:170-309` | **str** enum (dotted string values) |
| `ConnectionVisibility` | `applications.py:311-319` | int enum |
| `TeamMembershipState` | `applications.py:406-414` | int enum |
| `ActivityLocationKind` | `applications.py:700-708` | **str** enum (`"gc"`/`"pc"`) |
| `TokenType` | `applications.py:997-1008` | **str** enum |
| `ApplicationRoleConnectionMetadataRecordType` | `applications.py:1011-1037` | int enum |
| `ApplicationIntegrationType` | `applications.py:1088-1096` | int enum (dict-key, §3.4) |
| `ApplicationContextType` | `applications.py:1099-1110` | int enum |

### 2.2 Classes and their notable fields
- `OwnConnection` — `applications.py:322-359`; `id: str` (hash, third-party non-snowflake),
  `visibility: ConnectionVisibility | int`, `integrations: Sequence[guilds.PartialIntegration]`. **D.**
- `OwnGuild(guilds.PartialGuild)` — `applications.py:362-379`; `features: Sequence[str |
  GuildFeature]`, `is_owner`, `my_permissions: Permissions`, two approximate counts. **D/T.**
- `OwnApplicationRoleConnection` — `applications.py:382-403`; `platform_name`/`platform_username`,
  `metadata: Mapping[str, str]`. **D.**
- `TeamMember(users.User)` — `applications.py:417-548`; `@attrs.define(eq=False…)`. `membership_state:
  TeamMembershipState | int`, `permissions: Sequence[str]`, `team_id`, `user: User`. **`app` property
  delegates `self.user.app`** (`:438-442`); ~15 override properties delegate to `self.user`;
  `__hash__`/`__eq__` delegate to `self.user` (`:518-524`). **T (identity delegation).**
- `Team(snowflakes.Unique)` — `applications.py:551-630`; **dead `app` field** (`:556`,
  `SKIP_DEEP_COPY`), `name`, `icon_hash`, `members: Mapping[Snowflake, TeamMember]` (re-keyed),
  `owner_id`; `make_icon_url` (no `app`), `__str__`. **T (re-keyed members).**
- `InviteApplication(guilds.PartialApplication)` — `applications.py:633-697`; **dead `app` field**
  (`:638`), `cover_image_hash`, `public_key: bytes` (hex), `make_cover_image_url`. **T.**
- `ActivityLocation` — `applications.py:711-726`; `id: str`, `kind: ActivityLocationKind | str`,
  `channel_id`, `guild_id`. **D.**
- `ActivityInstance` — `applications.py:729-747`; `application_id`, `instance_id`, `launch_id`,
  `location: ActivityLocation`, `users: Sequence[Snowflake]`. **D.**
- `ApplicationInstallParameters` — `applications.py:750-759`; `scopes: Sequence[str]`, `permissions`.
- `Application(guilds.PartialApplication)` — `applications.py:762-887`; **dead `app` field** (`:767`),
  `owner: User`, `flags: ApplicationFlags`, `public_key: bytes` (hex), `team: Team | None`,
  `install_parameters`, `integration_types_config: Mapping[ApplicationIntegrationType,
  ApplicationIntegrationConfiguration]` (enum-keyed, §3.4), `event_webhooks_status:
  ApplicationEventWebhookStatus | int`, `event_webhooks_types: Sequence[ApplicationEventWebhookType |
  str]`, `make_cover_image_url`. **T.**
- `AuthorizationApplication(guilds.PartialApplication)` — `applications.py:890-914`; `public_key: bytes`
  (hex), nullable bot flags. **T.**
- `AuthorizationInformation` — `applications.py:917-936`; `application`, `expires_at: datetime`,
  `scopes: Sequence[OAuth2Scope | str]`, `user: User | None`. **D.**
- `PartialOAuth2Token` — `applications.py:939-962`; `access_token: str` (hash), `token_type: TokenType
  | str`, **`expires_in: datetime.timedelta`** (seconds number, §3.5), `scopes: Sequence[OAuth2Scope |
  str]`. **T (timedelta).**
- `OAuth2AuthorizationToken(PartialOAuth2Token)` — `applications.py:965-985`; `refresh_token`,
  `webhook: webhooks.IncomingWebhook | None`, `guild: guilds.RESTGuild | None`.
- `OAuth2ImplicitToken(PartialOAuth2Token)` — `applications.py:988-994`; `state: str | None`.
- `ApplicationRoleConnectionMetadataRecord` — `applications.py:1040-1064`; `type:
  …MetadataRecordType | int`, `key: str` (hash), `name`, `description`, `name_localizations`/
  `description_localizations: Mapping[Locale | str, str]` (`factory=dict`). **D.**
- `ApplicationIntegrationConfiguration` — `applications.py:1067-1073`; `oauth2_install_parameters:
  OAuth2InstallParameters | None`. **D.**
- `OAuth2InstallParameters` — `applications.py:1076-1085`; `scopes: Sequence[OAuth2Scope]`,
  `permissions`. **D.**

Free function `get_token_id` (`applications.py:1113-1136`) — unaffected.

--------------------------------------------------------------------------------------------------

## 3. Target design

### 3.1 Enums — strict custom (adopt #2770; `../02-enums/00-strategy-and-forward-compat.md`).
Strict-type every union field: `OwnConnection.visibility`→`ConnectionVisibility`,
`TeamMember.membership_state`→`TeamMembershipState`, `ActivityLocation.kind`→`ActivityLocationKind`,
`PartialOAuth2Token.token_type`→`TokenType`, all `scopes`→`Sequence[OAuth2Scope]`,
`event_webhooks_status`→`ApplicationEventWebhookStatus`,
`event_webhooks_types`→`Sequence[ApplicationEventWebhookType]`,
`ApplicationRoleConnectionMetadataRecord.type`→`ApplicationRoleConnectionMetadataRecordType`,
`OwnGuild.features`→`Sequence[GuildFeature]` (`05-guilds-members-roles.md`).

### 3.2 Dead `app` fields
Drop the `app` field on `Team` (`:556`), `InviteApplication` (`:638`), `Application` (`:767`) and their
factory injections (`entity_factory.py:717`/`2513`/`751`). Remove `TeamMember.app` property
(`:438-442`) — it delegates to `self.user.app`, which no longer exists. No helper methods depend on
these (this module is in the 10-dead-app-fields set, conventions §8); confirm via grep that no external
code reads `application.app`/`team.app`/`invite_application.app`.

### 3.3 `TeamMember(users.User, eq=False)`
```python
class TeamMember(users.User, frozen=True, kw_only=True, eq=False):
    membership_state: TeamMembershipState        # strict
    permissions: typing.Sequence[str]
    team_id: snowflakes.Snowflake
    user: users.User
    # ~15 override properties delegate to self.user; __hash__/__eq__ delegate to self.user
```
Identity is delegated to the wrapped `user` (`__eq__`/`__hash__` at `:518-524`). This is the same
pattern as `guilds.Member` — the `eq=False` + inherited/hand-written dunders must survive msgspec
`frozen=True` (conventions §2 VERIFY, and note that `User` itself already relies on the inherited
`Unique` dunders). Keep the hand-written `__hash__`/`__eq__` that delegate to `self.user`.

### 3.4 Enum-keyed `integration_types_config` (hard case)
`Application.integration_types_config: Mapping[ApplicationIntegrationType, …]` is decoded from a JSON
object whose **keys are strings** (`"0"`, `"1"`) that the factory casts via
`ApplicationIntegrationType(int(k))` (dossier 05 §6.13, `deserialize_application:703`). msgspec supports
`IntEnum` dict keys, but the JSON keys arrive as strings, so either (a) type the field
`Mapping[ApplicationIntegrationType, …]` and rely on msgspec coercing the string key to the IntEnum
(VERIFY msgspec accepts stringified-int enum keys), or (b) re-key in the residual transform. Same shape
as interactions' `authorizing_integration_owners` (`11-interactions.md` §3.4). Detailed in
`../05-entity-factory/02-hard-cases-and-transforms.md`.

### 3.5 Other transforms
- **hex→bytes `public_key`** (`Application`/`InviteApplication`/`AuthorizationApplication`): wire is a
  hex string, field is `bytes` (`bytes.fromhex(payload["verify_key"])`, `entity_factory.py:759`). Field
  renamed (`verify_key`→`public_key`) + hex-decode → residual transform / field hook (conventions §4).
- **`expires_in` timedelta**: Discord sends seconds as a bare number; msgspec native timedelta expects
  ISO-8601 duration → unusable (conventions §4). Keep the `datetime.timedelta(seconds=…)` conversion in
  the residual factory.
- **`Team.members`** array→`{member.id: member}` re-keying (dossier 05 §3f).
- **localization maps** `name_localizations`/`description_localizations`: `Mapping[Locale, str]` keyed
  on a `Locale` str-enum; `factory=dict`→`default_factory=dict`.

--------------------------------------------------------------------------------------------------

## 4. Step-by-step migration

1. Adopt #2770 for the 11 enums (1 flag, 6 int, 4 str) — keep them custom, strict-type the fields.
2. Convert the leaf records (`OwnConnection`, `OwnApplicationRoleConnection`, `ActivityLocation`,
   `ActivityInstance`, `ApplicationInstallParameters`, `OAuth2InstallParameters`,
   `ApplicationIntegrationConfiguration`, `AuthorizationInformation`,
   `ApplicationRoleConnectionMetadataRecord`) to frozen Structs; strict enums + localization maps.
3. Convert `TeamMember` (`eq=False`, identity delegation) and `Team` (drop dead `app`, re-keyed
   members).
4. Convert the `Application` family (drop dead `app`; hex `public_key`; enum-keyed
   `integration_types_config`; nested `team`; strict `flags`/`event_webhooks_*`).
5. Convert the OAuth2 token hierarchy (`PartialOAuth2Token`→`OAuth2AuthorizationToken`/
   `OAuth2ImplicitToken`); `expires_in` timedelta transform; strict `token_type`/`scopes`.
6. Convert `OwnGuild` (inherits `guilds.PartialGuild`); strict `features`.
7. Slim the factory: drop the 3 `app=self._app` injections; keep the hex/timedelta/re-keying/enum-key
   transforms.

--------------------------------------------------------------------------------------------------

## 5. Affected files & symbols

| Path / anchor | Change |
|---|---|
| `hikari/applications.py:83-1110` | 11 enums stay custom; adopt #2770 (strict fields, `is_unknown`) |
| `hikari/applications.py:322-403` | `OwnConnection`/`OwnGuild`/`OwnApplicationRoleConnection` → Structs |
| `hikari/applications.py:417-630` | `TeamMember`(eq=False)/`Team` → Structs; drop dead `app`; re-keyed members |
| `hikari/applications.py:633-914` | `InviteApplication`/`Application`/`AuthorizationApplication` → Structs; hex `public_key`; enum-keyed config; drop dead `app` |
| `hikari/applications.py:917-1085` | OAuth2 tokens + install/config records → Structs; `expires_in` timedelta |
| `hikari/applications.py:1040-1064` | `ApplicationRoleConnectionMetadataRecord` → Struct; localization maps |
| `hikari/impl/entity_factory.py:703-759` | `deserialize_application`: drop app, keep hex/enum-key transforms |
| `hikari/impl/entity_factory.py:717,751,2513` | drop `Team`/`Application`/`InviteApplication` app injection |
| `05-guilds-members-roles.md` | `GuildFeature`, `PartialGuild`/`PartialApplication` bases |

--------------------------------------------------------------------------------------------------

## 6. Risks / gotchas

1. **`TeamMember` identity delegation** — `eq=False` + hand-written `__hash__`/`__eq__` delegating to
   `self.user` must survive frozen; it inherits from `users.User`, so this rides on the same
   two-level `eq=False`+`Unique` VERIFY as `guilds.Member` (conventions §2, `02-users.md` risk 1).
2. **Enum-keyed dict from string JSON keys** — `integration_types_config` (and interactions'
   `authorizing_integration_owners`) need the string→IntEnum key coercion verified or re-keyed.
3. **hex `public_key`** — three classes decode `verify_key` hex→`bytes`; a plain `bytes` field would
   base64-decode under msgspec, not hex-decode, so this MUST be a transform/field hook.
4. **`expires_in` timedelta** — native msgspec timedelta is ISO-8601; the seconds-number field must
   stay a residual conversion.
5. **Dead app fields** — dropping is safe only if nothing reads `entity.app`; grep before removing.
   `TeamMember.app` (delegating) must also go and any caller updated to `team_member.user`-based access.
6. **`OwnConnection.id` is a string** (third-party account id, not a snowflake) — keep it a plain `str`
   hash field; do not route through the Snowflake hook.

--------------------------------------------------------------------------------------------------

## 7. Verification

- Decode an `Application` → `flags` an `ApplicationFlags`, `public_key` the hex-decoded `bytes`,
  `integration_types_config` keyed by `ApplicationIntegrationType`, `team.members` a
  `Mapping[Snowflake, TeamMember]`; no `app` attribute exists.
- Decode a `PartialOAuth2Token` → `token_type` a `TokenType`, `expires_in` a `timedelta`, `scopes` a
  sequence of `OAuth2Scope`.
- `TeamMember` equality: two team members wrapping equal users compare equal and hash equal.
- Decode an unknown `OAuth2Scope`/`ActivityLocationKind` string → str-enum `is_unknown` pseudo-member
  (forward-compat).
- Grep proves no `self.app` / `app` field remains in `applications.py`.

--------------------------------------------------------------------------------------------------

## 8. Open questions / decisions

Cross-link `../00-overview/05-decisions-log.md`:

- **eq=False + `Unique` through `User`→`TeamMember`** — the two-level identity VERIFY (shared with
  `guilds.Member`).
- **Enum-keyed dict coercion** — VERIFY msgspec accepts stringified-int `IntEnum` dict keys, else
  re-key in the transform (`../05-entity-factory/02-hard-cases-and-transforms.md`).
- **Dead app fields** — confirm no external reader of `application.app`/`team.app`/
  `invite_application.app` before removal (conventions §8).
