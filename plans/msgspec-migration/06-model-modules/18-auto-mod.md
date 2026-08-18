# Auto-moderation

Purpose: migrate `hikari/auto_mod.py` — 4 enums, two polymorphic hierarchies (`PartialAutoModAction` →
3 actions, `PartialAutoModTrigger` → 5 triggers), and the `AutoModRule` container carrying a **dead**
`app` field. Both hierarchies resist a clean msgspec tagged union: the action's fields live nested under
`metadata`, and the trigger's discriminator (`trigger_type`) lives on the *rule* payload, not inside the
trigger object. This is a residual-transform-heavy module.

--------------------------------------------------------------------------------------------------

## 1. Objective

- Freeze the action, trigger, and rule Structs; drop the **dead** `AutoModRule.app` field
  (`auto_mod.py:231`) with no helper re-homing (confirmed: **no `self.app` in `auto_mod.py`** — a
  dead-`app` module, conventions §8, `../03-app-removal-and-helpers/01-app-field-removal.md`).
- Port the 4 enums to stdlib and drop the `AutoModKeywordPresetType | int` tolerance on
  `KeywordPresetTrigger.presets`.
- Preserve the two polymorphic dispatches (action by `type`, trigger by `trigger_type`) with their
  current **raise-on-unknown-type** semantics, and the `metadata`/`trigger_metadata` nesting/flatten.
- Normalise the legacy `hash=True` spelling on `AutoModRule` (dossier 03 §2.1).

Decode classification: `AutoModRule` is **T** (polymorphic trigger + actions, both nested). `AutoModTimeout`
and `AutoModSendAlertMessage` are **T** (fields flattened out of `metadata`). `AutoModBlockMessage`,
`SpamTrigger` are near-**D** (empty payloads). `KeywordTrigger`/`KeywordPresetTrigger`/`MentionSpamTrigger`/
`MemberProfileTrigger` are near-**D** *given* the trigger payload is `trigger_metadata` (the discriminator
is external).

--------------------------------------------------------------------------------------------------

## 2. Current state (file:line anchors)

### 2.1 Enums
`AutoModActionType(int, enums.Enum)` `auto_mod.py:57` (BLOCK_MESSAGE=1, SEND_ALERT_MESSAGE=2, TIMEOUT=3,
BLOCK_MEMBER_INTERACTION=4); `AutoModEventType` `:78`; `AutoModTriggerType` `:88` (KEYWORD=1, SPAM=3,
KEYWORD_PRESET=4, MENTION_SPAM=5, MEMBER_PROFILE=6); `AutoModKeywordPresetType` `:107`.

### 2.2 Actions (polymorphic by `type`)
- `PartialAutoModAction` `auto_mod.py:122` — `type: AutoModActionType`.
- `AutoModBlockMessage` `:130` — empty (just `type`).
- `AutoModSendAlertMessage` `:135` — `channel_id: Snowflake` (from `metadata.channel_id`,
  `entity_factory.py:4770`).
- `AutoModTimeout` `:143` — `duration: timedelta` (from `metadata.duration_seconds`,
  `entity_factory.py:4777`).
- `AutoModBlockMemberAction` `:154` — empty; **not parsed back** (no mapping entry; dossier 03 §4.2).

### 2.3 Triggers (polymorphic by `trigger_type`, read from `trigger_metadata`)
- `PartialAutoModTrigger` `auto_mod.py:160` — `type: AutoModTriggerType`.
- `KeywordTrigger` `:168` — `keyword_filter`, `regex_patterns`, `allow_list`.
- `SpamTrigger` `:182` — empty.
- `KeywordPresetTrigger` `:187` — `allow_list`, `presets: Sequence[AutoModKeywordPresetType | int]` `:193`.
- `MentionSpamTrigger` `:198` — `mention_total_limit`, `mention_raid_protection_enabled`.
- `MemberProfileTrigger` `:209` — `keyword_filter`, `regex_patterns`, `allow_list`.

### 2.4 Rule
- `AutoModRule(snowflakes.Unique)` `auto_mod.py:228` — `@attrs.define(hash=True, …)` (**legacy spelling**
  of `unsafe_hash`, dossier 03 §2.1). Fields: `app` `:231` (**dead**), `id` (`eq=True, hash=True`) `:236`,
  `guild_id`, `name`, `creator_id`, `event_type: AutoModEventType`, `trigger: PartialAutoModTrigger`,
  `actions: Sequence[PartialAutoModAction]`, `is_enabled`, `exempt_role_ids`, `exempt_channel_ids`.

### 2.5 Factory
- Actions: `_deserialize_auto_mod_block_message` `entity_factory.py:4761`,
  `_deserialize_auto_mod_block_send_alert_message` `:4766` (reads `payload["metadata"]["channel_id"]`),
  `_deserialize_auto_mod_timeout` `:4774` (reads `payload["metadata"]["duration_seconds"]`);
  `deserialize_auto_mod_action` `:4781` dispatches on `type` via `_auto_mod_action_mapping`, raising
  `UnrecognisedEntityError` `:4789`.
- Triggers: `_deserialize_auto_mod_keyword_trigger` `:4791` … `_member_profile_trigger` `:4825`, each
  taking the `trigger_metadata` object (may be `None`).
- Rule: `deserialize_auto_mod_rule` `:4837` dispatches the trigger on `trigger_type` via
  `_auto_mod_trigger_mapping` (raising `UnrecognisedEntityError` `:4843`), then calls
  `trigger_converter(payload.get("trigger_metadata"))` `:4852` and builds `actions` from
  `payload["actions"]` `:4853`.

--------------------------------------------------------------------------------------------------

## 3. Target design

### 3.1 Enums → stdlib
The 4 enums → `int, enum.Enum` + `_missing_`; drop `AutoModKeywordPresetType | int` on
`KeywordPresetTrigger.presets` (`../02-enums/03-strict-enum-field-inventory.md`).

### 3.2 Why neither hierarchy is a clean tagged union
- **Action.** The discriminator `type` **is** a top-level field of the action object (good), but the
  action's real fields (`channel_id`, `duration_seconds`) live **nested under `metadata`**
  (`entity_factory.py:4770`/`:4777`). A tagged union would decode a wire Struct with a `metadata`
  sub-object; lifting those fields up to `AutoModSendAlertMessage.channel_id`/`AutoModTimeout.duration`
  is a **flatten transform** msgspec cannot do declaratively. Recommendation: keep a residual dispatch on
  `type` (or decode to a `metadata`-carrying wire Struct then transform), preserving the flatten.
- **Trigger.** The discriminator `trigger_type` is a field of the **rule** payload, not of the
  `trigger_metadata` object (which has *no* type field). This is the same shape as audit-log entry
  options keyed on the entry's `action_type` (dossier 05 §6 case) — **not** expressible as a tagged
  union on the trigger object. Recommendation: keep the residual dispatch on the rule's `trigger_type`,
  passing `trigger_metadata` (possibly `None`) to the selected converter.

```python
# Actions
class PartialAutoModAction(msgspec.Struct, frozen=True, kw_only=True):
    type: AutoModActionType

class AutoModBlockMessage(PartialAutoModAction, frozen=True, kw_only=True): ...      # empty
class AutoModSendAlertMessage(PartialAutoModAction, frozen=True, kw_only=True):
    channel_id: snowflakes.Snowflake        # T: flattened from metadata.channel_id
class AutoModTimeout(PartialAutoModAction, frozen=True, kw_only=True):
    duration: datetime.timedelta            # T: metadata.duration_seconds (seconds hook)

# Triggers
class PartialAutoModTrigger(msgspec.Struct, frozen=True, kw_only=True):
    type: AutoModTriggerType
class KeywordTrigger(PartialAutoModTrigger, frozen=True, kw_only=True):
    keyword_filter: typing.Sequence[str]
    regex_patterns: typing.Sequence[str]
    allow_list: typing.Sequence[str]
class SpamTrigger(PartialAutoModTrigger, frozen=True, kw_only=True): ...              # empty
class KeywordPresetTrigger(PartialAutoModTrigger, frozen=True, kw_only=True):
    allow_list: typing.Sequence[str]
    presets: typing.Sequence[AutoModKeywordPresetType]     # was `| int`
class MentionSpamTrigger(PartialAutoModTrigger, frozen=True, kw_only=True):
    mention_total_limit: int
    mention_raid_protection_enabled: bool
class MemberProfileTrigger(PartialAutoModTrigger, frozen=True, kw_only=True):
    keyword_filter: typing.Sequence[str]
    regex_patterns: typing.Sequence[str]
    allow_list: typing.Sequence[str]
```
- The residual converters keep setting `type=`/`type` from the dispatch key
  (`AutoModTriggerType.KEYWORD`, etc., `entity_factory.py:4796`) — the concrete Structs keep an explicit
  `type` field (unlike stickers' `ClassVar`, because the value is context-derived from the rule's
  `trigger_type`, not a fixed constant per class... though in practice each converter builds exactly one
  type). Either keep `type` a plain field set by the converter, or make it a `ClassVar` per subtype
  (matching stickers, `15-stickers.md`). Recommend keeping it a plain field to mirror the current shape.
- `AutoModBlockMemberAction` (`auto_mod.py:154`) is currently **not decoded** (no mapping entry) — it
  stays out of the action union until a decoder is added; decode of a `BLOCK_MEMBER_INTERACTION` action
  raises today, and continues to.

### 3.3 AutoModRule (T)
```python
class AutoModRule(snowflakes.Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    id: snowflakes.Snowflake
    guild_id: snowflakes.Snowflake
    name: str
    creator_id: snowflakes.Snowflake
    event_type: AutoModEventType
    trigger: AnyAutoModTrigger      # residual polymorphic build from trigger_type + trigger_metadata
    actions: typing.Sequence[AnyAutoModAction]
    is_enabled: bool                # field(name="enabled")
    exempt_role_ids: typing.Sequence[snowflakes.Snowflake]      # field(name="exempt_roles")
    exempt_channel_ids: typing.Sequence[snowflakes.Snowflake]   # field(name="exempt_channels")
    # NO app
```
- Normalise the legacy `hash=True` class flag to the standard `Unique` + `eq=False` id-only identity
  (conventions §2). `id` is already the sole eq/hash field.
- `trigger` and `actions` are built by the residual dispatch (§3.2) — `AutoModRule` is **T** and cannot be
  decoded declaratively even once the leaf triggers/actions are Structs.
- Renamed keys (`enabled`, `exempt_roles`, `exempt_channels`) are declarative via `field(name=…)`.

--------------------------------------------------------------------------------------------------

## 4. Step-by-step migration

1. Port the 4 enums to stdlib; drop `AutoModKeywordPresetType | int`.
2. Convert the 3 action Structs; keep the `metadata` flatten for `AutoModSendAlertMessage.channel_id` and
   `AutoModTimeout.duration` (seconds hook) as residual transforms; keep `deserialize_auto_mod_action`'s
   `type` dispatch + raise-on-unknown.
3. Convert the 5 trigger Structs; keep the residual dispatch on the rule's `trigger_type` feeding
   `trigger_metadata`; keep raise-on-unknown.
4. Convert `AutoModRule`; normalise `hash=True`→`Unique`/`eq=False`; drop the **dead** `app`; add the
   `enabled`/`exempt_roles`/`exempt_channels` renames; keep the trigger/action residual builds.
5. Update `deserialize_auto_mod_rule`/`deserialize_auto_mod_action` (`entity_factory.py:4761-4857`) to
   stop injecting `app`.

--------------------------------------------------------------------------------------------------

## 5. Affected files & symbols

| Path / anchor | Change |
|---|---|
| `hikari/auto_mod.py:57-117` (enums) | 4 enums → stdlib; strict `presets` |
| `hikari/auto_mod.py:122-155` (actions) | frozen Structs; `metadata` flatten **T** (alert/timeout) |
| `hikari/auto_mod.py:160-223` (triggers) | frozen Structs; residual dispatch by rule `trigger_type` |
| `hikari/auto_mod.py:228-264` (`AutoModRule`) | frozen `Unique`/`eq=False`; drop dead `app`; renames; residual trigger/actions |
| `hikari/impl/entity_factory.py:4761-4857,425-436` | drop `app`; keep both dispatches + `metadata`/`trigger_metadata` handling |
| `../05-entity-factory/01-polymorphism-and-tagged-unions.md` | why action/trigger are NOT clean tagged unions |
| `../05-entity-factory/02-hard-cases-and-transforms.md` | `metadata` flatten, external-discriminator trigger dispatch |
| `../03-app-removal-and-helpers/01-app-field-removal.md` | the dead `app` field |

--------------------------------------------------------------------------------------------------

## 6. Risks / gotchas

1. **Trigger discriminator is external.** `trigger_type` lives on the rule, not the `trigger_metadata`
   object — a tagged union on the trigger cannot work; the dispatch stays hand-written (dossier 05 §6).
2. **Action fields are nested under `metadata`.** `channel_id`/`duration_seconds` must be flattened up —
   a residual transform, not a declarative field; `duration` also needs the seconds→timedelta hook.
3. **`trigger_metadata` may be `None`** (`entity_factory.py:4852`) — the empty triggers (`SpamTrigger`)
   receive `None`; keep the `assert payload is not None` guards only where fields are read.
4. **`AutoModBlockMemberAction` is unparsed** — decode of `BLOCK_MEMBER_INTERACTION` raises today and
   continues to; do not silently add it to the union without a decoder.
5. **Legacy `hash=True` spelling** on `AutoModRule` — normalise to `Unique`/`eq=False` (semantics
   unchanged; id-only identity).
6. **Raise-on-unknown preserved** for both action and trigger dispatch (`entity_factory.py:4789`/`:4843`).

--------------------------------------------------------------------------------------------------

## 7. Verification

- Decode a rule with a `KEYWORD` trigger → `trigger` is `KeywordTrigger` with the filters; a `SPAM`
  trigger with `trigger_metadata: null` → `SpamTrigger`; unknown `trigger_type` → decode error.
- Decode actions: `SEND_ALERT_MESSAGE` → `channel_id` from `metadata.channel_id`; `TIMEOUT` → `duration`
  a `timedelta(seconds=metadata.duration_seconds)`; unknown `type` → decode error;
  `BLOCK_MEMBER_INTERACTION` → error (unparsed).
- `AutoModRule`: `enabled`→`is_enabled`, `exempt_roles`→`exempt_role_ids`,
  `exempt_channels`→`exempt_channel_ids`; identity by `id` (hashable dict key).
- Strict enum: unknown `AutoModKeywordPresetType` int in `presets` → pseudo-member.
- Grep: no `self.app` and no `app=` construction remains for auto-mod entities.

--------------------------------------------------------------------------------------------------

## 8. Open questions / decisions

Cross-link `../00-overview/05-decisions-log.md`:
- **Residual dispatch vs wire-Struct+transform** for actions/triggers — both keep the flatten and the
  external-discriminator dispatch; recommend the residual dispatch (least churn). Settle in
  `../05-entity-factory/02-hard-cases-and-transforms.md`.
- **`type` as plain field vs `ClassVar`** on the concrete triggers/actions — recommend a plain field set
  by the converter (mirrors current shape; contrast stickers' `ClassVar`, `15-stickers.md`).
- **`duration` seconds→timedelta hook** — `../01-foundations/02-custom-scalar-types-and-hooks.md`.
- No tri-state `UNDEFINED` fields in this module.
