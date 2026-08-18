# Polls

Purpose: migrate `hikari/polls.py` — 1 enum and 5 **unhashable value objects** (`PollMedia`,
`PollAnswer`, `PollResult`, `PollAnswerCount`, `Poll`). None subclass `snowflakes.Unique` and none carry
an `app` field. The defining constraints are the deliberate non-hashability (class-level `hash=False`),
the polymorphic `emoji` on `PollMedia`, the nullable `expiry`, and the `answer_counts` sequence on
`PollResult`.

--------------------------------------------------------------------------------------------------

## 1. Objective

- Freeze the 5 poll Structs while **preserving their non-hashable contract** (conventions §2: "Poll value
  objects are currently `hash=False` — keep them non-hashable"). No `app` field exists to remove.
- Port `PollLayoutType` to stdlib (`int, enum.Enum`).
- Preserve the polymorphic `PollMedia.emoji`, the nullable `Poll.expiry`, and the `answer_counts`
  sequence.

Decode classification: `Poll` and `PollMedia` are **T** (the polymorphic `emoji`, the nullable `expiry`
datetime, and the residual `deserialize_poll` traversal). `PollAnswer`, `PollResult`, `PollAnswerCount`
are **D** (flat scalars + nested Structs, no transform).

--------------------------------------------------------------------------------------------------

## 2. Current state (file:line anchors)

### 2.1 Enum
`PollLayoutType(int, enums.Enum)` `polls.py:91` (DEFAULT=1).

### 2.2 Value objects (all `weakref_slot=False`, all effectively unhashable)
- `PollMedia` `polls.py:42` — `@attrs.define(hash=False)`; `text: str | None = None` `:45`,
  `emoji: emojis.Emoji | None = None` `:48`.
- `PollAnswer` `polls.py:54` — `@attrs.define(hash=False)`; `answer_id: int` `:57`,
  `poll_media: PollMedia` `:60`.
- `PollResult` `polls.py:66` — `@attrs.define(hash=False)`; `is_finalized: bool` `:69`,
  `answer_counts: Sequence[PollAnswerCount]` `:72`.
- `PollAnswerCount` `polls.py:78` — `@attrs.define(hash=False)`; `id: int` `:81`, `count: int` `:84`,
  `me_voted: bool` `:87`.
- `Poll` `polls.py:99` — `@attrs.define(kw_only=True, repr=True)` (**no** `hash=False`, but **no**
  `unsafe_hash` either → mutable-eq class → `__hash__` is `None`, i.e. also unhashable); `question:
  PollMedia` `:103`, `answers: Sequence[PollAnswer]` `:106`, `expiry: datetime | None` `:109`,
  `allow_multiselect: bool` `:112`, `layout_type: PollLayoutType` `:115`, `results: PollResult | None`
  `:118`.

Factory: `deserialize_poll` (`entity_factory.py:4724`) — builds `answers`, `PollMedia` (text + optional
emoji), nullable `expiry`, and optional `results` with `answer_counts`. Dossier 05 §4 flags a
shadowing bug-magnet: the inner comprehension reuses the name `payload` (`:4744-4745`).

--------------------------------------------------------------------------------------------------

## 3. Target design

### 3.1 Enum → stdlib
`PollLayoutType` → `int, enum.Enum` + `_missing_`. (No `| int` union on `Poll.layout_type` today — already
strict-typed.)

### 3.2 Frozen + non-hashable value objects
```python
class PollMedia(msgspec.Struct, frozen=True, kw_only=True):     # T (polymorphic emoji)
    __hash__ = None                                             # preserve unhashable contract
    text: str | None = None
    emoji: emojis.CustomEmoji | emojis.UnicodeEmoji | None = None

class PollAnswer(msgspec.Struct, frozen=True, kw_only=True):    # D
    __hash__ = None
    answer_id: int
    poll_media: PollMedia

class PollAnswerCount(msgspec.Struct, frozen=True, kw_only=True):   # D
    __hash__ = None
    id: int
    count: int
    me_voted: bool

class PollResult(msgspec.Struct, frozen=True, kw_only=True):    # D
    __hash__ = None
    is_finalized: bool
    answer_counts: typing.Sequence[PollAnswerCount] = ()

class Poll(msgspec.Struct, frozen=True, kw_only=True):          # T (expiry, nested media)
    __hash__ = None
    question: PollMedia
    answers: typing.Sequence[PollAnswer] = ()
    expiry: datetime.datetime | None = None
    allow_multiselect: bool
    layout_type: PollLayoutType
    results: PollResult | None = None
```
- **Non-hashability under frozen (the key tension).** `frozen=True` makes msgspec auto-generate a
  `__hash__` over all fields. For the scalar-only `PollAnswerCount` that would *newly* make it hashable
  (a behaviour change); for `Poll`/`PollResult`/`PollMedia` (which hold sequences/nested objects) the
  generated `__hash__` would raise `TypeError` at hash time — same net effect as today, but a different
  failure mode (runtime vs immediate `TypeError` on `hash(x)`). To preserve the current contract exactly
  (`__hash__ is None` → immediate unhashable), set `__hash__ = None` in each class body.
  **VERIFY (extends conventions §2):** that msgspec permits `frozen=True` together with an explicit
  `__hash__ = None` (immutability retained, object stays unhashable). If msgspec rejects it, fall back to
  accepting msgspec's generated `__hash__` and document the behaviour change for `PollAnswerCount`.
- Value objects are not `Unique` and are non-hashable → do **not** use them as dict keys anywhere (grep
  to confirm; they are only ever list elements / nested fields today).

### 3.3 Polymorphic `PollMedia.emoji` and nullable `expiry` (T)
- `PollMedia.emoji` is a `CustomEmoji` when it carries an `id`, else a `UnicodeEmoji` — discriminated by
  **key presence**, not a tag field, so it is a residual dispatch
  (`03-emojis-and-files-resources.md`, `../05-entity-factory/02-hard-cases-and-transforms.md`).
- `Poll.expiry` is a nullable RFC3339 datetime (native msgspec decode; `T | None`) — the one non-scalar
  on `Poll` besides the nested media.
- `answer_counts` is built from the `results.answer_counts` array; keep it a plain `Sequence`
  (`tuple`/`list`) — the residual `deserialize_poll` populates it.

### 3.4 Fix the `payload` shadowing while transforming
When rewriting `deserialize_poll` into the residual transform, rename the inner-comprehension `payload`
(`entity_factory.py:4744-4745`) to avoid the documented shadowing bug-magnet (dossier 05 §4).

--------------------------------------------------------------------------------------------------

## 4. Step-by-step migration

1. Port `PollLayoutType` to stdlib.
2. Convert the 5 value objects to frozen Structs, each with `__hash__ = None` (VERIFY msgspec accepts it).
3. Wire `PollMedia.emoji` as the polymorphic union (residual key-presence dispatch); keep `Poll.expiry`
   nullable-native; keep `answer_counts` as a sequence.
4. Rewrite `deserialize_poll` as the residual transform; rename the shadowing inner `payload`.

--------------------------------------------------------------------------------------------------

## 5. Affected files & symbols

| Path / anchor | Change |
|---|---|
| `hikari/polls.py:91` (`PollLayoutType`) | → stdlib |
| `hikari/polls.py:42-49` (`PollMedia`) | frozen; `__hash__=None`; polymorphic `emoji` (**T**) |
| `hikari/polls.py:54-88` (`PollAnswer`/`PollResult`/`PollAnswerCount`) | frozen; `__hash__=None` (**D**) |
| `hikari/polls.py:99-119` (`Poll`) | frozen; `__hash__=None`; nullable `expiry`; nested media (**T**) |
| `hikari/impl/entity_factory.py:4724-…` (`deserialize_poll`) | residual transform; rename shadowing `payload` |
| `../05-entity-factory/02-hard-cases-and-transforms.md` | polymorphic emoji, nullable expiry |
| `03-emojis-and-files-resources.md` | `CustomEmoji`/`UnicodeEmoji` reference types |

--------------------------------------------------------------------------------------------------

## 6. Risks / gotchas

1. **Non-hashability under frozen.** msgspec generates `__hash__` for frozen Structs; preserving the
   `hash=False` contract needs an explicit `__hash__ = None` per class. VERIFY msgspec allows this
   combination; otherwise `PollAnswerCount` silently becomes hashable and the sequence-holding structs
   raise at hash time instead of immediately.
2. **Polymorphic `emoji`** by `id` presence — a residual dispatch, not a tagged union.
3. **`payload` shadowing** in the current comprehension (`entity_factory.py:4744-4745`) is a latent bug;
   fix it during the transform rewrite.
4. **No `app`, no snowflake identity** — these are pure value records; do not add `Unique` or object
   identity by accident.

--------------------------------------------------------------------------------------------------

## 7. Verification

- Decode a `Poll` with `results` → `answer_counts` is a sequence of `PollAnswerCount`; with no `results`
  → `results is None`.
- Decode a `Poll` with a set expiry → `expiry` is a tz-aware datetime; with `null`/absent → `None`.
- Decode a `PollMedia` with a custom emoji (`id` present) → `emoji` is `CustomEmoji`; unicode →
  `UnicodeEmoji`; absent → `None`.
- `hash(poll)` / `hash(poll_media)` raise `TypeError` (unhashable preserved); the objects are immutable
  (frozen).
- Strict enum: unknown `layout_type` int → pseudo-member.

--------------------------------------------------------------------------------------------------

## 8. Open questions / decisions

Cross-link `../00-overview/05-decisions-log.md`:
- **VERIFY** `frozen=True` + explicit `__hash__ = None` yields an immutable, unhashable msgspec Struct
  (extends the conventions §2 value-object hashing decision). If unsupported, accept the generated
  `__hash__` and document `PollAnswerCount` becoming hashable.
- **Polymorphic `emoji`** transform location — `../05-entity-factory/02-hard-cases-and-transforms.md`.
- No `app`, no tri-state `UNDEFINED` fields in this module.
