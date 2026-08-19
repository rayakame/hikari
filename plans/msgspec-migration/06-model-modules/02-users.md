# Users

Purpose: migrate `hikari/users.py` — the `PartialUser` → `User` → `OwnUser` hierarchy plus the two
value objects `AvatarDecoration` and `PrimaryGuild`. Users are referenced everywhere (member,
emoji creator, message author, interaction actor), so this lands early (dependency order,
`00-README.md` §3, after scalars). The module is a clean showcase of the four constraints: an
abstract-`app`-property to remove, ~11 `UndefinedOr` decoded tri-state fields, two strict custom
enums (adopting #2770), and a deep frozen hierarchy with id-only identity.

--------------------------------------------------------------------------------------------------

## 1. Objective

- Freeze the `PartialUserImpl`/`UserImpl`/`OwnUser` hierarchy (`frozen=True, kw_only=True, eq=False`)
  with id-only identity inherited from `snowflakes.Unique`.
- Remove the `app` field (1 declaration) and the abstract `app` property (2 sites); re-home the 4
  `self.app.*` helper methods (`../03-app-removal-and-helpers/02-helper-method-inventory/04-users-webhooks-audit.md`).
- Keep `UserFlag`/`PremiumType` as hikari's custom `Flag`/`Enum` (adopt #2770); strict-type the fields
  (drop the `| int`/`| str` arms), decoded via the shared `dec_hook`.
- Preserve the 34 CDN/property helpers that do NOT touch `app` (avatar/banner URL builders, mention,
  display-name logic).

Decode classification: **D** with a few **T** fields. `PartialUserImpl`/`UserImpl`/`OwnUser` are
flat renamed-scalar records (declarative once `field(name=...)` maps `avatar`→`avatar_hash` etc.),
except `accent_color` (Color hook), `avatar_decoration.expires_at` (epoch-millis, transform), and
`flags` (default `UserFlag.NONE` when key absent). `AvatarDecoration`/`PrimaryGuild` are **D** value
objects.

--------------------------------------------------------------------------------------------------

## 2. Current state (file:line anchors)

### 2.1 Enums
- `UserFlag(enums.Flag)` — `users.py:59-124`, badge bitfield (`1<<0`..`1<<51`, non-contiguous).
- `PremiumType(int, enums.Enum)` — `users.py:127-141` (NONE/NITRO_CLASSIC/NITRO/NITRO_BASIC).

### 2.2 Value objects (not `Unique`)
- `AvatarDecoration` — `users.py:144-203`; `@attrs.define(kw_only=True, weakref_slot=False)`; fields
  `asset_hash: str`, `sku_id: Snowflake`, `expires_at: datetime | None`; `make_url(...)` builds a CDN
  URL (no `app`). `expires_at` is decoded from an **epoch-millis** number (dossier 05 §4 user).
- `PrimaryGuild` — `users.py:206-274`; fields `identity_guild_id: Snowflake | None`,
  `identity_enabled: bool | None`, `tag: str | None`, `badge_hash: str | None`; `make_url(...)` CDN
  (no `app`; raises `ValueError` if id/hash missing).

### 2.3 Abstract bases
- `PartialUser(snowflakes.Unique, abc.ABC)` — `users.py:277-614`. Abstract `app` property
  (`:292-295`), abstract data properties (`avatar_decoration`, `avatar_hash`, `banner_hash`,
  `accent_color`, `discriminator`, `username`, `global_name`, `is_bot`, `is_system`, `flags`,
  `mention`, `primary_guild` — all `UndefinedOr`/`UndefinedNoneOr`), concrete `accent_colour` alias
  (`:320-323`), `display_name` (`:346-352`), and the **3 app helpers** `fetch_dm_channel`
  (`:387-407`), `fetch_self` (`:409-427`), `send` (`:429-614`).
- `User(PartialUser, abc.ABC)` — `users.py:617-861`. Overrides `app` (`:625-629`) and the data
  properties to non-`UndefinedOr` (full user), adds concrete CDN helpers `default_avatar_url`
  (`:664-674`), `display_avatar_decoration` (`:676-682`), `display_avatar_url` (`:684-687`),
  `display_banner_url` (`:689-695`), `make_avatar_url` (`:759-809`), `make_banner_url` (`:811-861`).

### 2.4 Concrete wire models
- `PartialUserImpl(PartialUser)` — `users.py:864-943`; `@attrs_extensions.with_copy` +
  `@attrs.define(unsafe_hash=True, kw_only=True, weakref_slot=False)`. `id` (`hash=True`), `app`
  field (`:876-878`, `SKIP_DEEP_COPY`), then 11 `UndefinedOr`/`UndefinedNoneOr` fields
  (`discriminator`, `username`, `global_name`, `avatar_decoration`, `avatar_hash`, `banner_hash`,
  `accent_color`, `is_bot`, `is_system`, `flags`, `primary_guild`). Concrete `mention`
  (`:923-935`), `__str__` (`:937-943`).
- `UserImpl(PartialUserImpl, User)` — `users.py:946-990`; re-declares the 11 fields as **non-**
  `UndefinedOr` full types (`discriminator: str`, `flags: UserFlag`, `accent_color: Color | None`,
  `primary_guild: PrimaryGuild | None`, …).
- `OwnUser(UserImpl)` — `users.py:993-1076`; adds `is_mfa_enabled: bool`,
  `locale: str | locales.Locale | None`, `is_verified: bool | None`, `email: str | None`,
  `premium_type: PremiumType | int | None`; overrides `fetch_self`→`fetch_my_user` (app helper),
  and `fetch_dm_channel`/`send` to `raise TypeError` (`NoReturn`, no app).

Factory sites (dossier 05 §7): `UserImpl` `app=self._app` at `entity_factory.py:4501`, `OwnUser` at
`:4520`; shared `_UserFields` intermediate at `entity_factory.py:124-138` parses `accent_color`
(int→Color), `avatar_decoration` (nested, epoch-millis expiry), `primary_guild` (nested), renames
`avatar`→`avatar_hash`; `deserialize_user` adds `flags=UserFlag(public_flags)` defaulting to
`UserFlag.NONE`.

--------------------------------------------------------------------------------------------------

## 3. Target design

### 3.1 Enums

```python
class UserFlag(enums.Flag):                     # stays custom Flag (../02-enums/00-strategy-and-forward-compat.md)
    NONE = 0; DISCORD_EMPLOYEE = 1 << 0; ...; RESTRICTED_COLLABORATOR = 1 << 51

class PremiumType(int, enums.Enum):             # stays custom Enum; #2770 mints an is_unknown member on a miss
    NONE = 0; NITRO_CLASSIC = 1; NITRO = 2; NITRO_BASIC = 3
```

### 3.2 Value objects → frozen Structs

```python
class AvatarDecoration(msgspec.Struct, frozen=True, kw_only=True):   # not Unique -> default eq ok
    asset_hash: str
    sku_id: snowflakes.Snowflake
    expires_at: datetime.datetime | None                # epoch-millis on wire -> T (see §3.5)
    def make_url(self, *, file_format=UNDEFINED, size=4096, lossless=True) -> files.URL: ...  # verbatim

class PrimaryGuild(msgspec.Struct, frozen=True, kw_only=True):
    identity_guild_id: snowflakes.Snowflake | None
    identity_enabled: bool | None
    tag: str | None
    badge_hash: str | None
    def make_url(self, *, ...) -> files.URL: ...        # verbatim, keeps the ValueError guard
```

### 3.3 Concrete hierarchy → frozen Structs (app-less)

`PartialUser`/`User` stay abstract but **lose the `app` abstract property** (`:292-295`, `:625-629`)
and the 3 app helpers move out (§3.4). The `Unique`-derived identity is retained; declare the impls
`eq=False` so msgspec inherits `Unique.__hash__`/`__eq__` (id-only identity per conventions §3–§4,
V1 RESOLVED, dossier 16).

```python
class PartialUserImpl(PartialUser, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    id: snowflakes.Snowflake
    # NO app field.
    discriminator: undefined.UndefinedOr[str] = undefined.UNDEFINED
    username: undefined.UndefinedOr[str] = undefined.UNDEFINED
    global_name: undefined.UndefinedNoneOr[str] = undefined.UNDEFINED
    avatar_decoration: undefined.UndefinedNoneOr[AvatarDecoration] = undefined.UNDEFINED
    avatar_hash: undefined.UndefinedNoneOr[str] = undefined.UNDEFINED   # field(name="avatar")
    banner_hash: undefined.UndefinedNoneOr[str] = undefined.UNDEFINED   # field(name="banner")
    accent_color: undefined.UndefinedNoneOr[colors.Color] = undefined.UNDEFINED
    is_bot: undefined.UndefinedOr[bool] = undefined.UNDEFINED           # field(name="bot")
    is_system: undefined.UndefinedOr[bool] = undefined.UNDEFINED        # field(name="system")
    flags: undefined.UndefinedOr[UserFlag] = undefined.UNDEFINED        # field(name="public_flags")
    primary_guild: undefined.UndefinedNoneOr[PrimaryGuild] = undefined.UNDEFINED

class UserImpl(PartialUserImpl, User, frozen=True, kw_only=True, eq=False):
    discriminator: str; username: str; global_name: str | None
    avatar_decoration: AvatarDecoration | None; avatar_hash: str | None; banner_hash: str | None
    accent_color: colors.Color | None; is_bot: bool; is_system: bool
    flags: UserFlag; primary_guild: PrimaryGuild | None

class OwnUser(UserImpl, frozen=True, kw_only=True, eq=False):
    is_mfa_enabled: bool
    locale: locales.Locale | None            # was `str | locales.Locale | None` -> strict (b)
    is_verified: bool | None
    email: str | None
    premium_type: PremiumType | None         # was `PremiumType | int | None` -> strict (b)
```

- The 11 `UndefinedOr` fields carry role (ii) tri-state (D5): `default=undefined.UNDEFINED` reproduces
  "partial payload omitted the key" (`../01-foundations/03-undefined-and-unset.md`). This is the
  canonical decoded-entity `UNDEFINED` case (`PartialMessage` is the other, dossier 09 §6.3).
- All non-`app` properties/methods port verbatim: `mention`, `__str__`, `display_name`,
  `accent_colour`, `default_avatar_url`, `display_avatar_*`, `make_avatar_url`, `make_banner_url`.
  None touch `app`; they use `self.id`/`self.discriminator`/`self.avatar_hash` (34 properties/helpers
  total across the two ABCs and impls).

### 3.4 app removal — the 4 helpers

| Helper | Location | `self.app.*` used | Re-home |
|---|---|---|---|
| `PartialUser.fetch_dm_channel` | `:387-407` | `app.rest.create_dm_channel(self.id)` | `rest.create_dm_channel(user.id)` |
| `PartialUser.fetch_self` | `:409-427` | `app.rest.fetch_user(self.id)` | `rest.fetch_user(user.id)` |
| `PartialUser.send` | `:429-614` | `app.cache.get_dm_channel_id` + `app.rest.create_message` (DM resolve+create) | **new free function / rest method** — no 1:1 equivalent (dossier 04; `../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md`) |
| `OwnUser.fetch_self` | `:1026-1045` | `app.rest.fetch_my_user()` | `rest.fetch_my_user()` |

`OwnUser.fetch_dm_channel` (`:1047-1050`) and `OwnUser.send` (`:1052-1076`) are `NoReturn` overrides
that only `raise TypeError` — they carry no `app` and can stay as guards or be dropped with `send`.
`PartialUser.send` is the only non-trivial one: it resolves a cached DM channel id then creates the
message, so it becomes a free function `send_dm(rest, user, ...)` (or a new `rest` convenience) —
enumerated in the new-rest-methods file. Remove the abstract `app` property from both ABCs.

### 3.5 Transform (T) fields

- `accent_color`: JSON int → `Color` via the scalar hook (declarative once typed `Color | None`).
- `avatar_decoration.expires_at`: **epoch-millis number**, not RFC3339 → must bypass native datetime
  decode (`time.unix_epoch_to_datetime`, incl. max/min clamp) via a field-specific hook or residual
  transform (conventions §4, `../05-entity-factory/02-hard-cases-and-transforms.md`).
- `flags`: absent-key default is `UserFlag.NONE` in the full `UserImpl`, not `UNDEFINED`
  (`deserialize_user`); set `default=UserFlag.NONE` on the concrete field, `UNDEFINED` on the partial.
- `locale` on `OwnUser`: native str-enum decode; drop the `str |` arm.

--------------------------------------------------------------------------------------------------

## 4. Step-by-step migration

1. Adopt #2770 for `UserFlag`/`PremiumType` — keep the custom enums, strict-type the fields
   (`../02-enums/`).
2. Convert `AvatarDecoration`, `PrimaryGuild` to frozen Structs; keep `make_url` verbatim; drop
   `with_copy` where present.
3. Remove the abstract `app` property from `PartialUser` (`:292-295`) and `User` (`:625-629`).
4. Extract the 4 `self.app` helpers per §3.4; `PartialUser.send` → free function in the new-rest file;
   delete `fetch_dm_channel`/`fetch_self`/`OwnUser.fetch_self` bodies (callers use `rest.*`).
5. Convert `PartialUserImpl` → frozen Struct: drop the `app` field, keep `id`, set the 11 tri-state
   fields to `default=undefined.UNDEFINED`, add `field(name=...)` for the renamed keys
   (`avatar`/`banner`/`bot`/`system`/`public_flags`).
6. Convert `UserImpl` (full types) and `OwnUser` (strict `locale`/`premium_type`); confirm the
   3-level frozen/kw_only/eq=False config inherits.
7. Wire `accent_color` (Color hook) and `avatar_decoration.expires_at` (epoch hook) into the residual
   factory / `_UserFields` slimmed transform.
8. Update `deserialize_user`/`deserialize_my_user` (`entity_factory.py:4495/4517`) to stop injecting
   `app=self._app`.

--------------------------------------------------------------------------------------------------

## 5. Affected files & symbols

| Path / anchor | Change |
|---|---|
| `hikari/users.py:59-141` | `UserFlag`/`PremiumType` stay custom; adopt #2770 (strict typing, `is_unknown`) |
| `hikari/users.py:144-274` | `AvatarDecoration`, `PrimaryGuild` → frozen Structs |
| `hikari/users.py:277-614` | `PartialUser`: drop abstract `app`; extract 3 app helpers |
| `hikari/users.py:617-861` | `User`: drop abstract `app`; CDN helpers stay |
| `hikari/users.py:864-990` | `PartialUserImpl`/`UserImpl` → frozen Structs, drop `app` field, tri-state defaults, key renames |
| `hikari/users.py:993-1076` | `OwnUser` → frozen Struct; strict `locale`/`premium_type`; `fetch_self`→rest |
| `hikari/impl/entity_factory.py:124-138,4476-4520` | `_UserFields`/`deserialize_user`/`deserialize_my_user`: drop `app`, keep `accent_color`/epoch/`flags` transforms |
| `../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md` | `PartialUser.send` DM resolve+create |

--------------------------------------------------------------------------------------------------

## 6. Risks / gotchas

1. **`Member`/`TeamMember` depend on `User` identity.** `guilds.Member(users.User, eq=False)`
   (`05-guilds-members-roles.md`) and `applications.TeamMember(users.User, eq=False)` inherit `User`'s
   `eq`/`hash`. The base identity is V1 RESOLVED (a frozen `eq=False` Struct over `Unique` keeps
   `Unique`'s id-only dunders, dossier 16); the module-specific residual is asserting that a *further*
   `eq=False` subclass still inherits them — the §8 identity check.
2. **`Member.app` is a property** (`guilds.py:514-518`) returning `self.user.app`, not a field.
   Removing `User.app` removes `Member.app` too — the member helper re-homing must account for it
   (`05-guilds-members-roles.md`).
3. **Tri-state vs full-type split** — the same field name is `UndefinedOr[str]` on `PartialUserImpl`
   and `str` on `UserImpl`; msgspec allows the subclass to redeclare, but the defaults differ
   (`UNDEFINED` vs required). Keep both.
4. **`avatar_decoration.expires_at` epoch** must not use native datetime decode (it is a number);
   losing the `unix_epoch_to_datetime` clamp changes out-of-range behavior (dossier 09 risk 6).
5. **`display_name` short-circuits on `UNDEFINED`** (`global_name or username`) — with `UNDEFINED`
   being falsy this still works, but confirm the D5 sentinel stays falsy (it does — dossier 09 §6.1).
6. **Deprecated `discriminator`** logic in `default_avatar_url` (`:664-674`) stays; do not drop the
   field during migration even though Discord sends `"0"`.

--------------------------------------------------------------------------------------------------

## 7. Verification

- Decode a partial user payload missing `username`/`global_name` → those fields are
  `undefined.UNDEFINED`, `id` present; `__str__` returns `"Partial user ID …"`.
- Decode a full user → `UserImpl` with `flags` a `UserFlag`, `accent_color` a `Color | None`,
  `avatar_decoration` an `AvatarDecoration | None`.
- Decode `OwnUser` with an unknown `locale` string → `Locale` pseudo-member (forward-compat), and a
  `premium_type` outside 0-3 → `PremiumType` pseudo-member.
- Identity: two `UserImpl` with equal `id` compare equal and hash equal regardless of other fields;
  frozen (attribute set raises).
- Grep proves no `self.app` remains in `users.py`; the 4 helpers resolve via `rest.*` /
  `send_dm(rest, …)` in caller tests.

--------------------------------------------------------------------------------------------------

## 8. Open questions / decisions

Cross-link `../00-overview/05-decisions-log.md`:

- **D5:** decoded-entity tri-state on `PartialUserImpl` — keep `undefined.UNDEFINED` defaults (VERIFY
  msgspec accepts `T | UndefinedType` unions with a non-UNSET default).
- **D9 / new-rest:** `PartialUser.send` (DM resolve+create) becomes a free function `send_dm(rest, …)`
  — confirm signature in `../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md`.
- **eq=False identity across two inheritance levels** (`User` → `Member`/`TeamMember`): V1 is
  RESOLVED for the base (`UniqueStruct` keeps `Unique`'s id-only dunders, dossier 16); the residual
  here is a module-specific assertion that a further `eq=False` subclass still inherits `Unique`'s
  `__eq__`/`__hash__` rather than reverting to object identity.
