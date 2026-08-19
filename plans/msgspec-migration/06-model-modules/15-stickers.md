# Stickers

Purpose: migrate `hikari/stickers.py` — 2 enums, `StickerPack`, the `PartialSticker` base, and its two
subtypes `StandardSticker`/`GuildSticker`. The defining features are the `init=False` **constant
discriminator** `type` field on the subtypes (→ `ClassVar` or tagged union) and the **same-JSON-key,
two-shapes** divergence where `payload["tags"]` becomes a comma-split `list[str]` on `StandardSticker`
but the raw `str` on `GuildSticker`. No `app` fields anywhere (a dead-`app` module, conventions §8).

--------------------------------------------------------------------------------------------------

## 1. Objective

- Freeze the 4 sticker Structs; no `app` field exists to remove (confirmed: **no `self.app` in
  `stickers.py`**) — this module is app-free already.
- Keep the 2 enums as hikari's custom `Enum` (adopt #2770 strict typing) and drop the
  `StickerFormatType | int` tolerance on `PartialSticker.format_type`.
- Express the `StandardSticker`/`GuildSticker` constant `type` discriminator as a `ClassVar` (or a tagged
  union) and preserve the divergent `tags`/`tag` transform.

Decode classification: `PartialSticker` is near-**D** (id, name, `format_type` enum). `StandardSticker`
is **T** (the comma-split `tags` and the constant `type`). `GuildSticker` is near-**D** (a plain
`tags`→`tag` rename + the constant `type`, plus a nested optional `user`). `StickerPack` is near-**D**
(a nested `StandardSticker` list).

--------------------------------------------------------------------------------------------------

## 2. Current state (file:line anchors)

### 2.1 Enums
`StickerType(int, enums.Enum)` `stickers.py:51` (STANDARD=1, GUILD=2); `StickerFormatType(int, enums.Enum)`
`stickers.py:62` (PNG/APNG/LOTTIE/GIF).

### 2.2 Models
- `StickerPack(snowflakes.Unique)` `stickers.py:82` — `id` (hash), `name`, `description`,
  `cover_sticker_id: Snowflake | None`, `stickers: Sequence[StandardSticker]`, `sku_id`,
  `banner_asset_id: Snowflake | None`; `make_banner_url` `:106` (no `app`).
- `PartialSticker(snowflakes.Unique)` `stickers.py:154` — `id` (hash), `name`,
  `format_type: StickerFormatType | int` `:163`; `make_url` `:166` (no `app`).
- `StandardSticker(PartialSticker)` `stickers.py:255` —
  `type: StickerType = attrs.field(init=False, default=StickerType.STANDARD)` `:258`,
  `description: str | None`, `pack_id`, `sort_value`, `tags: Sequence[str]` `:270`.
- `GuildSticker(PartialSticker)` `stickers.py:276` —
  `type: StickerType = attrs.field(init=False, default=StickerType.GUILD)` `:279`,
  `description: str | None`, `guild_id`, `is_available`, `tag: str` `:291`, `user: User | None`.

### 2.3 Factory (the `tags`/`tag` divergence, dossier 05 §3i)
- `StandardSticker.tags = [t.strip() for t in payload["tags"].split(",")]` (`entity_factory.py:3378`) —
  a comma-separated **string** → `list[str]`.
- `GuildSticker.tag = payload["tags"]` (`entity_factory.py:3390`) — the **same** JSON key kept as the raw
  `str`.
- `PartialSticker.format_type` cast from `StickerFormatType(payload["format_type"])`.

--------------------------------------------------------------------------------------------------

## 3. Target design

### 3.1 Enums → strict custom (adopt #2770)
`StickerType`, `StickerFormatType` stay `int, enums.Enum` (hikari's custom `Enum`, unchanged,
`../02-enums/00-strategy-and-forward-compat.md`); PR #2770's `_EnumMeta.__call__` mints an `is_unknown`
pseudo-member on unrecognised values and decode routes through the shared `dec_hook`. Drop
`StickerFormatType | int` (`../02-enums/03-strict-enum-field-inventory.md`).

### 3.2 Constant discriminator `type` → ClassVar (recommended) or tagged union
The `init=False` constant `type` (`stickers.py:258`/`:279`) is a fixed per-subclass value that is not a
per-instance decoded field and not accepted by `__init__` — exactly a discriminator constant
(dossier 03 §3.3). msgspec has no `init=False`; two clean expressions:

- **Option A — `typing.ClassVar` constant (recommended).** msgspec ignores `ClassVar` (it is a class
  attribute, not a decoded field), so `StandardSticker.type` still returns `StickerType.STANDARD` with
  zero wire footprint. This is the least-churn mapping and matches the current `init=False` semantics
  precisely:
  ```python
  class StandardSticker(PartialSticker, frozen=True, kw_only=True, eq=False):
      type: typing.ClassVar[StickerType] = StickerType.STANDARD
      description: str | None
      pack_id: snowflakes.Snowflake
      sort_value: int
      tags: typing.Sequence[str]          # T: comma-split of payload["tags"]

  class GuildSticker(PartialSticker, frozen=True, kw_only=True, eq=False):
      type: typing.ClassVar[StickerType] = StickerType.GUILD
      description: str | None
      guild_id: snowflakes.Snowflake
      is_available: bool
      tag: str = msgspec.field(name="tags")   # near-D: raw string, renamed key
      user: users.User | None = None
  ```
- **Option B — tagged union on `type`.** If a `deserialize_sticker` dispatch by `type` (1/2) is preferred
  over the current per-method construction, make `StandardSticker`/`GuildSticker` a
  `tag_field="type"`/`tag=1|2` union. This raises on unknown `type` — acceptable for the closed
  standard/guild pair. The `tags`/`tag` divergence still requires the residual transform on `StandardSticker`.

Recommend **Option A**: the two subtypes are built by distinct top-level deserializers, so a runtime tag
dispatch is not required; the `ClassVar` keeps the public `sticker.type` attribute intact.

### 3.3 The `tags`/`tag` same-key divergence (T)
Because the identical JSON key `tags` yields two different Python shapes, it **cannot** be a shared
declarative field:
- `StandardSticker.tags` — the residual factory keeps `[t.strip() for t in payload["tags"].split(",")]`
  (`entity_factory.py:3378`). This is the single **T** on `StandardSticker`.
- `GuildSticker.tag` — a straight `msgspec.field(name="tags")` rename; no transform needed.

`PartialSticker`/`StickerPack`:
```python
class PartialSticker(snowflakes.Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    id: snowflakes.Snowflake
    name: str
    format_type: StickerFormatType          # was `| int`
    # make_url verbatim (routes.*, no app)

class StickerPack(snowflakes.Unique, msgspec.Struct, frozen=True, kw_only=True, eq=False):
    id: snowflakes.Snowflake
    name: str
    description: str
    cover_sticker_id: snowflakes.Snowflake | None = None
    stickers: typing.Sequence[StandardSticker] = ()
    sku_id: snowflakes.Snowflake
    banner_asset_id: snowflakes.Snowflake | None = None
    # make_banner_url verbatim
```
Identity: all subclass `snowflakes.Unique` → `eq=False` + inherited id-only dunders (per conventions
§3–§4, V1 RESOLVED, dossier 16 — the frozen `eq=False` Struct keeps `Unique`'s `__eq__`/`__hash__`
with no hand-written re-attachment).

--------------------------------------------------------------------------------------------------

## 4. Step-by-step migration

1. Adopt #2770's strict custom enums (keep custom `Enum`); drop `StickerFormatType | int`.
2. Convert `PartialSticker` and `StickerPack` to frozen `Unique` Structs (`eq=False`); keep `make_url`/
   `make_banner_url`.
3. Convert `StandardSticker`/`GuildSticker`; replace the `init=False` constant `type` with a
   `typing.ClassVar[StickerType]` (Option A); keep `StandardSticker.tags` as the comma-split residual
   transform; make `GuildSticker.tag` a `field(name="tags")` rename.
4. Update `deserialize_standard_sticker`/`deserialize_guild_sticker` (`entity_factory.py:3360-3391`) to
   stop passing `type=` (now a `ClassVar`) and to keep the `tags` split on the standard path only.

--------------------------------------------------------------------------------------------------

## 5. Affected files & symbols

| Path / anchor | Change |
|---|---|
| `hikari/stickers.py:51,62` (enums) | 2 enums stay custom (#2770 strict typing); strict `format_type` |
| `hikari/stickers.py:82-149` (`StickerPack`) | frozen `Unique` Struct; nested `StandardSticker` list |
| `hikari/stickers.py:154-250` (`PartialSticker`) | frozen `Unique` Struct; strict `format_type`; keep `make_url` |
| `hikari/stickers.py:255-271` (`StandardSticker`) | `type`→`ClassVar`; `tags` comma-split **T** |
| `hikari/stickers.py:276-300` (`GuildSticker`) | `type`→`ClassVar`; `tag`←`field(name="tags")`; nested `user` |
| `hikari/impl/entity_factory.py:3360-3391` | drop `type=` kwarg; keep `tags` split on standard path |
| `../05-entity-factory/02-hard-cases-and-transforms.md` | the `tags`/`tag` same-key divergence |
| `02-users.md`, `01-scalars-snowflakes-colors-permissions-locales.md` | `User`/`Snowflake` reference types |

--------------------------------------------------------------------------------------------------

## 6. Risks / gotchas

1. **`ClassVar` vs decoded field.** msgspec treats a `ClassVar` as a class attribute (not decoded, not in
   `__init__`) — the intended behaviour for the constant `type`. If Option B (tagged union) is chosen
   instead, `type` becomes the tag and the two paths must not both set it.
2. **Same-key, two-shapes divergence.** `payload["tags"]` → `list[str]` (Standard, comma-split) vs raw
   `str` (Guild). A single shared field is impossible; the Standard split stays a residual transform.
3. **`GuildSticker.user`** is the uploader, only present with the `MANAGE_GUILD_EXPRESSIONS` permission —
   keep it optional (`None` default).
4. **`StickerPack.stickers`** nests `StandardSticker` — its constant `type` `ClassVar` must resolve there
   too (it does, being a class attribute).

--------------------------------------------------------------------------------------------------

## 7. Verification

- Decode a `StandardSticker` whose `tags == "a, b ,c"` → `tags == ["a", "b", "c"]` (stripped);
  `sticker.type is StickerType.STANDARD` (read from the `ClassVar`, not in the payload).
- Decode a `GuildSticker` whose `tags == "wave"` → `tag == "wave"` (raw string);
  `sticker.type is StickerType.GUILD`.
- Decode a `StickerPack` → `stickers` is a list of `StandardSticker`; `make_banner_url` resolves when
  `banner_asset_id` is set, else `None`.
- Identity: two stickers with equal `id` are equal and hashable (`Unique` dunders).
- Strict enum: unknown `format_type` int → pseudo-member (forward-compat).

--------------------------------------------------------------------------------------------------

## 8. Open questions / decisions

Cross-link `../00-overview/05-decisions-log.md`:
- **Constant discriminator mapping** — `ClassVar` (recommended, Option A) vs tagged union (Option B).
  If any code relies on constructing a sticker with an explicit `type=`, the `ClassVar` breaks that
  (it is no longer an `__init__` kwarg) — audit construction sites/tests.
- **`tags`/`tag` divergence** transform location — settle in
  `../05-entity-factory/02-hard-cases-and-transforms.md`.
- No `app`, no tri-state `UNDEFINED` fields in this module.
