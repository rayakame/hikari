# Glossary

Definitions of the terms of art used throughout this planning set. Where a term names a concrete code
object, an anchor is given. Cross-references point to the plan file that owns the concept.

## Architecture terms

**Wire model / wire struct.** A `msgspec.Struct` whose fields mirror Discord's JSON payload 1:1
(native types, tagged unions, `UNSET` for optionals), decoded fast from bytes at Layer 1. Distinct
from the **public struct** the user sees. In a fully declarative model the two coincide. See
[02-target-architecture.md](02-target-architecture.md) §2.

**Public struct.** The frozen, app-less `msgspec.Struct` a bot author receives — the successor to
today's `attrs` model. Same public attribute names and id-only identity as today, minus `app` and its
helpers.

**Declarative decode.** `msgspec.json.decode(bytes, type=X)` with no custom traversal code — the fast
path. A model is "declarative-decodable" when its shape needs only tagged unions, `field(name=…)`
renames, native types, and the global `dec_hook`. See [01-goals-and-non-goals.md](01-goals-and-non-goals.md).

**Transform-residual (residual factory).** The slimmed `entity_factory` that remains after
declarative decode absorbs the easy cases. It transforms wire structs (or `msgspec.Raw`) into public
structs for the ~13 hard-case categories (re-keying, flattening, sibling-typing, context injection,
computed fields, classmethod construction, lazy guild). It **never injects `app`**. See
[../05-entity-factory/02-hard-cases-and-transforms.md](../05-entity-factory/02-hard-cases-and-transforms.md).

**App-less.** Having no `app: traits.RESTAware` field. Constraint (a): decoded entities cannot carry a
runtime client, so the field and all `self.app.*` helper methods are removed. Callers use `rest.*` /
`cache.*` directly. See [../03-app-removal-and-helpers/00-strategy.md](../03-app-removal-and-helpers/00-strategy.md).

**Two-layer design.** The realistic migration shape: Layer 1 fast wire-struct decode, Layer 2
residual transform to public structs. A single-layer `decode(bytes, type=PublicStruct)` is not
achievable for the hard cases (dossier 05 §9).

## msgspec terms

**`msgspec.Struct`.** msgspec's typed, slotted, C-backed record class — the `attrs.define`
replacement. Always slotted (no `__dict__` unless `dict=True`); config (`frozen`, `kw_only`,
`tag_field`, …) is inherited by subclasses (dossier 13 §1).

**`frozen=True`.** Struct config making instances immutable (`obj.x = …` raises `AttributeError:
immutable type`) and auto-generating `__hash__`. The `attrs` `unsafe_hash=True` + immutability
replacement; constraint (c). All fields must be hashable when the struct itself is hashed.

**`eq=False` (struct-level).** Suppresses msgspec's generated all-field `__eq__`/`__hash__`. Used so
wire structs inherit id-only identity from the `snowflakes.Unique` base instead of comparing every
field. msgspec has **no per-field** eq/hash control, unlike attrs (dossier 13 §19). See D3.

**`kw_only=True`.** Makes all fields keyword-only, lifting msgspec's ban on a required field following
an optional one on the same class — mandatory for hikari's deep hierarchies (dossier 13 §4).

**`dec_hook` / `enc_hook`.** The custom-type escape hatches. `dec_hook(type, obj)` fires during typed
decode when the schema annotation is a **custom (non-native) type** — `type` is the annotation, `obj`
is the raw JSON scalar; it returns an instance of `type`. `enc_hook(obj)` fires when the encoder meets
an object it cannot serialize natively; it must return a natively-encodable value. One hook per
`Decoder`/`Encoder`, so each dispatches on the type (dossier 13 §8). Used for `Snowflake`, `Color`,
`Permissions`, `UnicodeEmoji`, **and hikari's custom `Enum`/`Flag`** — msgspec treats the latter as
custom types because they are not `enum.Enum` subclasses, so `dec_hook` returns `t(obj)` and `enc_hook`
returns `o.value` (D2; dossier 15). See [../01-foundations/02-custom-scalar-types-and-hooks.md](../01-foundations/02-custom-scalar-types-and-hooks.md).

**Tagged union.** msgspec's polymorphic-decode mechanism: a base class declares `tag_field="type"`,
each concrete subclass declares `tag=<value>`, and decoding a `Union[...]` routes by the
discriminator. Nested-in-list works. Raises `ValidationError` on an unknown tag (dossier 13 §14).
Replaces the 19 hand-rolled dispatch tables where the discriminator is a literal on each struct. See
[../05-entity-factory/01-polymorphism-and-tagged-unions.md](../05-entity-factory/01-polymorphism-and-tagged-unions.md).

**`msgspec.Raw`.** A `bytes` subclass holding an undecoded JSON sub-document. Lets decode be deferred
and re-run later — the escape hatch for **peek-then-dispatch** polymorphism where the soft-skip
semantics or forward-compat require inspecting the tag before choosing a struct (dossier 13 §11, §14).

**`msgspec.structs.replace(struct, **changes)`.** Returns a new struct with the given fields changed —
frozen-safe. Replaces the cache's copy-and-mutate flows (e.g. message edits) since frozen structs
cannot be mutated in place (dossier 13 §6).

**`msgspec.convert` / `to_builtins`.** `convert(obj, T, from_attributes=…)` builds a struct from a
dict or arbitrary object; `to_builtins(obj, str_keys=…)` lowers structs/enums to plain builtins.
`convert` is the incremental bridge for a dict-in decode boundary before bytes-in lands
(dossier 13 §7). See [../01-foundations/05-decode-boundary-and-decoders.md](../01-foundations/05-decode-boundary-and-decoders.md).

**`forbid_unknown_fields`.** Struct config; default `False`, meaning unknown JSON keys are **ignored**
on decode — matches today's `payload.get()` tolerance and Discord's habit of adding fields. Kept at
the default (dossier 13 §1).

**`msgspec.UNSET` / `UnsetType` / `NODEFAULT`.** `UNSET` is msgspec's fixed `enum` singleton for
"field absent." A field typed `T | UnsetType = UNSET` is **omitted on encode even when
`omit_defaults=False`** and decodes to `UNSET` when the key is absent (vs `None` for explicit
`null`) — modelling JavaScript-style `undefined` vs `null`. `bool(UNSET) is False`. `NODEFAULT` is the
internal "no default set" marker (dossier 13 §3). Contrast **UNDEFINED** below.

## hikari terms

**UNDEFINED / `UndefinedType` / `UndefinedOr[T]`.** hikari's bespoke tri-state sentinel
(`hikari/undefined.py`), used in ~1714 annotations across 33 modules, meaning "value / null / absent"
(CONVENTIONS §5). Two roles: (i) REST **request** params meaning "don't send" (the majority —
orthogonal to msgspec, kept), and (ii) decoded **entity** fields meaning "this partial payload omitted
the key," distinct from `None`. `bool(UNDEFINED) is False`, like `UNSET`. The preferred plan (D5)
keeps `hikari.UNDEFINED` and sets it as the field default; msgspec's `UNSET` is the fallback.
**`UNSET` (msgspec) ≠ `UNDEFINED` (hikari)** — `UNSET` is a fixed enum singleton, `UndefinedType` has
bespoke `__copy__`/`__reduce__`/`__new__`-guard machinery (dossier 13 §19). See
[../01-foundations/03-undefined-and-unset.md](../01-foundations/03-undefined-and-unset.md).

**`snowflakes.Unique`.** The ABC (`snowflakes.py:103-132`) that defines id-based `__eq__`/`__hash__`.
Kept as the identity base of every wire struct so `eq=False` structs inherit id-only identity. See D3.

**`Snowflake(int)`.** hikari's Discord-ID type (`snowflakes.py:51`), an `int` subclass. On the wire it
is a JSON **string** of digits. Needs a `dec_hook` (`Snowflake(obj)`, handles str and int) and, for
encode, `enc_hook`/pre-lowering because msgspec cannot encode int subclasses (dossier 13 §8, §11).

**Pseudo-member.** A value-preserving enum member minted at runtime by hikari's custom
`Enum.__call__` / `Flag.__call__` for an unknown Discord value (via `cls.__new__(cls, value)` + set
`_name_ = None` / `_value_ = value`, cached in the bounded `_temp_members_` map, `enums.py:39`). It is
a real instance (`isinstance`/`==`/`int()`/`str()` all work, and `is_unknown` reports `True`) and is
what preserves forward-compat under strict enum fields (D2). The custom `Flag` always did this
(`enums.py:381`); PR hikari-py/hikari#2770 extends it to scalar `Enum`. Distinct from hikari's
pre-#2770 behavior, where an unknown scalar value was returned as a bare `int`/`str`
(dossier 15 §2).

**`is_unknown`.** The property PR hikari-py/hikari#2770 adds to both custom `Enum` and `Flag` members,
reporting whether the member holds a value not documented as part of the enum
(`Enum.is_unknown = self._value_ not in self._value_to_member_map_`;
`Flag.is_unknown = bool(self._value_ & ~self.__class__.__everything__._value_)`). True exactly for the
pseudo-members minted on unknown Discord values; the marker a caller uses to detect a forward-compat
value (dossier 15 §2).

**Custom `Flag` (kept).** hikari's bespoke `Flag` (`enums.py:516`), a non-`enum.Flag` metaclass type
exposing ~20 set-like methods (`.all/.any/.none/.split/.difference/.intersection/.union/.is_subset/…`,
`enums.py:683-829`) and already minting a value-preserving pseudo-member on unknown bits
(`enums.py:381`). It is **kept**, not ported to stdlib `enum.IntFlag`: the custom implementation is
faster at runtime, and #2770 only adds `is_unknown` plus the strict field typing. Decoded via the
global `dec_hook`. See [../02-enums/01-flags-migration.md](../02-enums/01-flags-migration.md).

**`RefCell`.** The mutable reference-counting wrapper (`internal/cache.py:1007-1029`) holding a shared
cache payload plus a `ref_count` and a reassignable `object` slot. It is the heart of the cache GC
scheme and **stays mutable** even when its payload becomes a frozen struct (dossier 07 §4.3, §10.2).
Its dead twin `Cell` (`internal/cache.py:989`) is deleted.

**`GuildRecord`.** The per-guild mutable index container (`internal/cache.py:187-290`) holding the
guild plus membership indexes. Not an entity; **stays mutable** (dossier 07 §4.5).

**`*Data` layer.** The app-less storage models (`MemberData`, `MessageData`, `RichActivityData`, …)
the cache decomposes entities into on set and rebuilds on get. Under frozen + no-app its jobs shrink
to holding `RefCell` cross-references, in-place edit (`MessageData.update`), and the
`has_been_deleted` meta-flag — a maintainer decision (D8) whether to keep it mutable or store frozen
structs directly. See [../04-frozen-and-cache/01-cache-data-layer-and-mutation.md](../04-frozen-and-cache/01-cache-data-layer-and-mutation.md).

**`with_copy` / `SKIP_DEEP_COPY`.** The `attrs_extensions` decorator (applied 246×) installing
codegen'd `__copy__`/`__deepcopy__`, and the field-metadata key (149× markers, almost all on `app`)
telling the deep copier to skip a field. Both are deleted under constraint (c) (dossier 07 §2).

**`UnrecognisedEntityError`.** The `HikariError` (`errors.py:127`) raised when a polymorphic dispatch
hits an unknown type. In hard-fail dispatch (channels, threads, interactions, auto-mod, scheduled
events) it is raised and callers may swallow it; in soft-skip dispatch (components, some audit
entries) the offending element is dropped with a debug log. Both semantics must be preserved
(dossier 02 §D.2). See [../05-entity-factory/01-polymorphism-and-tagged-unions.md](../05-entity-factory/01-polymorphism-and-tagged-unions.md).

**Context injection / context kwargs.** The 36 `deserialize_*` methods whose params default to
`UNDEFINED` and accept caller-supplied `guild_id`/`user_id`/`member`/`user`/`thread_id` that are
**not** in the child JSON (Discord omits `guild_id` on nested objects; hikari threads it down from the
parent). msgspec has no per-node context mechanism, so these stay in the residual factory
(dossier 05 §6.11).

**`GatewayGuildDefinition`.** The public ABC (`api/entity_factory.py:63`) and its lazy implementer
`_GatewayGuildDefinition` (`entity_factory.py:140`) that defer deserializing a large `GUILD_CREATE`
payload until each accessor (`channels()`, `members()`, …) is called. Antithetical to msgspec's
decode-everything-now model; preserved as a bespoke residual object (dossier 05 §4).

## Process terms

**FLAGGED.** A decision the maintainer must choose between two presented options; the plan recommends
but does not silently pick. Currently only D10 (events/interactions app). See
[05-decisions-log.md](05-decisions-log.md) §4.

**VERIFY.** An empirical probe that gates a locked default. If the probe fails, the plan specifies a
named fallback. Consolidated in
[../12-appendices/01-open-questions-and-verifications.md](../12-appendices/01-open-questions-and-verifications.md).
