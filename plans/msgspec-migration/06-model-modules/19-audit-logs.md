# Audit logs

Purpose: migrate `hikari/audit_logs.py` — 2 enums, `AuditLogChange`, the `BaseAuditLogEntryInfo`
hierarchy (7 entry-info subtypes dispatched by the entry's `action_type`), `AuditLogEntry`, and the
`AuditLog(typing.Sequence)` page container. This module holds the migration's **single hardest
sibling-typing case**: the 40+-entry per-change-key converter table that types
`AuditLogChange.new_value`/`old_value` off the change's `key` string. It also carries two live-`app`
entities and tolerant skip loops.

--------------------------------------------------------------------------------------------------

## 1. Objective

- Freeze all audit-log Structs; drop the `BaseAuditLogEntryInfo.app` (`audit_logs.py:506`) and
  `AuditLogEntry.app` (`:700`) fields and re-home their **live** helpers
  (`MessagePinEntryInfo.fetch_channel/fetch_message`, `MessageDeleteEntryInfo.fetch_channel`,
  `MemberMoveEntryInfo.fetch_channel`, `AuditLogEntry.fetch_user`) to `rest.*`
  (`../03-app-removal-and-helpers/02-helper-method-inventory/04-users-webhooks-audit.md`) — this is
  **not** a dead-`app` module.
- Keep the 2 enums as hikari's custom `Enum` (adopt #2770 strict typing); `AuditLogChangeKey` stays open
  (tolerant) via #2770's `is_unknown` pseudo-members.
- Preserve the 40+-entry change-key converter table (sibling-dependent value typing) in the residual
  factory, the entry-info dispatch by `action_type`, the tolerant skip loops, and the
  `AuditLog(Sequence)` subclass contract.

Decode classification: **everything here is T.** `AuditLog` (Sequence subclass + 6 array→Mapping
re-keyings + tolerant skips), `AuditLogEntry` (change table + options polymorphism + nullable
`target_id`/`user_id` + `guild_id` context), `AuditLogChange` (sibling-typed values), and the entry-info
subtypes (dispatch by external `action_type`, timedelta conversions) all need residual transforms.

--------------------------------------------------------------------------------------------------

## 2. Current state (file:line anchors)

### 2.1 Enums
- `AuditLogChangeKey(str, enums.Enum)` `audit_logs.py:64` — ~70 members; **explicitly open** (docstring
  `:65`: "Others may exist … default to the raw string"); aliases `COLOUR = COLOR` `:277`,
  `COLOURS = COLORS` `:280`, and the odd `$add`/`$remove` values `:271`/`:274`.
- `AuditLogEventType(int, enums.Enum)` `audit_logs.py:300` — ~60 members.

### 2.2 AuditLogChange (the sibling-typing core)
`AuditLogChange` `audit_logs.py:286` — `new_value: Any | None` `:289`, `old_value: Any | None` `:292`,
`key: AuditLogChangeKey | str` `:295`. The value types are chosen at decode by the `key` via the
`_audit_log_entry_converters` table (built `entity_factory.py:487-528`, applied `:995-1002`).

### 2.3 Entry-info hierarchy (dispatch by the entry's `action_type`)
- `BaseAuditLogEntryInfo` `audit_logs.py:502` — `app` `:506` (**note the inconsistent signature**: has
  `metadata={SKIP_DEEP_COPY}` but no `hash=False`, dossier 03 §7.2).
- `ChannelOverwriteEntryInfo(BaseAuditLogEntryInfo, snowflakes.Unique)` `:512` — `id` (hash),
  `type: PermissionOverwriteType | int`, `role_name: str | None`.
- `MessagePinEntryInfo` `:531` — `channel_id`, `message_id`; `fetch_channel` `:543`, `fetch_message` `:569`
  (both `self.app.rest.*`).
- `MemberPruneEntryInfo` `:597` — `delete_member_days: timedelta`, `members_removed: int`.
- `MessageBulkDeleteEntryInfo` `:609` — `count`.
- `MessageDeleteEntryInfo(MessageBulkDeleteEntryInfo)` `:618` — `channel_id`; `fetch_channel` `:624`.
- `MemberDisconnectEntryInfo` `:653` — `count`.
- `MemberMoveEntryInfo(MemberDisconnectEntryInfo)` `:662` — `channel_id`; `fetch_channel` `:668`.

### 2.4 AuditLogEntry and the AuditLog page
- `AuditLogEntry(snowflakes.Unique)` `audit_logs.py:697` — `app` `:700`, `id` (hash), `guild_id`,
  `target_id: Snowflake | None`, `changes: Sequence[AuditLogChange]`, `user_id: Snowflake | None`,
  `action_type: AuditLogEventType | int`, `options: BaseAuditLogEntryInfo | None`, `reason: str | None`;
  `fetch_user` `:729` (`self.app.rest.fetch_user`, returns `None` if `user_id is None`).
- `AuditLog(typing.Sequence[AuditLogEntry])` `audit_logs.py:756` — `@attrs.define(repr=False)`; 6
  `Mapping[Snowflake, T]` fields (`auto_mod_rules`, `entries`, `integrations`, `threads`, `users`,
  `webhooks`); `__getitem__`/`__iter__`/`__len__` over `entries` (`:777-793`).

### 2.5 Factory
- The change-key converter table `entity_factory.py:487-528` (40+ entries: `Snowflake`,
  `_deserialize_seconds_timedelta`/`_deserialize_day_timedelta`/`lambda v: timedelta(minutes=v)`,
  `_with_int_cast(Permissions)`, `Color`, `_deserialize_color_gradient`, `bool`, `int`, `str`, enums
  `GuildMFALevel`/`GuildVerificationLevel`/`GuildExplicitContentFilterLevel`/…/`StickerFormatType`/
  `IntegrationExpireBehaviour`, `iso8601` datetime, and the map-returning
  `_deserialize_audit_log_change_roles` `:902` / `_deserialize_audit_log_overwrites` `:914`).
- `deserialize_audit_log_entry` `:975` — applies the converter per `key` `:995-1002`, dispatches `options`
  by `action_type` via `_audit_log_event_mapping` (raising `UnrecognisedEntityError` `:1022`).
- `deserialize_audit_log` `:1037` — the **tolerant skip loops**: try/except `UnrecognisedEntityError`
  around entries `:1042-1049`, auto-mod rules `:1052-1059`, threads `:1068-1075`, webhooks `:1077-1085`;
  array→Mapping re-key of integrations `:1061` and users `:1065`.

--------------------------------------------------------------------------------------------------

## 3. Target design

### 3.1 Enums → strict custom (adopt #2770)
`AuditLogEventType` (`int, enums.Enum`) and `AuditLogChangeKey` (`str, enums.Enum`) both stay hikari's
custom `Enum` (unchanged, `../02-enums/00-strategy-and-forward-compat.md`); PR #2770's `_EnumMeta.__call__`
(`hikari/internal/enums.py:154`) mints an `is_unknown` pseudo-member on unrecognised values.
`AuditLogChangeKey` is **open-ended by design**; the #2770 pseudo-member — a `str`-subclass instance that
keeps the raw string in `_value_` — preserves the current "default to the raw string" tolerance
(`Enum | str` collapses to bare `AuditLogChangeKey`, dossier 09 §5). Keep the `COLOUR`/`COLOURS` aliases
and the `$add`/`$remove` values.

### 3.2 AuditLogChange — the change-key converter table stays (sibling-dependent value typing)
`new_value`/`old_value` are typed by the sibling `key` via 40+ converters — the canonical
sibling-dependent typing that msgspec **cannot** express (no tagged union, no field-off-field typing;
dossier 05 §3j/§6.3). The converter dict remains a hand-written residual table, unchanged in spirit:
```python
class AuditLogChange(msgspec.Struct, frozen=True, kw_only=True):
    new_value: typing.Any | None = None
    old_value: typing.Any | None = None
    key: AuditLogChangeKey       # bare custom enum; #2770 pseudo-member keeps the raw string on unknown
```
The residual `deserialize_audit_log_entry` decodes each change's `key`, looks up
`_audit_log_entry_converters[key]`, and applies it to `new_value`/`old_value` (guarding `None`), exactly
as today (`entity_factory.py:995-1002`). Custom-scalar converters route through the new hooks (Snowflake,
Color, Permissions, timedelta) but the **key→type mapping is data**, not something the type system can
carry. Keep the table verbatim; only its individual converters change to the msgspec hook equivalents.
This is the module's standout hard case — flag it prominently in
`../05-entity-factory/02-hard-cases-and-transforms.md`.

### 3.3 Entry-info hierarchy — dispatch by external `action_type`
The `options` object is discriminated by the entry's `action_type` (`entity_factory.py:1017`), **not** by
a field of the options object — the same external-discriminator shape as auto-mod triggers
(`18-auto-mod.md` §3.2). So this is **not** a tagged union; keep the `_audit_log_event_mapping` residual
dispatch (raise-on-unknown preserved, `entity_factory.py:1022`).
```python
class BaseAuditLogEntryInfo(msgspec.Struct, frozen=True, kw_only=True):   # NO app
    ...

class ChannelOverwriteEntryInfo(BaseAuditLogEntryInfo, snowflakes.Unique, frozen=True, kw_only=True, eq=False):
    id: snowflakes.Snowflake
    type: channels.PermissionOverwriteType      # was `| int`
    role_name: str | None = None

class MessagePinEntryInfo(BaseAuditLogEntryInfo, frozen=True, kw_only=True):
    channel_id: snowflakes.Snowflake
    message_id: snowflakes.Snowflake            # fetch_channel/fetch_message removed
class MemberPruneEntryInfo(BaseAuditLogEntryInfo, frozen=True, kw_only=True):
    delete_member_days: datetime.timedelta      # days hook
    members_removed: int
class MessageBulkDeleteEntryInfo(BaseAuditLogEntryInfo, frozen=True, kw_only=True):
    count: int
class MessageDeleteEntryInfo(MessageBulkDeleteEntryInfo, frozen=True, kw_only=True):
    channel_id: snowflakes.Snowflake            # fetch_channel removed
class MemberDisconnectEntryInfo(BaseAuditLogEntryInfo, frozen=True, kw_only=True):
    count: int
class MemberMoveEntryInfo(MemberDisconnectEntryInfo, frozen=True, kw_only=True):
    channel_id: snowflakes.Snowflake            # fetch_channel removed
```
- Fix the inconsistent `BaseAuditLogEntryInfo.app` signature (`audit_logs.py:506`, no `hash=False`) — moot
  once `app` is dropped, but note it during removal.
- Entry-info helper re-homing (live `app`):

| Helper | Location | Re-home |
|---|---|---|
| `MessagePinEntryInfo.fetch_channel` | `:543` | `rest.fetch_channel(info.channel_id)` |
| `MessagePinEntryInfo.fetch_message` | `:569` | `rest.fetch_message(info.channel_id, info.message_id)` |
| `MessageDeleteEntryInfo.fetch_channel` | `:624` | `rest.fetch_channel(info.channel_id)` |
| `MemberMoveEntryInfo.fetch_channel` | `:668` | `rest.fetch_channel(info.channel_id)` |

### 3.4 AuditLogEntry (T)
```python
class AuditLogEntry(snowflakes.Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    id: snowflakes.Snowflake
    guild_id: snowflakes.Snowflake             # context-injected on gateway
    target_id: snowflakes.Snowflake | None = None
    changes: typing.Sequence[AuditLogChange] = ()
    user_id: snowflakes.Snowflake | None = None
    action_type: AuditLogEventType             # was `| int`
    options: BaseAuditLogEntryInfo | None = None   # residual dispatch by action_type
    reason: str | None = None
    # NO app; fetch_user removed → rest.fetch_user(entry.user_id) (None-guarded by caller)
```

### 3.5 AuditLog(Sequence) — the ABC-subclass hazard
`AuditLog` subclasses `typing.Sequence[AuditLogEntry]` and implements `__getitem__`/`__iter__`/`__len__`
over `entries` (`audit_logs.py:777-793`), inheriting `count`/`index`/`__contains__`/`__reversed__` mixins
from the ABC. Turning it into a frozen msgspec Struct that also subclasses `collections.abc.Sequence`
needs verification (Struct + non-Struct ABC base + slots; dossier 03 §5):
```python
class AuditLog(msgspec.Struct, typing.Sequence[AuditLogEntry], frozen=True, kw_only=True):
    auto_mod_rules: typing.Mapping[snowflakes.Snowflake, auto_mod.AutoModRule]
    entries: typing.Mapping[snowflakes.Snowflake, AuditLogEntry]
    integrations: typing.Mapping[snowflakes.Snowflake, guilds.PartialIntegration]
    threads: typing.Mapping[snowflakes.Snowflake, channels.GuildThreadChannel]
    users: typing.Mapping[snowflakes.Snowflake, users.User]
    webhooks: typing.Mapping[snowflakes.Snowflake, webhooks.PartialWebhook]
    # __getitem__/__iter__/__len__ verbatim (over self.entries)
```
- **VERIFY (extends conventions §2):** a `frozen=True` Struct with a `typing.Sequence` ABC base retains
  the ABC mixin methods and does not conflict with msgspec's slot layout. If it does, fall back to
  keeping `AuditLog` as a **non-Struct** hand-written frozen class wrapping the 6 mappings (it is a page
  container, not a decoded leaf — no per-field decode benefit is lost).
- The 6 `Mapping[Snowflake, T]` fields are **array→Mapping re-keyings** built in the residual factory
  (`entity_factory.py:1061-1093`) — not declarative.
- **Tolerant skip loops preserved:** entries/auto-mod-rules/threads/webhooks that raise
  `UnrecognisedEntityError` are **skipped**, not fatal (`entity_factory.py:1042-1085`). Because the
  underlying decoders (channels/webhooks/auto-mod) become tagged-union decodes that *raise* on unknown
  tag, the skip must be preserved via a `msgspec.Raw` peek-then-dispatch prepass or the retained
  try/except loops (conventions §3 last bullet). Keep the try/except loops in the residual `deserialize_audit_log`.

--------------------------------------------------------------------------------------------------

## 4. Step-by-step migration

1. Adopt #2770's strict custom enums (keep custom `Enum`); keep `AuditLogChangeKey` open via #2770's
   `is_unknown` pseudo-members (raw-string tolerance) with its aliases and `$add`/`$remove` values.
2. Convert `AuditLogChange` to a frozen Struct; keep the 40+-entry key→converter table in the residual
   factory, swapping individual converters to the msgspec hook equivalents.
3. Convert the entry-info hierarchy to frozen Structs; drop `BaseAuditLogEntryInfo.app`; re-home the 4
   live helpers to `rest.*`; keep the `action_type`-keyed dispatch (raise-on-unknown).
4. Convert `AuditLogEntry`; drop `app`; re-home `fetch_user`; keep `guild_id` context, nullable
   `target_id`/`user_id`, and the `options` residual dispatch.
5. Convert `AuditLog`: VERIFY the Struct+`Sequence` ABC combination; keep the 6 array→Mapping re-keyings
   and the tolerant skip loops in the residual factory.
6. Update `deserialize_audit_log_entry`/`deserialize_audit_log` (`entity_factory.py:975-1094`) to stop
   injecting `app`.

--------------------------------------------------------------------------------------------------

## 5. Affected files & symbols

| Path / anchor | Change |
|---|---|
| `hikari/audit_logs.py:64-296` (`AuditLogChangeKey`, `AuditLogChange`) | open custom str enum + #2770 pseudo-members; frozen; sibling-typed values via table |
| `hikari/audit_logs.py:300-499` (`AuditLogEventType`) | stays custom (#2770 strict typing) |
| `hikari/audit_logs.py:502-692` (entry-info hierarchy) | frozen Structs; drop `app`; re-home 4 helpers; dispatch by `action_type` |
| `hikari/audit_logs.py:697-751` (`AuditLogEntry`) | frozen `Unique`; drop `app`; re-home `fetch_user`; nullable ids; `options` dispatch |
| `hikari/audit_logs.py:756-793` (`AuditLog`) | frozen Struct + `Sequence` ABC (VERIFY) or non-Struct wrapper; 6 re-keyings |
| `hikari/impl/entity_factory.py:487-528` | change-key converter table → msgspec-hook converters (kept as data) |
| `hikari/impl/entity_factory.py:902-920,975-1094` | drop `app`; keep `action_type` dispatch, re-keyings, tolerant skips |
| `../03-app-removal-and-helpers/02-helper-method-inventory/04-users-webhooks-audit.md` | the 5 live helpers |
| `../05-entity-factory/02-hard-cases-and-transforms.md` | change-key table, re-keying, tolerant skips, external-discriminator options |
| `18-auto-mod.md`, `13-webhooks.md`, `04-channels.md`, `02-users.md`, `05-guilds-members-roles.md` | referenced entity types |

--------------------------------------------------------------------------------------------------

## 6. Risks / gotchas

1. **The 40+-entry change-key table is the migration's standout sibling-typing case.** It cannot be a
   tagged union or field-off-field typing; it stays a hand-written data table in the residual factory.
   Missing/mis-typing a converter silently corrupts `new_value`/`old_value` for that key.
2. **`AuditLog(Sequence)` ABC subclass** — Struct + non-Struct ABC base + slots is a msgspec sharp edge;
   VERIFY, else keep `AuditLog` a hand-written frozen wrapper.
3. **Tolerant skip loops.** Underlying decoders now raise on unknown tag; the entries/rules/threads/
   webhooks skip semantics must be preserved (Raw peek or retained try/except), or an unknown thread type
   would abort a whole audit-log page instead of being skipped.
4. **External `action_type` discriminator** for `options` — not a tagged union; keep the mapping dispatch.
5. **Live `app`** — audit logs is NOT dead-`app`; 5 helpers across the entry-info hierarchy and
   `AuditLogEntry` must be re-homed (including `fetch_user`'s `None`-guard, now on the caller).
6. **`BaseAuditLogEntryInfo.app` inconsistent signature** (`audit_logs.py:506`, no `hash=False`) — noted;
   moot after removal.
7. **`AuditLogChangeKey` must stay open** — new Discord change keys appear constantly; #2770's
   `is_unknown` pseudo-member (raw-string fallback) is mandatory, not optional.

--------------------------------------------------------------------------------------------------

## 7. Verification

- Decode a change with `key == "afk_timeout"` → `new_value`/`old_value` are `timedelta`; `key == "$add"`
  → the role-map converter runs; an **unknown** key → `key` is a raw-string pseudo-member and values pass
  through untyped (parity with today).
- Decode entries whose `action_type` selects `ChannelOverwriteEntryInfo`/`MemberPruneEntryInfo`/… →
  correct `options` subtype; an entry-info for an unmapped `action_type` with `options` present → the
  entry is **skipped** (tolerant), not fatal.
- Decode an audit log containing an unknown thread/webhook type → that item is skipped; the page still
  decodes with the remaining items.
- `AuditLog` behaves as a `Sequence` (`len`, indexing, iteration over `entries.values()`); the 6 mappings
  are keyed by snowflake.
- `AuditLogEntry` identity by `id`; `fetch_user` re-homed (caller guards `user_id is None`).
- Strict enums: unknown `AuditLogEventType` int → pseudo-member; unknown `AuditLogChangeKey` → raw-string
  pseudo-member.
- Grep: no `self.app` and no `app=` construction remains for audit-log entities.

--------------------------------------------------------------------------------------------------

## 8. Open questions / decisions

Cross-link `../00-overview/05-decisions-log.md`:
- **VERIFY** `AuditLog` as a `frozen=True` Struct subclassing `typing.Sequence` (ABC mixins + slots); else
  keep it a hand-written frozen wrapper (recommended fallback — it is a container, not a decoded leaf).
- **Change-key converter table** — remains a residual data table (the standout sibling-typing case);
  location `../05-entity-factory/02-hard-cases-and-transforms.md`.
- **Tolerant skip preservation** — Raw peek-then-dispatch vs retained try/except loops (conventions §3);
  recommend retaining the loops in the residual `deserialize_audit_log`.
- **D9:** the 5 live helpers re-home to `rest.*`; `fetch_user`'s `None`-guard moves to the caller.
- **`options` external-discriminator dispatch** stays hand-written (mirrors auto-mod triggers).
