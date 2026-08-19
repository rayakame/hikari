# Breaking Changes and Changelog

Purpose: the full catalog of user-visible breaking changes the migration introduces, each with a
severity, whether a deprecation window is feasible, and the towncrier `changes/` fragment that must
land with it. This is the compatibility contract for the `3.0.0` release and the source material for
the first-ever hikari migration guide.

Release vehicle: current `2.5.1.dev0` (`hikari/_about.py:41`) → **`3.0.0` major bump**. Per EffVer /
`CONTRIBUTING.md:13-27`, "Big changes to the public facing API" is a major bump — the only channel
through which hard breaks are permitted without a full deprecation window (dossier 12 §2).

Severity legend (dossier 12 §5):
- **S1** — silently changes runtime behavior or breaks common user code with no type-checker signal.
- **S2** — breaks user code but surfaces loudly as an import/attribute/type error.
- **S3** — niche / advanced-usage break.

---

## 1. Objective

1. Enumerate every user-visible break so nothing lands unannounced.
2. Rank each by severity and blast radius.
3. State per change whether it can be softened by a deprecation window or must be a hard break.
4. Specify the exact `changes/` fragments (`{PR}.{type}.md`) to add.

---

## 2. Current state (change-management machinery)

- **Public surface:** 631 symbols across 82 module `__all__`s, assembled into the flat `hikari`
  namespace by star-imports + explicit re-exports (`hikari/__init__.py:30-148`); no top-level
  `__all__`. A generated `hikari/__init__.pyi` mirrors it (dossier 12 §1).
- **Deprecation tooling:** `hikari/internal/deprecation.py` — `warn_deprecated(...)`,
  `check_if_past_removal(...)` (raises once the removal version ships), and a no-op `deprecated`
  decorator (dossier 12 §3). **Currently zero live deprecations** in shipping modules (dossier 12
  §3.3) — the migration starts from a clean slate.
- **Changelog:** towncrier `25.8.0` (`pyproject.toml:214-230`); fragments in `changes/` named
  `{PR}.{type}.md`; types `breaking` / `deprecation` / `feature` / `optimization` / `bugfix` /
  `documentation`. The dir currently holds development fragments including exactly one `breaking`
  (`changes/2768.breaking.md`) and zero `deprecation` (dossier 12 §4.3). Preview with
  `towncrier --draft`.
- **No migration guide exists** (`docs/` has only the rendered changelog + index + logo, dossier 12 §8).

---

## 3. Breaking-change catalog

### 3.1 Helper-method + `app` attribute removal (constraint (a)) — S1/S2, highest blast radius

The `app: traits.RESTAware` field is removed from all JSON-decoded entities (24–25 base-class
declarations inherited by 64 concrete entities, dossier 05 §7), and the app-delegating helper methods
that dereference `self.app` are removed. The count is option-dependent: **163** `self.app.*` sites
across 20 modules (126 `rest.*` + 37 `cache.*` sites, dossier 04 §0) is the floor, and the **true
total is 173** once the 10 `self.user.app.*` sites on `guilds.Member` are counted. Under the
recommended D10 Option 2 only the ~114 **wire-entity** helpers are removed — the ~59 **event AND
interaction** helpers are retained (§3.9); Option 1 removes all ~173.

Representative removed public methods (dossier 04 §3, §5):
- `messages.py`: `Message.respond/edit/delete/add_reaction/remove_reaction/remove_all_reactions/fetch_channel`.
- `channels.py`: `send/fetch_message/fetch_history/pin_message/delete_messages/edit/edit_overwrite/…`.
- `guilds.py`: 37 `PartialGuild`/`Guild` helpers (`ban/kick/edit/fetch_roles/create_*_channel/get_member/…`).
- `users.py`: `fetch_dm_channel/send/fetch_self`.
- `webhooks.py`: `execute/fetch_message/edit_message/delete_message/edit/delete/fetch_self`.
- events / interactions: response and fetch sugar is retained under the recommended D10 Option 2 —
  both event AND interaction helpers keep `app`+helpers (see §3.9).

Replacement: callers use `rest.<method>(entity.<id>, …)` / `cache.get_*(…)` directly; the no-1:1
cluster gets new rest methods / free functions ([`../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md`](../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md)).

- **Severity:** `.respond/.send/.edit` are **S1** (ubiquitous in tutorials/examples); the `app`
  attribute removal is **S2** (loud `AttributeError`).
- **Blast radius:** hikari's own examples break — `event.message.respond(...)` appears throughout
  `examples/` (dossier 12 §5.1); every quick-start must be rewritten to `rest.create_message(...)`.
- **Deprecation window:** partial. A pre-`3.0` `2.6` could decorate the still-attrs helpers with
  `warn_deprecated(..., removal_version="3.0.0", additional_info="Use rest.* directly")`, but `app`
  itself cannot keep working once decode stops injecting it. Realistically a **hard remove at `3.0.0`**
  with a thorough migration guide; the optional `2.6` warning pass is the one break that maps cleanly
  onto the existing tooling (dossier 12 §6). See §5.

### 3.2 Strict enums (delivered by PR hikari-py/hikari#2770, constraint (b)) — S1, behavioral change

hikari **keeps** its fast custom `Enum`/`Flag` (not a stdlib port). The strict-enum break is delivered
by upstream PR hikari-py/hikari#2770, which the migration adopts/rebases onto; its
`changes/2770.breaking.md` states the contract:
> Casting an unknown value to an enum or flag type now returns an unknown member which keeps hold of
> the raw value instead of returning the value unchanged, and casting a value of the wrong type now
> raises `TypeError`; model fields and REST parameters are now typed with only the enum/flag type
> instead of a union with its raw type.

Today `EnumType(unknown_int)` returns the raw `int` unchanged (`enums.py:154-156`) and
`Flag(unknown_bits)` already fabricates a pseudo-member (`enums.py:381-412`); 142 `Enum | int` typings
(and further `| str`, dossier 12 §5.2 / dossier 05 §3d) encode this leniency.

After #2770:
- Fields (and REST params) are typed as the **bare strict enum/flag** (the `| int`/`| str` tolerance
  unions are dropped) — exactly the strict-enum field inventory
  ([`../02-enums/03-strict-enum-field-inventory.md`](../02-enums/03-strict-enum-field-inventory.md)).
- Forward-compat is preserved by the custom enum itself, **not** by union widening: `Enum.__call__` now
  mints a value-preserving `is_unknown` pseudo-member **instance** for unknown int/str values (the
  custom `Flag` already did, and keeps its unknown bits). Because the shared `dec_hook` returns that
  instance, msgspec accepts unknown Discord values. #2770 adds an `is_unknown` property to both
  (`changes/2770.feature.md`).
- **Semantic change (must be documented):** an unknown int-enum value is today a bare `int`; after
  #2770 it is an enum pseudo-member — `x == the_int` and `int(x)` still work, but `type(x) is int`
  is now **False** and `isinstance(x, TheEnum)` is now **True**. User code doing `if msg.type == 999`
  keeps working; user code doing `type(msg.type) is int` breaks (dossier 12 §5.2, CONVENTIONS §3).
- **New behavior:** casting a value of the **wrong type** (e.g. a `str` to an int-enum) now raises
  `TypeError` (the `__objtype__` guard) instead of passing it through.
- The rich custom `Flag` API (`.all/.any/.none/.split/.difference/…`, ~20 methods) is **kept unchanged**
  — the enums stay custom, so it is **not** a break.

- **Severity:** **S1** (the unknown-value type change is silent; the union-typing change is also a
  typing-level break for downstream typed code; the wrong-type `TypeError` is loud).
- **Deprecation window:** none — the break rides on #2770; the forward-compat mitigation is the custom
  enum's pseudo-member *design*, not a warning window (dossier 12 §6).

### 3.3 Frozen (immutable) models (constraint (c)) — S2

No model is frozen today (all `@attrs.define` mutable-with-slots, dossier 12 §5.4). After migration
decoded entities are frozen `msgspec.Struct`s, so `model.attr = x` raises. **Builders stay mutable**
(`Embed` and the 42 `special_endpoints` builders — critical caveat, dossier 12 §5.4, D11); `errors.py`
stays exceptions (dossier 12 §5.6). Only decoded entities freeze.

- **Severity:** **S2** (loud `AttributeError`/`FrozenInstanceError` on in-place mutation).
- **Related identity change:** cache reads now return shared frozen instances by reference (no copy),
  so `cache.get_x(id) is cache.get_x(id)` is now True and mutating a cached object is impossible
  (previously each read was a fresh mutable copy). This is a behavior change consumers may rely on.
- **Deprecation window:** none — behavioral.

### 3.4 attrs copy / evolve / asdict / isinstance contract removed — S2/S3

Deleting attrs and `internal/attrs_extensions.py` (D8) removes observable behavior (dossier 12 §5.5):
- `copy.copy(entity)` / `copy.deepcopy(entity)` no longer run hikari's custom shallow/deep semantics;
  frozen structs make copying an identity concern. **S2** for the copy protocol.
- `attrs.evolve(model, field=…)` stops working → use `msgspec.structs.replace(...)`. **S3**.
- `attrs.asdict` / `attrs.astuple` / `attrs.fields` / `attrs.has` on models → use
  `msgspec.structs.asdict` / `.fields` / `msgspec.to_builtins`. **S3**.
- `isinstance(x, attrs.AttrsInstance)` / `attr.has(type(x))` to detect a hikari model stops working
  (models are now `msgspec.Struct`s). Affects serialization libraries/plugins in the ecosystem. **S3**.

- **Deprecation window:** none — the type identity itself changes.

### 3.5 `UNDEFINED` sentinel — preserve if possible (S1 if identity changes)

`undefined.UNDEFINED` is used ~1912× (dossier 12 §5.7) / ~1714 `UndefinedOr[...]` annotations
(CONVENTIONS §5) and is the public "field not provided" marker in both REST request params and
decoded partial-entity fields. **Preferred decision (D5):** keep `hikari.UNDEFINED` as the public
sentinel and set it as the `default` on the decoded tri-state Struct fields, leaving the thousands of
`is UNDEFINED` checks and the whole REST param layer untouched. If the D5 VERIFY gate fails (msgspec
rejects `T | UndefinedType` unions), fall back to `msgspec.UNSET` with a public compatibility shim.

- **Severity:** **S1 only if** the sentinel identity changes; the D5 preferred path is designed to
  **avoid** the break. Flag as compat-sensitive; resolve the VERIFY gate before coding
  ([`../01-foundations/03-undefined-and-unset.md`](../01-foundations/03-undefined-and-unset.md)).

### 3.6 `orjson` → msgspec internal JSON — S3, mostly internal

orjson is not re-exported; JSON lives behind `internal/data_binding.py`. Break surface is limited to
users who imported hikari's internal JSON helpers or relied on exact orjson error types / float / int
-key behaviors (dossier 12 §5.8). `default_json_dumps`/`default_json_loads` names are kept to minimize
ripple (dossier 14 §10.3).

### 3.7 Exceptions stay attrs/plain classes — not a break, a scope exclusion

The 22 `auto_exc` error classes (`errors.py`) do **not** migrate to Structs (msgspec cannot subclass
`Exception`). Documented so reviewers don't expect them to change (dossier 12 §5.6, D3).

### 3.8 Builders stay mutable — not a break, a scope exclusion

`Embed` (mutable fluent builder) and the 42 `special_endpoints` builders stay mutable (D11). Called
out so the freeze is understood as decoded-entity-only (dossier 12 §5.4).

### 3.9 Events and interactions (FLAGGED D10) — severity depends on the decision

Recommended **option 2** (CONVENTIONS §8, [`../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md`](../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md)):
events and interactions are hand-constructed by the factories, so `app` injection is trivial and the
"can't inject on decode" constraint does not bite. Under option 2 events keep `app`+helpers and
interaction response sugar (`build_response`, `create_initial_response`) survives, **also** mirrored on
`rest.*`. This **avoids** the S1 break for interaction responses. Option 1 (fully app-less) would make
this the single most breaking change. This is a maintainer call — present both in the decisions log.

### 3.10 Downstream ecosystem coordination

The `3.0.0` break lands hardest not in end-user bots but in the command/component frameworks built on
hikari, which reach into exactly the surfaces this migration removes:

- **tanjun** and **lightbulb** (command frameworks) depend on `app` injection and on dispatched
  entities carrying a client reference.
- **arc** / **crescent** (command frameworks) build on the same app-aware entity and interaction
  model.
- **miru** (component/view framework) and **yuyo** (component/pagination helpers) depend on
  `interaction.create_initial_response(...)` and on `entity.respond()` / `channel.send()` response
  sugar.
- Serialization / plugin code across the ecosystem relies on `attrs` model introspection
  (`attrs.fields` / `attrs.asdict` / `isinstance(x, attrs.AttrsInstance)`), which stops detecting a
  hikari model once entities are `msgspec.Struct`s (§3.4).

Coordination required:

1. **Pre-`3.0` announcement.** Publish the break catalog and migration guide to the maintainers of the
   frameworks above before the `3.0.0` PRs merge, so they can prepare compatible releases in parallel.
2. **Impacted-consumer list.** Track tanjun, lightbulb, arc, crescent, miru, and yuyo as the known
   blocking consumers; each needs a hikari-`3.0`-compatible release.
3. **Coordinated release window.** Align the `3.0.0` release with (or slightly behind) framework-
   compatible releases so users are not stranded on a broken dependency graph — a `3.0.0` that ships
   before its ecosystem can migrate strands every downstream bot on the old line.

---

## 4. Severity + deprecation-window summary

| Change | Severity | Deprecation window? | Channel |
|---|---|---|---|
| Helper + `app` removal (§3.1) | S1/S2 | Partial (`2.6` warn on still-attrs helpers) | `breaking` + guide (+ optional `2.6` `deprecation`) |
| Strict enums (§3.2, PR #2770) | S1 | No | #2770 `breaking` + guide |
| Frozen models (§3.3) | S2 | No | `breaking` + guide |
| attrs copy/evolve/asdict/isinstance (§3.4) | S2/S3 | No | `breaking` + guide |
| `UNDEFINED` identity (§3.5) | S1 if changed | Preserve (avoid) | avoid; document if fallback |
| orjson internal (§3.6) | S3 | No (internal) | `breaking` (brief) |
| Custom `Flag` API (§3.2) | preserve | Preserve | avoid the break |
| Exceptions / builders (§3.7, §3.8) | — | scope exclusion | note in guide |
| Events/interactions D10 (§3.9) | option-dependent | option 2 avoids the interaction break | `breaking` + `feature` |

Bottom line: a **major (`3.0.0`)** release where the bulk are hard breaks landed via `breaking`
fragments; a single optional `2.6` deprecation pass can pre-warn only the helper removal.

---

## 5. Deprecation-window option (the optional `2.6` pass)

If the maintainer wants to soften the highest-blast-radius break (§3.1):

1. On a `2.6` line (still attrs), decorate each helper with
   `warn_deprecated(f"{Class}.{method}", removal_version="3.0.0", additional_info="Use rest.<equivalent> directly")`.
2. Ship `2.6`; users get a runtime `DeprecationWarning` pointing at the `rest.*` replacement while the
   helpers still work.
3. `3.0.0` deletes them. Note the version-gating subtlety: `check_if_past_removal` only hard-raises
   once `3.0.0` *final* ships and the code is still present (dossier 12 §3.1) — so the physical
   deletion must be done in the `3.0.0` PRs, not left to the guard.

This is the only break that maps cleanly onto the existing tooling; the strict-enum / frozen / attrs
-contract breaks are behavioral and cannot be pre-warned. Whether to spend a `2.6` line at all is a
release-calendar decision — cross-link [`00-phasing-and-sequencing.md`](00-phasing-and-sequencing.md)
§8 (Q-P1) and [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md).

---

## 6. `changes/` fragments to add

Following `{PR}.{type}.md`. Cluster the breaks so the CHANGELOG reads as ~5 sections, not 20 modules
(fragment numbers reconciled at the integration-branch merge, [`01-pr-breakdown.md`](01-pr-breakdown.md)
X2). Fragment bodies are free-form markdown and may use nested bullets (dossier 12 §7).

**`{PR}.breaking.md` — helper/app removal:**
```markdown
Entity helper methods and the `app` attribute have been removed from deserialized models.
Models no longer carry a client reference, so methods that used it are gone. Use the REST/cache
client directly:
- `message.respond(...)`      -> `rest.create_message(message.channel_id, ...)`
- `channel.send(...)`         -> `rest.create_message(channel.id, ...)`
- `message.edit(...)`         -> `rest.edit_message(message.channel_id, message.id, ...)`
- `guild.ban(user)`           -> `rest.ban_user(guild.id, user)`
- `user.fetch_dm_channel()`   -> `rest.create_dm_channel(user.id)`
- `guild.get_member(user)`    -> `cache.get_member(guild.id, user)`
See the 3.0 migration guide for the full mapping and the new helpers for cases without a 1:1 REST
call (`fetch_member_roles`, DM send, webhook token resolution, permission-overwrite editing).
```

**`{PR}.breaking.md` — strict enums (adopts PR #2770):**
```markdown
Enums are now strict (upstream PR #2770). Model fields and REST parameters are typed as the exact
enum/flag (the `EnumType | int` / `| str` tolerance unions are gone). Forward-compatibility is
preserved: an unknown Discord value now casts to a value-preserving "unknown member" (`int(x)` /
`str(x)` / `==` still work; the new `is_unknown` property is `True`), and unknown flag bits are kept.
Note the semantic changes: `SomeEnum(unknown)` no longer returns a bare `int` — `type(x) is int` is
now `False` and `isinstance(x, SomeEnum)` is now `True`; and casting a value of the wrong type now
raises `TypeError`.
```

**`{PR}.breaking.md` — frozen models:**
```markdown
Deserialized models are now immutable (frozen). Setting an attribute raises. To derive a modified
copy use `msgspec.structs.replace(model, field=...)` (replaces `attrs.evolve`). Introspection idioms
move from `attrs.*` to `msgspec.structs.*` / `msgspec.to_builtins`. Builders (e.g. `Embed`) remain
mutable. Cached objects are now shared by reference and cannot be mutated in place.
```

**`{PR}.breaking.md` — backend switch:**
```markdown
The data model and JSON backend moved from attrs + orjson to msgspec. `msgspec` is now a required
core dependency; the optional `orjson` speedup and the `hikari.internal.attrs_extensions` module have
been removed. Models are `msgspec.Struct`s, so `isinstance(x, attrs.AttrsInstance)` no longer detects
a hikari model.
```

**`{PR}.optimization.md`:**
```markdown
- JSON decoding/encoding now uses msgspec (no orjson/stdlib-json branching).
- Frozen models let the cache drop its per-read copy/deepcopy machinery; cache reads return shared
  instances directly.
```

**`{PR}.documentation.md`:**
```markdown
Added a 3.0 migration guide covering the removal of entity helper methods and the `app` attribute,
strict enums, frozen models, and the attrs -> msgspec introspection equivalents.
```

**Optional `{PR}.deprecation.md` (only on a `2.6` line, §5):**
```markdown
Entity helper methods that call the client (e.g. `Message.respond`, `Channel.send`, `Guild.ban`) are
deprecated and will be removed in `3.0.0`. Use the equivalent `rest.*` / `cache.*` calls.
```

Preview the assembled CHANGELOG with `towncrier --draft` before merge (dossier 12 §7).

---

## 7. Affected files and symbols

| Area | Anchor |
|---|---|
| Public namespace | `hikari/__init__.py:30-148`; `hikari/__init__.pyi` (regen) |
| Deprecation tooling | `hikari/internal/deprecation.py:48-102`; version gate `internal/ux.py:389-413` |
| Helpers / `app` | 173 methods / 20 modules (163 `self.app.*` + 10 `self.user.app.*` on `guilds.Member`; dossier 04); `impl/entity_factory.py` `app=self._app` ×63 |
| Enums (PR #2770) | `hikari/internal/enums.py:154-156` (`__call__`), `:381-412` (`Flag`); 142 `Enum \| int` typings |
| attrs contract | `internal/attrs_extensions.py`; `tests/hikari/internal/test_attr_extensions.py` |
| `UNDEFINED` | `hikari/undefined.py`; ~1912 uses |
| towncrier | `pyproject.toml:214-230`; `changes/`; `changes/.template.md.jinja` |
| Migration guide (new) | `docs/`; `mkdocs.yml` nav; attrs inventory `mkdocs.yml:137` |
| Examples (mypy-gated) | `examples/*`; `pipelines/mypy.nox.py:43` |

---

## 8. Risks / gotchas

- **Examples are CI-gated** (`pipelines/mypy.nox.py:43`) — a breaking change that lands without the
  example rewrite fails CI. Bundle the example rewrite into the same release train (P3/H3).
- **`.pyi` stub drift** (`ci.yml:130-137`) — every surface change (helper removal, model reshape)
  changes `stubgen` output; regenerate all 5 stubs or the gate fails.
- **`verify-types`** re-measures public-API type completeness after helper removal; newly-untyped
  exports fail (dossier 14 §4.3).
- **No public-API snapshot test today** (dossier 12 §9) — accidental symbol drops during a refactor of
  this size go unguarded; add one ([`01-pr-breakdown.md`](01-pr-breakdown.md) X3).
- **`check_if_past_removal` does not delete code** — if a `2.6` deprecation pass is taken, the physical
  deletion in `3.0.0` is still manual (dossier 12 §3.1).

---

## 9. Verification

- `towncrier --draft` renders the intended `3.0.0` CHANGELOG sections.
- The migration guide covers every S1/S2 row in §4 with a concrete before/after.
- The public-API snapshot test (X3) confirms only intended symbols were removed.
- Examples + docs build green under the new surface.

---

## 10. Open questions / decisions

- **Spend a `2.6` deprecation line?** (§5). Cross-link [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md), dossier 12 §6.
- **D5 `UNDEFINED` vs `UNSET`** — resolve the VERIFY gate; determines whether §3.5 is a break at all.
- **D10 events/interactions** — determines the §3.9 severity.
- **Depth of the migration guide** — full per-method mapping table vs cluster-level guidance?
  Recommended: full table for the helper removal (it is the dominant burden, dossier 12 §10.2).
