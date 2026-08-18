# Emojis and the files.Resource family

Purpose: migrate `hikari/emojis.py` (`Emoji` ABC, `UnicodeEmoji`, `CustomEmoji`, `KnownCustomEmoji`)
and settle the cross-cutting **`files.Resource` multiple-inheritance hazard** — the single sharpest
edge in the model migration, where several wire models are simultaneously data records **and**
`files.Resource` subclasses (Struct + non-Struct ABC mixin). This file owns the emoji classes and the
Resource design decision; the concrete data-carrying Resource subclasses in other modules
(`messages.Attachment`, `components.MediaResource`, `embeds.EmbedImage`/`EmbedVideo`) reference the
decision made here.

--------------------------------------------------------------------------------------------------

## 1. Objective

- Keep `UnicodeEmoji(str, Emoji)` a `str` subclass; route it through the global `dec_hook`.
- Freeze `CustomEmoji` / `KnownCustomEmoji` as app-less Structs with id-only identity, preserving the
  `Emoji`/`WebResource` behavior (twemoji/CDN URL, `mention`, `filename`).
- Remove `KnownCustomEmoji.app` (1 declaration) — this module has **0** `self.app` helper methods, so
  app removal is field-only (no helper fallout).
- Decide how a frozen `msgspec.Struct` can also be a `files.Resource` (abstract-property + slots
  clash) and apply it to the emoji classes and the four data-carrying Resource subclasses elsewhere.
- Confirm `files.*` reader/stream classes stay **mutable, non-Struct** (they hold live handles).

Decode classification: `UnicodeEmoji` is a scalar hook; `CustomEmoji`/`KnownCustomEmoji` are **T**
(emoji is discriminated by **presence of `id`**, not a tag field — `deserialize_emoji`,
`entity_factory.py:2015`) and `KnownCustomEmoji` re-keys `role_ids` and nests a `user`.

--------------------------------------------------------------------------------------------------

## 2. Current state (file:line anchors)

### 2.1 emojis.py
- `Emoji(files.WebResource, abc.ABC)` — `emojis.py:48-102`; `__slots__=()`; abstract `name`
  (`:59-62`), `url` (`:64-68`), `url_name` (`:70-73`), `mention` (`:75-78`); concrete `parse`
  classmethod (`:80-102`) dispatching custom-vs-unicode by `<…>` wrapping.
- `UnicodeEmoji(str, Emoji)` — `emojis.py:105-227`; **`str` subclass, not attrs**. `name`/`url_name`/
  `mention` return `self` (`:126-141`); computed `codepoints` (`:143-147`), `filename` (twemoji PNG
  rule incl. the `0xFE0F` variation-selector edge case, `:149-166`), `url` (twemoji CDN, `:168-189`),
  `unicode_escape`; classmethods `parse_codepoints`/`parse_unicode_escape`/`parse`.
- `CustomEmoji(snowflakes.Unique, Emoji)` — `emojis.py:230-329`; `@attrs_extensions.with_copy` +
  `@attrs.define(unsafe_hash=True, kw_only=True, weakref_slot=False)`; `# noqa: PLW1641 - No __hash__`.
  Fields `id: Snowflake` (`hash=True`), `name: str`, `is_animated: bool`. Custom `__str__`→`mention`
  (`:265-267`), custom `__eq__` (`:269-274`, by `id`, guarded to `CustomEmoji`), computed `filename`
  (`:276-279`), `url_name` (`:281-285`), `mention` (`:287-291`), `url` (CDN, `:293-299`), `parse`
  classmethod using `_CUSTOM_EMOJI_REGEX` (`emojis.py:45`).
- `KnownCustomEmoji(CustomEmoji)` — `emojis.py:332-379`; adds `app: traits.RESTAware`
  (`:343-345`, `SKIP_DEEP_COPY`), `guild_id: Snowflake | None`, `role_ids: Sequence[Snowflake]`,
  `user: users.User | None`, `is_colons_required`/`is_managed`/`is_available: bool`.

### 2.2 files.py Resource family (dossier 09 §8)
- `Resource(abc.ABC, Generic[ReaderImplT])` — `files.py:425-555`; `__slots__=()`; abstract `url`
  (`:435-438`) and `filename` (`:440-443`); concrete `extension`/`read`/`save`/`stream`, `__str__`,
  `__eq__` (by url), `__hash__` (`(cls, url)`).
- `WebResource(Resource[WebReader], abc.ABC)` — `files.py:669-756`.
- Reader/stream classes (attrs, mutable, hold live handles): `AsyncReader` (`:337`), `WebReader`
  (`:563`), `ThreadedFileReader` (`:807`), `IteratorReader` (`:976`) + context-manager impls.
- **Data-carrying Resource subclasses in other modules** (the hazard set):
  `messages.Attachment(snowflakes.Unique, files.WebResource)` (`messages.py:269`) with `url: str`
  (`:281`) and `filename: str` (`:284`) as **fields**; `components.MediaResource(files.Resource[…])`
  (`components.py:407`); `embeds.EmbedResource`/`EmbedResourceWithProxy`/`EmbedImage`/`EmbedVideo`
  (`embeds.py:56/99/139/162`). `pyproject.toml:180` documents the friction:
  `reportIncompatibleVariableOverride = "none"  # Cannot overwrite abstract properties using attrs`.

--------------------------------------------------------------------------------------------------

## 3. Target design

### 3.1 UnicodeEmoji — unchanged str subclass, add hook

```python
if type_ is emojis.UnicodeEmoji:
    return emojis.UnicodeEmoji(obj)          # obj is the JSON str; str subclass, methods intact
# encode: str subclass encodes natively -> no enc_hook
```

Type reaction/tag emoji fields as `UnicodeEmoji` where the value has no `id`
(`entity_factory.py:1431,1449,1698,1716`). All computed props (`filename`, `url`, `codepoints`,
`mention`) port verbatim — they read `self`, no `app`.

### 3.2 CustomEmoji / KnownCustomEmoji → frozen Structs (app-less)

```python
class CustomEmoji(snowflakes.Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    id: snowflakes.Snowflake
    name: str
    is_animated: bool                        # field(name="animated") if decoded declaratively
    # __eq__/__hash__: keep the custom by-id __eq__ (emojis.py:269-274) OR rely on inherited Unique;
    # NOTE the custom __eq__ accepts ONLY CustomEmoji (not subclasses) — see risk 4.
    def __str__(self): return self.mention   # verbatim
    @property
    def filename(self): ...                  # verbatim
    # url_name / mention / url properties verbatim; parse classmethod verbatim

class KnownCustomEmoji(CustomEmoji, frozen=True, kw_only=True, eq=False):
    # NO app field.
    guild_id: snowflakes.Snowflake | None
    role_ids: typing.Sequence[snowflakes.Snowflake]      # array; declarative list, not re-keyed
    user: users.User | None
    is_colons_required: bool                 # field(name="require_colons")
    is_managed: bool                         # field(name="managed")
    is_available: bool                       # field(name="available")
```

- Drop `with_copy`; frozen ⇒ copy machinery dead (D8).
- `app` field removed; **no helper methods reference `self.app`** in this module (grep: 0), so nothing
  else changes — the removal is purely the field + the factory `app=self._app` site
  (`entity_factory.py:2002`).
- Identity: keep `Unique` + `eq=False`. `CustomEmoji` currently hand-writes `__eq__` (by id) — either
  keep that method (it is compatible with `eq=False`, msgspec won't overwrite it) or delete it and
  rely on `Unique.__eq__`. Prefer **keeping** the hand-written `__eq__` only if its `CustomEmoji`-only
  guard is intentional; otherwise `Unique.__eq__` (which checks `isinstance(other, type(self))`) is
  the cleaner inherited path. See risk 4.

### 3.3 The Resource multiple-inheritance decision (applies module-wide)

Two structurally different sub-cases:

| Sub-case | Classes | Nature of `url`/`filename` |
|---|---|---|
| **Computed** | `UnicodeEmoji`, `CustomEmoji`, `KnownCustomEmoji` | `url`/`filename` are **@property** computed from `self`/fields → no field/property clash |
| **Data** | `messages.Attachment`, `components.MediaResource`, `embeds.EmbedImage`/`EmbedVideo` | `url`/`filename` are **attrs fields** that satisfy the abstract properties → the field IS the property |

- **Computed sub-case (emojis):** the only question is whether a `msgspec.Struct` may inherit a
  non-Struct ABC (`Emoji`/`WebResource`) that declares `__slots__=()`, abstract properties, and
  concrete methods but **no data fields**. msgspec permits non-Struct mixin bases provided they add no
  fields; the abstract `url`/`filename` are satisfied by the subclass's `@property`, and `read`/`save`/
  `stream` are inherited methods. **VERIFY** (see §7) that `class E(Emoji, msgspec.Struct, frozen=True)`
  builds without a slots/MRO error and that `isinstance(e, files.Resource)` holds so emojis remain
  usable as upload attachments.
- **Data sub-case (Attachment et al.):** a Struct **field** named `url` must override an inherited
  abstract **property** `url`. msgspec Struct fields are slot descriptors; an inherited abstract
  property with the same name is a data descriptor on a base class, and Python resolves the subclass
  slot first — but this is exactly the edge `pyproject.toml:180` had to silence for attrs.
  **Recommended resolution:** demote `Resource`/`WebResource` from an enforced `abc.ABC` with abstract
  properties to a **`typing.Protocol` (runtime-checkable) or a plain mixin** whose `url`/`filename`
  are ordinary (non-abstract) attributes, so a Struct field cleanly provides them with no
  abstract-override or slots conflict. The concrete data subclasses then declare `url: str` /
  `filename: str` as normal Struct fields and gain `read`/`save`/`stream`/`extension` from the mixin.
  This keeps the "any Attachment/Emoji is uploadable" contract while removing the ABC friction. The
  final choice is a maintainer decision (see the files plan file and
  `../00-overview/05-decisions-log.md`); this module implements whichever is chosen for the emoji
  computed sub-case.

### 3.4 files.* readers stay mutable, non-Struct

`AsyncReader`/`WebReader`/`ThreadedFileReader`/`IteratorReader` and the context-manager impls hold
live `aiohttp.StreamReader`/`BinaryIO` handles and are **mutable runtime plumbing, not wire data**
(dossier 09 §8.2). Constraint (c) does **not** apply: they stay attrs (or become plain classes),
never frozen Structs. `URL`/`File`/`Bytes` (`files.py:760/871/1056`) are plain-slots classes, never
JSON-decoded — leave as-is.

--------------------------------------------------------------------------------------------------

## 4. Step-by-step migration

1. Register the `UnicodeEmoji` scalar hook (`../01-foundations/02-custom-scalar-types-and-hooks.md`).
2. Settle the Resource decision (§3.3) with the files plan author; for emojis, confirm the
   computed-sub-case VERIFY passes (Struct + `Emoji` ABC mixin).
3. Convert `CustomEmoji` → frozen Struct: keep `id`/`name`/`is_animated`, port all computed props and
   `parse`; decide `__eq__` (keep hand-written or inherit `Unique`).
4. Convert `KnownCustomEmoji` → frozen Struct: drop `app` field, add `field(name=...)` for
   `require_colons`/`managed`/`available`, keep `role_ids` as a plain list, nest `user`.
5. Update `deserialize_emoji`/`deserialize_known_custom_emoji` (`entity_factory.py:2015/1989`) to drop
   `app=self._app`; keep the id-presence discriminator (custom-vs-unicode) as a residual **T**.
6. Leave `files.*` readers untouched (or de-attrs to plain classes independently).

--------------------------------------------------------------------------------------------------

## 5. Affected files & symbols

| Path / anchor | Change |
|---|---|
| `hikari/emojis.py:105-227` | `UnicodeEmoji` unchanged type; add dec_hook |
| `hikari/emojis.py:230-329` | `CustomEmoji` attrs → frozen Struct; drop `with_copy`; keep props/parse |
| `hikari/emojis.py:332-379` | `KnownCustomEmoji` → frozen Struct; drop `app`; key renames |
| `hikari/files.py:425-555,669-756` | `Resource`/`WebResource`: ABC → Protocol/mixin decision (data sub-case) |
| `hikari/files.py:337,563,807,976` | reader classes stay mutable non-Struct |
| `hikari/impl/entity_factory.py:1989,2002,2015` | drop `app`; keep id-presence discriminator |
| `hikari/messages.py:269`, `hikari/components.py:407`, `hikari/embeds.py:56-162` | data-carrying Resource subclasses apply §3.3 (owned by `06-messages.md`/`08-components.md`/`07-embeds.md`) |

--------------------------------------------------------------------------------------------------

## 6. Risks / gotchas

1. **Struct + non-Struct ABC mixin (the headline hazard).** Emojis inherit `Emoji`→`WebResource`→
   `Resource` (all ABCs). If msgspec rejects a Struct with a non-Struct ABC base, the emoji classes
   need the Protocol/mixin demotion (§3.3) too, not just the data sub-case. VERIFY before committing.
2. **Field-overrides-abstract-property (Attachment/MediaResource/EmbedImage/EmbedVideo).** The data
   sub-case is the reason `reportIncompatibleVariableOverride` is disabled today; msgspec may be
   stricter than attrs. The Protocol/mixin demotion is the safe path.
3. **`UnicodeEmoji` as an upload attachment** relies on being a `files.WebResource`; the twemoji
   `url`/`filename` must still resolve after the Resource redesign (dossier 09 risk 9).
4. **`CustomEmoji.__eq__` guard is `CustomEmoji`-only** (`emojis.py:271`), so today a `KnownCustomEmoji`
   compares equal to a `CustomEmoji` with the same id (isinstance passes). `Unique.__eq__` uses
   `isinstance(other, type(self))`, which is asymmetric across the subclass — decide deliberately
   whether to keep the looser hand-written `__eq__` or adopt `Unique`'s stricter one (behavior change).
5. **`role_ids` is a plain array**, not a re-keyed Mapping — declarative list decode, no transform
   (contrast guild `roles`).
6. **`KnownCustomEmoji.user`** nests a `users.User` (dependency on `02-users.md` landing first).

--------------------------------------------------------------------------------------------------

## 7. Verification

- **Emoji-as-Struct VERIFY:** build `class KnownCustomEmoji(CustomEmoji, msgspec.Struct, frozen=True,
  kw_only=True, eq=False)` and assert construction, immutability, `isinstance(e, files.Resource)`, and
  that `e.url`/`e.filename`/`e.mention` compute correctly. If it fails, apply the Protocol/mixin
  demotion and re-run.
- **UnicodeEmoji hook:** `Decoder(UnicodeEmoji).decode(b'"\\ud83d\\ude00"')` yields a `UnicodeEmoji`
  with working `codepoints`/`filename`.
- **Custom emoji decode:** a reaction payload with `id` → `CustomEmoji`; without `id` → `UnicodeEmoji`
  (id-presence discriminator preserved).
- **KnownCustomEmoji:** decode drops `app`; `role_ids` is a `list[Snowflake]`; `user` nests; frozen.
- Grep: no `self.app` in `emojis.py` (already 0), no `app` field remains.

--------------------------------------------------------------------------------------------------

## 8. Open questions / decisions

Cross-link `../00-overview/05-decisions-log.md`:

- **Resource ABC → Protocol/mixin** (maintainer decision, shared with the files plan file): required
  for the data sub-case (`Attachment`/`MediaResource`/`EmbedImage`/`EmbedVideo`), possibly for the
  emoji computed sub-case too. Determines whether Structs can carry `url`/`filename`.
- **`CustomEmoji.__eq__`:** keep the hand-written `CustomEmoji`-only guard or adopt inherited
  `Unique.__eq__` (subtle cross-subclass equality change).
- **eq=False + Unique VERIFY** (conventions §2) — emojis rely on it like every other wire Struct.
