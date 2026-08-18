# Base Struct Conventions

The canonical shape every wire model becomes: a frozen, kw-only, app-less `msgspec.Struct`
that keeps id-only identity via the existing `snowflakes.Unique` mixin. Locks decision D3 and
serves constraints (a) app-less, (b) strict, (c) frozen. Includes the empirical experiment
that must confirm `frozen=True, eq=False` inherits `Unique`'s `__eq__`/`__hash__`.

## 1. Objective

- Define the one struct recipe all ~157 wire models (dossier 03 §4.1) follow, so per-module plans
  in [`../06-model-modules/`](../06-model-modules/00-README.md) can reference it instead of
  re-deriving it.
- Preserve **id-only** hash/equality (83 classes hash by `id` alone today) without msgspec's
  all-field `eq`/`hash` breaking on unhashable list/dict fields.
- Prove the `eq=False` + inherited-`Unique`-dunders design empirically before any module adopts it.

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

Canonical target (decision D3):

```python
class PartialChannel(snowflakes.Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    id: snowflakes.Snowflake
    name: str | None = None
    type: ChannelType = ...          # strict enum, no `| int` (constraint b, see ../02-enums/)
    # NO app field (constraint a).
```

Rules (each a locked D3 sub-decision):

1. **`frozen=True, kw_only=True` on hierarchy base classes.** msgspec inherits struct config to
   subclasses (dossier 13 §1, verified), so these go on the small set of base classes
   (`PartialChannel`, `PartialUser`, `PartialGuild`, …) and the deep hierarchies inherit them.
   `kw_only` is mandatory: hikari adds required fields in subclasses after optional base fields, and
   msgspec bans required-after-optional unless `kw_only=True` (dossier 13 §4, verified `TypeError:
   Required field 'b' cannot follow optional fields`).

2. **Identity stays id-only via `eq=False` + inherited `Unique` dunders.** Declare wire Structs with
   `eq=False` so msgspec does **not** generate all-field `__eq__` (which would compare list/dict
   fields and change identity semantics, and whose companion all-field `__hash__` would raise on
   unhashable fields). Keep `snowflakes.Unique` as a base so the inherited id-based `__eq__`/`__hash__`
   apply. **This is gated on the experiment in §4 — do not roll out until it passes.**

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
clears it from `__abstractmethods__`, so instantiation works. msgspec's `StructMeta` cooperates with
`ABCMeta` (dossier 13 §1, verified for `@property`/`@abstractmethod`). This is also the pattern
behind the pyright `reportIncompatibleVariableOverride` relaxation
(`pyproject.toml:180`) — the experiment in §4 must confirm both instantiation and the type-checker
outcome (see [`00-dependencies-and-tooling.md`](00-dependencies-and-tooling.md) §3.3).

## 4. The `eq=False` + `Unique` experiment (must pass before rollout)

Question: does `msgspec.Struct, frozen=True, eq=False` on a class whose non-Struct base
(`Unique`) defines `__eq__`/`__hash__` yield (a) immutability, (b) id-only equality inherited from
`Unique`, (c) a working `__hash__` even when the struct holds unhashable fields, and (d) a struct
`id` field satisfying `Unique`'s abstract `id` property? msgspec's auto-`__hash__` is tied to
`frozen=True`; the unknown is whether `eq=False` suppresses it (leaving `Unique.__hash__`) or msgspec
sets `__hash__ = None`.

### 4.1 Probe

```python
# probe_eq_hash.py  — run under the pinned msgspec (target 0.21.1), CPython 3.10 AND 3.11+
import abc, msgspec

class Unique(abc.ABC):
    __slots__ = ()
    @property
    @abc.abstractmethod
    def id(self) -> int: ...
    def __hash__(self) -> int:
        return hash(self.id)
    def __eq__(self, other: object) -> bool:
        return isinstance(other, type(self)) and self.id == other.id

class PartialChannel(Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    id: int
    name: str | None = None
    perms: list[int] = []          # unhashable field on purpose

a = PartialChannel(id=1, name="x", perms=[1, 2])
b = PartialChannel(id=1, name="y", perms=[3])   # same id, different other fields
c = PartialChannel(id=2, name="x", perms=[1, 2])

# (a) immutability
try:
    a.name = "z"; imm = False
except AttributeError:
    imm = True

# (b) id-only equality inherited from Unique
eq_id_only = (a == b) and (a != c)

# (c) hashable despite the unhashable `perms` field, and hash == hash(id)
try:
    h_ok = (hash(a) == hash(1)) and (len({a, b, c}) == 2)   # a,b collapse; c distinct
except TypeError:
    h_ok = False

# (d) which dunders are actually in play
which_eq  = PartialChannel.__eq__ is Unique.__eq__
which_hash = PartialChannel.__hash__ is Unique.__hash__
hash_is_none = PartialChannel.__hash__ is None

# (e) abstract `id` satisfied (construction above already proves it; assert type)
abstract_ok = isinstance(a, Unique)

print(dict(imm=imm, eq_id_only=eq_id_only, h_ok=h_ok,
           which_eq=which_eq, which_hash=which_hash,
           hash_is_none=hash_is_none, abstract_ok=abstract_ok,
           config=PartialChannel.__struct_config__.frozen))
```

Also decode-test it, to prove `eq=False` does not break typed decode:

```python
dec = msgspec.json.Decoder(PartialChannel)
obj = dec.decode(b'{"id":1,"name":"x","perms":[1,2]}')
assert obj == PartialChannel(id=1, name="x", perms=[1, 2])   # relies on Unique.__eq__
```

### 4.2 Branch A — favorable (expected): `eq=False` leaves `Unique`'s dunders in place

Predicted result: `imm=True, eq_id_only=True, h_ok=True, which_eq=True, which_hash=True,
hash_is_none=False, abstract_ok=True`. msgspec, with `eq=False`, generates neither `__eq__` nor an
all-field `__hash__`, so both resolve up the MRO to `Unique`. **Action:** adopt the canonical recipe
as-is; wire Structs subclass `Unique` (directly or via an intermediate base) and declare
`frozen=True, kw_only=True, eq=False`. No per-class dunder code needed.

### 4.3 Branch B — fallback: msgspec sets `__hash__ = None` (or shadows `__eq__`) under `eq=False`

If `hash_is_none=True` or `which_hash=False`/`which_eq=False`, msgspec has clobbered the inherited
dunders. Then explicitly re-attach `Unique`'s dunders on the hierarchy base(s). Two equivalent
options — pick the one that survives msgspec's metaclass:

```python
# Option B1: assign on each wire base class after definition
class PartialChannel(Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    id: snowflakes.Snowflake
    ...
PartialChannel.__eq__  = Unique.__eq__      # type: ignore[assignment]
PartialChannel.__hash__ = Unique.__hash__   # type: ignore[assignment]

# Option B2: a shared mixin that re-declares the dunders, placed left of Struct in the MRO
class _UniqueStructBase(snowflakes.Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    __eq__  = snowflakes.Unique.__eq__
    __hash__ = snowflakes.Unique.__hash__
```

Re-run the probe against the chosen option; require `imm`, `eq_id_only`, `h_ok`, and `abstract_ok`
all `True`. Prefer B2 (one base, config + dunders inherited) if msgspec permits assigning
`__eq__`/`__hash__` in a Struct body; fall back to B1 (post-hoc assignment on each base) otherwise.

Document the observed branch and the CPython versions tested in
[`../12-appendices/01-open-questions-and-verifications.md`](../12-appendices/01-open-questions-and-verifications.md).

## 5. Step-by-step migration

1. Run the §4 probe on CPython 3.10 and 3.11+ against the pinned msgspec; record Branch A or B.
2. Introduce a shared wire base (recommended even under Branch A) — e.g. `_UniqueStructBase` in
   `hikari/snowflakes.py` or an internal module — carrying `frozen=True, kw_only=True, eq=False` (and
   the dunder re-attachment if Branch B). Wire hierarchies subclass it instead of bare `Unique`.
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
| `hikari/snowflakes.py` | `:103-132` | keep `Unique`; possibly host `_UniqueStructBase`; Branch B dunder re-attach |
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
   on the lowest supported version.

## 8. Verification

- The §4 probe passing on 3.10 and 3.11+ (Branch A or a fixed Branch B), including the decode-test.
- A migrated exemplar module (recommend `channels.py` `PartialChannel` subtree) round-trips:
  `Decoder(...).decode(payload)` equals a hand-built instance; `hash`/set-membership behave id-only.
- `nox -s slotscheck` confirms slots survive; `nox -s mypy`/`pyright` confirm the field-satisfies-
  abstract-property pattern (ties to pyright `:180`, see 00-dependencies §3.3).
- Existing identity tests (see [`../10-testing/02-cache-copy-and-enum-tests.md`](../10-testing/02-cache-copy-and-enum-tests.md))
  still assert `a == b` iff same id.

## 9. Open questions / decisions

Cross-link [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md):

- Q-STRUCT-1 (VERIFY): §4 probe outcome — Branch A vs B — and the chosen Branch-B option.
- Q-STRUCT-2: keep `Unique.__eq__` asymmetric, or make it symmetric (`type(self) is type(other)`)?
- Q-STRUCT-3: per value-object `eq` policy (all-field vs `eq=False`) — settle globally or per module?
- Q-STRUCT-4: for the 4 `_x` fields, collapse-to-public vs keep-storage-plus-property (rule 6).
