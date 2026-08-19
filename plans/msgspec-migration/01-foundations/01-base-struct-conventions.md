# Base Struct Conventions

The canonical shape every wire model becomes: a frozen, kw-only, app-less `msgspec.Struct`
that keeps id-only identity via the existing `snowflakes.Unique` mixin. Locks decision D3 and
serves constraints (a) app-less, (b) strict, (c) frozen. The `frozen=True, eq=False` +
inherited-`Unique`-dunders design is **empirically confirmed** (msgspec 0.21.1, against the real
`snowflakes.Unique`; dossier 16, [`../12-appendices/03-base-struct-identity-verified.md`](../12-appendices/03-base-struct-identity-verified.md)),
subject to two mechanical requirements proven there and folded in below: a combined
`ABCMeta`+`StructMeta` metaclass on the shared base, and `kw_only=True` repeated per struct level.

## 1. Objective

- Define the one struct recipe all ~157 wire models (dossier 03 §4.1) follow, so per-module plans
  in [`../06-model-modules/`](../06-model-modules/00-README.md) can reference it instead of
  re-deriving it.
- Preserve **id-only** hash/equality (83 classes hash by `id` alone today) without msgspec's
  all-field `eq`/`hash` breaking on unhashable list/dict fields.
- The `eq=False` + inherited-`Unique`-dunders design is **empirically confirmed** in §4 (dossier 16);
  this file folds in the two mechanical requirements that confirmation uncovered (R1 combined
  metaclass, R2 per-level `kw_only`).

## 2. Current state (file:line)

Canonical wire model today — `channels.PartialChannel` (`hikari/channels.py:353-373`, dossier 03 §2.1):

```python
@attrs.define(unsafe_hash=True, kw_only=True, weakref_slot=False)
class PartialChannel(snowflakes.Unique):
    app: traits.RESTAware = attrs.field(repr=False, eq=False, hash=False, metadata={SKIP_DEEP_COPY: True})
    id:   snowflakes.Snowflake = attrs.field(hash=True, repr=True)
    name: str | None           = attrs.field(eq=False, hash=False, repr=True)
    type: ChannelType | int    = attrs.field(eq=False, hash=False, repr=True)
```

Identity model (dossier 03 §2.1, §7.1):

- `@attrs.define(unsafe_hash=True, kw_only=True, weakref_slot=False)` is the dominant signature —
  **83 classes** across the 26 model modules.
- Exactly one field (`id`) is `hash=True`; every other field is `eq=False, hash=False` (hence
  `eq=False` appears **556×** and `hash=False` **584×** as field kwargs). Net: **hash and equality
  by `id` alone.**
- `snowflakes.Unique` (`hikari/snowflakes.py:103-132`) is an ABC that already defines id-based
  `__hash__` (`hash(self.id)`) and `__eq__` (`isinstance(other, type(self)) and self.id == other.id`),
  plus `__int__`/`__index__` and a `created_at` property. `id` is an **abstract property**
  (`snowflakes.py:108-111`). attrs regenerates per-class `__eq__`/`__hash__` that override Unique's;
  Unique's is the fallback for classes that do not regenerate.
- `weakref_slot=False` on 175/175 model classes; `kw_only=True` on 173/175 (exceptions
  `components.ActionRowComponent` `hikari/components.py:277`, `guilds.WelcomeChannel`
  `hikari/guilds.py:1523`); `slots=True` implicit (attrs default). `frozen=True` on **0** — models
  are mutable today, but grep found **zero** `object.__setattr__`, `__attrs_post_init__`,
  `on_setattr`, or post-construction field assignment on models (dossier 03 §7.3): they are already
  write-once in practice.
- `repr=False` appears **453×** (hide noisy/secret fields); attrs has a per-field repr toggle.
- 4 leading-underscore alias fields (dossier 03 §6): `channels.py:1498` `_emoji` (`alias="emoji"`),
  `presences.py:128` `_application_id`, `embeds.py:233` `_inline`, `sessions.py:66` `_created_at`.

msgspec `Struct` config (dossier 13 §1, all defaults): `frozen=False, eq=True, kw_only=False,
weakref=False, dict=False` (always slotted), config **inherited** by subclasses that do not
re-declare it. There is **no per-field `eq`/`hash`/`repr`** control — `eq` is all-or-nothing per
struct.

## 3. Target design

Canonical target (decision D3), verified end-to-end in dossier 16:

```python
import abc, msgspec
from hikari import snowflakes

class _StructABCMeta(abc.ABCMeta, type(msgspec.Struct)):
    """Reconcile Unique's ABCMeta with msgspec's StructMeta (see rule 1 / §3.1)."""

# Shared base carrying the metaclass + config; subclasses inherit the metaclass automatically.
class UniqueStruct(snowflakes.Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False,
                   metaclass=_StructABCMeta):
    """Base for all id-identity wire models; id-only __eq__/__hash__ come from Unique."""

class PartialChannel(UniqueStruct, frozen=True, kw_only=True):   # metaclass inherited; kw_only REPEATED
    id: snowflakes.Snowflake
    name: str | None = None
    type: ChannelType = ...          # strict enum, no `| int` (constraint b, see ../02-enums/)
    # NO app field (constraint a).
```

Rules (each a locked D3 sub-decision):

1. **A combined metaclass is required, and `kw_only=True` is repeated per level.** `type(msgspec.Struct)`
   is `StructMeta`, which does **not** subclass `ABCMeta`, so a bare
   `class X(snowflakes.Unique, msgspec.Struct, …)` raises `TypeError: metaclass conflict` (dossier 16
   §R1, verified — this is the real cause of the error a first attempt hits). Define
   `class _StructABCMeta(abc.ABCMeta, type(msgspec.Struct)): ...` once and set it on the shared base
   (`UniqueStruct`); subclasses inherit it automatically and must **not** re-declare it. `frozen`
   inherits reliably (it is in `__struct_config__`), but **`kw_only` does not**: it is not stored in
   `StructConfig` and does not propagate through an empty base + intermediate field-declaring classes
   (dossier 16 §R2, verified — a subclass that adds a required field after an inherited optional one
   fails with `Required field '…' cannot follow optional fields` unless it re-declares `kw_only=True`).
   hikari's hierarchies are exactly this shape, so the convention is: **declare `frozen=True,
   kw_only=True` on every struct class that adds fields** (frozen repetition is belt-and-suspenders;
   kw_only repetition is mandatory). `kw_only` itself is required because hikari adds required fields
   in subclasses after optional base fields.

2. **Identity stays id-only via `eq=False` + inherited `Unique` dunders.** Declare wire Structs with
   `eq=False` so msgspec does **not** generate all-field `__eq__` (which would compare list/dict
   fields and change identity semantics, and whose companion all-field `__hash__` would raise on
   unhashable fields). Keep `snowflakes.Unique` as a base so the inherited id-based `__eq__`/`__hash__`
   apply. Empirically confirmed in §4 (dossier 16); the only residual is the CPython 3.10-floor re-run.

3. **Value objects that are not `Unique`** (embed pieces, poll value objects, activity assets,
   `IntegrationAccount`, …): decide per class. Immutable scalar records may accept msgspec's default
   all-field `eq` (fine, and cheap). Poll value objects are `hash=False` today
   (`@attrs.define(hash=False, ...)`, `hikari/polls.py`, 4 classes) — keep them non-hashable; with
   `frozen=True` msgspec would auto-generate `__hash__`, so set `eq=False` (or hand-write
   `__hash__ = None`) to preserve unhashability. Detail per module in
   [`../06-model-modules/16-polls.md`](../06-model-modules/16-polls.md).

4. **slots** are automatic (msgspec Structs have no `__dict__`; `dict=False` default) — matches attrs
   `slots=True`. Do **not** set `weakref=True` unless a weakref is actually taken (matches attrs
   `weakref_slot=False`).

5. **`repr`**: msgspec has no per-field repr toggle. Accept msgspec's default all-field repr except
   where a field is secret (tokens) — hand-write `__repr__` for those and call them out per module
   (e.g. OAuth token structs, `applications.py` token hierarchy). Do not use `repr_omit_defaults`
   (all-or-nothing, unrelated to the secret-field need).

6. **Leading-underscore aliases** (4 fields): since frozen makes everything read-only, collapse
   `_x`+property to a plain public field `x` where the property is a trivial pass-through
   (`embeds._inline`→`is_inline` and `presences._application_id` are candidates). Keep `_x` storage +
   `x` property only where the property does real computation (`channels.ForumTag._emoji` splits into
   `unicode_emoji`/`emoji_id`), accepting `_x=` as the constructor kwarg or adding a `@classmethod`
   constructor. **Never** rely on `msgspec.field(name=…)`/`rename` to rename the init kwarg — it
   renames only the wire key; the constructor keyword stays the Python attribute name (dossier 13
   §12, verified). Full treatment per module.

7. **Errors stay exceptions.** The 22 `errors.py` `auto_exc` classes are exception types, not data
   records — excluded from the Struct migration (dossier 03 §4.3).

8. **Not frozen wire Structs** (see the file that covers each): `files.*` readers (mutable,
   hold live handles); `impl/config.py` (5 classes, mutable) and `internal/routes.py` (3
   route objects), which stay on `attrs` and are covered in
   [`../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md`](../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md)
   §3.4; cache `RefCell`/`GuildRecord`/`*Data`
   ([`../04-frozen-and-cache/01-cache-data-layer-and-mutation.md`](../04-frozen-and-cache/01-cache-data-layer-and-mutation.md));
   and `special_endpoints` builders ([`../08-builders/00-special-endpoints-builders.md`](../08-builders/00-special-endpoints-builders.md)).

### 3.1 Abstract `id` property and `Unique`

`Unique.id` is an `@property @abc.abstractmethod` (`snowflakes.py:108-111`). A Struct field named
`id` places an `id` slot descriptor in the namespace, which overrides the abstract property and
clears it from `__abstractmethods__`, so instantiation works (verified in dossier 16 —
`isinstance(leaf, Unique)` True, construction and decode succeed at hierarchy depth 3). `StructMeta`
does **not** itself subclass `ABCMeta` (so the combined `_StructABCMeta` of rule 1 is what makes the
ABC + Struct composition legal); once the metaclass is combined, `@property`/`@abstractmethod`
interop works. The real `Unique` is kept **unchanged** — its `__slots__ = ()` and abstract `id`
property compose fine (a struct built on it is still slotted, `hasattr(inst, "__dict__")` False);
there is **no** need to remove `Unique.__slots__`. This is also the pattern behind the pyright
`reportIncompatibleVariableOverride` relaxation (`pyproject.toml:180`); the type-checker outcome is
tracked separately (see [`00-dependencies-and-tooling.md`](00-dependencies-and-tooling.md) §3.3).

## 4. The `eq=False` + `Unique` result (RESOLVED — empirically confirmed)

Question: does `msgspec.Struct, frozen=True, eq=False` on a class whose non-Struct base (`Unique`)
defines `__eq__`/`__hash__` yield (a) immutability, (b) id-only equality inherited from `Unique`,
(c) a working `__hash__` even when the struct holds unhashable fields, and (d) a struct `id` field
satisfying `Unique`'s abstract `id` property?

**Answer: YES on all four** — msgspec, with `eq=False`, generates neither `__eq__` nor an all-field
`__hash__`, so both resolve up the MRO to `Unique` (`__hash__` is **not** nulled). Verified on msgspec
0.21.1 against the real `hikari.snowflakes.Unique` across a depth-3 hierarchy (dossier 16 /
[`../12-appendices/03-base-struct-identity-verified.md`](../12-appendices/03-base-struct-identity-verified.md)).
Observed: `imm=True, eq_id_only=True, h_ok=True, which_eq(Unique)=True, which_hash(Unique)=True,
hash_is_none=False, isinstance_Unique=True, frozen=True, slotted=True`, kw_only enforced, and decode
(with the Snowflake `dec_hook`, incl. string→`Snowflake`) round-trips and compares equal via
`Unique.__eq__`.

The design is adopted as-is — **no per-class dunder re-attachment is needed** — subject to the two
mechanical requirements uncovered while confirming it (both now baked into rule 1 and §3.1):

- **R1 — combined metaclass.** `StructMeta` is not an `ABCMeta` subclass, so a bare
  `class X(Unique, msgspec.Struct, …)` raises `TypeError: metaclass conflict`. Use the shared
  `_StructABCMeta(abc.ABCMeta, type(msgspec.Struct))` on the base; it is inherited by subclasses.
  (An earlier external run mistakenly concluded `Unique.__slots__` must be removed; it must **not** —
  keeping the real `Unique` with `__slots__ = ()` works and stays slotted.)
- **R2 — repeat `kw_only=True` per level.** `kw_only` is not in `StructConfig` and does not reliably
  inherit through an empty base + intermediate field-declaring classes; declare it on every struct
  class that adds fields.

### 4.1 The corrected probe (as run)

```python
import abc, msgspec
from hikari.snowflakes import Snowflake, Unique

class _StructABCMeta(abc.ABCMeta, type(msgspec.Struct)): ...

class UniqueStruct(Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False,
                   metaclass=_StructABCMeta): ...

class PartialChannel(UniqueStruct, frozen=True, kw_only=True):
    id: Snowflake
    name: str | None = None

class GuildChannel(PartialChannel, frozen=True, kw_only=True):
    guild_id: Snowflake
    perms: list[int] = []                         # unhashable field, added deep in the tree

def dec_hook(t, o):
    return Snowflake(o) if t is Snowflake else (_ for _ in ()).throw(NotImplementedError(t))

a = GuildChannel(id=Snowflake(1), name="x", guild_id=Snowflake(9), perms=[1, 2])
b = GuildChannel(id=Snowflake(1), name="y", guild_id=Snowflake(0), perms=[3])   # same id
assert (a == b)                                    # id-only eq from Unique
assert hash(a) == hash(Snowflake(1)) and len({a, b}) == 1    # hashable despite unhashable perms
assert GuildChannel.__hash__ is Unique.__hash__ and GuildChannel.__eq__ is Unique.__eq__
try: a.name = "z"; assert False
except AttributeError: pass                        # frozen
obj = msgspec.json.Decoder(GuildChannel, dec_hook=dec_hook).decode(
    b'{"id":"1","name":"x","guild_id":"9","perms":[1,2]}')   # string snowflakes on the wire
assert obj == a and type(obj.id) is Snowflake
```

Run it on CPython 3.10 as well as 3.11+ to confirm the ABC/StructMeta interplay holds on the 3.10
floor (the confirming run above was 3.11; the mechanism is version-independent but the floor must be
checked before rollout — carried as the residual sub-item in
[`../12-appendices/01-open-questions-and-verifications.md`](../12-appendices/01-open-questions-and-verifications.md)).

## 5. Step-by-step migration

1. Re-run the §4 probe on CPython 3.10 (the confirming run was 3.11); the result is expected to hold
   (version-independent mechanism) but the 3.10 floor must be checked.
2. Add the combined metaclass `_StructABCMeta(abc.ABCMeta, type(msgspec.Struct))` and a shared wire
   base (e.g. `UniqueStruct` in `hikari/snowflakes.py` or an internal module) carrying
   `frozen=True, kw_only=True, eq=False, metaclass=_StructABCMeta`. Wire hierarchies subclass it
   instead of bare `Unique`, and **each subclass that adds fields repeats `frozen=True, kw_only=True`**
   (R2). No dunder re-attachment is needed (§4).
3. Per module (dependency order, [`../06-model-modules/00-README.md`](../06-model-modules/00-README.md)):
   convert `@attrs.define(unsafe_hash=True, kw_only=True, weakref_slot=False)` classes to the target
   recipe; drop per-field `eq=`/`hash=`/`repr=` kwargs; remove the `app` field (constraint a,
   [`../03-app-removal-and-helpers/01-app-field-removal.md`](../03-app-removal-and-helpers/01-app-field-removal.md)).
4. Handle the 2 non-kw_only classes (`ActionRowComponent`, `WelcomeChannel`) explicitly — force
   `kw_only=True` and fix their construction sites.
5. Collapse or keep each of the 4 `_x` alias fields per §3 rule 6.
6. Convert value-object classes per §3 rule 3; preserve poll unhashability.
7. Add hand-written `__repr__` to secret-bearing structs (rule 5).

## 6. Affected files and symbols

| Path | Anchor | Change |
|------|--------|--------|
| `hikari/snowflakes.py` | `:103-132` | keep `Unique` unchanged (incl. `__slots__ = ()`); host the shared `UniqueStruct` base + `_StructABCMeta` metaclass (R1); no dunder re-attachment (§4) |
| model modules (26) | 175 `@attrs.define` sites | convert to target recipe; drop per-field eq/hash/repr |
| `hikari/channels.py` | `:277`, `:1498` | non-kw_only `ActionRowComponent`; `_emoji` alias handling |
| `hikari/guilds.py` | `:1523` | non-kw_only `WelcomeChannel` |
| `hikari/polls.py` | 4 `hash=False` classes | preserve unhashability under frozen |
| `hikari/presences.py` `hikari/embeds.py` `hikari/sessions.py` | `:128`, `:233`, `:66` | alias-field collapse/keep |

## 7. Risks and gotchas

1. **`Unique.__eq__` is asymmetric across the hierarchy.** It uses `isinstance(other, type(self))`,
   so `partial == text` (a `GuildTextChannel`) can be `True` while `text == partial` is `False`
   (dossier 03 §2.1 notes attrs *regenerates* per-class exact-class eq, which is symmetric). Under
   `eq=False` we lose that regeneration and fall back to Unique's isinstance form. Behavior change.
   Recommendation: accept it (cross-type entity comparison is rare) OR make `Unique.__eq__` symmetric
   with `type(self) is type(other)`. Flag for the maintainer.
2. **All-field `eq` on value objects** compares nested lists/dicts and can be surprising (and slow)
   for large records. Choose `eq=False` per value class when identity/`is` semantics are wanted.
3. **`repr` leaks.** Default all-field repr now includes fields attrs hid with `repr=False` (453
   sites), notably tokens. Audit for secrets before accepting defaults (rule 5).
4. **Frozen assumption.** Freezing relies on models being write-once; the grep evidence (zero
   post-construction mutation) supports it, but any hidden mutation surfaces as `AttributeError:
   immutable type`. The cache mutation audit lives in
   [`../04-frozen-and-cache/01-cache-data-layer-and-mutation.md`](../04-frozen-and-cache/01-cache-data-layer-and-mutation.md).
5. **3.10 floor.** Re-run the probe on 3.10 specifically — struct-config and ABC interplay must hold
   on the lowest supported version (the confirming run was 3.11; the mechanism is version-independent
   but unverified on 3.10).
6. **Metaclass conflict + silent `kw_only` gap (dossier 16).** Forgetting the combined metaclass
   surfaces immediately (`TypeError: metaclass conflict`), but forgetting to repeat `kw_only=True` on
   a subclass is **silent** until that subclass adds a required field after an inherited optional one
   — then class creation fails with `Required field '…' cannot follow optional fields`. Enforce
   `frozen=True, kw_only=True` on every field-adding struct as a lint/review rule, not by trusting
   inheritance.

## 8. Verification

- The §4 probe (already passing on 3.11 incl. the decode-test) re-run and passing on the 3.10 floor.
- A migrated exemplar module (recommend `channels.py` `PartialChannel` subtree) round-trips:
  `Decoder(...).decode(payload)` equals a hand-built instance; `hash`/set-membership behave id-only.
- `nox -s slotscheck` confirms slots survive; `nox -s mypy`/`pyright` confirm the field-satisfies-
  abstract-property pattern (ties to pyright `:180`, see 00-dependencies §3.3).
- Existing identity tests (see [`../10-testing/02-cache-copy-and-enum-tests.md`](../10-testing/02-cache-copy-and-enum-tests.md))
  still assert `a == b` iff same id.

## 9. Open questions / decisions

Cross-link [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md):

- Q-STRUCT-1 (RESOLVED): §4 confirmed the favorable outcome (`eq=False` inherits `Unique`'s dunders,
  no re-attachment needed), plus R1 (combined metaclass) and R2 (per-level `kw_only`). Only the 3.10
  re-run remains as a residual check.
- Q-STRUCT-2: keep `Unique.__eq__` asymmetric, or make it symmetric (`type(self) is type(other)`)?
- Q-STRUCT-3: per value-object `eq` policy (all-field vs `eq=False`) — settle globally or per module?
- Q-STRUCT-4: for the 4 `_x` fields, collapse-to-public vs keep-storage-plus-property (rule 6).
