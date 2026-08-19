# Invites

Purpose: migrate `hikari/invites.py` — 3 enums, the `InviteCode` ABC mixin, and 5 wire models
(`VanityURL`, `InviteGuild`, `InviteRole`, `Invite`, `InviteWithMetadata`). The module carries 2
**dead** `app` fields (`VanityURL.app`, `Invite.app`) that call no `self.app.*` — they drop with zero
helper fallout — plus two subclasses that inherit `app` from `guilds.PartialGuild`/`PartialRole`. The
central complexity is the `_InviteFields` intermediate, the `guild`/`channel` vs `guild_id`/`channel_id`
context split, the `role_ids`-from-`roles` fallback, and `InviteRole`'s sibling `color`/`colors` typing.

--------------------------------------------------------------------------------------------------

## 1. Objective

- Freeze all 5 invite Structs; drop the 2 **dead** `app` fields (`VanityURL.app` `invites.py:121`,
  `Invite.app` `invites.py:356`) with no helper re-homing (confirmed: **no `self.app` reference exists
  in `invites.py`** — this is one of the 10 dead-`app` modules, conventions §8,
  `../03-app-removal-and-helpers/01-app-field-removal.md`).
- Keep the 3 enums as hikari's custom `Enum`/`Flag` (adopt strict typing from PR
  hikari-py/hikari#2770) and drop the `InviteType | int` / `TargetType | int` tolerance unions
  (`../02-enums/03-strict-enum-field-inventory.md`).
- Preserve the `InviteType.GUILD` default when the gateway omits `type` (`entity_factory.py:2538`).
- Preserve `InviteRole`'s `color`/`colors` (+`colour`/`colours`) sibling typing and the tolerant
  `features` enum-array cast.

Decode classification: `Invite` and `InviteWithMetadata` are **T** (the `_InviteFields` intermediate,
`guild`/`channel` context split, `role_ids`-from-`roles` fallback, `InviteType` default, `max_age`
timedelta and computed `expires_at`). `InviteGuild` is **T** (inherits `PartialGuild`, `features`
enum-array, nested `welcome_screen`, renamed `icon`/`splash`/`banner` hashes). `InviteRole` is **T**
(sibling `color`/`colors`). `VanityURL` is near-**D** once `app` is dropped.

--------------------------------------------------------------------------------------------------

## 2. Current state (file:line anchors)

### 2.1 Enums
- `TargetType(int, enums.Enum)` `invites.py:66` (STREAM=1, EMBEDDED_APPLICATION=2).
- `InviteType(int, enums.Enum)` `invites.py:77` (GUILD=0, GROUP_DM=1, FRIEND=2).
- `InviteFlags(enums.Flag)` `invites.py:91` (NONE=0, IS_GUEST_INVITE=1<<0).

### 2.2 Models
- `InviteCode(abc.ABC)` `invites.py:101` — pure mixin: abstract `code` property `:106` + `__str__`
  building `https://discord.gg/{code}` `:111`. No fields.
- `VanityURL(InviteCode)` `invites.py:118` — `app` `:121` (**dead**), `code` (hash) `:126`, `uses` `:129`.
- `InviteGuild(guilds.PartialGuild)` `invites.py:134` — inherits `PartialGuild` (which owns the `app`
  field, removed in `05-guilds-members-roles.md`); adds `features: Sequence[str | GuildFeature]` `:137`,
  `splash_hash`/`banner_hash`/`description` `:140-150`, `verification_level: GuildVerificationLevel | int`
  `:153`, `vanity_url_code` `:156`, `welcome_screen: WelcomeScreen | None` `:163`, `nsfw_level` `:166`.
  `make_splash_url` `:169` / `make_banner_url` `:214` use `routes.*` (no `app`).
- `InviteRole(guilds.PartialRole)` `invites.py:269` — `color: Color` `:276`, `colors: ColorGradient`
  `:279`, `position` `:286`, `icon_hash` `:289`, `unicode_emoji: UnicodeEmoji | None` `:292`;
  `colour`/`colours` alias properties `:296`/`:301`, `make_icon_url` `:305` (no `app`).
- `Invite(InviteCode)` `invites.py:353` — `app` `:356` (**dead**), `code` (hash) `:361`,
  `type: InviteType | int` `:364`, `guild: InviteGuild | None` `:372`, `guild_id` `:379`,
  `channel: PartialChannel | None` `:385`, `channel_id` `:392`, `inviter: User | None` `:399`,
  `target_type: TargetType | int | None` `:402`, `target_user`/`target_application` `:405-408`,
  `guild_scheduled_event: ScheduledEvent | None` `:411`, `flags: InviteFlags` `:414`,
  `roles: Sequence[InviteRole]` `:417`, `role_ids: Sequence[Snowflake]` `:426`,
  `approximate_active_member_count`/`approximate_member_count` `:429-435`, `expires_at` `:441`.
- `InviteWithMetadata(Invite)` `invites.py:451` — `uses` `:458`, `max_uses: int | None` `:461`,
  `max_age: timedelta | None` `:469`, `is_temporary` `:475`, `created_at` `:478`,
  a bare `expires_at: datetime | None` re-annotation `:481` (docstring override, not a new field),
  `uses_left` property `:488`.

### 2.3 Factory (residual transform sources)
- `deserialize_vanity_url` `entity_factory.py:2474` — `uses=int(payload["uses"])`.
- `_set_invite_attributes` `entity_factory.py:2477` builds the `_InviteFields` intermediate:
  builds `InviteGuild` inline `:2484` (`features=[GuildFeature(f) for f in ...]`, renamed
  `icon`/`splash`/`banner`, nested `welcome_screen`), the `guild`/`guild_id` and `channel`/`channel_id`
  context split `:2478-2508`, `InviteType(payload.get("type", InviteType.GUILD))` `:2538`,
  `flags=InviteFlags(payload.get("flags", 0))` `:2550`, and the `role_ids`-from-`roles` fallback
  `:2531-2534`.
- `_deserialize_invite_role` `entity_factory.py:2557` — sibling `colors` typing: `ColorGradient` from
  the `colors` object when present, else `ColorGradient.of(payload["color"])` from the flat int
  `:2558-2561`; `unicode_emoji` via the `UnicodeEmoji` hook `:2564`.
- `deserialize_invite` `:2578` / `deserialize_invite_with_metadata` `:2607` — the latter computes
  `max_age = timedelta(seconds=raw_max_age)` and `expires_at = created_at + max_age` when
  `raw_max_age > 0` `:2615-2617`.

--------------------------------------------------------------------------------------------------

## 3. Target design

### 3.1 Enums → strict custom (adopt #2770)
```python
class TargetType(int, enums.Enum): ...     # unchanged custom Enum; #2770 mints is_unknown pseudo-members
class InviteType(int, enums.Enum): ...
class InviteFlags(enums.Flag): ...         # custom Flag kept (already mints pseudo-members)
```
The enum class definitions are unchanged — hikari keeps its fast custom `Enum`/`Flag`
(`../02-enums/00-strategy-and-forward-compat.md`). PR hikari-py/hikari#2770 makes the shared
`_EnumMeta.__call__` (`hikari/internal/enums.py:154`) mint an `is_unknown` pseudo-member instance on an
unrecognised value and drops the `| int`/`| str` field unions. Fields decode through the shared
`dec_hook` (`t(obj)`), which returns an instance of `t` because #2770 guarantees the pseudo-member
(`../01-foundations/02-custom-scalar-types-and-hooks.md`). Drop `InviteType | int` (`Invite.type`),
`TargetType | int | None` (`Invite.target_type`), `GuildVerificationLevel | int`
(`InviteGuild.verification_level`); unknown values become `is_unknown` pseudo-members that preserve
forward-compat.

### 3.2 InviteCode mixin, VanityURL, Invite
```python
class InviteCode(abc.ABC):                         # unchanged: __slots__=(), abstract code, __str__
    ...

class VanityURL(InviteCode, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    code: str
    uses: int                                       # int(...) on wire; typed int decodes natively
    # NO app

class Invite(InviteCode, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    code: str
    type: InviteType = InviteType.GUILD             # default when gateway omits (T-preserved)
    guild: InviteGuild | None = None
    guild_id: snowflakes.Snowflake | None = None
    channel: channels.PartialChannel | None = None
    channel_id: snowflakes.Snowflake | None = None
    inviter: users.User | None = None
    target_type: TargetType | None = None
    target_user: users.User | None = None
    target_application: applications.InviteApplication | None = None
    guild_scheduled_event: scheduled_events.ScheduledEvent | None = None
    flags: InviteFlags = InviteFlags.NONE
    roles: typing.Sequence[InviteRole] = ()
    role_ids: typing.Sequence[snowflakes.Snowflake] = ()
    approximate_active_member_count: int | None = None
    approximate_member_count: int | None = None
    expires_at: datetime.datetime | None = None
    # NO app

class InviteWithMetadata(Invite, frozen=True, kw_only=True, eq=False):
    uses: int
    max_uses: int | None
    max_age: datetime.timedelta | None              # per-field timedelta hook (seconds)
    is_temporary: bool
    created_at: datetime.datetime
    @property
    def uses_left(self) -> int | None: ...          # verbatim (invites.py:488)
```
- Identity: `VanityURL`/`Invite` hash by `code` today (`code` is the sole `hash=True` field). They are
  **not** `snowflakes.Unique` — `eq`/`hash` are by `code`, not a snowflake. Declaring the Structs
  `eq=False` would fall back to object identity, changing semantics. **Recommendation:** hand-write a
  small `__eq__`/`__hash__` over `code` (or a shared `_CodeIdentity` mixin mirroring `Unique` but keyed
  on `code`). Flag under §8 / `../00-overview/05-decisions-log.md`.
- `InviteWithMetadata.expires_at` (`invites.py:481`) is a docstring-only re-annotation of the inherited
  field; in msgspec drop the re-declaration and keep the inherited field (a subclass re-annotation with
  no new default is redundant).
- `max_age` is a bare-seconds number on the wire (not ISO8601 duration) — msgspec native `timedelta`
  is unusable; use a per-field `Annotated[timedelta, "seconds"]` hook or keep the residual conversion
  (conventions §4, `../01-foundations/02-custom-scalar-types-and-hooks.md`).

### 3.3 InviteGuild, InviteRole
```python
class InviteGuild(guilds.PartialGuild, frozen=True, kw_only=True, eq=False):  # PartialGuild drops app upstream
    features: typing.Sequence[guilds.GuildFeature]   # tolerant array; pseudo-members replace str fallback
    splash_hash: str | None = msgspec.field(name="splash")
    banner_hash: str | None = msgspec.field(name="banner")
    description: str | None
    verification_level: guilds.GuildVerificationLevel
    vanity_url_code: str | None
    welcome_screen: guilds.WelcomeScreen | None
    nsfw_level: guilds.GuildNSFWLevel
    # make_splash_url / make_banner_url: verbatim (routes.*, no app)

class InviteRole(guilds.PartialRole, frozen=True, kw_only=True, eq=False):
    color: colors.Color                              # flat int via Color hook
    colors: colors.ColorGradient                     # T: `colors` object OR ColorGradient.of(color)
    position: int
    icon_hash: str | None = msgspec.field(name="icon")
    unicode_emoji: emojis.UnicodeEmoji | None        # UnicodeEmoji hook
    @property
    def colour(self): return self.color              # verbatim
    @property
    def colours(self): return self.colors
    # make_icon_url: verbatim
```
- `InviteGuild.features` is a tolerant enum array: `GuildFeature` is an open custom `str` enum, so the
  `str | GuildFeature` union collapses to bare `GuildFeature` with #2770's `__call__` minting
  `is_unknown` pseudo-members for unknown features — the `data_binding.cast_variants_array`
  swallow-and-skip helper
  (`data_binding.py:411-438`) is no longer needed for scalar enum arrays (it stays only for
  polymorphic-variant arrays that can raise `UnrecognisedEntityError`).
- `InviteRole.colors` (sibling typing, dossier 05 §3j) cannot be declarative — a residual transform
  builds it from the `colors` object when present else `ColorGradient.of(color)`
  (`../05-entity-factory/02-hard-cases-and-transforms.md`).
- Renamed hash keys (`icon`/`splash`/`banner` → `*_hash`) are declarative via `msgspec.field(name=…)`.

### 3.4 The `_InviteFields` intermediate and context split
`_InviteFields` (`entity_factory.py:_InviteFields`) de-dups the shared parse between `Invite` and
`InviteWithMetadata`. It survives in the residual factory: `guild`/`guild_id` and `channel`/`channel_id`
are populated from whichever the payload supplies (gateway sends only IDs; REST sends the objects), and
`role_ids` falls back to `[r.id for r in roles]` when the payload omits `role_ids`
(`entity_factory.py:2531-2534`). These are **T** context/computed fields — msgspec cannot derive them
declaratively.

--------------------------------------------------------------------------------------------------

## 4. Step-by-step migration

1. Adopt #2770's strict custom enums (keep custom `Enum`/`Flag`, `../02-enums/`); drop the
   `InviteType`/`TargetType`/`GuildVerificationLevel` tolerance unions.
2. Convert `VanityURL` and `Invite` to frozen Structs; drop both **dead** `app` fields; add the
   `code`-keyed `__eq__`/`__hash__`; set defaults (`type=GUILD`, `flags=NONE`, empty `roles`/`role_ids`).
3. Convert `InviteGuild`/`InviteRole` to frozen Structs subclassing the app-less
   `PartialGuild`/`PartialRole`; wire renamed hashes (`field(name=…)`), `features` array,
   `color` (hook), `colors` (sibling **T**), `unicode_emoji` (hook); keep alias properties and
   `make_*_url`.
4. Convert `InviteWithMetadata`; drop the redundant `expires_at` re-annotation; add the per-field
   `max_age` seconds hook; keep `uses_left`.
5. Keep the `_InviteFields` intermediate + `_set_invite_attributes` in the residual factory for the
   context split, `InviteType` default, and `role_ids` fallback; keep `_deserialize_invite_role`'s
   sibling `colors` transform.
6. Update `deserialize_vanity_url`/`deserialize_invite`/`deserialize_invite_with_metadata` to stop
   injecting `app`.

--------------------------------------------------------------------------------------------------

## 5. Affected files & symbols

| Path / anchor | Change |
|---|---|
| `hikari/invites.py:66-91` (enums) | 3 enums stay custom (#2770 strict typing); strict fields |
| `hikari/invites.py:118-131` (`VanityURL`) | frozen Struct; drop dead `app`; `code` identity |
| `hikari/invites.py:134-264` (`InviteGuild`) | frozen Struct(PartialGuild); renamed hashes; `features` array; nested `welcome_screen` |
| `hikari/invites.py:269-348` (`InviteRole`) | frozen Struct(PartialRole); `color`/`colors` sibling typing; alias props |
| `hikari/invites.py:353-447` (`Invite`) | frozen Struct; drop dead `app`; `code` identity; defaults |
| `hikari/invites.py:451-496` (`InviteWithMetadata`) | frozen Struct; drop redundant re-annotation; `max_age` seconds hook |
| `hikari/impl/entity_factory.py:2474-2637` | drop `app`; keep `_InviteFields`, context split, `role_ids` fallback, `InviteRole` `colors` transform |
| `../05-entity-factory/02-hard-cases-and-transforms.md` | context split, sibling `colors`, `role_ids` fallback |
| `../03-app-removal-and-helpers/01-app-field-removal.md` | the 2 dead `app` fields |
| `05-guilds-members-roles.md`, `09-applications-and-oauth.md`, `17-scheduled-events.md` | base/reference types |

--------------------------------------------------------------------------------------------------

## 6. Risks / gotchas

1. **`code`-keyed identity, not snowflake.** `VanityURL`/`Invite` are NOT `Unique`; they hash/eq by
   `code`. `eq=False` alone falls back to object identity — must hand-write `__eq__`/`__hash__` over
   `code` or reuse a `code`-keyed mixin.
2. **Dead `app`, but only for own fields.** `VanityURL.app`/`Invite.app` drop cleanly; `InviteGuild`/
   `InviteRole` inherit `app` from `PartialGuild`/`PartialRole` — those removals live in
   `05-guilds-members-roles.md`, not here.
3. **Sibling `colors` typing** — forgetting the `colors`-object-else-`ColorGradient.of(color)` branch
   yields a wrong gradient for non-gradient roles.
4. **`role_ids` fallback** is derived from `roles` when absent (`entity_factory.py:2531-2534`) — a
   computed value not present in every payload; keep it a residual transform, not a declarative list.
5. **`InviteType` default** — the gateway omits `type`; the field default `InviteType.GUILD` must be
   preserved (`entity_factory.py:2538`).
6. **`max_age` unit** — a bare seconds number, not ISO8601; msgspec native `timedelta` is unusable.

--------------------------------------------------------------------------------------------------

## 7. Verification

- Decode a REST invite (objects present) and a gateway invite (only `guild_id`/`channel_id`, no `type`):
  the former populates `guild`/`channel`; the latter leaves them `None`, sets `type == InviteType.GUILD`,
  and `role_ids` derives from `roles` or the raw `role_ids`.
- Decode an `InviteRole` with a `colors` object → `colors` is that gradient; with only flat `color` →
  `colors == ColorGradient.of(color)`; `colour`/`colours` aliases resolve; `unicode_emoji` is a
  `UnicodeEmoji`.
- Decode an `InviteWithMetadata` with `max_age > 0` → `max_age` is a `timedelta`, `expires_at ==
  created_at + max_age`; with `max_age == 0` → both `None`.
- Identity: two invites with equal `code` are equal and equal-hash; usable as dict keys.
- Strict enums: unknown `GuildFeature` string / `InviteType` int → pseudo-member (forward-compat).
- Grep: no `self.app` and no `app=` construction remains for invite entities.

--------------------------------------------------------------------------------------------------

## 8. Open questions / decisions

Cross-link `../00-overview/05-decisions-log.md`:
- **`code`-keyed identity** for `VanityURL`/`Invite` under frozen `eq=False` — hand-written dunders vs a
  shared `code` identity mixin (extends the conventions §2 `Unique`/`eq=False` decision to a non-snowflake key).
- **D5:** invite decoded fields use `None`/defaults, not `UNDEFINED` — no tri-state fields here.
- **`max_age` per-field timedelta hook** (seconds) — settle the `Annotated[timedelta, unit]` mechanism in
  `../01-foundations/02-custom-scalar-types-and-hooks.md`.
- **Sibling `colors` transform** and **`role_ids` fallback** live in
  `../05-entity-factory/02-hard-cases-and-transforms.md`.
