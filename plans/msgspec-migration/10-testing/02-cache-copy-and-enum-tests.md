# Cache Copy Assertions and Enum Tolerance Tests

Purpose: specify the two assertion-level rewrites that frozen structs (constraint (c)) and strict
enums (constraint (b)) force — the ~24 copy/identity assertions in the cache tests that become invalid
or trivially true, and the raise/skip/preserve unknown-value tests plus the new tagged-union
unknown-tag tests. Consumes [`00-test-strategy.md`](./00-test-strategy.md) and
[`01-fixtures-and-helpers.md`](./01-fixtures-and-helpers.md).

## 1. Objective

- (c) Convert cache copy-isolation assertions ("the stored/returned object is a *distinct* copy") to
  value-equality or identity assertions, because a frozen struct is shared by reference and copying is
  removed (see [`../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md`](../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md)).
- (b) Rewrite the three unknown-enum-value strategies (raise / skip / preserve-raw) to the strict-enum
  pseudo-member contract (D2) and add tagged-union unknown-tag tests
  (see [`../05-entity-factory/01-polymorphism-and-tagged-unions.md`](../05-entity-factory/01-polymorphism-and-tagged-unions.md)).

## 2. Current state

### 2.1 Cache copy/identity assertions (constraint (c))

The cache stores **copies** of entities and tests assert the stored/returned object is a distinct
object from the input, and that mutable sub-sequences are re-wrapped as fresh tuples. Inventory
(dossier 07 §10.3, dossier 11 §4):

| Assertion group | Location | Count | What it asserts today |
|---|---|---|---|
| `is not` copy-isolation | `tests/hikari/impl/test_cache.py` | **21** | returned/stored object is a *distinct* copy (of 155 total `assert ... is` identity asserts) |
| `copy.copy` expectation | `tests/hikari/internal/test_cache.py:70-76` | 1 block | `GuildStickerData.build_from_entity` calls `copy.copy(user)` and wraps in `RefCell` |
| `copy`/`assert_not`/`deepcopy` (whole cache) | `tests/hikari/impl/test_cache.py` + `internal/test_cache.py` | **~24 total** | distinctness of returned entities |

Representative — `tests/hikari/impl/test_cache.py:2266-2270`:
```python
assert member_entry.object.role_ids == (65345234, 123123)
assert member_entry.object.role_ids is not member_model.role_ids   # <-- distinctness
assert member_entry.object.guild_avatar_hash == "gay"
assert member_entry.object.guild_banner_hash == "gayge"
assert isinstance(member_entry.object.role_ids, tuple)
```

The `copy.copy` expectation — `tests/hikari/internal/test_cache.py:70-76`:
```python
with mock.patch.object(copy, "copy") as mock_copy:
    with mock.patch.object(cache, "RefCell") as refcell:
        data = cache.GuildStickerData.build_from_entity(mock_sticker)
assert data.user is refcell.return_value
mock_copy.assert_called_once_with(mock_user)          # <-- asserts a per-field copy happened
refcell.assert_called_once_with(mock_copy.return_value)
```

The root cause is the copy engine: `hikari/internal/cache.py:126-127` `CacheMappingView._copy`,
`RefCell.copy` (`:1004`), `copy_guild_channel` (`:1048`), and the ~104 cache copy sites (dossier 07
§3). All of it is deleted once entities are frozen (dossier 07 §10.1).

### 2.2 Unknown-enum-value tests (constraint (b))

Current behavior is **three different strategies**, each pinned by tests
(dossier 11 §3, `tests/hikari/impl/test_entity_factory.py`):

1. **RAISE** — unknown audit-log `action_type` → `errors.UnrecognisedEntityError` (`:1663-1671`):
   ```python
   audit_log_entry_payload["action_type"] = 1000
   with pytest.raises(errors.UnrecognisedEntityError):
       entity_factory_impl.deserialize_audit_log_entry(audit_log_entry_payload, guild_id=...)
   ```
2. **SKIP** — unknown sub-entity types silently dropped from collections:
   `..._action_type_unknown_gets_ignored` (`:1739`), `..._skips_unknown_webhook_type` (`:1748`),
   `..._skips_unknown_thread_type` (`:1768`), `..._skips_unknown_auto_mod_rule_type` (`:1788`).
3. **PRESERVE RAW** — unknown string enum members kept verbatim (`:941`, `:952`): payload
   `"features": ["DISCOVERABLE","FORCE_RELAY"]` →
   `assert own_guild.features == [guild_models.GuildFeature.DISCOVERABLE, "FORCE_RELAY"]`
   (`"FORCE_RELAY"` is not a member and survives as a bare `str`).

Root mechanism — the custom metaclass `hikari/internal/enums.py:154-156`:
```python
def __call__(cls, value: object) -> Enum:
    return cls._value_to_member_map_.get(value, value)   # miss -> return raw value
```
This is why fields are typed `EnumType | int`. The pinned metaclass test —
`tests/hikari/internal/test_enums.py:208-216`:
```python
def test_call_when_not_member(self):
    class Enum(int, enums.Enum):
        foo = 9; bar = 18; baz = 27
    returned = Enum(69)
    assert returned == 69
    assert type(returned) is not Enum        # <-- raw-int fall-through
```

Tests also feed **raw ints straight into strict-enum fields** at construction
(`tests/hikari/internal/test_cache.py:62` `format_type=123`,
`tests/hikari/interactions/test_command_interactions.py:56` `command_type=1`, `:61`
`app_permissions=543123`).

## 3. Target design

### 3.1 Cache copy assertions → identity / value equality

Under frozen structs the cache stores and returns the **same object**; there is no copy. Rewrite
rules:

| Old assertion | New assertion | Rationale |
|---|---|---|
| `x.role_ids is not member_model.role_ids` | `x.role_ids == member_model.role_ids` (or delete) | no copy taken; both reference the same tuple → `is not` is now False. Value-equality preserves the real intent (the data round-trips). |
| `returned is not stored` (distinctness) | `returned is stored` | `get_*` returns the stored frozen struct by reference (dossier 07 §10.1) |
| `isinstance(x.role_ids, tuple)` | **keep** | the entity still normalizes to a tuple at construction; unaffected by copy removal |
| `mock_copy.assert_called_once_with(user)` (`internal/test_cache.py:74`) | delete or rewrite to whatever `*Data`/`RefCell` wiring survives | the per-field `copy.copy` is gone; the `*Data` layer decision (below) determines the replacement |

Example rewrite of `tests/hikari/impl/test_cache.py:2266-2270`:
```python
assert member_entry.object.role_ids == (65345234, 123123)
# removed: assert member_entry.object.role_ids is not member_model.role_ids
assert member_entry.object.guild_avatar_hash == "gay"
assert member_entry.object.guild_banner_hash == "gayge"
assert isinstance(member_entry.object.role_ids, tuple)     # still true if normalization kept
```

The `internal/test_cache.py:70-76` block depends on the `*Data`-layer decision
(see [`../04-frozen-and-cache/01-cache-data-layer-and-mutation.md`](../04-frozen-and-cache/01-cache-data-layer-and-mutation.md)):
- If `*Data` is **kept as a mutable carrier** wrapping a frozen struct and still holds a
  `RefCell[User]`, the test keeps a `RefCell` assertion but **drops the `copy.copy` assertion** (the
  user struct is frozen, no defensive copy needed): assert `data.user is refcell.return_value` and
  `refcell.assert_called_once_with(mock_user)` (no `mock_copy`).
- If `*Data` is **dropped** and the frozen struct is stored directly with mutation moved to
  `RefCell`, delete this test and re-point coverage at the new set/get path.

The 21 `is not` flips in `impl/test_cache.py` are found by grepping `\bis not\b` within that file and
filtering to entity-field comparisons (exclude `is not None`).

### 3.2 Strict-enum unknown-value contract in tests

Per D2, the custom enums are **kept** (not ported to stdlib) and, with PR hikari-py/hikari#2770,
unknown values decode to a **value-preserving `is_unknown` pseudo-member**: the shared `dec_hook`
routes the field to the custom `Enum`/`Flag.__call__`, which returns a pseudo-member **instance** that
msgspec accepts (the hook's result must be an instance of the annotated type). The three legacy
strategies map onto the new contract by **dispatch kind**, which the entity_factory plan splits into
scalar tolerance vs polymorphic dispatch (CONVENTIONS §3):

| Legacy behavior | Field/context | New contract | Test rewrite |
|---|---|---|---|
| RAISE (`action_type=1000`) | polymorphic dispatch on a discriminator (audit entry, channel, thread, interaction, auto-mod, scheduled event) | tagged union raises on unknown **tag** — behavior preserved (CONVENTIONS §3) | keep `pytest.raises(...)` but expect the new error type (see §3.3) |
| SKIP (`skips_unknown_webhook_type/thread_type/auto_mod_rule_type`, `action_type_unknown_gets_ignored`) | soft-skip in a collection (components in action rows/containers, some audit entries) | `msgspec.Raw` peek-then-dispatch prepass retains the skip; unknown sub-entity dropped from the collection | keep the test; assert the unknown item is absent and known items survive |
| PRESERVE RAW (`features == [..., "FORCE_RELAY"]`) | scalar str-enum field in a list | pseudo-member: `"FORCE_RELAY"` decodes to a `GuildFeature` pseudo-member that `== "FORCE_RELAY"` | change the assertion (below) |

The PRESERVE-RAW test rewrite — `tests/hikari/impl/test_entity_factory.py:941-952`:
```python
# BEFORE
assert own_guild.features == [guild_models.GuildFeature.DISCOVERABLE, "FORCE_RELAY"]
# AFTER (pseudo-member is value-equal to the raw string, but is now a GuildFeature)
assert own_guild.features == [guild_models.GuildFeature.DISCOVERABLE, guild_models.GuildFeature("FORCE_RELAY")]
assert own_guild.features[1] == "FORCE_RELAY"                     # still value-equal
assert isinstance(own_guild.features[1], guild_models.GuildFeature)   # NEW: was a bare str before
```

Scalar-tolerance unknown-value tests (the ones NOT on a dispatch discriminator, e.g. an unknown
`GuildVerificationLevel`, `MessageType`, `StickerFormatType`) must **stop expecting a bare int** and
expect a pseudo-member:
```python
# unknown int decodes to a value-preserving pseudo-member
v = entity_factory_impl.deserialize_sticker(payload_with_format_type_999)
assert v.format_type == 999
assert int(v.format_type) == 999
assert isinstance(v.format_type, stickers.StickerFormatType)     # NEW
# was: assert v.format_type == 999 and type(...) is int
```

Construction-time int literals (`format_type=123`, `command_type=1`, `app_permissions=543123`) still
**construct** fine (msgspec does not validate on `__init__`, dossier 11 §5) — but downstream
`.name`/identity/`is`-comparisons break. Two fixes:
- feed a real member or pseudo-member via `unknown_enum(cls, value)`
  (see [`01-fixtures-and-helpers.md`](./01-fixtures-and-helpers.md) §3.4) instead of a raw int; or
- if the test only needs value-equality, assert `== value` and `isinstance(..., cls)` rather than
  `type(...) is int`.

### 3.3 `internal/test_enums.py` update (1308 lines)

The custom metaclass is **kept** and modified by PR hikari-py/hikari#2770 (pseudo-member-on-miss
`__call__`, `is_unknown`, wrong-type `TypeError`) — it is **not** removed, so the machinery tests are
**updated in place**, not deleted-because-the-metaclass-is-gone (dossier 11 §5b, §10.3):

| Test / group | Fate | Reason |
|---|---|---|
| `test_call_when_not_member` (`:208-216`) | rewrite | #2770's `__call__` no longer returns a raw int; assert `cls(69) == 69`, `int(cls(69)) == 69`, `isinstance(cls(69), cls)`, `cls(69).is_unknown` (pseudo-member instance) |
| `test_call_when_member` (`:200-207`) | keep | member lookup is unchanged |
| `_value_to_member_map_` / `test_cache` / `test_cache_when_temp_values_over_MAX_CACHED_MEMBERS` | **keep** (extend) | the bounded `_temp_members_` cache stays; #2770 extends the same temp-member path to `Enum` (cap `_MAX_CACHED_MEMBERS`, `enums.py:39`) — the cache tests keep exercising it |
| `__call__` / metaclass internals tests | keep (adapt to #2770) | the metaclass stays; update expectations to the pseudo-member-on-miss behavior |
| `TestFlag`/`TestIntFlag` set-API tests (`.all/.any/.none/.split/.difference/…`) | **keep unchanged** | the custom `Flag` and its ~20-method set-API are kept as-is (`enums.py:683-829`) — no IntFlag port |
| `test_deprecated` (`:1283`) | keep only if `deprecated` aliasing survives | the machinery is currently unused by concrete enums; drop if removed (Q3) |

New tests to add for the #2770 strict-enum contract:
- `cls(unknown)` returns an `is_unknown` pseudo-member that is `== unknown`, `int(x)`/`str(x)` work,
  `isinstance(x, cls)` True, `type(x) is not int/str`.
- wrong-type input raises: `cls("wrong")` on an int-enum raises `TypeError` (the `__objtype__` guard).
- custom `Flag` unknown-bit preservation (lossless forward-compat) — feed a bitmask with an undefined
  bit and assert it round-trips and `is_unknown` is True.
- `msgspec.json.decode(b'999', type=SomeIntEnum, dec_hook=dec_hook)` produces the pseudo-member — the
  hook routes `999` to `SomeIntEnum(999)` and msgspec accepts the returned instance (empirically
  verified, dossier 15; see [`../12-appendices/02-custom-enum-feasibility.md`](../12-appendices/02-custom-enum-feasibility.md)
  and [`../02-enums/02-int-and-str-enums-migration.md`](../02-enums/02-int-and-str-enums-migration.md)).

### 3.4 Tagged-union unknown-tag tests (new)

Where polymorphism moves to msgspec tagged unions, the RAISE behavior is preserved (an unknown tag
raises) and the SOFT-SKIP behavior needs a `Raw` peek prepass
(see [`../05-entity-factory/01-polymorphism-and-tagged-unions.md`](../05-entity-factory/01-polymorphism-and-tagged-unions.md)).
Tests:

```python
# RAISE-on-unknown-tag (channels, threads, interactions, auto-mod, scheduled events,
# audit action_type): decoding an unrecognised discriminator raises.
def test_deserialize_channel_unknown_type_raises():
    payload["type"] = 9999
    with pytest.raises(<UnrecognisedEntityError or msgspec.ValidationError>):
        entity_factory_impl.deserialize_channel(payload)

# SOFT-SKIP (components in action rows, some audit entries): the unknown item is dropped,
# known siblings survive.
def test_deserialize_action_row_skips_unknown_component_type():
    row = entity_factory_impl.deserialize_component(action_row_with_one_unknown_child)
    assert [type(c) for c in row.components] == [components.ButtonComponent]   # unknown dropped
```

The **error-type decision** is a maintainer call: keep `errors.UnrecognisedEntityError` (wrap
msgspec's `ValidationError` at the dispatch boundary to preserve the public exception) or expose
`msgspec.ValidationError`. Recommend wrapping to keep the public contract; assert the wrapped type in
tests. Cross-link [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md).

## 4. Step-by-step migration

1. Land after the cache freeze/copy-removal source PRs
   (see [`../11-rollout/01-pr-breakdown.md`](../11-rollout/01-pr-breakdown.md)); the assertions can
   only be flipped once `get_*`/`set_*` stop copying.
2. In `tests/hikari/impl/test_cache.py`: grep `\bis not\b`, filter to entity-field comparisons, flip
   the 21 copy-isolation asserts to `==` or `is` per §3.1; convert entity-field mutations to `evolve`.
3. In `tests/hikari/internal/test_cache.py`: rewrite the `:70-76` `copy.copy` expectation per the
   `*Data`-layer decision.
4. In `tests/hikari/impl/test_entity_factory.py`: rewrite the RAISE test (`:1663`), the four
   `skips_unknown_*` tests (`:1739/1748/1768/1788`), and the PRESERVE-RAW test (`:952`) to §3.2/§3.4;
   audit every unknown-value assert for `type(...) is int` and flip to pseudo-member checks.
5. In `tests/hikari/internal/test_enums.py`: apply the §3.3 table; add the new strict-enum and
   custom Flag unknown-bit preservation tests.
6. Add the tagged-union unknown-tag tests (§3.4) alongside the factory polymorphism migration.
7. Audit construction-time int literals feeding enum fields across the suite and fix per §3.2.

## 5. Affected files & symbols

| Path | Anchor | Change |
|---|---|---|
| `tests/hikari/impl/test_cache.py` | 21 `is not` asserts (e.g. `:2267`); entity-field mutations | flip to `==`/`is`; `evolve` |
| `tests/hikari/internal/test_cache.py` | `:62` (`format_type=123`), `:70-76` (`copy.copy`) | pseudo-member ctor / rewrite copy expectation |
| `tests/hikari/impl/test_entity_factory.py` | `:952` preserve, `:1663` raise, `:1739/1748/1768/1788` skip | rewrite to strict-enum + tagged-union contract |
| `tests/hikari/internal/test_enums.py` | `:200-216` call tests; `_value_to_member_map_`/cache tests; `TestIntFlag`; `:1283` deprecated | heavy rewrite per §3.3 |
| `tests/hikari/interactions/test_command_interactions.py` | `:56` `command_type=1`, `:61` `app_permissions=543123` | pseudo-member / value-equality |

## 6. Risks / gotchas

- **`is not` false-negatives.** A blind `is not` → `==` flip on a line that was actually
  `is not None` would change meaning. Filter mechanically: only flip comparisons between two entity
  fields / a field and a stored input, never `is not None`.
- **Pseudo-member equality is value-based but type-changed.** `pseudo == raw` holds, but
  `type(pseudo) is int` is now False. Any test asserting the exact type (not value) of an unknown enum
  value must flip to `isinstance`.
- **Skip-semantics require a `Raw` prepass.** If the entity_factory migration does a naive tagged-union
  decode without the peek prepass, the four `skips_unknown_*` tests will start *raising* instead of
  skipping — a behavior regression. The tests are the guard; do not weaken them to `pytest.raises`
  unless the maintainer intentionally drops soft-skip (CONVENTIONS §3 says preserve it).
- **`copy` mock removal.** `internal/test_cache.py:70-76` patches the module-level `copy`; once the
  cache no longer imports/uses `copy`, patching `copy.copy` there patches a no-longer-called function
  and the assertion fails as "not called". Rewrite, do not just delete the patch context.

## 7. Verification

- `tests/hikari/impl/test_cache.py` green with the flipped asserts; a targeted check that
  `cache.get_role(id) is cache.get_role(id)` (same frozen object returned, no copy) holds under the
  new implementation, confirming the `is not` → `is` direction was correct (dossier 07 §10.1,
  open question 6).
- Round-trip test: `msgspec.json.decode(payload, type=Guild).features` contains a pseudo-member for an
  unknown feature string that `== "FORCE_RELAY"` and `isinstance(..., GuildFeature)`.
- The four `skips_unknown_*` tests still assert the unknown item is absent and known siblings survive.
- The RAISE tests raise the agreed public error type at the dispatch boundary.
- `internal/test_enums.py` covers: member lookup, `is_unknown` pseudo-member minting/equality/`int()`/
  `str()`, wrong-type `TypeError`, custom `Flag` unknown-bit round-trip, and the (unchanged) custom
  `Flag` set-API.

## 8. Open questions / decisions

Cross-linked to [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md):

1. **Unknown-tag error type** — wrap msgspec `ValidationError` as `errors.UnrecognisedEntityError`
   (recommended, preserves public contract) or surface `ValidationError`? Determines the
   `pytest.raises(...)` target in the RAISE tests.
2. **Pseudo-member cache tested** — #2770 keeps the bounded `_temp_members_` cache
   (`_MAX_CACHED_MEMBERS`, `enums.py:39`) and extends it to `Enum`; keep the existing cache tests (they
   still exercise the same mechanism). See SD2.
3. **`*Data` layer fate** — decides whether `internal/test_cache.py:70-76` keeps a `RefCell` assertion
   (mutable `*Data` carrier) or is deleted (frozen struct stored directly). See
   [`../04-frozen-and-cache/01-cache-data-layer-and-mutation.md`](../04-frozen-and-cache/01-cache-data-layer-and-mutation.md).
4. **Soft-skip preserved?** Confirm the maintainer keeps soft-skip for components/audit sub-entities
   (CONVENTIONS §3) so the four `skips_unknown_*` tests stay skip-not-raise.
