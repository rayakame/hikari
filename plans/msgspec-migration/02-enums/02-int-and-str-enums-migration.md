# Int and Str Enums Migration — 55 + 12 Custom Enums Kept, Strict-Typed via #2770

Purpose: keep hikari's 55 int enums and 12 str enums on the custom `_EnumMeta`/`Enum` implementation,
adopt PR hikari-py/hikari#2770's pseudo-member `__call__` (so an unknown Discord value decodes to an
`is_unknown` member instead of the raw scalar), drop the `| int`/`| str` field unions, and
decode/encode them through the shared `dec_hook`/`enc_hook`. This is the half of the enum migration
that #2770 exists for: pre-#2770 the custom `Enum` returns the **raw value** on a miss, which the
msgspec hook cannot accept; #2770 fixes that by minting a member instance (dossier 15 §1–§3).

Serves constraint (b) and decision D2 (`../00-overview/05-decisions-log.md`).

--------------------------------------------------------------------------------------------------

## 1. Objective

- **Keep** `class X(int, enums.Enum)` (55 types) and `class X(str, enums.Enum)` (12 types) on the custom
  metaclasses — they are faster at runtime than stdlib `enum`. Do **not** port to
  `enum.IntEnum`/`enum.StrEnum`; do **not** add a `_missing_` mixin.
- Adopt #2770's `_EnumMeta.__call__`, which mints and caches a **value-preserving pseudo-member
  instance** on a lookup miss (the `Flag` already did this), and #2770's `Enum.is_unknown` property.
- Type every field with the bare strict enum; the `| int`/`| str` drop is inventoried in
  `03-strict-enum-field-inventory.md` and is exactly #2770's typing sweep.
- Decode/encode through the shared hook (`../01-foundations/02-custom-scalar-types-and-hooks.md`):
  `dec_hook` returns `t(raw)`, `enc_hook` returns `o.value`.

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

All are declared on the custom `_EnumMeta`; every one of these declarations is **kept unchanged**.

### 2.3 Current tolerance (`enums.py:154-156`) — the reason #2770 is a prerequisite

```python
def __call__(cls, value):     # _EnumMeta.__call__ (pre-#2770)
    return cls._value_to_member_map_.get(value, value)   # unknown -> raw int/str
```

`MessageType(99)` returns the bare int `99`; `Locale("xx")` returns the bare str. This is what the
`SomeEnum | int` / `SomeEnum | str` field unions admit. But a bare int/str is **not** an instance of
the enum type, so the msgspec hook (`return t(raw)`) fails msgspec's instance-of-type check on any
unknown value: `ValidationError: Expected 'MessageType', got 'int'` (dossier 15 §3, Probe A). The fix
is #2770, which makes `__call__` mint a member instance on a miss (§4).

--------------------------------------------------------------------------------------------------

## 3. msgspec behavior through the hook (verified)

From dossier 15 §1–§3 (msgspec 0.21.1 / CPython 3.11), against the real `hikari.internal.enums`:

- Because the custom `Enum` is **not** an `enum.Enum` subclass, msgspec routes a field typed with it to
  `dec_hook(t, raw)`, which returns `t(raw)` — the enum's own constructor. msgspec then checks the
  result is an instance of `t`.
- **Pre-#2770 (raw-on-miss):** known values decode to members (PASS); unknown int/str values FAIL the
  instance check (`Expected 'X', got 'int'`).
- **With #2770 (pseudo-member on miss):** `decode 999 -> MessageType` yields
  `<MessageType.UNKNOWN 999: 999>`, `isinstance(...)` True, `int()==999`, `==999` True (PASS);
  `decode "zz" -> a str enum` yields a str pseudo-member (PASS); unknown scalar, unknown list element,
  and unknown `dict[...]` **key** all decode to pseudo-members (PASS); encoding an unknown pseudo-member
  round-trips the raw value (`999 -> b'999'`) through `enc_hook`.
- The fast value→member table is unchanged; the pseudo-member path runs **only on a miss** → no
  happy-path decode cost beyond the single per-field hook call (the trade-off documented in
  `00-strategy-and-forward-compat.md` §7).

--------------------------------------------------------------------------------------------------

## 4. Target design — #2770's pseudo-member `__call__` plus the hook

There is **no** `_missing_` mixin and **no** new base class. The custom `Enum` is kept; #2770 changes
its metaclass `__call__` and adds `is_unknown`. Verbatim from the PR head (dossier 15 §2):

```python
def __call__(cls, value: object) -> Enum:
    """Cast a value to the enum, returning an unknown member if the value is not a known one."""
    try:
        return cls._value_to_member_map_[value]
    except KeyError:
        try:
            return cls._temp_members_[value]
        except KeyError:
            if not isinstance(value, cls.__objtype__):
                msg = f"{cls.__name__} values must be of type {cls.__objtype__.__name__}, not {type(value).__name__}"
                raise TypeError(msg) from None
            member = cls.__new__(cls, value)
            member._name_ = None
            member._value_ = value
            cls._temp_members_[value] = member
            if len(cls._temp_members_) > _MAX_CACHED_MEMBERS:
                cls._temp_members_.popitem()
            return member
```

Plus `Enum.is_unknown` → `self._value_ not in self._value_to_member_map_`, and `Enum.name` lazily
naming unknowns `f"UNKNOWN {self._value_!r}"`.

Concrete enums are unchanged:

```python
class MessageType(int, enums.Enum):   # kept exactly as today
    DEFAULT = 0
    RECIPIENT_ADD = 1
    ...

class Locale(str, enums.Enum):        # kept exactly as today
    ID = "id"
    DA = "da"
    ...
```

Decode/encode goes through the shared hook (design owned by
`../01-foundations/02-custom-scalar-types-and-hooks.md`):

```python
# decode: t is the annotated enum type, obj the decoded JSON int/str
if issubclass(t, (enums.Enum, enums.Flag)):
    return t(obj)          # #2770: known member, or a minted pseudo-member on a miss
# encode: emit the plain primitive
if isinstance(o, (enums.Enum, enums.Flag)):
    return o.value
```

Verified decode behavior (dossier 15 §3, Probe B):

```python
msgspec.json.decode(b'999',  type=MessageType)   # <MessageType.UNKNOWN 999: 999>, int(x)==999, x==999
msgspec.json.decode(b'"xx"', type=Locale)         # str pseudo-member, str(x)=='xx', x=='xx'
msgspec.json.decode(b'{"xx":"hi"}', type=dict[Locale, str])   # {<Locale unknown 'xx'>: 'hi'}
```

Design notes:

- **`__objtype__` guard.** `_EnumMeta` already carries `__objtype__` (the mixed-in `int`/`str`;
  `enums.py:187,333`). #2770's `__call__` uses it to raise `TypeError` when a value of the wrong type is
  cast. msgspec passes the decoded primitive (int for an int-enum field, str for a str-enum field),
  which matches `__objtype__`, so the happy path never trips this; a genuinely wrong wire type surfaces
  as a `ValidationError` (msgspec converts a hook `TypeError` into `ValidationError`).
- **Bounded cache.** #2770 mints into `_temp_members_` bounded by `_MAX_CACHED_MEMBERS = 4096`
  (`enums.py:39`) with `popitem()` eviction — the same mechanism the custom `Flag` has always used
  (`enums.py:409`). A hostile stream of distinct unknown values cannot grow memory without limit.
- **`str()` is unchanged.** Because the custom `Enum` is kept, its existing `__str__`
  (`enums.py:353-354`, member name for int enums; value for str enums via the str base) is preserved
  as-is. There is no `enum.StrEnum`/`enum.IntEnum` `str()` drift to reconcile and no cross-version
  `str()` verification — the old stdlib-port concern is withdrawn as moot
  (`../12-appendices/01-open-questions-and-verifications.md`).

--------------------------------------------------------------------------------------------------

## 5. Step-by-step migration

1. Adopt #2770 (changes `_EnumMeta.__call__` to mint pseudo-members, adds `_temp_members_` to the enum
   namespace, adds `Enum.is_unknown`, adds the `__objtype__` wrong-type guard) as part of the enum
   prerequisite PR (`04-enums-module-and-machinery.md`). No declaration-site or member-body edits.
2. Add the enum/flag branch to the shared `dec_hook`/`enc_hook`
   (`../01-foundations/02-custom-scalar-types-and-hooks.md`).
3. In the incremental phase (hand-written factory still constructing structs), the existing
   `EnumType(raw)` casts stay valid — post-#2770 they route through the pseudo-member `__call__` on a
   miss instead of returning a bare int, so callers that expected a bare int change behavior (see §6
   risk 1).
4. Drop the entity-field `| int`/`| str` unions per `03-strict-enum-field-inventory.md` (delivered by
   #2770's typing sweep).
5. Fix the two entity_factory typing bugs uncovered by the sweep (`entity_factory.py:152`,`:166`) —
   detailed in `03-strict-enum-field-inventory.md` §4.

--------------------------------------------------------------------------------------------------

## 6. Risks / gotchas

1. **Behavior change: unknown value is now a pseudo-member, not a bare primitive.** After #2770,
   `MyEnum(unknown_raw)` returns an enum instance where `type(x) is int/str` is **False** and
   `isinstance(x, MyEnum)` is **True** (dossier 02 §F.2, dossier 15 §2). Any caller doing
   `type(x) is int` or an explicit `isinstance(x, int) and not isinstance(x, MyEnum)` branch changes
   behavior. Grep such guards before landing. This is the documented semantic change in
   `00-strategy-and-forward-compat.md` §6 and is delivered by #2770 (`changes/2770.breaking.md`).
2. **Wrong-type input now raises `TypeError`.** #2770's `__objtype__` guard means casting a value of
   the wrong Python type (e.g. a str into an int enum outside the wire path) raises instead of returning
   the raw value. Through the hook it surfaces as `ValidationError`. Confirm no code relied on the old
   silent pass-through.
3. **Cache hashability.** The minted member's value keys `_temp_members_`; int and str values are
   hashable — fine (unchanged from the custom `Flag` cache).
4. **Dict-key encoding (Locale maps).** On **encode**, the `enc_hook` returns the enum key's `.value`
   (the str "en-US"), not its `.name` — verify and pin (relevant to localization maps in
   `../06-model-modules/09-applications-and-oauth.md` and `../06-model-modules/10-commands.md`). On
   decode, #2770's pseudo-member covers unknown keys (dossier 15 §3, verified for `dict[...]` keys).
5. **`GuildFeature` / `OAuth2Scope` list fields.** `list[GuildFeature | str]` etc. become
   `list[GuildFeature]`; the pseudo-member `__call__` fires per element on unknowns via the hook
   (verified nested-list decode, dossier 15 §3).
6. **`ApplicationEventWebhookType` collision.** There is both a str enum
   `ApplicationEventWebhookType` (`applications.py:130`) and an int enum
   `ApplicationEventWebhookStatus` (`applications.py:116`) — do not conflate them; both stay custom.
7. **Internal-only enums.** `GatewayDataFormat`/`ChannelInfoField`/`GatewayCompression`
   (`api/shard.py`) and config-ish enums that are never JSON-decoded still receive #2770's `__call__`
   uniformly but carry no forward-compat requirement (no decode path).

--------------------------------------------------------------------------------------------------

## 7. Affected files & symbols

| Path | Anchors | Change |
|---|---|---|
| `hikari/internal/enums.py` | `_EnumMeta.__call__` (`:154`), `Enum` (`:257`) | #2770 diffs: pseudo-member `__call__` + `_temp_members_` + `is_unknown`; base kept |
| int-enum modules | 55 sites (§2.1) | **base unchanged**; drop `\| int` on fields (see `03-…`) |
| str-enum modules | 12 sites (§2.2) | **base unchanged**; drop `\| str` on fields (see `03-…`) |
| `hikari/impl/entity_factory.py` | `:152`, `:166`, plus cast sites (dossier 02 §D.1) | fix typing bugs; casts route through #2770 `__call__` |
| `hikari/internal/cache.py` | §C.1 cache-view rows | drop `\| int`/`\| str` (inventory in `03-…`) |

The msgspec hook branch itself lives in `../01-foundations/02-custom-scalar-types-and-hooks.md`.

--------------------------------------------------------------------------------------------------

## 8. Verification

- **RESOLVED (dossier 15, empirical):** decode unknown values for a representative int and str enum,
  standalone, in `list[...]`, and as `dict[...]` keys through the hook; the minted #2770 pseudo-member
  preserves `int()`/`str()`/`==` and `isinstance`, and `is_unknown` is True
  (`../12-appendices/02-custom-enum-feasibility.md`). Add as regression tests.
- Cache bound test: decode 5000 distinct unknown values into one enum; assert
  `len(TheEnum._temp_members_) <= 4096`.
- Encode test: round-trip a struct with an enum field and a `dict[Locale, str]` field; assert the wire
  output uses enum `.value` (via `enc_hook`).
- Wrong-type test: casting a wrong-typed value raises `TypeError`; through the hook it surfaces as
  `ValidationError`.
- Happy-path decode benchmark vs a stdlib-enum control (the per-field hook cost, `00-strategy-and-
  forward-compat.md` §7) — record in `../11-rollout/02-performance-benchmarking.md`.

--------------------------------------------------------------------------------------------------

## 9. Open questions / decisions

Cross-linked to `../00-overview/05-decisions-log.md` (D2) and
`../12-appendices/01-open-questions-and-verifications.md`:

1. Adopt #2770's `_temp_members_` cache bound (4096, `enums.py:39`) as-is (recommended, parity with the
   existing `Flag` cache) or tune it? Recommendation: keep the existing cap.
2. `str()` policy: preserved unchanged (custom enums kept — int→name, str→value). No decision needed;
   the old stdlib `str()` verification is withdrawn as moot.
3. Whether `errors.py:250` `code: ShardCloseCode | None` (an int enum) needs any extra handling: no — it
   is in the 55 int-enum set and inherits #2770's pseudo-member `__call__` automatically.
