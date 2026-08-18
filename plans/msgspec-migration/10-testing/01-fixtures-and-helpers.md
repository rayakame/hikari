# Test Fixtures and Helpers

Purpose: specify the concrete test-helper changes that let the rest of the suite convert mechanically
— the `evolve()` wrapper, a stub-entity builder layer, the fate of `mock_class_namespace`, and how to
mock an app-less entity alongside an external `rest`/`cache` client. This is the enabling PR that
[`00-test-strategy.md`](./00-test-strategy.md) step 1 refers to; land it before any model-test edits.

## 1. Objective

Provide a small, shared helper surface so the ~250-350 frozen-struct mutation sites and the ~28
`app=`-carrying construction files convert with find-and-replace rather than bespoke edits, and so
future churn is localized to one module. Serves constraints (a) app-less, (c) frozen.

## 2. Current state

The only shared helper module is `tests/hikari/hikari_test_helpers.py` (174 lines, read in full).
Public surface (dossier 11 §1):

| Symbol | Lines | Purpose | Migration exposure |
|---|---|---|---|
| `mock_class_namespace(klass, *, init_, slots_, implement_abstract_methods_, rename_impl_, **ns)` | 43-81 | throwaway **subclass** of `klass` with abstract methods auto-mocked + extra class attrs; used **85×** | HIGH |
| `retry`, `timeout`, `ensure_occurs_quickly` | 84-132 | async timing utilities | none |
| `ContextManagerMock` / `AsyncContextManagerMock` | 135-164 | ctx-manager assertion mocks | none |
| `CopyingAsyncMock` | 167-173 | `AsyncMock` that `copy.copy`s args before recording | LOW (frozen structs still copy fine) |

There is **no stub-entity/factory layer** — every test spells out full kwargs (dossier 11 §2). The
closest thing is the ad-hoc `make_user` / `make_team_member` / `make_guild_member` /
`make_known_custom_emoji` local helpers in `tests/hikari/integration/test_equality_comparisons.py:34-102`.

### 2.1 `mock_class_namespace` mechanics (`tests/hikari/hikari_test_helpers.py:54-81`)

```python
if slots_ or slots_ is None and hasattr(klass, "__slots__"):
    namespace["__slots__"] = ()
if init_ is False:
    namespace["__init__"] = lambda _: None
if implement_abstract_methods_ and hasattr(klass, "__abstractmethods__"):
    for method_name in klass.__abstractmethods__:
        ...
        namespace[method_name] = mock.Mock(...) / mock.AsyncMock(spec_set=attr, ...)
for attribute in namespace.keys():
    assert hasattr(klass, attribute), f"invalid namespace attribute {attribute!r} provided"
name = "Mock" + klass.__name__ if rename_impl_ else klass.__name__
return type(name, (klass,), namespace)          # dynamic subclass of the real class
```

Two uses: (1) instantiate abstract wire bases that carry abstract helper methods
(`channels.PartialChannel/TextableChannel/GuildChannel/PermissibleGuildChannel`,
`commands.PartialCommand`, `guilds.Guild`, `invites.InviteWithMetadata`, `users.PartialUser/User`,
1 each in flat model tests); (2) instantiate abstract event classes by supplying abstract
`message`/`shard` properties as class-level mocks. It is also how the **factory itself** is
instantiated: `tests/hikari/impl/test_entity_factory.py:398-401`
`mock_class_namespace(entity_factory.EntityFactoryImpl, slots_=False)(mock_app)`.

Usage concentration (top): `events/test_reaction_events.py`:13, `impl/test_event_manager_base.py`:10,
`events/test_typing_events.py`:6, `events/test_message_events.py`:6, `impl/test_rate_limits.py`:5,
`events/test_channel_events.py`:5, `test_channels.py`:4, `impl/test_rest_bot.py`:4 … (85 total).

## 3. Target design

### 3.1 `evolve()` — the mutation-site replacement

Add to `hikari_test_helpers.py`:

```python
import msgspec

def evolve(obj: _T, **overrides: typing.Any) -> _T:
    """Return a copy of a frozen msgspec Struct with `overrides` applied.

    The frozen-struct analogue of the old ``model.attr = value`` idiom. Returns a NEW
    instance; the original is unchanged.
    """
    return msgspec.structs.replace(obj, **overrides)
```

Conversion is mechanical:

```python
# BEFORE (tests/hikari/test_messages.py:157-158)
message.id = 789
message.channel_id = 456
# AFTER
message = evolve(message, id=789, channel_id=456)
```

`msgspec.structs.replace` respects `kw_only`, applies field defaults for anything not overridden, and
returns a valid frozen instance — no `__init__` re-validation quirk because it copies from the source
struct. It is the single lever that unlocks the ~250-350 mutation sites (dossier 11 §9).

### 3.2 Stub-entity builders — collapse full-kwargs literals

Add a `tests/hikari/stubs.py` (new module) of `make_<entity>(**overrides)` builders that default every
required field and forward overrides. Generalize the existing `test_equality_comparisons.py:34-102`
pattern. Example:

```python
# tests/hikari/stubs.py
import msgspec
from hikari import channels, snowflakes, users, guilds, messages, emojis

def make_partial_channel(**overrides):
    base = dict(
        id=snowflakes.Snowflake(1234567),
        name="foo",
        type=channels.ChannelType.GUILD_NEWS,
    )                                     # NOTE: no `app=` — the field is gone (constraint (a))
    base.update(overrides)
    return channels.PartialChannel(**base)

def make_user(**overrides):
    base = dict(
        id=snowflakes.Snowflake(115590097100865541),
        discriminator="0001", username="testing", global_name=None,
        avatar_decoration=None, avatar_hash=None, banner_hash=None,
        accent_color=None, is_bot=False, is_system=False,
        flags=users.UserFlag.NONE, primary_guild=None,
    )
    base.update(overrides)
    return users.UserImpl(**base)
```

Benefits: (i) one place absorbs the `app=` removal and any future required-field additions;
(ii) a test overrides only the field under test (`make_user(username="other")`), matching the intent
that construct-then-mutate used to express; (iii) shrinks the 30-kwarg `messages.Message(...)`
literals to `make_message(content="hi")`.

Scope: build stubs for the high-churn entities first — `User`/`OwnUser`, `Member`, `Message`,
`PartialChannel` + concrete channel types, `Guild`/`GatewayGuild`, `Role`, `KnownCustomEmoji`,
`GuildSticker`, `Invite`, and the interaction types. The long tail can keep inline literals.

### 3.3 Mocking app-less entities + an external rest/cache client

The `mock_app` fixture stays, but its role changes: it is no longer an **entity field**, it is the
**external client** that tests drive directly. Two shapes:

```python
# The app-less entity: build via stub, no app kwarg
message = make_message(id=snowflakes.Snowflake(789), channel_id=snowflakes.Snowflake(456))

# The external client the caller now uses instead of message.app.rest
rest = mock.AsyncMock(spec_set=hikari.api.RESTClient)
cache = mock.Mock(spec_set=hikari.api.Cache)
```

A pure-delegation helper test that was:

```python
# BEFORE — tests/hikari/test_channels.py:117-122 (PartialChannel.delete)
async def test_delete(self, model):
    model.app.rest.delete_channel = mock.AsyncMock()
    assert await model.delete() is model.app.rest.delete_channel.return_value
    model.app.rest.delete_channel.assert_called_once_with(1234567)
```

is **deleted** (the `delete()` helper no longer exists; `rest.delete_channel` is covered in
`tests/hikari/impl/test_rest.py`). An argument-shaping helper (e.g. `Message.respond` reply handling,
`tests/hikari/test_messages.py:301-355`) is **moved**: test the free function / new rest method that
absorbs the logic, driving the mock `rest` directly and asserting the shaped call
(see [`../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md`](../03-app-removal-and-helpers/03-new-rest-methods-and-free-functions.md)).

Provide a fixture in `hikari_test_helpers.py` or a module-local fixture:

```python
@pytest.fixture
def rest():
    return mock.AsyncMock(spec_set=hikari.api.RESTClient)

@pytest.fixture
def cache():
    return mock.Mock(spec_set=hikari.api.Cache)
```

### 3.4 Constructing pseudo-member enum values in tests

Strict enums (D2) mint value-preserving pseudo-members via `_missing_` on lookup miss. In tests, an
unknown value is produced by **calling the enum**, not by feeding a bare int:

```python
# A known member
channels.ChannelType.GUILD_TEXT                      # -> real member

# An UNKNOWN value (pseudo-member) — what Discord-adds-a-new-type looks like
unknown = channels.ChannelType(9999)                 # -> pseudo-member, == 9999, isinstance OK
assert unknown == 9999
assert int(unknown) == 9999
assert isinstance(unknown, channels.ChannelType)     # NEW: True (was `type(x) is int` before)
```

Add a helper so tests do not hand-poke `int.__new__`:

```python
def unknown_enum(enum_cls, value):
    """Produce the forward-compat pseudo-member an unknown Discord value decodes to."""
    return enum_cls(value)     # routes through the shared `_missing_` (D2)
```

Document the semantic change loudly (CONVENTIONS §3): pre-migration an unknown int-enum value was a
bare `int` (`type(x) is int`); post-migration it is an enum pseudo-member
(`isinstance(x, TheEnum)` is now True, `type(x) is int` is now False, but `x == the_int`,
`int(x)`, `str(x)` all still work). Tests that asserted `type(x) is int` on an unknown value must
flip to `isinstance(x, TheEnum)` / value-equality.

### 3.5 `mock_class_namespace` — keep, extend, or fork

Decision hinges on open question §8.1 of [`00-test-strategy.md`](./00-test-strategy.md) (do abstract
bases stay ABCs?). Recommended path (dossier 11 §10.1): **keep abstract wire bases as non-Struct ABCs
and make only concrete leaves frozen Structs.** Under that choice:

- `mock_class_namespace` **survives for the abstract-base tests** (`PartialChannel`, `Guild`, `User`,
  etc.) because those bases remain ABCs with `__abstractmethods__`.
- Every `mock_class_namespace(Abstract)(app=..., **kwargs)` call must **drop `app=`** (the abstract
  base no longer declares it) — a mechanical sweep across the 85 sites.
- The factory-instantiation call `mock_class_namespace(EntityFactoryImpl, slots_=False)(mock_app)`
  (`tests/hikari/impl/test_entity_factory.py:398-401`) is unaffected — `EntityFactoryImpl` is an impl
  class, not a frozen Struct, and still legitimately takes the app/rest client.

If instead abstract bases become frozen Structs, add a sibling `struct_class_namespace` that builds a
concrete leaf via the stub layer plus method overrides, because `type(name, (Struct,), {...})` with
`__slots__=()` + `__abstractmethods__` injection is incompatible with msgspec Struct config
(dossier 11 §1). Present both; recommend the ABC-bases path for minimal helper churn.

### 3.6 `CopyingAsyncMock` — low risk, keep

`CopyingAsyncMock` (`:167-173`) `copy.copy`s call args to snapshot mutable arguments. Frozen structs
still `copy.copy` fine (returns self-equivalent), so it keeps working. No change needed unless a test
relied on the copy producing a **distinct** object for a struct arg — none do (it snapshots
request-body dicts, not entities).

## 4. Step-by-step migration

1. Add `evolve()` to `tests/hikari/hikari_test_helpers.py` (§3.1). No behavior change to existing
   tests; purely additive.
2. Add `unknown_enum()` helper (§3.4) and the `rest`/`cache` fixtures (§3.3).
3. Create `tests/hikari/stubs.py` with the high-churn `make_*` builders (§3.2), each **without** an
   `app` kwarg. Port the four `make_*` helpers currently inline in `test_equality_comparisons.py`.
4. Decide abstract-bases fate (§3.5, open question). If ABCs: sweep the 85 `mock_class_namespace`
   sites to drop `app=`. If Structs: add `struct_class_namespace`.
5. Land this as a standalone "test-helper foundation" PR ahead of the per-module test edits
   (see [`../11-rollout/01-pr-breakdown.md`](../11-rollout/01-pr-breakdown.md)). It touches only
   helper/stub modules, so it can merge before source freezing begins.

## 5. Affected files & symbols

| Path | Symbol / anchor | Change |
|---|---|---|
| `tests/hikari/hikari_test_helpers.py` | new `evolve`, `unknown_enum`; `mock_class_namespace` `:43-81` | add helpers; sweep `app=` out of `mock_class_namespace` call sites |
| `tests/hikari/stubs.py` | new `make_*` builders | create |
| `tests/hikari/integration/test_equality_comparisons.py` | `make_user`/`make_team_member`/`make_guild_member`/`make_known_custom_emoji` `:34-102` | move into `stubs.py`, drop `app=`/`app=mock.Mock()` |
| all `tests/hikari/**` model tests | `mock_class_namespace(...)` (85 sites) | drop `app=` kwarg |

## 6. Risks / gotchas

- **`evolve` on an entity holding a nested list/dict** copies the reference (shallow), matching the
  old shallow-copy behavior — fine, but a test that then mutates the nested list mutates it in the
  "new" struct too. This matches pre-migration shallow-copy semantics; no regression, but do not
  assume deep isolation.
- **`spec_set` on the mock client** must track the real `RESTClient`/`Cache` ABC surface; if a helper
  was moved to a *new* rest method, the mock's `spec_set` must include it or the assertion silently
  passes on a typo. Prefer `spec_set=hikari.api.RESTClient` over a bare `mock.AsyncMock()`.
- **`mock_class_namespace`'s `assert hasattr(klass, attribute)` guard (`:76-77`)** will fail if a test
  still passes `app=` as a namespace attribute after the field is removed — this is actually a useful
  tripwire that surfaces missed `app=` removals.
- **Stub drift.** A stub with stale defaults hides a required-field addition. Keep stubs minimal and
  let msgspec's missing-required-arg `TypeError` at construction catch gaps early.

## 7. Verification

- After step 1-3, the existing suite still passes unchanged (helpers are additive; stubs unused yet).
- A unit test for `evolve` itself: `evolve(make_user(), username="x").username == "x"` and the
  original is untouched.
- A unit test for `unknown_enum`: `unknown_enum(channels.ChannelType, 9999) == 9999` and
  `isinstance(...) is True`.
- Grep gate: no `app=` remains inside `mock_class_namespace(...)` or `make_*` builders after the sweep.

## 8. Open questions / decisions

Cross-linked to [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md):

1. **Abstract bases: ABC vs Struct** (drives §3.5) — recommend ABCs so `mock_class_namespace`
   survives with only an `app=` sweep.
2. **`stubs.py` vs fixtures** — a module of `make_*` functions is more flexible than pytest fixtures
   (composable, override-friendly); recommend functions. Confirm the maintainer prefers this over a
   `conftest.py` fixture set (there is no `conftest.py` today).
3. **How much of the long tail gets a stub** — recommend stubbing only high-churn entities now; the
   rest keep inline literals until they become painful.
