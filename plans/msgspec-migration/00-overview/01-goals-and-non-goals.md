# Goals and Non-Goals

An explicit scope boundary for the migration. Everything a reviewer might assume is included but is
not — and everything that looks optional but is mandatory — is called out here so no downstream plan
file has to re-litigate scope. Decisions referenced by number are defined in
[05-decisions-log.md](05-decisions-log.md).

## 1. Objective

Fix the boundary of the migration precisely, so effort estimates, the PR breakdown
([11-rollout/01-pr-breakdown.md](../11-rollout/01-pr-breakdown.md)), and the breaking-change catalog
([11-rollout/03-breaking-changes-and-changelog.md](../11-rollout/03-breaking-changes-and-changelog.md))
all draw the same line. This file serves all three constraints by stating which of their consequences
are pursued now and which are deliberately deferred.

## 2. Goals (in scope)

### 2.1 Data layer

| # | Goal | Constraint | Plan file |
|---|---|---|---|
| G1 | Replace all 175 model-module `@attrs.define` classes that are wire models with frozen `msgspec.Struct` types | (c) | [../06-model-modules/00-README.md](../06-model-modules/00-README.md) |
| G2 | Adopt PR hikari-py/hikari#2770's strict enum typing on the 80 custom enum/flag types — **keep** hikari's fast `hikari/internal/enums.py` `Enum`/`Flag` (no stdlib port) and decode them via the shared global `dec_hook` | (b) | [../02-enums/00-strategy-and-forward-compat.md](../02-enums/00-strategy-and-forward-compat.md) |
| G3 | Drop the ~150 `SomeEnum \| int` / `\| str` tolerance unions on entity fields | (b) | [../02-enums/03-strict-enum-field-inventory.md](../02-enums/03-strict-enum-field-inventory.md) |
| G4 | Remove the `app` field from all JSON-decoded entities and delete their app-delegating helper methods. Count is option-dependent: 163 `self.app.*` sites is the floor; the true total is **173** including the 10 `self.user.app.*` sites on `guilds.Member`. Under the recommended D10 Option 2 the ~114 **wire-entity** helpers are removed and the ~59 event/interaction helpers are retained; Option 1 removes all ~173 (see [../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md](../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md)) | (a) | [../03-app-removal-and-helpers/00-strategy.md](../03-app-removal-and-helpers/00-strategy.md) |
| G5 | Slim `hikari/internal/attrs_extensions.py` in the first pass — remove the dead deep-copy half and the cache-only shallow-copy path, but retain `with_copy` for the deferred non-Struct consumers (the 42 `special_endpoints` builders (~15 `with_copy`), `impl/config.py` (5), `internal/routes.py` (3), `errors.py` (2)). Delete it wholesale only in a later phase, once every consumer is off attrs | (c) | [../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md](../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md) |
| G6 | Collapse the 104 cache copy sites to identity returns; delete dead `Cell` | (c) | [../04-frozen-and-cache/01-cache-data-layer-and-mutation.md](../04-frozen-and-cache/01-cache-data-layer-and-mutation.md) |

### 2.2 JSON boundary

| # | Goal | Decision | Plan file |
|---|---|---|---|
| G7 | Replace `orjson` in `hikari/internal/data_binding.py` with `msgspec.json` | D6 | [../01-foundations/04-json-data-binding.md](../01-foundations/04-json-data-binding.md) |
| G8 | Introduce module-level `msgspec.json.Decoder`/`Encoder` instances with a single global `dec_hook`/`enc_hook` | D4 | [../01-foundations/02-custom-scalar-types-and-hooks.md](../01-foundations/02-custom-scalar-types-and-hooks.md) |
| G9 | Make msgspec a core dependency; remove `orjson` from the `speedups` extra | D7 | [../01-foundations/00-dependencies-and-tooling.md](../01-foundations/00-dependencies-and-tooling.md) |

### 2.3 Factory

| # | Goal | Decision | Plan file |
|---|---|---|---|
| G10 | Introduce tagged-union decode for the 19 polymorphic dispatch tables where the discriminator is a literal on each struct | D1 | [../05-entity-factory/01-polymorphism-and-tagged-unions.md](../05-entity-factory/01-polymorphism-and-tagged-unions.md) |
| G11 | Retain a slimmed residual factory for the ~13 hard-case categories | D1 | [../05-entity-factory/02-hard-cases-and-transforms.md](../05-entity-factory/02-hard-cases-and-transforms.md) |

## 3. Non-goals (explicitly out of scope)

These are deliberately excluded. Each has a rationale; several are candidates for a later,
independent change.

### 3.1 Errors stay exceptions

The 22 `errors.py` classes are declared `@attrs.define(auto_exc=True, ..., slots=False)`
(dossier 03 §4.3). They are exception types, not data records. They are **not** converted to structs.
If `attrs` is removed from the tree entirely they become plain `class X(Exception)` with a manual
`__init__`, or keep a thin `attrs`/`dataclass`; `slots=False` there is deliberate (exceptions need
`__dict__`/`args`). No struct migration touches them. (Decision D3 scope note.)

### 3.2 Outbound builders are deferred (D11)

The 42 `impl/special_endpoints.py` builder classes serialize **to** Discord and are never decoded.
They are kept as-is in the first pass: they emit dicts via the existing builders, and
`msgspec.json.encode` serializes the dict. Converting them to frozen structs with `enc_hook` + `UNSET`
omit-on-encode is a large orthogonal change touching the public builder API and is **deferred**. See
[../08-builders/00-special-endpoints-builders.md](../08-builders/00-special-endpoints-builders.md).

### 3.3 REST request-body encoding stays hand-built (D7)

The `JSONObjectBuilder` / `StringMapBuilder` / `URLEncodedFormBuilder` request-body builders are
retained; they already skip `UNDEFINED` and stringify snowflakes. Only their dict output is fed to
`msgspec.json.encode`. Rewriting request encoding as declarative struct encode is a non-goal for this
migration.

### 3.4 Method-parameter input lenience is unchanged (orthogonal to D2)

The ~80 method-parameter unions typed `| int` for input lenience (e.g.
`video_quality_mode: UndefinedOr[VideoQualityMode | int]`, dossier 02 §C.3) exist so callers may pass
a raw int/str. They are **not** decoded by msgspec and are orthogonal to constraint (b). The
recommendation is to **keep input lenience**; tightening them is a separate ergonomics decision, out
of scope here. Constraint (b) removes only the ~150 unions on **decoded entity fields**.

### 3.5 `UndefinedOr` public API is preserved

`hikari.undefined.UNDEFINED` and the `UndefinedOr[T]` alias remain the public tri-state sentinel for
REST **request** params (the vast majority of the ~1714 annotations, CONVENTIONS §5). The preferred
plan (D5) keeps `hikari.UNDEFINED` outright; the thousands of `is UNDEFINED` identity checks and the
entire REST-param layer are untouched. Replacing the public sentinel wholesale is a non-goal.

### 3.6 The lazy `GatewayGuildDefinition` contract is preserved

`GatewayGuildDefinition` (`hikari/api/entity_factory.py:63`) is a public ABC whose lazy
deserialization deliberately avoids eagerly decoding huge `GUILD_CREATE` payloads (dossier 05 §4).
Eager msgspec decode of `GUILD_CREATE` would regress memory/CPU on large guilds. Preserving (or
explicitly redesigning) the laziness is required; discarding it is a non-goal. See
[../05-entity-factory/02-hard-cases-and-transforms.md](../05-entity-factory/02-hard-cases-and-transforms.md).

### 3.7 No behavioral change to the public model shape

The public attribute names, model hierarchy, and id-only identity semantics are preserved. The
migration is a re-platforming, not an API redesign, except where a constraint forces a change
(app-less models, strict enum field types, immutability). Renaming public fields, restructuring the
hierarchy, or changing snowflake identity semantics are non-goals.

### 3.8 The `deprecated` enum-alias machinery is out of scope

`enums.deprecated` / `_DeprecatedAlias` (`hikari/internal/enums.py:42-74`) is **unused by any concrete
enum** (dossier 02 §A.4). The custom enums module is kept, so this dead helper is left as-is (or
dropped as an unrelated cleanup); the msgspec migration neither ports nor redesigns it.

## 4. Boundary cases (in scope, but bounded)

- **`embeds.Embed`** is a hand-written mutable builder (`embeds.py:257`), not an `attrs` class. Its
  nested pieces become structs; `Embed` itself stays a hand-written builder or a non-frozen struct
  with custom decode (dossier 03 §5). Converting `Embed` to a pure frozen decoded struct is out of
  scope — its `from_received_embed` classmethod path is preserved.
- **`files.Resource` family** multiple-inheritance (`Attachment`, `MediaResource`, `EmbedImage/Video`)
  is a known sharp edge (Struct + non-Struct mixin, dossier 03 §5). It is handled explicitly in the
  model-module and files plan files; a mechanical attrs→Struct swap is **not** assumed.
- **`Member` / `TeamMember`** inherit equality from a wrapped `users.User` via `eq=False`
  (`guilds.py:422`, `applications.py:418`). This delegation is preserved deliberately, not by
  default (dossier 03 §5).

## 5. Success criteria

The migration is complete when: all 157 wire models are frozen app-less structs (G1, G4, G5); their
app-delegating helpers are removed at the scope the D10 decision fixes — the ~114 **wire-entity**
helpers under the recommended Option 2 (which retains the ~59 event/interaction helpers), or all ~173
app-delegating helpers under Option 1
([../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md](../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md));
all 80 enums are strict custom enums (adopting #2770) with no `| int`/`| str` entity-field unions
(G2, G3); the cache returns
bare frozen structs with no copy machinery (G5, G6); `data_binding.py` uses msgspec and `orjson` is
gone (G7, G9); the existing test suite passes with the identity/copy assertions rewritten
([../10-testing/02-cache-copy-and-enum-tests.md](../10-testing/02-cache-copy-and-enum-tests.md)); and
the FLAGGED D10 decision has been made by the maintainer. The deferred non-goals (builders,
request-encoding, input-lenience tightening) are tracked but not required.
