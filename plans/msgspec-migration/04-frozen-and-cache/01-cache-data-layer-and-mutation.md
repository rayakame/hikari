# Cache data layer and in-place mutation

Purpose: decide the fate of the `*Data` storage layer and rewrite every in-place
mutation the cache performs, now that public entities are frozen. `RefCell` and
`GuildRecord` stay mutable; `Cell` is deleted; message edits and presence-emoji
reassignment move to `msgspec.structs.replace` + `RefCell.object` swap; and
`has_been_deleted` gets a new home.

## 1. Objective

- Serve constraint (c): the mutation-heavy internal cache carriers must keep
  working when the *payloads* they hold are frozen Structs that cannot be edited
  in place.
- Choose between the two `*Data`-layer strategies (dossier 07 §10.2, §11 OQ-1)
  and specify the mutation rewrites precisely enough to implement.
- Localise where `has_been_deleted` lives and how `MessageData.update`,
  `RichActivityData.emoji` reassignment, and `update_guild`'s patch become
  frozen-safe.

This file owns the *mutable internals*. The copy-machinery deletion is in
[`00-frozen-structs-and-copy-removal.md`](00-frozen-structs-and-copy-removal.md);
the app-injection collapse and view/storage strategy are in
[`02-cache-app-and-views.md`](02-cache-app-and-views.md).

## 2. Current state

### 2.1 The `*Data` layer (`hikari/internal/cache.py`)

`BaseData[ValueT]` (`internal/cache.py:293-333`) is the abstract base for 8
storage models. Contract: `build_entity(app) -> ValueT` (rebuild a live entity,
**app injected here**) and `build_from_entity(entity) -> Self` (decompose). Its
docstring states fields are assumed immutable and mutable fields must be copied
in `build_*` overrides. Every `*Data` class is
`@attrs_extensions.with_copy @attrs.define(kw_only=True, repr=False,
weakref_slot=False)`.

| Data class | Anchor | Wraps | Notable mutable / cross-ref state |
|---|---|---|---|
| `InviteData` | `:336-421` | `InviteWithMetadata` | `inviter`/`target_user` = `RefCell[User] \| None`; roles tuple |
| `MemberData` | `:424-485` | `Member` | `user` = `RefCell[User]`; role_ids tuple; **`has_been_deleted: bool` `init=False` (:444)** |
| `KnownCustomEmojiData` | `:488-541` | `KnownCustomEmoji` | `user` = `RefCell[User] \| None` |
| `GuildStickerData` | `:544-588` | `GuildSticker` | `user` = `RefCell[User] \| None` |
| `RichActivityData` | `:591-673` | `RichActivity` | **`emoji` = `RefCell[CustomEmoji] \| str \| None` reassigned at cache time** |
| `MemberPresenceData` | `:676-709` | `MemberPresence` | `activities` = tuple of `RichActivityData` |
| `MessageData` | `:729-925` | `Message` | `author`/`member`/`referenced_message`/`user_mentions` = `RefCell`s; **in-place `update()` (:884-925)** |
| `VoiceStateData` | `:928-986` | `VoiceState` | `member` = `RefCell[MemberData] \| None` |

The `*Data` layer's real jobs (dossier 07 §11): (i) strip `app` (simply not
stored, re-added via the `build_entity(app)` param); (ii) hold `RefCell`
cross-references so shared sub-entities (users, members, referenced messages,
unknown emojis) are reference-counted, not re-embedded; (iii) enable in-place
edit (`MessageData.update`) and the `has_been_deleted` meta-flag.

### 2.2 `RefCell` and `Cell`

`RefCell[ValueT]` (`internal/cache.py:1007-1029`) is the mutable reference
primitive:

```python
@attrs_extensions.with_copy
@attrs.define(repr=False, weakref_slot=False)
class RefCell(typing.Generic[ValueT]):
    object: ValueT = attrs.field(repr=True)          # REASSIGNED in place
    ref_count: int = attrs.field(default=0, kw_only=True)  # MUTATED in place
    def copy(self) -> ValueT: return copy.copy(self.object)
```

`.object` is reassigned at `impl/cache.py:1273` (member), `:1424` (unknown
emoji), `:1585` (user), `:1929, 1935` (message). `ref_count` is mutated by
`_increment_ref_count` (`:140-141`) at 20+ sites (dossier 07 §5.5: lines 141,
302, 433, 1048, 1054, 1122, 1266, 1297, 1431, 1561, 1772, 1805, 1911, 1914,
1918; reads at 1108, 1299, 1557, 1795). This is the heart of the GC scheme for
users, members, unknown emojis, and referenced messages — **`RefCell` cannot be
frozen.**

`Cell[ValueT]` (`internal/cache.py:989-1004`) is identical to `RefCell` minus
`ref_count`. It has **no references anywhere in the repo** (dossier 07 §0.5,
§4.4) — dead code.

### 2.3 `GuildRecord`

`GuildRecord` (`internal/cache.py:187-290`, verified read) is a per-guild index:
`is_available`, `guild` (`GatewayGuild | None`),
`channels`/`threads`/`emojis`/`stickers`/`roles` (`SnowflakeSet | None`),
`invites` (`list[str] | None`), `members`/`presences`/`voice_states`
(`ExtendedMutableMapping | None`). Every field is `| None`, reassigned in place
across the impl; `empty()` (`:270-290`) drives GC of the whole record. It is a
pure mutable index — **stays mutable**, is not an entity, does not become a
frozen Struct.

### 2.4 The mutation inventory (dossier 07 §8 — verified against source)

| Mutation | Anchor | Target kind | Frozen impact |
|---|---|---|---|
| `RefCell.ref_count += n` | `impl:141` (20+ callers) | RefCell | RefCell stays mutable |
| `RefCell.object = <new>` | `impl:1273, 1424, 1585, 1929, 1935` | RefCell slot | slot reassign OK; payload frozen |
| `MemberData.has_been_deleted = ...` | `impl:1119, 1269, 1271, 1276`; decl `internal:444` | Data meta-flag | can't live on a frozen struct → new home (§4.3) |
| `RichActivityData.emoji = emoji_data` | `impl:1432` | Data field | rebuild activity or keep Data mutable (§4.4) |
| `MessageData.update(...)` (8 fields) | `internal:884-925`; called `impl:1906, 1975` | Data fields | biggest blocker → `structs.replace` + RefCell swap (§4.5) |
| `guild.member_count/joined_at/is_large = ...` | `impl:591-593` | **copy** of `GatewayGuild` | operates on a private `copy.copy` before `set_guild` → `structs.replace` (§4.6) |
| `channel.permission_overwrites = {...}` | `internal:1055` (`copy_guild_channel`) | **copy** of channel | disappears if channels stored directly & frozen (§4.7) |
| `GuildRecord.<field> = ...` | throughout impl | internal index | GuildRecord stays mutable |
| `self._me = copy.copy(user)` | `impl:1092` | attribute rebind | fine (rebind, not field mutation) |

Verified: no site mutates an object returned to a caller; no site mutates a
shared payload except through the `RefCell.object` slot *swap* (replace, not
mutate). `update_guild` and `copy_guild_channel` mutate *private fresh copies*.

### 2.5 `UNDEFINED` vs `None` on partial updates

`MessageData.update` (`internal/cache.py:884-925`, verified read) is driven
entirely by `is not undefined.UNDEFINED` checks: `content`, `edited_timestamp`,
`is_pinned`, `attachments`, `embeds`, `components`, `user_mentions`,
`role_mention_ids`, `channel_mentions`, `mentions_everyone`. The tri-state
(absent vs explicit `None`) must survive the migration.

## 3. Target design — the `*Data`-layer decision

Two strategies (dossier 07 §10.2, §11 OQ-1). Both are presented; the
**recommended** path is Strategy A (least churn), with Strategy B documented as
the cleaner long-term end-state.

### Strategy A (RECOMMENDED) — keep `*Data` as MUTABLE carriers of frozen public Structs

Keep the 8 `*Data` classes, but:

- They are **plain mutable** classes (drop `@with_copy`; keep `@attrs.define`
  mutable, or convert to non-frozen `msgspec.Struct` — msgspec Structs are
  mutable unless `frozen=True` is set). They are internal, never JSON-decoded,
  never returned to callers.
- They **stop stripping/re-adding `app`** — `build_entity` loses its `app`
  param (constraint (a); see
  [`02-cache-app-and-views.md`](02-cache-app-and-views.md) §3) and returns a
  bare frozen public Struct.
- They keep jobs (ii) `RefCell` cross-refs and (iii) in-place edit /
  `has_been_deleted`. Mutation stays exactly where it is today
  (`MessageData.update`, `RichActivityData.emoji =`, `has_been_deleted =`) — the
  carrier is mutable, so nothing about those flows changes except that the
  *rebuilt public Struct* is frozen.
- `build_from_entity` no longer needs defensive `copy.copy` on nested sequences
  (frozen payloads are safe to alias) — those copies drop (dossier 07 §3.2,
  §10.1).

Why recommended: **minimal blast radius.** The reference-counting GC scheme, the
partial-update `UNDEFINED` logic, and `has_been_deleted` all keep their current
home. Only the `app` plumbing and the defensive copies are removed. The 8
`build_entity(app)` methods lose a parameter and a field assignment — a
mechanical edit.

### Strategy B — store frozen public Structs directly, move mutation onto `RefCell` + `structs.replace`

Delete the `*Data` layer. Store frozen public Structs directly (inside a
`RefCell` where cross-referencing/GC is needed, directly in the entry dict
otherwise). Then:

- **Message edits** rebuild the frozen `Message` via
  `msgspec.structs.replace(old, **changed_fields)` and swap `RefCell.object`.
- **`has_been_deleted`** moves onto `RefCell` (a new `deleted: bool` field) or a
  `GuildRecord`-level deleted-set.
- **`RichActivityData.emoji` reassignment** becomes a rebuild of the frozen
  `RichActivity`/`MemberPresence` (or the emoji `RefCell` is threaded at build
  time).
- Cross-references (user/member/referenced-message `RefCell`s currently held by
  the `*Data` object) must be re-homed — either onto `RefCell` wrappers keyed in
  side tables, or reconstructed on read. This is the churn cost.

Why not (yet) recommended: the `*Data` object is the natural place to hold the
`RefCell` cross-references AND the mutable meta-state; deleting it forces both
into new structures. Strategy B is cleaner (one fewer layer, all storage is the
public struct) but is a larger, riskier change to the GC-heavy `_set_message`
(`impl:1887-1940`) / `_set_member` (`impl:1255-1279`) / `set_presence`
(`impl:1412-1438`) paths.

**Recommendation:** ship Strategy A in the frozen+no-app phase; keep Strategy B
on the table as a follow-up simplification once the declarative-decode end-state
(CONVENTIONS §1) is in place and the `*Data` layer's app-stripping job is fully
gone. Record as decision D8 in
[`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md).

## 4. Target design — the specific rewrites

The following apply under **Strategy A** primarily, with the Strategy-B variant
noted where they differ.

### 4.1 Delete `Cell`

`Cell` (`internal/cache.py:989-1004`) is dead. Delete the class and its
`@with_copy` decorator outright. (Dossier 07 §0.5.)

### 4.2 `RefCell` — mutable, no more `copy`

`RefCell` stays a mutable generic wrapper. Its `.copy()` method
(`internal/cache.py:1021-1029`) currently returns `copy.copy(self.object)`;
since the payload is now a frozen struct that is safe to share, `.copy()`
becomes `return self.object` (identity), and `unwrap_ref_cell`
(`:1032-1045`) likewise returns `cell.object` without copying. `ref_count` and
`.object` slot reassignment are unchanged — they are the GC primitive
(`RefCell` is **not** frozen). Remove `@with_copy`; keep `@attrs.define` mutable
(or leave as-is minus the decorator).

Under **Strategy B**, `RefCell` additionally grows a `deleted: bool` field
(§4.3).

### 4.3 `has_been_deleted` — where it lives

Today it is `MemberData.has_been_deleted` (`init=False`, decl
`internal/cache.py:444`), set at `impl/cache.py:1119, 1269, 1271, 1276`, read by
`_can_remove_member` (`:1107-1108` — `ref_count < 1 AND object.has_been_deleted`)
and by `get_members_view_for_guild` (`:1242-1244`).

- **Strategy A:** unchanged — it stays on the mutable `MemberData` carrier. No
  work beyond confirming `MemberData` is mutable (it is, per Strategy A).
- **Strategy B:** it cannot live on a frozen `Member` struct. Move it to the
  member's `RefCell` as `RefCell.deleted: bool`. Every read/write site
  (`impl:1107-1108, 1119, 1242-1244, 1269, 1271, 1276`) retargets from
  `member_data.has_been_deleted` to `member_cell.deleted`.

### 4.4 `RichActivityData.emoji` reassignment

`set_presence` (`impl/cache.py:1412-1438`, verified read) builds
`MemberPresenceData` then, per activity whose emoji is an unknown
`CustomEmoji`, creates/refreshes an `_unknown_custom_emoji_entries` `RefCell`
and points `activity_data.emoji = emoji_data` (`:1432`), ref-incrementing.

- **Strategy A:** `RichActivityData` is a mutable carrier → the `emoji =`
  reassignment stays exactly as-is. No change.
- **Strategy B:** the emoji `RefCell` must be threaded into the frozen
  `RichActivity` at build time (before the public struct is frozen) or the
  presence is rebuilt via `structs.replace`. Prefer resolving the unknown-emoji
  `RefCell` *before* constructing the frozen activity struct so no post-build
  reassignment is needed.

### 4.5 `MessageData.update` — the biggest blocker

`MessageData.update` (`internal/cache.py:884-925`, verified read) mutates up to
10 fields in place, each guarded by `is not undefined.UNDEFINED`, and is called
from `_set_message` for referenced-message chains (`impl:1906`) and from
`update_message` (`impl:1975`).

- **Strategy A (RECOMMENDED):** `MessageData` stays a mutable carrier. `update`
  is unchanged **except** its defensive copies of the frozen payloads drop:
  - `self.attachments = tuple(map(copy.copy, message.attachments))`
    (`:903`) → `self.attachments = tuple(message.attachments)` (attachments are
    frozen).
  - `self.embeds = tuple(map(_copy_embed, message.embeds))` (`:906`) →
    `tuple(message.embeds)` once `Embed` is frozen/immutable (embeds are a
    special case — see [`../06-model-modules/07-embeds.md`](../06-model-modules/07-embeds.md); `_copy_embed` at `internal:712-726` can be deleted if `Embed` becomes safe to share).
  - `user_mentions` RefCell rebuild (`:914`) keeps wrapping in `RefCell` but
    drops the inner `copy.copy(user)`.
  - `channel_mentions` dict rebuild (`:921`) drops the per-value `copy.copy`.
  The `is not undefined.UNDEFINED` tri-state logic is untouched — see §4.8.
- **Strategy B:** `update` is replaced by
  `new_message = msgspec.structs.replace(cell.object, **{f: v for the
  UNDEFINED-passing fields})` followed by `cell.object = new_message`. The
  `RefCell` cross-references (author/member/user_mentions) that `MessageData`
  held must be recomputed and stored alongside; this is the churn that makes B
  heavier for messages specifically.

### 4.6 `update_guild` patch

`update_guild` (`impl/cache.py:579-596`, verified read) takes
`guild = copy.copy(guild)` (`:586`), then patches `member_count`, `joined_at`,
`is_large` from the cached guild (`:591-593`) because Discord omits them on
`GUILD_UPDATE`, then `set_guild(guild)`.

Under frozen `GatewayGuild`, the `copy.copy` + field assignment is illegal.
Rewrite (both strategies) as:

```python
cached_guild = self.get_guild(guild.id)
if cached_guild:
    guild = msgspec.structs.replace(
        guild,
        member_count=cached_guild.member_count,
        joined_at=cached_guild.joined_at,
        is_large=cached_guild.is_large,
    )
self.set_guild(guild)
```

`msgspec.structs.replace` returns a new frozen struct with the three fields
overridden. (Verify it is permitted on a `frozen=True` Struct — it is, per
dossier 13 capability matrix.)

### 4.7 `copy_guild_channel`

`copy_guild_channel` (`internal/cache.py:1048-1058`) shallow-copies the channel
then rebuilds `permission_overwrites` with per-value `copy.copy` (`:1055`)
because the channel holds a *mutable* overwrite mapping a shallow copy would
alias. Under frozen channels whose `permission_overwrites` is an immutable
mapping/tuple (model-module concern — see
[`../06-model-modules/04-channels.md`](../06-model-modules/04-channels.md)),
this function's entire purpose evaporates. Delete it; channel get/set store and
return the frozen channel directly (see
[`02-cache-app-and-views.md`](02-cache-app-and-views.md) §4). Same for
`_copy_embed` (`internal:712-726`) once `Embed` is safe to share.

### 4.8 `UNDEFINED` on partial updates → sentinel decision

The tri-state on partial message updates (absent vs explicit `None`) must
survive. Per CONVENTIONS §5 (decision D5), the preferred path keeps
`hikari.undefined.UNDEFINED` as the field default; the fallback adopts
`msgspec.UNSET`. The cache is a heavy consumer via `MessageData.update` and
`update_message` (`impl:1949-1977`). This file does not decide the sentinel — it
inherits whatever
[`../01-foundations/03-undefined-and-unset.md`](../01-foundations/03-undefined-and-unset.md)
resolves — but flags that **all `is not undefined.UNDEFINED` checks in
`MessageData.update` and `update_message` must migrate identically** (find/replace
to `is not UNSET` if the fallback is chosen; unchanged if UNDEFINED is kept).
Under Strategy A the `MessageData` carrier still stores these fields as
`UndefinedOr[...]` mutable slots, so keeping `UNDEFINED` is the zero-churn
option.

## 5. Step-by-step migration

1. **Delete `Cell`** (`internal/cache.py:989-1004`) and its `@with_copy`.
2. **Make `RefCell` mutable-only:** remove `@with_copy`; change `.copy()` /
   `unwrap_ref_cell` to identity returns (§4.2). Keep `ref_count` + `.object`
   slot semantics.
3. **Keep `GuildRecord` mutable** — remove only its `@with_copy` decorator
   (`internal/cache.py:187`); no structural change.
4. **Adopt Strategy A for the `*Data` layer:** drop `@with_copy` on all 8
   classes; drop `app` from `build_entity` signatures and bodies
   (co-change with [`02-cache-app-and-views.md`](02-cache-app-and-views.md) §3);
   drop defensive `copy.copy` on nested payloads in `build_from_entity` /
   `MessageData.update` (§4.5).
5. **Rewrite `update_guild`** to `msgspec.structs.replace` (§4.6).
6. **Delete `copy_guild_channel` and `_copy_embed`** once channels/embeds are
   frozen-safe (§4.7); retarget their call sites (`impl:811, 820, 851, 859`;
   message embed path) to direct store/return.
7. **Migrate the `UNDEFINED` checks** in `MessageData.update` (`:884-925`) and
   `update_message` (`:1949-1977`) per the sentinel decision (§4.8) — no-op if
   UNDEFINED is kept.
8. **(Deferred) Strategy B**, if adopted later: delete the `*Data` classes;
   move `has_been_deleted` to `RefCell.deleted`; rewrite message edits as
   `structs.replace` + slot swap; re-home the `RefCell` cross-references. Gate on
   a dedicated PR; see [`../11-rollout/01-pr-breakdown.md`](../11-rollout/01-pr-breakdown.md).

## 6. Affected files and symbols

| File | Anchor | Change |
|---|---|---|
| `hikari/internal/cache.py` | `:989-1004` (`Cell`) | delete |
| `hikari/internal/cache.py` | `:1007-1029` (`RefCell`) | drop `@with_copy`; `.copy()`→identity; stays mutable |
| `hikari/internal/cache.py` | `:1032-1045` (`unwrap_ref_cell`) | drop inner copy |
| `hikari/internal/cache.py` | `:187-290` (`GuildRecord`) | drop `@with_copy`; stays mutable |
| `hikari/internal/cache.py` | `:293-333` (`BaseData`), 8 `*Data` classes | drop `@with_copy`; drop `app` from `build_entity`; drop defensive copies |
| `hikari/internal/cache.py` | `:444` (`MemberData.has_been_deleted`) | A: unchanged; B: move to `RefCell.deleted` |
| `hikari/internal/cache.py` | `:884-925` (`MessageData.update`) | drop payload copies; keep/replace UNDEFINED checks; B: `structs.replace` |
| `hikari/internal/cache.py` | `:712-726` (`_copy_embed`), `:1048-1058` (`copy_guild_channel`) | delete once frozen-safe |
| `hikari/impl/cache.py` | `:579-596` (`update_guild`) | `copy.copy`+patch → `structs.replace` |
| `hikari/impl/cache.py` | `:1412-1438` (`set_presence`) | A: unchanged; B: resolve emoji RefCell pre-build |
| `hikari/impl/cache.py` | `:1887-1940` (`_set_message`), `:1949-1977` (`update_message`) | drop copies; B: rewrite edits as `structs.replace`+swap |
| `hikari/impl/cache.py` | `:1107-1119, 1242-1276` (member GC) | A: unchanged; B: retarget `has_been_deleted`→`RefCell.deleted` |

## 7. Risks and gotchas

1. **Strategy choice is load-bearing.** A adds no new structures but keeps a
   layer that the declarative end-state ultimately wants gone; B is the clean
   target but touches the GC-critical set paths. Do not blend them
   half-and-half within one entity type.
2. **`msgspec.structs.replace` on frozen Structs** — confirm it returns a new
   frozen instance and honors `kw_only`/defaults (dossier 13). It is the crux of
   `update_guild` (both strategies) and message edits (Strategy B).
3. **Referenced-message chains** (`impl:1899-1906`) call
   `MessageData.update` on the *referenced* message. Under Strategy B this
   becomes a `structs.replace` + `RefCell.object` swap on the referenced cell —
   verify the ref-count bookkeeping around `_referenced_messages`
   (`impl:1794-1833`) still balances after the swap.
4. **UNDEFINED semantics.** If the sentinel changes (fallback D5), every
   partial-update check must migrate atomically or a "field omitted" is
   mis-read as "field set to None," corrupting message edits. Keep the two
   `MessageData.update` / `update_message` sites in one PR.
5. **`RichActivityData.emoji` union** (`RefCell[CustomEmoji] | str | None`)
   under Strategy B must be resolved before freezing the activity — a frozen
   struct cannot receive the post-hoc `RefCell` assignment. Strategy A avoids
   this entirely.
6. **Enum strictness in Data fields** touches `MessageData.flags` (copied at
   `impl:824`) and the `X | int` unions on Data models (`InviteData.type/
   target_type`, `MemberData.guild_flags`, `GuildStickerData.format_type`,
   `RichActivityData.type`, `MemberPresenceData.visible_status`,
   `MessageData.type`). See [`02-cache-app-and-views.md`](02-cache-app-and-views.md)
   §5 — these carry over as strict enums; the cache never re-parses raw ints (the
   entity_factory already resolved them), so no unknown-value handling is needed
   at the cache boundary.

## 8. Verification

1. **Mutation-still-works tests:** message edit (`update_message`) applies a
   partial update and the cached `Message` reflects only the provided fields;
   referenced-message update propagates; presence unknown-emoji ref-count
   increments/decrements balance across set/clear.
2. **`update_guild` patch test:** a `GUILD_UPDATE` omitting
   `member_count`/`joined_at`/`is_large` preserves the cached values via
   `structs.replace` (regression for `impl:591-593`).
3. **GC balance test:** create/delete flows for users, members, unknown emojis,
   referenced messages leave `ref_count` at 0 and evict the entries
   (`_can_remove_*` / `_garbage_collect_*` unchanged).
4. **`has_been_deleted` semantics:** a member referenced by a cached voice
   state / message lingers after `delete_member` and is hidden from
   `get_members_view_for_guild`, then GC'd when the last reference drops
   (Strategy A: on `MemberData`; Strategy B: on `RefCell.deleted`).
5. **Grep-clean:** no `copy.copy` / `.copy()` remains in `internal/cache.py`
   except intentional `dict` snapshots in `freeze()` (owned by
   [`02-cache-app-and-views.md`](02-cache-app-and-views.md)); `Cell` gone.

## 9. Open questions and decisions

Cross-linked to [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md) (decision D8, and D5 for the sentinel).

- **OQ-1 (decision):** Strategy A (mutable `*Data` carriers) vs Strategy B
  (frozen structs stored directly + `structs.replace`). Recommended: A now, B as
  a follow-up. Maintainer call.
- **OQ-2:** If Strategy B, does `has_been_deleted` live on `RefCell.deleted` or a
  `GuildRecord`-level deleted-set? (RefCell is cleaner — the flag is per-member.)
- **OQ-3:** `UNDEFINED` vs `msgspec.UNSET` for partial-update fields — inherited
  from [`../01-foundations/03-undefined-and-unset.md`](../01-foundations/03-undefined-and-unset.md); cache prefers keeping UNDEFINED (zero churn under Strategy A).
- **OQ-4:** Confirm the cache never re-parses raw enum ints (dossier 07 §11 OQ-6)
  — the entity_factory resolves enums before `set_*`, so Data enum fields are
  already strict values.
