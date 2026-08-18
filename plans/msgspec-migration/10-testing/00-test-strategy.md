# Test Strategy for the msgspec Migration

Purpose: establish how the existing `tests/` suite must change to keep passing (and keep meaning
something) once wire models become frozen, app-less, strict-enum msgspec Structs. This file is the
umbrella; the mechanics of the shared helpers are in
[`01-fixtures-and-helpers.md`](./01-fixtures-and-helpers.md) and the copy/enum assertion rewrites are
in [`02-cache-copy-and-enum-tests.md`](./02-cache-copy-and-enum-tests.md).

## 1. Objective

Adapt the test suite to the three forcing constraints without silently dropping coverage:

- (a) **No `app` injection** — remove `app=` from every constructed entity and delete every
  `assert entity.app is mock_app` and every `entity.app.rest.*` / `entity.app.cache.*` delegation
  test (163 helper methods vanish; see
  [`../03-app-removal-and-helpers/00-strategy.md`](../03-app-removal-and-helpers/00-strategy.md)).
- (b) **Strict enums** — rewrite the raise / skip / preserve-raw unknown-value tests to the new
  pseudo-member contract (see [`../02-enums/00-strategy-and-forward-compat.md`](../02-enums/00-strategy-and-forward-compat.md)).
- (c) **Frozen structs** — replace the pervasive "construct-then-mutate" idiom with
  construct-with-final-values or `msgspec.structs.replace`, and invert the cache copy-isolation
  assertions.

The strategy is **mechanical wherever possible**: introduce a thin helper layer once, then convert
call sites in bulk, so the ~28 model-constructing files and the two huge factory/cache test files do
not each get a bespoke hand-edit.

## 2. Current state (how tests are built today)

There is **no `conftest.py` anywhere in the repo** and **no stub-entity/factory layer**. Every test
hand-builds each entity by calling the real `attrs` constructor with full keyword arguments,
including `app=`. Inventory (dossier 11 §0, §9):

| Metric | Count | Source |
|---|---|---|
| Total test files | 84 | `find tests -name '*.py'` |
| Total `def test_*` | ~2940 | grep |
| `async def test_*` | 759 | grep |
| Files constructing models with `app=` | 28 | grep |
| `.app.rest.` helper-exercise lines | 274 | grep |
| `.app.cache.` helper-exercise lines | 116 | grep |
| `assert <e>.app is mock_app` (entity_factory test) | 59 | grep |
| `.app` references (entity_factory test) | 154 | grep |
| `deserialize_` call sites (entity_factory test) | 860 | grep |
| `mock_class_namespace` usages | 85 | grep |
| Broad construct-then-mutate lines (superset, 37 files) | 729 | grep |
| Genuine frozen-struct field mutations (estimate) | ~250-350 | analysis |
| `is not` cache copy-isolation asserts (`impl/test_cache.py`) | 21 | grep |
| `EnumType \| int` model fields | ~32-50 | grep |
| Files importing `attrs` directly | 3 | grep |
| Files importing `orjson`/`json` | 0 | grep |

### 2.1 The four construction patterns

1. **Pattern A — direct constructor, full kwargs (dominant).**
   `tests/hikari/test_channels.py:48-50`:
   ```python
   follow = channels.ChannelFollow(
       channel_id=snowflakes.Snowflake(9459234123), app=mock_app, webhook_id=snowflakes.Snowflake(3123123)
   )
   ```
   `tests/hikari/test_messages.py:118-152` builds `messages.Message(app=None, id=..., ~30 kwargs ...)`.
2. **Pattern B — `mock_class_namespace(AbstractBase)(**kwargs)`** for abstract wire bases that carry
   abstract helper methods and cannot be constructed directly. `tests/hikari/test_channels.py:100-103`:
   ```python
   return hikari_test_helpers.mock_class_namespace(channels.PartialChannel, rename_impl_=False)(
       app=mock_app, id=snowflakes.Snowflake(1234567), name="foo", type=channels.ChannelType.GUILD_NEWS
   )
   ```
3. **Pattern C — `mock.Mock(spec_set=Model)`** for collaborators only needed as stand-ins
   (`tests/hikari/test_messages.py:123-124` `author=mock.Mock(spec_set=users.User)`).
4. **Pattern D — `mock.Mock()` app fixture** — the near-universal `mock_app`
   (`tests/hikari/impl/test_entity_factory.py:393-395`).

Because there is no abstraction between the tests and the constructors, every constructor-signature
change (drop `app`, freeze, strict-enum field types) is felt directly in hundreds of literal call
sites. That is the whole reason this migration should introduce a helper layer (§4,
[`01-fixtures-and-helpers.md`](./01-fixtures-and-helpers.md)).

### 2.2 kw_only construction already dominates

173/175 model classes are `kw_only=True` today (dossier 03 §2), so the msgspec `kw_only=True` base
(CONVENTIONS §2) does not change how tests pass arguments — they already pass everything by keyword.
The two positional exceptions (`components.ActionRowComponent`, `guilds.WelcomeChannel`) are the only
places a positional test call could exist; audit those two constructors specifically.

## 3. Target design (what "correct" looks like after migration)

### 3.1 Construction: final-values, not mutate-after

msgspec frozen Structs reject attribute assignment. The idiom that breaks everywhere is
"build a base fixture, then set one attribute per test":

```python
# BEFORE — tests/hikari/test_channels.py:109-111
def test_str_operator_when_name_is_None(self, model):
    model.name = None                     # AttributeError on a frozen Struct
    assert str(model) == "Unnamed PartialChannel ID 1234567"
```

Two sanctioned replacements:

```python
# AFTER (a) — construct with the final value
model = make_partial_channel(name=None)
assert str(model) == "Unnamed PartialChannel ID 1234567"

# AFTER (b) — evolve an existing frozen instance
import msgspec
model2 = msgspec.structs.replace(model, name=None)
```

`msgspec.structs.replace(obj, **changes)` returns a **new** frozen instance with the overrides
applied and is the direct analogue of the old in-place set. A suite-wide `evolve(model, **overrides)`
wrapper (defined in [`01-fixtures-and-helpers.md`](./01-fixtures-and-helpers.md)) lets the ~250-350
mutation sites convert nearly mechanically: `model.x = v` becomes `model = evolve(model, x=v)`.

### 3.2 No `app` anywhere

Every `app=mock_app` / `app=None` / `app=object()` kwarg is deleted from constructions because the
field no longer exists (24 declarations removed, dossier 03 §0). The `mock_app` fixture survives, but
only to stand in as the **external** `rest` / `cache` client that helper tests now call directly
(§3.3), not as an entity field.

### 3.3 Helper-method tests become `rest`/`cache` tests or are deleted

The 163 `self.app.*` helper methods are removed, so their delegation tests lose their subject. Per
CONVENTIONS §8 and dossier 11 §10.2:

- **Pure delegation** (helper just forwards to `rest.<x>` with the same args) → **delete** the
  delegation test; coverage already lives in `tests/hikari/impl/test_rest.py` for the real
  `rest.<x>`. Lowest effort, acceptable.
- **Argument-shaping helpers** (the no-1:1-rest cluster: `Message.respond`'s `reply=True→self`,
  `Member.fetch_roles` client-side filter, `PartialUser.send` DM resolve, webhook token resolution,
  `PermissibleGuildChannel.edit_overwrite` target-type inference, guild-scoped cache getters) →
  **move** the test to whatever free function / new rest method absorbs that logic
  (see [`../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md`](../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md)).
- **Pure helpers that never touch `self.app`** (`make_*_url`, `Message.make_link`,
  `MessageReference.message_link`, `PartialChannel.mention`, `str()`, `Reaction.burst_colours` alias,
  `ForumTag.emoji_id`/`unicode_emoji`, `PermissionOverwrite.unset`) → **keep**; only their fixtures
  need the frozen-construction fix.

### 3.4 The 4 leading-underscore fields — kwarg shift

CONVENTIONS §2 collapses trivial `_x`+property pairs to a public field `x`. For the 4 model-module
alias fields (dossier 03 §6), the constructor kwarg used in tests changes:

| Field (source) | Today's ctor kwarg | Recommended after | Test impact |
|---|---|---|---|
| `channels.py:1498` `_emoji` (`ForumTag`) | `emoji=` (via `alias=`) | field renamed; `unicode_emoji`/`emoji_id` stay properties | `test_channels.py` `ForumTag` builds pass `emoji=` today (`:494-503`); keep working only if a classmethod/`emoji=` shim retained — otherwise switch to `_emoji=` |
| `presences.py:128` `_application_id` | `application_id=` (via `alias=`) | keep `_application_id` storage (property does work) → ctor kwarg becomes `_application_id=` | update `test_presences.py` construction |
| `embeds.py:233` `_inline` (`EmbedField`) | `inline=` (via `alias=`) | rename to public `is_inline`-style or keep `_inline=` | update `test_embeds.py` |
| `sessions.py:66` `_created_at` | `init=False` (not passable) | keep computed property; still not a ctor kwarg | no test change |

Key rule from CONVENTIONS §2: **msgspec `field(name=…)` renames only the wire key, never the ctor
kwarg.** So wherever `_x` storage is retained, the test constructor kwarg is literally `_x=`. This is
a small, enumerable surface (3 passable fields) — call it out per model-module test rather than
sweeping it.

## 4. Step-by-step migration (ordered)

1. **Land the helper layer first** (before touching any model test): add `evolve()` and stub-entity
   builders to `tests/hikari/hikari_test_helpers.py` (or a new `tests/hikari/stubs.py`) as specified
   in [`01-fixtures-and-helpers.md`](./01-fixtures-and-helpers.md). Nothing else can proceed cleanly
   until `evolve` exists.
2. **Sequence with the source rollout.** Test changes for a given model module land in the **same PR**
   as that module's freeze+app-removal (see [`../11-rollout/01-pr-breakdown.md`](../11-rollout/01-pr-breakdown.md));
   do not try to convert all tests up front against un-migrated source.
3. **Per model-module test file**, in dependency order (users → emojis → channels → guilds → messages
   → …, matching [`../06-model-modules/00-README.md`](../06-model-modules/00-README.md)):
   1. delete all `app=` kwargs from constructions;
   2. convert construct-then-mutate → `evolve()` or final-value construction;
   3. delete pure-delegation helper tests; move argument-shaping helper tests to their new home;
   4. fix the 3 underscore-field ctor kwargs if that module owns one;
   5. re-run the file.
4. **`impl/test_entity_factory.py`** (8839 lines — the single biggest job): delete the 59
   `assert <e>.app is mock_app` asserts; strip `app=mock_app` from every expected-model literal;
   rewrite the unknown-enum raise/skip/preserve tests (§3 of
   [`02-cache-copy-and-enum-tests.md`](./02-cache-copy-and-enum-tests.md)); keep the 860
   `deserialize_*` call sites but re-point their per-field asserts where field types changed.
5. **`impl/test_cache.py`** (3180 lines): invert the 21 `is not` copy-isolation asserts to value or
   identity equality; convert entity-field mutations to `evolve`; confirm `set_*`/`get_*` no longer
   copy (details in [`02-cache-copy-and-enum-tests.md`](./02-cache-copy-and-enum-tests.md)).
6. **`internal/test_enums.py`** (1308 lines): replace the custom-metaclass tests with strict-enum
   pseudo-member tests (§3 of [`02-cache-copy-and-enum-tests.md`](./02-cache-copy-and-enum-tests.md)).
7. **`internal/test_attr_extensions.py`** (419 lines): **delete the file** — it tests the copy engine
   that [`../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md`](../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md)
   removes entirely.
8. **`integration/test_equality_comparisons.py`**: keep as-is IF `Unique.__eq__`/`__hash__` is
   preserved on the Structs (recommended, CONVENTIONS §2); otherwise rewrite (§8 open question).
9. **Interactions tests** (`interactions/test_*`): apply the D10 events/interactions decision
   (see [`../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md`](../03-app-removal-and-helpers/04-events-and-interactions-app-decision.md)) —
   under the recommended option 2, interaction response-builder tests (`build_response`,
   `create_response`) survive largely intact because interactions keep `app`.
10. **Green the whole suite** and diff coverage against the pre-migration baseline; any net-removed
    coverage must be a deliberate, documented deletion (pure-delegation tests), not an accident.

## 5. Affected files & symbols

| Path | Role | Change |
|---|---|---|
| `tests/hikari/hikari_test_helpers.py` | shared helper (174 lines) | add `evolve`; possibly a `struct_class_namespace`; `mock_class_namespace` audit (`:43-81`) |
| `tests/hikari/impl/test_entity_factory.py` | deserialize (8839 lines) | drop 59 app asserts, strip `app=`, enum-tolerance rewrites |
| `tests/hikari/impl/test_cache.py` | cache (3180 lines) | 21 copy asserts inverted, field mutations → `evolve` |
| `tests/hikari/internal/test_enums.py` | enum metaclass (1308 lines) | heavy rewrite to strict-enum contract |
| `tests/hikari/internal/test_attr_extensions.py` | copy engine (419 lines, ~26 tests) | **delete** |
| `tests/hikari/internal/test_cache.py` | Data copy behavior (76 lines) | rewrite `copy.copy` expectation `:70-76` |
| `tests/hikari/test_*.py` (flat model tests, ~40) | model construction | drop `app=`, construct-final/`evolve`, delete/move helper tests |
| `tests/hikari/interactions/test_*.py` (5) | interaction helpers | per D10 decision |
| `tests/hikari/integration/test_equality_comparisons.py` | id-equality (143 lines) | keep or rewrite per `Unique` decision |
| `tests/hikari/events/test_*.py` (16) | event construction | drop `app=` only if events go app-less (D10); else unchanged |

## 6. Risks / gotchas

- **msgspec does not validate on `__init__`** — only on decode. Passing a raw int to a strict-enum
  field at construction (e.g. `format_type=123` in `tests/hikari/internal/test_cache.py:62`,
  `command_type=1` in `tests/hikari/interactions/test_command_interactions.py:56`) still *constructs*.
  The test breaks later, at the first `.name` / `is Member` / identity comparison. These are latent,
  scattered failures — audit each construction that feeds an int/str literal into an enum field.
- **Structural equality latent flips.** If `Unique.__eq__`/`__hash__` is not preserved and structs
  fall back to msgspec's all-field `eq`, any entity holding a per-construction `object()`/`Mock()`
  (e.g. `tests/hikari/interactions/test_command_interactions.py:49-50` `member=object(), user=object()`)
  makes two otherwise "equal" entities structurally unequal — a wide, hard-to-predict source of
  failures. Preserving id-only identity (CONVENTIONS §2) avoids this.
- **`mock_class_namespace` coupling.** Its `__slots__=()` + subclass + `__abstractmethods__` injection
  assumes attrs/ABC semantics; msgspec Structs populate `__abstractmethods__` differently and reject
  the slots interplay. Whether it survives depends on whether abstract bases stay ABCs — see
  [`01-fixtures-and-helpers.md`](./01-fixtures-and-helpers.md) §2 and open question §8.1.
- **Do not convert tests ahead of source.** A test PR that freezes assumptions before the module is
  migrated will fail against the still-mutable attrs class. Keep test+source per-module PRs together.

## 7. Verification

- The suite is green after each per-module PR; CI runs the same `nox`/`pytest` targets unchanged
  (JSON swap is invisible to tests — no test imports `orjson`/`json`, dossier 11 §6).
- Coverage report (line + branch) is compared against the pre-migration baseline per module; net
  reductions are enumerated and justified (only pure-delegation deletions are allowed).
- A grep gate in CI (or a review checklist) asserts **zero** remaining `\.app\s*=` entity-construction
  kwargs and **zero** `\.app\.rest`/`\.app\.cache` in `tests/hikari/*.py` model tests after the
  app-removal PRs land.
- Spot-check that `evolve()`-based rewrites preserve the original test intent (same final field value,
  same assertion) rather than merely silencing the `AttributeError`.

## 8. Open questions / decisions

Cross-linked to [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md):

1. **Abstract model bases fate** — do `PartialChannel`, `GuildChannel`, `User`, `Guild`,
   `PartialCommand`, `InviteWithMetadata` become frozen Structs, Protocols, or stay ABCs? Decides
   whether `mock_class_namespace` (used 85×) survives or needs a `struct_class_namespace` sibling.
2. **`Unique` identity preserved?** If yes, `integration/test_equality_comparisons.py` is untouched;
   if structural equality is adopted, budget its rewrite plus an audit of every factory `==` assert.
3. **Delete vs port helper-delegation tests** — recommend delete for pure delegation, port for
   argument-shaping. Confirm the maintainer accepts relying on `impl/test_rest.py` for coverage.
4. **Introduce the shared stub/`evolve` layer now?** Recommended (this file assumes yes). The
   alternative — editing every literal in place across 28 files — is far more churn.
5. **Events app-less or not (D10)** — determines whether the 16 `events/test_*.py` files drop `app=`.
   Recommended option 2 (events keep app) leaves them largely untouched.
