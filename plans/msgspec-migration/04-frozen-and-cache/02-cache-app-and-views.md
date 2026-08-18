# Cache app-injection collapse and views

Purpose: remove the cache's role as the source of `app` for read-back entities.
`build_entity(app)` loses its parameter, the `_build_*` injectors collapse,
`CacheImpl._app` likely vanishes, the two storage strategies (Data vs
direct-entity) are reconciled under frozen+no-app, and `CacheView` immutability
becomes free while `freeze()` stays.

## 1. Objective

- Serve constraints (a) (no `app` injection) and (c) (frozen structs) at the
  cache boundary: `cache.get_*()` returns a **bare app-less frozen Struct**.
- Collapse the `build_entity(app)` mechanism and the `_build_*` injectors that
  re-attach `self._app` on read.
- Reconcile the two storage strategies (dossier 07 §6): the "Data" strategy
  loses its app re-injection; the "direct-entity" strategy loses the `app` that
  rode inside its `copy.copy`.
- Confirm `CacheView`'s immutability contract is now provided for free, while
  the mapping-wrapper `freeze()` stays (dict snapshot still needed).

This file owns the *app/view* surface. Copy deletion is in
[`00-frozen-structs-and-copy-removal.md`](00-frozen-structs-and-copy-removal.md);
the mutable-carrier redesign is in
[`01-cache-data-layer-and-mutation.md`](01-cache-data-layer-and-mutation.md).

## 2. Current state

### 2.1 The cache is today's source of `app` (dossier 07 §7)

`CacheImpl.__init__` stores `self._app = app` (`impl/cache.py:107-108`,
verified read) from the owning `RESTAware` bot. On read-back the cache supplies
`app` two different ways depending on storage strategy:

- **Data strategy** re-injects `self._app` at `build_entity` time via 8
  `_build_*` helpers. Verified: `_build_emoji` (`impl/cache.py:194-195`,
  `emoji_data.build_entity(self._app)`); the rest per dossier 07 §6 at anchors
  `:329` (sticker), `:879` (invite), `:1104` (member), `:1291` (presence),
  `:1594` (voice state), `:1792` (message). Each forwards `self._app` into the
  `*Data.build_entity(app)` method (`internal/cache.py`, e.g.
  `VoiceStateData.build_entity` `:948` `app=app`).
- **Direct-entity strategy** carries `app` *inside* the stored `copy.copy` of a
  full entity, because `copy_attrs` shallow-copies the `app` reference (dossier
  07 §2.2, §7).

### 2.2 The storage-strategy table (dossier 07 §6 — verified anchors)

"Set copy" = copy on write; "Get build/copy" = copy on read; "app source" = how
the returned object obtains `app` today.

| Entity (public) | Backing store | Strategy | Set copy | Get build/copy | app source |
|---|---|---|---|---|---|
| DM channel id | `_dm_channel_entries` | primitive | none | none (int) | n/a |
| `KnownCustomEmoji` | `_emoji_entries: *Data` | Data | `build_from_entity` | `_build_emoji`→`build_entity(self._app)` (`:195`) | re-injected |
| `GuildSticker` | `_sticker_entries: *Data` | Data | `build_from_entity` | `_build_sticker` (`:329`) | re-injected |
| `InviteWithMetadata` | `_invite_entries: *Data` | Data | `build_from_entity` | `_build_invite` (`:879`) | re-injected |
| `Member` | `guild_record.members: RefCell[*Data]` | Data+RefCell | `build_from_entity` | `_build_member` (`:1104`) | re-injected |
| `MemberPresence` | `guild_record.presences: *Data` | Data | `build_from_entity` | `_build_presence` (`:1291`) | re-injected |
| `VoiceState` | `guild_record.voice_states: *Data` | Data | `build_from_entity` | `_build_voice_state` (`:1594`) | re-injected |
| `Message` | `_message_entries/_referenced_messages: RefCell[*Data]` | Data+RefCell | `build_from_entity` | `_build_message` (`:1792`) | re-injected |
| `GatewayGuild` | `guild_record.guild` | Direct | `copy.copy` (`:562`) | `copy.copy` (`:498/506`) | carried inside copy |
| `PermissibleGuildChannel` | `_guild_channel_entries` | Direct | `copy_guild_channel` (`:859`) | `copy_guild_channel` (`:811`) | carried inside copy |
| `GuildThreadChannel` | `_guild_thread_entries` | Direct | `copy.copy` (`:730`) | `copy.copy` (`:688`) | carried inside copy |
| `Role` | `_role_entries` | Direct | **NONE (`:1538`)** | `copy.copy` (`:1511`) | carried inside copy |
| `OwnUser` | `_me` | Direct | `copy.copy` (`:1092`) | `copy.copy` (`:1086`) | carried inside copy |
| `User` | `_user_entries: RefCell[User]` | Direct+RefCell | `copy.copy` (`:1585/1588`) | `RefCell.copy` (`:1570`) | carried inside copy |
| `CustomEmoji` (unknown) | `_unknown_custom_emoji_entries: RefCell` | Direct+RefCell | `copy.copy` (`:1424/1428`) | (internal only) | carried inside copy |

Eight `_build_*` methods inject `self._app`; six direct-entity types carry `app`
inside their stored copy.

### 2.3 The views (dossier 07 §4.6)

| View | Anchor | Behavior |
|---|---|---|
| `CacheMappingView` | `internal/cache.py:95-158` | `__getitem__` returns `builder(entry)` (Data→entity) if a builder was set, else `self._copy(entry)` = `copy.copy` (`:126-140`). Read-time copy for direct-entity views. |
| `EmptyCacheView` | `:161-184` | Zero-length; raises on access. |
| `Cache3DMappingView` | `:1061-1069` | `_copy` overridden to a **no-op** (nested views already immutable). |

`CacheView` (`api/cache.py:47-65`) is documented as *"an immutable snapshot
view"* — the immutability guarantee is provided by these copies today.

### 2.4 The mapping wrappers `freeze()` (dossier 07 §4.7)

`ExtendedMutableMapping.freeze()` (`internal/collections.py:86-101`) returns a
plain `dict` snapshot; `FreezableDict.freeze` (`:122-123`) is `self._data.copy()`
(a dict copy, not an entity copy). Used everywhere the cache builds a view
(`get_roles_view` `impl:1518`, etc.). `LimitedCapacityCacheMap.freeze`
(`:146-201`) likewise.

## 3. Target design

### 3.1 `build_entity` loses `app`; the `_build_*` injectors collapse

Under constraint (a) the public frozen Structs have **no `app` field**. The Data
strategy's `build_entity(app)` therefore has no parameter to accept and no field
to set:

```python
# before (internal/cache.py, e.g. VoiceStateData)
def build_entity(self, app: traits.RESTAware, /) -> voices.VoiceState:
    return voices.VoiceState(app=app, channel_id=self.channel_id, ...)

# after
def build_entity(self) -> voices.VoiceState:
    return voices.VoiceState(channel_id=self.channel_id, ...)   # no app=
```

The 8 `_build_*` wrappers in `impl/cache.py` (`:195, 329, 879, 1104, 1291,
1594, 1792`) that only forwarded `self._app` either:

- become trivial `emoji_data.build_entity()` calls (keep them as thin adapters
  if the view-`builder=` callable API is retained — `CacheMappingView` takes a
  `builder` callback), or
- are inlined where the `builder=` argument previously received
  `self._build_emoji` etc.

Recommendation: keep the thin `_build_*` methods (they are the `builder=`
callback the views expect) but strip the `self._app` argument — smallest diff,
preserves the view builder wiring. Note two `*Data.build_entity` methods already
take and *ignore* the app arg (`MemberData` `internal:469`, `RichActivityData`
`internal:649`) — those simply drop the parameter.

### 3.2 `CacheImpl._app` — likely removed

`self._app` (`impl/cache.py:108`) exists to feed `build_entity`. Once no
`build_entity` needs it and no direct copy needs to preserve it, grep for any
other `self._app` use in `impl/cache.py`. Dossier 07 §10.2 finds none beyond
`build_entity`. If confirmed, **remove `self._app`** and drop the `app`
parameter's storage in `__init__` (the constructor may still *accept* `app` for
signature compatibility with the `MutableCache` interface — decide in
[`../09-rest-and-gateway/00-rest-client.md`](../09-rest-and-gateway/00-rest-client.md);
minimally, stop storing it). This severs the cache↔app coupling.

### 3.3 `cache.get_*` returns a bare app-less frozen Struct

Per constraint (a) end-state, getters return the stored frozen struct directly —
no app, no wrapper. Do **not** add an app-carrying wrapper/proxy (dossier 07 §7
option 2) — that re-creates a soft version of the app coupling the migration is
removing. Callers that need `rest`/`cache` use the externally-held client
(constraint (a); see
[`../03-app-removal-and-helpers/00-strategy.md`](../03-app-removal-and-helpers/00-strategy.md)).

### 3.4 Storage strategy reconciled under frozen+no-app

The two strategies converge because both lose their app mechanism:

| Strategy | Today | After frozen+no-app |
|---|---|---|
| Data (emoji/sticker/invite/member/presence/voice/message) | `*Data.build_entity(self._app)` on read; `build_from_entity` copies nested seqs on write | `build_entity()` returns bare frozen struct; write copies drop. `*Data` kept as mutable carrier (Strategy A, file 01) for RefCell cross-refs + edits |
| Direct (guild/channel/thread/role/me/user) | `copy.copy` on read/write; app rides inside | store the frozen struct **by reference** on write; return it **by reference** on read; no app to carry |

The direct-entity setters all become "store the argument" — exactly what
`set_role` (`impl:1538`) already does. The read paths all become "return the
stored struct." This is where the `set_role` no-copy asymmetry
([`00-frozen-structs-and-copy-removal.md`](00-frozen-structs-and-copy-removal.md)
§4.6) is repaired by making every direct setter match `set_role`, not the other
way round.

Note: some direct-entity types (guild, channel) formerly needed
`copy_guild_channel` / `structs.replace` for the *internal* patch flows
(`update_guild`, overwrite rebuild) — those are handled in
[`01-cache-data-layer-and-mutation.md`](01-cache-data-layer-and-mutation.md)
§4.6-4.7, not here. Here the concern is only the read/write *entity handoff*.

### 3.5 Views: immutability free, `freeze()` stays

- `CacheMappingView._copy` (`internal:125-127`) → identity (frozen values are
  safe to expose directly). `Cache3DMappingView._copy` stays a no-op.
- The `builder=` path (`CacheMappingView.__getitem__` `:137-138`) still calls
  `_build_*` for Data-backed views — now app-less (§3.1). Direct-backed views
  (roles, channels) use the identity `_copy`.
- **`CacheView` immutability is now provided for free** by the frozen values —
  the `api/cache.py:47-65` "immutable snapshot" contract holds without copies.
- **`freeze()` stays** (`collections.py:86-123`): it snapshots the *dict* (keys
  can still be added/removed even when values are frozen). `FreezableDict.freeze`
  and `LimitedCapacityCacheMap.freeze` are unchanged — they never copied the
  values, only the mapping.

### 3.6 Enum-strictness touch points in the Data models

Constraint (b) (strict enums) reaches the cache at the Data models (dossier 07
§10.2). The `X | int` tolerance unions on Data fields become the bare strict
enum: `InviteData.type`/`target_type`, `MemberData.guild_flags`,
`GuildStickerData.format_type`, `RichActivityData.type`,
`MemberPresenceData.visible_status`, `MessageData.type`. And
`MessageData.flags = copy.copy(message.flags)` (`impl:824`) — `copy.copy` on an
`IntFlag` is a no-op, so the copy drops and the field is stored directly. The
cache **never re-parses raw ints**: the entity_factory has already resolved
these to enum members before `set_*`, so no `_missing_`/unknown-value handling
is needed at the cache boundary (see
[`../02-enums/00-strategy-and-forward-compat.md`](../02-enums/00-strategy-and-forward-compat.md)).

## 4. Step-by-step migration

1. **Strip `app` from the 8 `*Data.build_entity` methods** (`internal/cache.py`;
   drop the `app: traits.RESTAware` param and every `app=app` construction
   kwarg). The two that already ignore the arg (`MemberData` `:469`,
   `RichActivityData` `:649`) just drop the parameter.
2. **Strip `self._app` from the 8 `_build_*` wrappers** (`impl:195, 329, 879,
   1104, 1291, 1594, 1792`) → `data.build_entity()`.
3. **Remove `CacheImpl._app`** (`impl:108`) after grep-confirming no other use;
   decide whether `__init__` still accepts `app` for interface compatibility
   (recommend: accept, do not store — coordinate with
   [`../09-rest-and-gateway/00-rest-client.md`](../09-rest-and-gateway/00-rest-client.md)).
4. **Convert direct-entity setters to store-by-reference:** `set_guild`
   (`:562`), `set_thread` (`:730`), `set_guild_channel` (`:859`), `set_me`
   (`:1092`), `_set_user` (`:1585/1588`), unknown-emoji create/refresh
   (`:1424/1428`) drop `copy.copy`/`copy_guild_channel`. `set_role` (`:1538`)
   already conforms.
5. **Convert direct-entity getters to return-by-reference:** `get_guild`
   (`:498/506`), `get_thread` (`:688`), `get_guild_channel` (`:811`), `get_me`
   (`:1086`), `get_role` (`:1511`), `get_user`/`RefCell.copy` (`:1570`) return
   the stored struct.
6. **Make `CacheMappingView._copy` identity** (`internal:125-127`); leave
   `Cache3DMappingView._copy` no-op (`:1061-1069`).
7. **Leave `freeze()` untouched** (`collections.py:86-123`) — verify it still
   snapshots the dict.
8. **Apply strict-enum field types** to the Data models (§3.6) — co-change with
   [`../02-enums/03-strict-enum-field-inventory.md`](../02-enums/03-strict-enum-field-inventory.md);
   drop `copy.copy(message.flags)` at `impl:824`.

## 5. Affected files and symbols

| File | Anchor | Change |
|---|---|---|
| `hikari/impl/cache.py` | `:107-108` (`__init__`, `_app`) | stop storing `app`; remove `_app` if unused |
| `hikari/impl/cache.py` | `:195, 329, 879, 1104, 1291, 1594, 1792` (`_build_*`) | drop `self._app` arg |
| `hikari/impl/cache.py` | `:562, 730, 859, 1092, 1424, 1428, 1585, 1588` | direct setters → store-by-reference |
| `hikari/impl/cache.py` | `:498, 506, 688, 811, 1086, 1511, 1570` | direct getters → return-by-reference |
| `hikari/impl/cache.py` | `:1538` (`set_role`) | already conformant; asymmetry closed |
| `hikari/impl/cache.py` | `:824` (`MessageData.flags` copy) | drop copy; store IntFlag directly |
| `hikari/internal/cache.py` | 8 `*Data.build_entity` (`:469, 649, 948, …`) | drop `app` param + `app=` kwargs |
| `hikari/internal/cache.py` | `:125-127` (`CacheMappingView._copy`) | → identity |
| `hikari/internal/cache.py` | `:1061-1069` (`Cache3DMappingView._copy`) | unchanged (no-op) |
| `hikari/internal/collections.py` | `:86-123` (`freeze`) | unchanged; verified still needed |
| `hikari/api/cache.py` | `:47-65` (`CacheView` contract) | doc: immutability now from frozen values |
| Data models | strict-enum fields (§3.6) | `X \| int` → bare enum |

## 6. Risks and gotchas

1. **Interface signature churn.** `Cache`/`MutableCache` (`api/cache.py`, 1763
   LOC) declare abstract getters/setters. Dropping app from `build_entity`
   changes internal signatures but the *public* getter signatures
   (`get_role(id) -> Role | None`) are unchanged — only the returned object loses
   `.app`. Confirm no abstract method typed a return as app-carrying.
2. **`_app` may have a hidden consumer.** Grep must be exhaustive before removing
   it (e.g. logging, settings, a helper). Dossier 07 §10.2 finds none, but
   re-verify at implementation time (Verification §7.2).
3. **Removing app is a public break.** `cache.get_guild(id).app` and every entity
   helper that used it stop existing (constraint (a)). This is the same break
   catalogued for the entity layer — cross-reference
   [`../11-rollout/03-breaking-changes-and-changelog.md`](../11-rollout/03-breaking-changes-and-changelog.md);
   do not add a compatibility app-wrapper (§3.3).
4. **View builder API.** If `_build_*` methods are removed rather than slimmed,
   the `CacheMappingView(items, builder=...)` call sites must be updated. Slim
   (keep the method, drop the arg) is lower-risk — keeps the `builder=` wiring.
5. **`freeze()` must stay.** A tempting but wrong simplification: "values are
   frozen, so views need no snapshot." False — the *dict* still mutates (keys
   added/removed by concurrent cache writes). Keep `freeze()` (dossier 07 §10.2).

## 7. Verification

1. **App-less return:** `assert not hasattr(cache.get_guild(id), "app")` for
   every getter; `cache.get_role(id) is cache.get_role(id)` (identity, no copy).
2. **`_app` removal:** `rg -n "self\._app" hikari/impl/cache.py` returns 0 after
   the change (or only the constructor param if kept for interface parity).
3. **View immutability:** a `CacheView` exposes the same frozen instance the
   cache holds; mutating the source dict (a later `set_*`) does not alter a
   previously-taken `freeze()` snapshot (dict snapshot semantics preserved).
4. **Data getters:** emoji/sticker/invite/member/presence/voice/message getters
   return correctly-typed bare structs with no `app` and correct nested
   `RefCell`-resolved sub-entities.
5. **Strict-enum fields:** cached entities carry enum members (not raw ints) on
   the former `X | int` Data fields; `MessageData.flags` round-trips as an
   `IntFlag`.
6. **Full cache suite** passes after the identity-assertion rewrite (file
   [`../10-testing/02-cache-copy-and-enum-tests.md`](../10-testing/02-cache-copy-and-enum-tests.md)).

## 8. Open questions and decisions

Cross-linked to [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md) (decisions D8, D9; constraint (a)).

- **OQ-1:** Remove `CacheImpl._app` entirely, or keep the constructor accepting
  `app` (unused) for `MutableCache` interface parity? Recommend: keep the param,
  drop the field. Coordinate with the REST/gateway wiring.
- **OQ-2 (settled here):** `cache.get_*` returns a bare app-less struct, no
  wrapper (constraint (a) on-rails reading; dossier 07 §7 option 1). Confirm no
  internal cache consumer reads `.app` off a returned object.
- **OQ-3:** Slim vs delete the 8 `_build_*` view-builder methods — recommend slim
  (keeps `builder=` wiring, smaller diff).
- Confirmed here: `freeze()` stays (dict snapshot still required); `CacheView`
  immutability is free under frozen values; the `set_role` asymmetry is repaired
  by making all direct setters store-by-reference.
