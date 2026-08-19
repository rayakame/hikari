# Frozen structs and copy-machinery removal

Purpose: gut the bespoke attrs copy engine — slimming it now, deleting it
wholesale in a later phase — and remove every defensive copy the cache takes, on
the strength of constraint (c) (frozen public Structs are safe to share by
reference). This file establishes the pre-condition — proving no code mutates a
model after construction — and the mechanical deletions that follow.
It is the base for the two cache files that follow
([`01-cache-data-layer-and-mutation.md`](01-cache-data-layer-and-mutation.md),
[`02-cache-app-and-views.md`](02-cache-app-and-views.md)).

## 1. Objective

- Serve constraint (c): public wire entities become `frozen=True` msgspec
  Structs, so a shared reference can never be mutated by a caller.
- Slim `hikari/internal/attrs_extensions.py` (256 LOC): remove the dead deep-copy
  half and the cache-only shallow-copy path, drop the ~221 `@with_copy`
  decorations on Struct-converted classes (of the 246 tree-wide), and delete the
  ~104 `copy.copy` call sites in the two cache modules. `with_copy` is **retained**
  for the ~25 deferred non-Struct consumers; the module is deleted wholesale only
  in a later phase, once every consumer is off attrs (§3.2, §3.4).
- Prove the safety pre-condition: **nothing mutates a wire model after it is
  built.** This is what makes the deletions sound rather than merely convenient.

The mutation-heavy *internal carriers* (`RefCell`, `GuildRecord`, the `*Data`
layer) are explicitly out of scope here — they stay mutable and are handled in
[`01-cache-data-layer-and-mutation.md`](01-cache-data-layer-and-mutation.md).
This file removes only copy/immutability scaffolding whose sole reason to exist
was that models were mutable.

## 2. Current state

### 2.1 The copy engine (`hikari/internal/attrs_extensions.py`)

The whole 256-line module exists only because attrs models are mutable and the
cache must isolate its stored copies from caller mutation (dossier 03 §1). Its
`__all__` (`attrs_extensions.py:25-31`) exports `copy_attrs`, `deep_copy_attrs`,
`invalidate_deep_copy_cache`, `invalidate_shallow_copy_cache`, `with_copy`.

| Symbol | Anchor | Role |
|---|---|---|
| `SKIP_DEEP_COPY` | `:40` | metadata key marking fields the deep copier skips (the `app` field) |
| `get_fields_definition` | `:61-86` | splits init/non-init fields; `:81` `key_word = field.name.removeprefix("_")` — the `_foo`-attr/`foo`-kwarg convention |
| `generate_shallow_copier` | `:90-113` | `exec`-codegens `def copy(m): r=cls(kwarg=m.attr,…); r.non_init=m.attr; return r` |
| `copy_attrs` | `:137-150` | public shallow copy → `get_or_generate_shallow_copier` |
| `generate_deep_copier` | `:163-192` | `exec`-codegens `std_copy.deepcopy` per field, skipping `SKIP_DEEP_COPY` |
| `deep_copy_attrs` | `:218-244` | public deep copy |
| `with_copy` | `:247-255` | installs `cls.__copy__ = copy_attrs`, `cls.__deepcopy__ = deep_copy_attrs` |

The module keeps two module-level caches `_DEEP_COPIERS`/`_SHALLOW_COPIERS`
(`:42-45`) invalidated on `ux` reload.

### 2.2 What is already dead in-tree (verified — dossier 07 §0.3, §2.3)

- `copy.deepcopy` is called **nowhere** in `hikari/` source.
- `deep_copy_attrs`, `generate_deep_copier`, `get_or_generate_deep_copier`,
  `invalidate_deep_copy_cache`, `SKIP_DEEP_COPY`, `_DEEP_COPIERS` have **zero
  live in-tree consumers** — the entire deep-copy half is dead weight today,
  independent of this migration.
- Only the shallow path (`copy.copy` → `copy_attrs`) is exercised, and only by
  the cache.

### 2.3 The `@with_copy` blast radius

`@attrs_extensions.with_copy` decorates **246 classes** across 49 source files
(dossier 07 §2.1); **103** of them are in the 26 model modules (dossier 03 §0,
§8 per-module table). The remainder are `events/*` classes, the
`internal/cache.py` `*Data`/`RefCell`/`GuildRecord`/`Cell` carriers, and the
**~25 deferred non-Struct consumers** this phase does *not* touch — the
`special_endpoints` builders (~15), `impl/config.py` (5), `internal/routes.py`
(3), `errors.py` (2). Of the 246, **~221** sit on classes that become Structs or
plain mutable carriers (and lose the decorator here); **~25** stay on attrs and
keep `with_copy` (§3.2, §3.4). The `SKIP_DEEP_COPY` metadata is set on **151
fields** tree-wide (a raw grep returns 151; dossier 04 §0) — ~149 of them the
`app` field (23 in model modules, dossier 03 §0).

### 2.4 The cache copy sites (~104)

Regex counts (dossier 07 §3): `internal/cache.py` = 85, `impl/cache.py` = 19.
The `impl/cache.py` sites are read/write defensive copies on the *direct-entity*
storage strategy and app-injection paths:

| Anchor | Call | Role |
|---|---|---|
| `impl/cache.py:498, 506` | `copy.copy(guild_record.guild)` | guild read copy |
| `impl/cache.py:562` | `guild_record.guild = copy.copy(guild)` | guild write copy |
| `impl/cache.py:586` | `guild = copy.copy(guild)` | `update_guild` copy-before-patch |
| `impl/cache.py:688, 730` | `copy.copy(thread)` | thread read/write |
| `impl/cache.py:811, 859` | `copy_guild_channel(channel)` | channel read/write |
| `impl/cache.py:1086, 1092` | `copy.copy(self._me / user)` | own-user read/write |
| `impl/cache.py:1424, 1428` | `copy.copy(emoji)` | unknown-emoji refresh/create |
| `impl/cache.py:1511` | `copy.copy(role)` | role read copy |
| `impl/cache.py:1570, 1585, 1588` | `copy.copy(user)` | user read/refresh/create |

`internal/cache.py` sites cluster in `CacheMappingView._copy` (`:125-127`),
`RefCell.copy`/`Cell.copy` (`:1021-1029`, `:996-1004`), `unwrap_ref_cell`
(`:1032-1045`), `copy_guild_channel` (`:1048-1058`), `_copy_embed` (`:712-726`),
and the per-`*Data` `build_from_entity`/`build_entity` bodies that snapshot
mutable nested sequences into tuples.

### 2.5 The safety pre-condition is already met (verified — dossier 03 §7.3)

Grep across the model modules found **zero** occurrences of any of:
`object.__setattr__`, `__attrs_post_init__`, `on_setattr`, `frozen=True` (i.e.
models are mutable-but-never-frozen today), or post-construction field
assignment on a wire model (dossier 03 §0 table rows for
`__attrs_post_init__` = 0, `on_setattr`/`frozen=True` = 0). Models are already
treated as write-once in practice. The only in-place mutation in the whole cache
touches internal carriers (`RefCell`, `GuildRecord`, `*Data`) or *private fresh
copies* (`update_guild`'s `copy.copy(guild)` at `impl/cache.py:586`;
`copy_guild_channel`'s overwrite-dict rebuild at `internal/cache.py:1055`) —
never a shared model. Full inventory in dossier 07 §8, carried into
[`01-cache-data-layer-and-mutation.md`](01-cache-data-layer-and-mutation.md) §2.

## 3. Target design

### 3.1 Frozen wire Structs make copies pointless

Per base-struct conventions (CONVENTIONS §2; see
[`../01-foundations/01-base-struct-conventions.md`](../01-foundations/01-base-struct-conventions.md)),
every wire model becomes:

```python
class PartialChannel(snowflakes.Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    id: snowflakes.Snowflake
    name: str | None = None
    type: ChannelType = ...
    # NO app field.
```

`frozen=True` forbids attribute assignment. A caller who receives a cached
struct cannot mutate it; a second caller who receives the *same instance*
therefore cannot be affected. The defensive copy the cache takes today is a
no-op under this contract, so **every read-time and write-time `copy.copy` on a
wire model collapses to an identity pass-through**.

Note the one shallow-immutability caveat: a frozen Struct with a `list`/`dict`
field still holds a mutable container (dossier 03 §3.2). The migration relies on
the entity_factory producing **tuples** for sequence fields (it already
snapshots to tuples today — see the `internal/cache.py` build_* comments at
`:463-465, 523-525, 690-691`, "stored in immutable sequences (tuples)"). Mapping
fields that must stay read-only are covered per model module in
[`../06-model-modules/`](../06-model-modules/). This is a model-shape concern,
not a cache concern, and does not block copy removal.

### 3.2 Slim `attrs_extensions.py` now; delete it wholesale later

In the first pass `attrs_extensions.py` is **SLIMMED, not deleted**: the dead
deep-copy half and the cache-only shallow-copy path are removed, but `with_copy`
is retained for the deferred non-Struct consumers — the 42 `special_endpoints`
builders (~15 `with_copy`), `impl/config.py` (5), `internal/routes.py` (3),
`errors.py` (2). `attrs_extensions.py` is deleted wholesale only in a later
phase, once every consumer is off attrs.

Concretely: the deep-copy half is already dead (§2.2) and goes; the shallow
`copy_attrs` path loses its only live consumer (the cache stops copying) and
goes; but `with_copy` — plus the `get_fields_definition` /
`generate_shallow_copier` machinery it needs — **stays** until the ~25 deferred
consumers (§3.4) migrate. Imports in Struct-converted modules are removed here
(see §5 table); imports in the four deferred consumers are retained while the
slimmed module survives.

### 3.3 Cache reads/writes become identity

| Today | After |
|---|---|
| `return copy.copy(role) if role else None` (`impl/cache.py:1511`) | `return role` |
| `self._role_entries[role.id] = role` (`impl/cache.py:1538`) | unchanged — already no copy; now uniformly correct (§4.6) |
| `CacheMappingView._copy = copy.copy` (`internal/cache.py:125-127`) | `_copy = staticmethod(lambda v: v)` — or drop `_copy` and inline identity |
| `guild_record.guild = copy.copy(guild)` (`impl/cache.py:562`) | `guild_record.guild = guild` |

`RefCell.copy`/`unwrap_ref_cell` still return `self.object` but no longer copy
it — see [`01-cache-data-layer-and-mutation.md`](01-cache-data-layer-and-mutation.md)
§4, which owns the `RefCell` changes. `copy_guild_channel` and `_copy_embed`
are analysed there too (their raison d'être is defensive copying of mutable
sub-objects, which frozen structs eliminate).

### 3.4 Deferred non-Struct attrs consumers (config, routes, builders, errors)

Four subsystems keep `attrs` — and therefore `with_copy` — through this phase.
They account for the ~25 `with_copy` usages held back from §3.2 and are the
reason `attrs_extensions.py` is slimmed rather than deleted now:

| Consumer | attrs classes / `with_copy` | frozen or mutable | Disposition here |
|---|---|---|---|
| `hikari/impl/config.py` | 5 classes (`with_copy`) | **mutable** — config objects are reconfigured after construction (proxy / HTTP / cache settings), so they must **not** be frozen | keep attrs + `with_copy`; no change this phase |
| `hikari/internal/routes.py` | 3 route objects (`with_copy`) | effectively write-once but **not** wire Structs; no benefit to a Struct conversion | keep attrs + `with_copy`; no change this phase |
| `hikari/impl/special_endpoints.py` | ~15 `with_copy` builders | **mutable** (fluent `set_*`; D11 exemption) | keep attrs + `with_copy` — [`../08-builders/00-special-endpoints-builders.md`](../08-builders/00-special-endpoints-builders.md) |
| `hikari/errors.py` | 2 `with_copy` | exception types, not data records (CONVENTIONS §7 rule 7) | keep attrs + `with_copy` |

`impl/config.py` (5) and `internal/routes.py` (3) do **not** become msgspec
Structs in this migration. For each, `config.py`'s classes stay **mutable** attrs
(reconfigurable settings holders) and `routes.py`'s route objects stay attrs
(write-once templates, not modelled data). Their `@with_copy` decorator and the
`import ... attrs_extensions` line are **retained while `attrs_extensions.py`
survives** (slimmed, §3.2), and are removed only in the later phase that deletes
the module wholesale — once these consumers have themselves migrated off attrs.
This subsection is the reference the base-struct conventions point to for
config/routes (CONVENTIONS §8); there is no separate per-file plan for them.

## 4. Step-by-step migration

This file's slice is the *scaffolding removal*. It is sequenced to run **after**
models are frozen (foundations + model-modules phases) and **before/with** the
cache-internal redesign in the sibling files. Ordered tasks:

1. **Confirm the pre-condition holds at freeze time.** Re-run the greps from
   dossier 03 §7.3 (`object.__setattr__`, `__attrs_post_init__`, `on_setattr`,
   direct `entity.field = …` on a wire model) over the *current* tree; assert 0
   hits on wire models. Any new hit introduced since the dossier must be
   re-homed onto an internal carrier before proceeding. (Verification §7.)
2. **Freeze the wire Structs** — owned by the foundations/model-module phases;
   this file depends on it. Do not remove copies until the structs they copy are
   frozen, or you lose the isolation guarantee prematurely.
3. **Remove the ~221 `@attrs_extensions.with_copy` decorations on
   Struct-converted classes** (of the 246 tree-wide). Mechanical: delete the
   decorator line above each class as it migrates. Model-module classes (103) are
   removed as those modules migrate to Structs; `events/*` and
   `internal/cache.py` carriers lose the decorator when they are converted
   (events) or become plain mutable classes (`*Data`/`RefCell`/`GuildRecord`,
   sibling file 01). The **~25 deferred non-Struct usages are NOT removed in this
   pass** — the `special_endpoints` builders (~15), `impl/config.py` (5),
   `internal/routes.py` (3), and `errors.py` (2) keep `with_copy` (§3.4); they
   lose it only when they migrate off attrs, in the later phase that deletes
   `attrs_extensions.py` wholesale.
4. **Delete every `metadata={SKIP_DEEP_COPY: True}`** (151 fields; ~149 on the
   `app` field). These vanish with the `app` field removal (constraint (a),
   [`../03-app-removal-and-helpers/01-app-field-removal.md`](../03-app-removal-and-helpers/01-app-field-removal.md)) — the two are the same edit for most fields.
5. **Slim `hikari/internal/attrs_extensions.py`** (§3.2): delete the dead
   deep-copy half and the cache-only shallow-copy path, but keep `with_copy` and
   the shallow-copier machinery it needs for the ~25 deferred consumers (§3.4).
   Remove the `attrs_extensions` import from every **Struct-converted** module;
   leave it in `impl/config.py`, `internal/routes.py`, `special_endpoints.py`,
   and `errors.py`. Wholesale deletion of the module (and those four imports) is a
   later-phase PR, once every consumer is off attrs
   ([`../11-rollout/01-pr-breakdown.md`](../11-rollout/01-pr-breakdown.md), PR B2).
6. **Collapse the `impl/cache.py` copy sites** (19, table §2.4) to identity
   returns / direct assignment. `get_role`/`get_guild`/`get_thread`/`get_me`
   read paths return the stored struct; `set_*` write paths store the argument
   directly.
7. **Collapse the `internal/cache.py` view copies:** `CacheMappingView._copy`
   (`:125-127`) becomes identity; `Cache3DMappingView._copy` (`:1061-1069`) is
   already a no-op and stays. Remove `copy` import from the module if no other
   user remains (there will be residual uses in the `*Data` layer until sibling
   file 01 lands — sequence step 7 after file 01's carrier redesign, or leave
   the import until then).
8. **Repair the `set_role` asymmetry** (§4.6 below) — becomes uniformly correct;
   record that the previously latent aliasing bug is now closed.
9. **Rewrite the copy/identity test assertions** (dossier 07 §10.3): ~24 lines
   across `tests/hikari/impl/test_cache.py` (3180 LOC) and
   `tests/hikari/internal/test_cache.py` (76 LOC) assert `is not` / distinct
   copies. Convert to identity-is-acceptable / value-equality assertions. Owned
   by [`../10-testing/02-cache-copy-and-enum-tests.md`](../10-testing/02-cache-copy-and-enum-tests.md); flagged here as a required co-change.

### 4.6 The `set_role` asymmetry, resolved

Today `set_role` stores the caller's object **without copying**
(`impl/cache.py:1538` `self._role_entries[role.id] = role`), while every other
direct-entity setter copies, and `get_role` copies on read (`:1511`). This is a
latent aliasing bug: a caller mutating the `Role` it passed to `set_role` would
bleed into the cache (dossier 07 §0.6). Under frozen `Role`, storing the
argument by reference is *uniformly correct* — the caller cannot mutate it — so
the asymmetry is resolved by making every other setter match `set_role` (store
by reference), not by adding a copy to `set_role`. See
[`02-cache-app-and-views.md`](02-cache-app-and-views.md) §4 for the direct-store
strategy table this closes out.

## 5. Affected files and symbols

| File | Anchor(s) | Change |
|---|---|---|
| `hikari/internal/attrs_extensions.py` | deep-copy half + shallow `copy_attrs` path | **slim** — delete dead deep-copy + cache shallow path; **keep** `with_copy` + shallow-copier machinery for the ~25 deferred consumers (wholesale delete is a later phase) |
| `hikari/impl/cache.py` | `:1511, 1086, 506, 498, 688, 1570` | read copies → identity return |
| `hikari/impl/cache.py` | `:562, 730, 859, 1092, 1585, 1588, 1424, 1428` | write copies → direct assignment |
| `hikari/impl/cache.py` | `:586` | `update_guild` copy-before-patch → `msgspec.structs.replace` (file 01 §5) |
| `hikari/impl/cache.py` | `:1538` | `set_role` no-copy — now uniformly correct |
| `hikari/internal/cache.py` | `:125-127` | `CacheMappingView._copy` → identity |
| `hikari/internal/cache.py` | `:1061-1069` | `Cache3DMappingView._copy` no-op — unchanged |
| `hikari/internal/cache.py` | `:1048-1058`, `:712-726` | `copy_guild_channel`, `_copy_embed` — see file 01 §4 |
| model modules (26) | 103 `@with_copy` sites | remove decorator |
| `events/*`, `internal/cache.py` | remaining Struct-converted `@with_copy` sites (~221 total with models) | remove decorator |
| `impl/config.py` (5), `internal/routes.py` (3), `special_endpoints.py` (~15), `errors.py` (2) | ~25 deferred `@with_copy` sites | **keep** — retained until they migrate off attrs (§3.4) |
| all modules | 151 `SKIP_DEEP_COPY` metadata entries (~149 on the `app` field) | remove (with `app` field) |
| `tests/hikari/impl/test_cache.py` | ~24 assert lines (3180 LOC) | rewrite (file [`../10-testing/02-cache-copy-and-enum-tests.md`](../10-testing/02-cache-copy-and-enum-tests.md)) |
| `tests/hikari/internal/test_cache.py` | (76 LOC) | rewrite copy assertions |

Grep `attrs_extensions` for the exhaustive import list (the ~25 deferred-consumer
imports are **retained**, not removed); grep `with_copy` for the 246 decorator
sites (~221 removed here, ~25 kept); grep `SKIP_DEEP_COPY` for the 151 metadata
sites (~149 on the `app` field).

## 6. Risks and gotchas

1. **Freeze ordering.** Removing copies before a struct is actually frozen
   reintroduces the aliasing bug the copies guarded against. Gate step 6/7 on
   step 2 (the struct is frozen). Per-PR sequencing in
   [`../11-rollout/01-pr-breakdown.md`](../11-rollout/01-pr-breakdown.md).
2. **Shallow immutability of container fields.** A frozen Struct with a `list`
   field is only shallowly immutable; a shared mutable list would defeat the
   isolation the deleted copies provided. Rely on the factory producing tuples
   (already the norm; anchors `internal/cache.py:463-465, 523-525, 690-691`).
   Any surviving `list`/`dict` field on a *cached* model is a hazard — enumerate
   per model in [`../06-model-modules/`](../06-model-modules/).
3. **`copy` import residue.** `internal/cache.py` keeps `import copy` used by the
   `*Data` layer until sibling file 01 removes the layer; do not delete the
   import prematurely.
4. **Non-cache `copy.copy` consumers.** Verify no code outside the cache relies
   on `entity.__copy__`/`__deepcopy__` (grep found only cache consumers, dossier
   03 §1). If a user subclass or external plugin called `copy.copy(entity)`, it
   still works (default `copy.copy` on a frozen slotted Struct returns a shallow
   clone) — but the custom fast-path is gone; document as a minor internal
   behavior change in
   [`../11-rollout/03-breaking-changes-and-changelog.md`](../11-rollout/03-breaking-changes-and-changelog.md).
5. **Test blast radius under-counts.** The ~24 identity assertions are the
   *known* ones; a full test run after freezing will surface any construction
   sites that mutated a model post-build in a test fixture. Treat surprises as
   pre-condition violations (§2.5), not as reasons to keep copies.

## 7. Verification

1. **Pre-condition probe.** `rg -n "object.__setattr__|__attrs_post_init__|on_setattr"
   hikari/` returns 0 on wire-model files; `rg -n "\.app\b" ` cross-checked
   against the app-removal file. Re-assert dossier 03 §7.3's zero counts.
2. **Freeze enforcement test.** For a representative wire Struct, assert
   `msgspec`-frozen behavior: `with pytest.raises((AttributeError, TypeError)):
   entity.name = "x"`.
3. **Identity-return test.** After copy removal, `cache.get_role(id) is
   cache.get_role(id)` and `cache.set_role(r); cache.get_role(r.id) is r` hold
   (no copy). Mirror for guild/thread/me/user getters.
4. **Grep-clean (scoped).** `rg -n "SKIP_DEEP_COPY|copy_attrs|deep_copy_attrs"
   hikari/` returns 0 after the phase completes (deep-copy half gone, metadata
   removed). `rg -n "attrs_extensions|with_copy"` returns **only** the ~25
   deferred consumers — `impl/config.py`, `internal/routes.py`,
   `special_endpoints.py`, `errors.py` — and no Struct-converted module; that
   residue reaches 0 only after the later wholesale-deletion phase (PR B2).
5. **Full cache suite** (`tests/hikari/impl/test_cache.py`) passes after the
   identity-assertion rewrite (file [`../10-testing/02-cache-copy-and-enum-tests.md`](../10-testing/02-cache-copy-and-enum-tests.md)).

## 8. Open questions and decisions

Cross-linked to [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md) (decision D8).

- **OQ-1:** Do any cached model fields remain a bare `list`/`dict` after the
  model-module migration (risk §6)? Must be resolved to tuples/read-only
  mappings before their copies are removed. Owner: model-module authors.
- **OQ-2:** Keep `import copy` in `internal/cache.py` until sibling file 01
  removes the `*Data` layer, or delete both in one PR? Sequencing call for
  [`../11-rollout/01-pr-breakdown.md`](../11-rollout/01-pr-breakdown.md).
- Confirmed resolved here: the deep-copy subsystem is dead and deletes with no
  behavior change (dossier 07 §0.3); `set_role`'s asymmetry becomes correct
  under frozen (§4.6). `attrs_extensions.py` is **slimmed, not deleted**, this
  phase — `with_copy` survives for the ~25 deferred non-Struct consumers (§3.2,
  §3.4); wholesale deletion is a later-phase PR
  ([`../11-rollout/01-pr-breakdown.md`](../11-rollout/01-pr-breakdown.md), PR B2).
