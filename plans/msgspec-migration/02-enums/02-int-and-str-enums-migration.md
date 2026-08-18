# Int and Str Enums Migration — 55 + 12 Enums to Stdlib

Purpose: reparent hikari's 55 int enums and 12 str enums off `enums.Enum` onto stdlib `enum`, attach a
shared value-preserving `_missing_` mixin so unknown Discord values still decode under strict field
types, and preserve today's `str()` semantics. This is the harder half of the enum migration: unlike
flags, scalar enums have **no** native forward-compat under msgspec (unknown value → `ValidationError`;
dossier 02 §E.2), and `SomeEnum | int` is a hard `TypeError` (dossier 13 §15).

Serves constraint (b) and decision D2 (`../00-overview/05-decisions-log.md`).

--------------------------------------------------------------------------------------------------

## 1. Objective

- Convert `class X(int, enums.Enum)` → `class X(_MissingMixin, int, enum.Enum)` (55 types) and
  `class X(str, enums.Enum)` → `class X(_MissingMixin, str, enum.Enum)` (12 types). **Not**
  `enum.StrEnum` / `enum.IntEnum` where subtle `str()` differences bite — see §6 (though `IntEnum` is
  acceptable for the int family if `str()` is overridden).
- Attach a shared `_missing_` that mints a **value-preserving** pseudo-member on a lookup miss, cached
  with a bounded dict mirroring `_MAX_CACHED_MEMBERS = 4096` (`enums.py:39`).
- Keep every field annotated with the bare strict enum; the `| int`/`| str` drop is inventoried in
  `03-strict-enum-field-inventory.md`.
- Preserve `str(member)` output per family (int → member name; str → member value).

--------------------------------------------------------------------------------------------------

## 2. Current state

### 2.1 The 55 int enums (dossier 02 §B.3), `class X(int, enums.Enum)`

`EventPrivacyLevel` (`scheduled_events.py:55`), `ScheduledEventType` (`:62`), `ScheduledEventStatus`
(`:75`); `SKUType` (`monetization.py:39`), `EntitlementType` (`:79`), `EntitlementOwnerType` (`:108`);
`PollLayoutType` (`polls.py:91`); `WebhookType` (`webhooks.py:60`); `TargetType` (`invites.py:66`),
`InviteType` (`:77`); `ApplicationEventWebhookStatus` (`applications.py:116`), `ConnectionVisibility`
(`:312`), `TeamMembershipState` (`:407`), `ApplicationRoleConnectionMetadataRecordType` (`:1012`),
`ApplicationIntegrationType` (`:1089`), `ApplicationContextType` (`:1100`); `StageInstancePrivacyLevel`
(`stage_instances.py:39`); `PremiumType` (`users.py:128`); `StickerType` (`stickers.py:51`),
`StickerFormatType` (`:62`); `CommandType` (`commands.py:56`), `OptionType` (`:70`),
`CommandPermissionType` (`:466`); `GuildExplicitContentFilterLevel` (`guilds.py:89`),
`GuildOnboardingMode` (`:103`), `GuildOnboardingPromptType` (`:114`), `GuildMessageNotificationsLevel`
(`:221`), `GuildMFALevel` (`:232`), `GuildPremiumTier` (`:243`), `GuildVerificationLevel` (`:280`),
`GuildNSFWLevel` (`:300`), `IntegrationExpireBehaviour` (`:1336`); `ChannelType` (`channels.py:92`),
`VideoQualityMode` (`:184`), `PermissionOverwriteType` (`:294`), `ForumSortOrderType` (`:1452`),
`ForumLayoutType` (`:1463`); `AutoModActionType` (`auto_mod.py:57`), `AutoModEventType` (`:78`),
`AutoModTriggerType` (`:88`), `AutoModKeywordPresetType` (`:107`); `MessageType` (`messages.py:74`),
`MessageReferenceType` (`:190`), `MessageActivityType` (`:248`), `ReactionType` (`:332`);
`ComponentType` (`components.py:78`), `ButtonStyle` (`:185`), `TextInputStyle` (`:222`), `SpacingType`
(`:233`), `MediaLoadingType` (`:247`); `ShardCloseCode` (`errors.py:151`); `AuditLogEventType`
(`audit_logs.py:300`); `InteractionType` (`interactions/base_interactions.py:75`), `ResponseType`
(`:94`); `ActivityType` (`presences.py:61`).

### 2.2 The 12 str enums (dossier 02 §B.2), `class X(str, enums.Enum)`

| Enum | file:line | Note |
|---|---|---|
| `Locale` | `locales.py:33` | used as a **dict key** in localization maps (dossier 02 §C.2) |
| `AuditLogChangeKey` | `audit_logs.py:64` | — |
| `ApplicationEventWebhookType` | `applications.py:130` | — |
| `OAuth2Scope` | `applications.py:171` | — |
| `ActivityLocationKind` | `applications.py:701` | — |
| `TokenType` | `applications.py:998` | — |
| `GuildFeature` | `guilds.py:125` | list-valued fields |
| `IntegrationType` | `guilds.py:1319` | — |
| `Status` | `presences.py:387` | — |
| `GatewayDataFormat` | `api/shard.py:46` | internal, not a wire field |
| `ChannelInfoField` | `api/shard.py:56` | internal |
| `GatewayCompression` | `api/shard.py:67` | internal |

### 2.3 Current tolerance (`enums.py:154-156`)

```python
def __call__(cls, value):     # _EnumMeta.__call__
    return cls._value_to_member_map_.get(value, value)   # unknown -> raw int/str
```

`MessageType(99)` returns the bare int `99`; `Locale("xx")` returns the bare str. This is what the
`SomeEnum | int` / `SomeEnum | str` field unions admit. msgspec cannot express that union and raises on
unknown values without a fallback — so tolerance must move into `_missing_`.

--------------------------------------------------------------------------------------------------

## 3. msgspec behavior (verified)

From dossier 02 §E.2/§E.4 and dossier 13 §10 (msgspec 0.21.1 / CPython 3.11):

- Unknown int enum value → `ValidationError: Invalid enum value 99`. Unknown str enum value →
  `ValidationError: Invalid enum value 'zzz'`. Strict-by-default; `strict=False` does **not** relax
  enum membership (it toggles primitive coercion only).
- msgspec **calls `_missing_`** on a value-table miss and **accepts a returned pseudo-member**. A
  `_missing_` returning `None` still raises; one returning a minted member decodes successfully.
- Verified for both int (`int.__new__`) and str (`str.__new__`), standalone, nested in `list[...]`,
  and as `dict[...]` **keys** (localization maps).
- The fast value→member C table is unchanged; `_missing_` runs only on a miss → no happy-path cost.

--------------------------------------------------------------------------------------------------

## 4. Target design — the shared `_missing_` mixin

Single mixin, applied first in the MRO so its `_missing_` wins. Cache is **per concrete class** (a
module-level registry, to avoid enum-class `__setattr__` friction and to prevent one shared cache
colliding values across different enums).

```python
import enum, typing

_MAX_CACHED_MEMBERS: typing.Final[int] = 1 << 12          # 4096, mirrors enums.py:39
_PSEUDO_CACHES: dict[type, dict[object, typing.Any]] = {}  # per-enum bounded caches


class _MissingMixin:
    """Mint a value-preserving pseudo-member on an unknown Discord value.

    msgspec invokes _missing_ on a value-table miss and accepts the returned member,
    so fields can be typed as the bare strict enum while unknown values still decode.
    """

    @classmethod
    def _missing_(cls, value: object) -> typing.Any:
        cache = _PSEUDO_CACHES.setdefault(cls, {})
        cached = cache.get(value)
        if cached is not None:
            return cached
        # cls._member_type_ is int for (int, Enum) enums, str for (str, Enum) enums.
        member = cls._member_type_.__new__(cls, value)
        member._name_ = f"UNKNOWN_{value}"
        member._value_ = value
        cache[value] = member
        if len(cache) > _MAX_CACHED_MEMBERS:
            cache.pop(next(iter(cache)))          # bounded FIFO eviction, like enums.py:409-410
        return member


class _IntEnum(_MissingMixin, int, enum.Enum):
    """Base for the 55 int enums; preserves hikari's `str() == member name`."""

    @typing.override
    def __str__(self) -> str:
        return self._name_                        # matches enums.py:352-354


class _StrEnum(_MissingMixin, str, enum.Enum):
    """Base for the 12 str enums; preserves hikari's `str() == member value`."""

    @typing.override
    def __str__(self) -> str:
        return self._value_                       # matches str-based enum today (enums.py:201-203)
```

Concrete enums then read:

```python
class MessageType(_IntEnum):
    DEFAULT = 0
    RECIPIENT_ADD = 1
    ...

class Locale(_StrEnum):
    ID = "id"
    DA = "da"
    ...
```

Decode behavior (verified pattern):

```python
msgspec.json.decode(b'999',  type=MessageType)   # <MessageType.UNKNOWN_999: 999>, int(x)==999, x==999
msgspec.json.decode(b'"xx"', type=Locale)         # <Locale.UNKNOWN_xx: 'xx'>, str(x)=='xx', x=='xx'
msgspec.json.decode(b'{"xx":"hi"}', type=dict[Locale, str])   # {<Locale.UNKNOWN_xx>: 'hi'}
```

Design notes:

- **`cls._member_type_`** is set by stdlib `EnumType` to the mixed-in value type (int/str). Minting via
  `cls._member_type_.__new__(cls, value)` works for both families with one code path.
- **Per-class module-level cache.** A `ClassVar` dict on the mixin would be **shared** by every enum
  (int `5` for two enums would collide) — hence the `_PSEUDO_CACHES[cls]` registry. `_missing_`
  receives the concrete `cls`, so each enum gets its own bounded dict.
- **Bounded cache.** FIFO eviction at 4096 mirrors `_FlagMeta._temp_members_` (`enums.py:409-410`),
  protecting against a hostile stream of distinct unknown values (e.g. spoofed IDs). Alternative:
  accept stdlib behavior and add no caching at all (stdlib does not auto-cache scalar pseudo-members,
  so every unknown decode re-mints) — the cache is a perf/identity optimization, not correctness.
- **`_missing_` return must be an instance of `cls`.** stdlib's lookup rejects a non-member return;
  `cls._member_type_.__new__(cls, value)` yields a genuine instance, so `isinstance(x, cls)` is True.

--------------------------------------------------------------------------------------------------

## 5. Step-by-step migration

1. Land `_MissingMixin`, `_IntEnum`, `_StrEnum` and `_PSEUDO_CACHES` in the rewritten
   `hikari/internal/enums.py` (`04-enums-module-and-machinery.md`). Export names as needed.
2. Reparent the 55 int enums: `class X(int, enums.Enum)` → `class X(_IntEnum)` (or keep
   `class X(_MissingMixin, int, enum.Enum)` if a per-module base is undesirable). Member bodies are
   unchanged.
3. Reparent the 12 str enums: `class X(str, enums.Enum)` → `class X(_StrEnum)`. Member bodies
   unchanged.
4. Carry over behavioral members: `MessageType` has no `__str__` override today (see §6 — the dossier
   anchor is a misattribution), so no port is needed there; the `_IntEnum.__str__` (name) preserves its
   behavior. Any enum with custom methods keeps them (stdlib enums support methods/properties/
   classmethods fully — dossier 13 §1).
5. Remove the manual `EnumType(raw)` casts and attrs `converter=` casts once fields are typed and
   decoded by msgspec (`03-strict-enum-field-inventory.md` §4). In the incremental phase (hand-written
   factory still constructing structs), these casts stay valid — `MyEnum(raw)` now routes through
   `_missing_` on a miss instead of returning a bare int, so callers that expected a bare int change
   behavior (see §7 risk 1).
6. Drop the entity-field `| int`/`| str` unions per `03-strict-enum-field-inventory.md`.
7. Fix the two entity_factory typing bugs uncovered by the sweep (`entity_factory.py:152`,`:166`) —
   detailed in `03-strict-enum-field-inventory.md` §3.

--------------------------------------------------------------------------------------------------

## 6. `str()` semantics — the real compatibility trap (VERIFY-E3)

hikari's current `str()` output **differs by family**, and stdlib changed enum `str()`/`format()` in
3.11:

| Member | hikari today | Anchor | Stdlib default (naive port) |
|---|---|---|---|
| `str(MessageType.DEFAULT)` | `"DEFAULT"` (name) | `Enum.__str__` copied in, `enums.py:352-354` | `"MessageType.DEFAULT"` for `(int,Enum)`; `"0"` for `IntEnum` |
| `str(Locale.EN_US)` | `"en-US"` (value) | `__str__` popped for str enums, `enums.py:201-203` | `"Locale.EN_US"` for `(str,Enum)`; `"en-US"` for `StrEnum` |

Because the naive port would silently change **both** families, the plan **explicitly overrides
`__str__`** on `_IntEnum` (→ name) and `_StrEnum` (→ value), reproducing today's behavior exactly and
insulating from version drift. This is why the design deliberately avoids `enum.StrEnum` / `enum.IntEnum`
sugar (whose `__str__` is fixed to the value): the explicit override on `(str, enum.Enum)` /
`(int, enum.Enum)` is the controllable path, and `enum.StrEnum` is unavailable on the 3.10 floor anyway
(dossier 02 §E.1).

Pin with tests: `str()`, `format()`, and f-string interpolation of one member per family, for every
supported CPython (3.10–3.14). Record results in
`../12-appendices/01-open-questions-and-verifications.md` (VERIFY-E3).

--------------------------------------------------------------------------------------------------

## 7. Risks / gotchas

1. **Behavior change: unknown value is now a pseudo-member, not a bare primitive.** After migration,
   `MyEnum(unknown_raw)` returns an enum instance where `type(x) is int/str` is **False** and
   `isinstance(x, MyEnum)` is **True** (dossier 02 §F.2). Any caller doing `type(x) is int` or an
   explicit `isinstance(x, int) and not isinstance(x, MyEnum)` branch changes behavior. Grep such
   guards before landing. This is the documented semantic change in
   `00-strategy-and-forward-compat.md` §6.
2. **Shared vs per-class cache.** A cache mistakenly declared as a mixin `ClassVar` would collide
   values across enums. The design uses a per-class registry (`_PSEUDO_CACHES[cls]`) — verify the
   `cls` passed to `_missing_` is the concrete enum, not the mixin (it is, per stdlib).
3. **`_missing_` and hashability.** The minted member's value must be hashable to key the cache; int
   and str values are hashable — fine.
4. **Dict-key encoding (Locale maps).** msgspec supports enum dict keys, and `_missing_` covers unknown
   keys on decode. On **encode**, confirm msgspec emits the enum key's `.value` (the str "en-US"), not
   its `.name` — verify and pin (dossier 02 §F.2 flags this; relevant to localization maps in
   `../06-model-modules/09-applications-and-oauth.md` and `../06-model-modules/10-commands.md`).
5. **`GuildFeature` / `OAuth2Scope` list fields.** `list[GuildFeature | str]` etc. become
   `list[GuildFeature]`; the `_missing_` fires per element on unknowns (verified nested-list decode).
6. **`ApplicationEventWebhookType` collision.** There is both a str enum
   `ApplicationEventWebhookType` (`applications.py:130`) and an int enum
   `ApplicationEventWebhookStatus` (`applications.py:116`) — do not conflate them; they migrate to
   `_StrEnum` and `_IntEnum` respectively.
7. **Internal-only enums.** `GatewayDataFormat`/`ChannelInfoField`/`GatewayCompression`
   (`api/shard.py`) and `CommandType`/config-ish enums that are never JSON-decoded still migrate for
   consistency but carry no forward-compat requirement; they need `_missing_` only if a decode path
   exists.

--------------------------------------------------------------------------------------------------

## 8. Affected files & symbols

| Path | Anchors | Change |
|---|---|---|
| `hikari/internal/enums.py` | rewrite | add `_MissingMixin`/`_IntEnum`/`_StrEnum`/`_PSEUDO_CACHES` |
| int-enum modules | 55 sites (§2.1) | base → `_IntEnum`; drop `\| int` on fields (see `03-…`) |
| str-enum modules | 12 sites (§2.2) | base → `_StrEnum`; drop `\| str` on fields (see `03-…`) |
| `hikari/impl/entity_factory.py` | `:152`, `:166`, plus cast sites (dossier 02 §D.1) | fix typing bugs; remove manual `EnumType(raw)` casts in declarative end-state |
| `hikari/internal/cache.py` | §C.1 cache-view rows | drop `\| int`/`\| str` (inventory in `03-…`) |

--------------------------------------------------------------------------------------------------

## 9. Verification

- **VERIFY-E2:** decode unknown values for a representative int and str enum, standalone, in
  `list[...]`, and as `dict[...]` keys; assert the minted member preserves `int()`/`str()`/`==` and
  `isinstance`. (Already verified in dossier 02 §E.4; add as regression tests.)
- **VERIFY-E3:** `str()`/`format()` per family across 3.10–3.14 (§6).
- Cache bound test: decode 5000 distinct unknown values into one enum; assert
  `len(_PSEUDO_CACHES[TheEnum]) <= 4096`.
- Encode test: round-trip a struct with an enum field and a `dict[Locale, str]` field; assert wire
  output uses enum `.value`.
- Happy-path decode benchmark vs baseline (fast table untouched) — record in
  `../11-rollout/02-performance-benchmarking.md`.

--------------------------------------------------------------------------------------------------

## 10. Open questions / decisions

Cross-linked to `../00-overview/05-decisions-log.md` (D2) and
`../12-appendices/01-open-questions-and-verifications.md`:

1. Per-enum base classes (`_IntEnum`/`_StrEnum`) vs inlining `(_MissingMixin, int, enum.Enum)` at each
   declaration. Recommendation: per-family bases for the `__str__` override and readability.
2. Bounded cache (recommended, parity with `enums.py:39`) vs no cache (re-mint each unknown decode).
3. `str()` policy: preserve today's split (int→name, str→value) — recommended — or unify to value?
   Unifying would be a further user-visible change; keep the split.
