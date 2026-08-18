# Embeds

Purpose: migrate `hikari/embeds.py`. This module is unusual: the nested pieces
(`EmbedResource`/`EmbedResourceWithProxy`/`EmbedImage`/`EmbedVideo`/`EmbedFooter`/`EmbedProvider`/
`EmbedAuthor`/`EmbedField`) are `attrs` classes built by the factory, but **`embeds.Embed` itself is a
hand-written, mutable, slotted builder** (`embeds.py:257`, `# noqa: PLW1641 - No __hash__`) with a
`from_received_embed` classmethod (`embeds.py:275-312`) — it is not attrs and cannot become a frozen
decoded Struct without breaking its builder API.

--------------------------------------------------------------------------------------------------

## 1. Objective

- Convert the 8 nested `attrs` pieces to frozen Structs (constraint (c)), resolving the
  `files.Resource` mixin on `EmbedResource`/`EmbedImage`/`EmbedVideo` (shared with `Attachment` /
  `components.MediaResource`, `03-emojis-and-files-resources.md`).
- **Keep `Embed` a hand-written mutable builder** — it is a builder/mixed class (dossier 03 §5), not a
  wire Struct; frozen does not apply, the same as the `special_endpoints` builders
  (`../08-builders/00-special-endpoints-builders.md`).
- Preserve `Embed.from_received_embed` as the residual-factory construction path (classmethod
  construction, dossier 05 §6.7); rewrite the one in-place mutation of a piece (`edit_field`) to
  replace the now-frozen `EmbedField`.
- No enums, no `app` field, no strict-enum work in this module.

Decode classification: pieces are **T** (built via `from_received_embed` with `files.ensure_resource`
wrapping); `Embed` is **T/classmethod-construction** and stays mutable — never
`msgspec.json.decode`d directly.

--------------------------------------------------------------------------------------------------

## 2. Current state (file:line anchors)

### 2.1 The Resource mixin pieces
- `EmbedResource(files.Resource[files.AsyncReader])` — `embeds.py:55-96`; field `resource`, computed
  `url`/`filename` properties (read `self.resource`), `stream` delegates. **Mixin: the abstract
  `url`/`filename` of `files.Resource` are satisfied by properties (not fields, unlike `Attachment`).**
- `EmbedResourceWithProxy(EmbedResource)` — `embeds.py:99-122`; adds `proxy_resource` (default None) +
  `proxy_url`/`proxy_filename` properties.
- `EmbedImage(EmbedResourceWithProxy)` — `embeds.py:139-159`; adds `height`/`width` (default None).
- `EmbedVideo(EmbedResourceWithProxy)` — `embeds.py:162-179`; adds `height`/`width`.

### 2.2 The plain pieces
- `EmbedFooter` — `embeds.py:125-136`; `text: str | None = None`, `icon: EmbedResourceWithProxy | None
  = None`.
- `EmbedProvider` — `embeds.py:182-201`; `name`/`url` (default None).
- `EmbedAuthor` — `embeds.py:204-219`; `name`/`url`/`icon` (default None).
- `EmbedField` — `embeds.py:222-247`; `name`, `value`, **`_inline: bool = attrs.field(alias="inline",
  default=False)`** (`:233`) + `is_inline` property **with a setter** (`:237-247`). The setter is used
  by `Embed.edit_field` (`:862-866`) to mutate a field in place.

### 2.3 `Embed` — the hand-written builder (`embeds.py:257-940`)
- Not attrs. `__slots__` of 12 `_`-prefixed attrs (`:260-273`).
- `from_received_embed(...)` classmethod (`:275-312`) — bypasses `__init__` via `super().__new__(cls)`
  and assigns the 12 slots directly; the entity_factory's `deserialize_embed` (`entity_factory.py:1786`)
  calls it to build a received embed from decoded pieces.
- `__init__` (`:314-351`) — user-facing; accepts `color`/`colour` (Colorish → `Color.of`), warns on
  naive `timestamp` and `astimezone()`s it.
- Mutable setters/properties: `title`/`description`/`url`/`color`/`colour`/`timestamp` setters
  (`:353-507`), `set_author` (`:617`), `set_footer` (`:663`), `set_image` (`:713`), `set_thumbnail`
  (`:753`), `add_field` (`:792`), `edit_field` (`:820`, **mutates an EmbedField**), `remove_field`
  (`:869`), `clear_fields` (`:894`). Custom `__repr__` (`:905`), `__eq__` (`:909`, all-slots),
  `total_length` (`:919`).
- `_ensure_embed_resource` helper (`embeds.py:250-254`) unwraps an `EmbedResource` or calls
  `files.ensure_resource`.

Factory: `serialize_embed` (`entity_factory.py:1879`, ~100 lines, `# noqa: C901, PLR0912, PLR0915`)
reads `Embed`'s properties to build the outbound dict; `deserialize_embed` (`:1786`) builds the pieces
(each guarded `if (x := payload.get(...)) and "url" in x`, wrapping URLs via `files.ensure_resource`)
and returns `Embed.from_received_embed(...)`.

--------------------------------------------------------------------------------------------------

## 3. Target design

### 3.1 Nested pieces → frozen Structs
```python
class EmbedResource(files.Resource[files.AsyncReader], msgspec.Struct, frozen=True, kw_only=True):
    resource: files.Resource[files.AsyncReader]
    @property
    def url(self) -> str: return self.resource.url            # computed, no mutation -> frozen-safe
    @property
    def filename(self) -> str: return self.resource.filename
    def stream(self, *, executor=None, head_only=False): return self.resource.stream(...)

class EmbedResourceWithProxy(EmbedResource, frozen=True, kw_only=True):
    proxy_resource: files.Resource[files.AsyncReader] | None = None
    # proxy_url / proxy_filename properties verbatim

class EmbedImage(EmbedResourceWithProxy, frozen=True, kw_only=True):
    height: int | None = None
    width: int | None = None

class EmbedVideo(EmbedResourceWithProxy, frozen=True, kw_only=True):
    height: int | None = None
    width: int | None = None

class EmbedFooter(msgspec.Struct, frozen=True, kw_only=True):
    text: str | None = None
    icon: EmbedResourceWithProxy | None = None

class EmbedProvider(msgspec.Struct, frozen=True, kw_only=True):
    name: str | None = None
    url: str | None = None

class EmbedAuthor(msgspec.Struct, frozen=True, kw_only=True):
    name: str | None = None
    url: str | None = None
    icon: EmbedResourceWithProxy | None = None

class EmbedField(msgspec.Struct, frozen=True, kw_only=True):
    name: str
    value: str
    inline: bool = False                     # was `_inline` (alias="inline"); collapse per conventions §2
    @property
    def is_inline(self) -> bool: return self.inline   # read-only; the setter is dropped (frozen)
```

The `EmbedResource` family satisfies its `files.Resource` abstract `url`/`filename` via **properties**
(computed from `self.resource`), so the mixin hazard is milder than `Attachment` (which uses fields).
The Struct + non-Struct ABC combination is still governed by the shared Resource decision in
`03-emojis-and-files-resources.md`; apply it identically. `EmbedField._inline` collapses to a plain
public `inline` field with a read-only `is_inline` property (dossier 03 §6 — trivial pass-through).

### 3.2 `Embed` stays a mutable builder
`Embed` is not converted to a Struct. Its setters that construct pieces now construct the frozen piece
Structs (`set_author`→`EmbedAuthor(...)`, `set_footer`→`EmbedFooter(...)`, `set_image`/`set_thumbnail`
→`EmbedImage(...)`, `add_field`→`EmbedField(...)`) — these already build new instances, so no change
beyond the pieces being frozen. **`edit_field`** (`:862-866`) currently mutates an `EmbedField` in
place; rewrite it to replace the field with a new frozen instance:
```python
old = self._fields[index]
self._fields[index] = EmbedField(
    name=name if name is not undefined.UNDEFINED else old.name,
    value=value if value is not undefined.UNDEFINED else old.value,
    inline=inline if inline is not undefined.UNDEFINED else old.inline,
)
```
(`self._fields` is a mutable `list` on the mutable `Embed`, so replacing an element is fine.)
`from_received_embed` stays as the factory's construction entry point (dossier 05 §6.7); the received
`timestamp` is already tz-aware from the ISO parse, so the naive-datetime warning path is not hit.

### 3.3 Serialize path
`serialize_embed` (`entity_factory.py:1879`) keeps reading `Embed`'s properties; it is outbound-only
and does not become a pure `msgspec.json.encode` call (conditional omit-if-None + nested recursion).
Covered in `../05-entity-factory/03-serialize-methods.md`.

--------------------------------------------------------------------------------------------------

## 4. Step-by-step migration

1. Resolve the `files.Resource` mixin strategy in `03-emojis-and-files-resources.md`.
2. Convert `EmbedResource`/`EmbedResourceWithProxy`/`EmbedImage`/`EmbedVideo` to frozen Structs with
   the computed `url`/`filename`/`proxy_*` properties and `stream` delegation.
3. Convert `EmbedFooter`/`EmbedProvider`/`EmbedAuthor` to frozen Structs.
4. Convert `EmbedField` to a frozen Struct; collapse `_inline`→`inline`, keep `is_inline` read-only,
   drop the setter.
5. Rewrite `Embed.edit_field` to replace (not mutate) the frozen `EmbedField`; leave the rest of
   `Embed` (mutable builder) unchanged, including `from_received_embed`.
6. Confirm `deserialize_embed`/`serialize_embed` (`entity_factory.py:1786`/`1879`) still work against
   the frozen pieces (they construct/read pieces, never mutate).

--------------------------------------------------------------------------------------------------

## 5. Affected files & symbols

| Path / anchor | Change |
|---|---|
| `hikari/embeds.py:55-179` | `EmbedResource`/`WithProxy`/`Image`/`Video` → frozen Structs (Resource mixin) |
| `hikari/embeds.py:125-219` | `EmbedFooter`/`EmbedProvider`/`EmbedAuthor` → frozen Structs |
| `hikari/embeds.py:222-247` | `EmbedField` → frozen Struct; `_inline`→`inline`, `is_inline` read-only |
| `hikari/embeds.py:820-867` | `Embed.edit_field` → replace frozen `EmbedField` |
| `hikari/embeds.py:257-940` | `Embed` — stays a mutable builder; setters build frozen pieces |
| `hikari/impl/entity_factory.py:1786-1878` | `deserialize_embed` builds frozen pieces → `from_received_embed` |
| `hikari/impl/entity_factory.py:1879-...` | `serialize_embed` unchanged (outbound); see `../05-entity-factory/03-serialize-methods.md` |

--------------------------------------------------------------------------------------------------

## 6. Risks / gotchas

1. **`Embed` cannot be frozen** — it is a user-facing mutable builder with ~15 setters and a
   received-embed alter ego via `from_received_embed`. Freezing it (or making it a decoded Struct)
   would break the builder API. Treat it like the `special_endpoints` builders: not a wire Struct.
2. **`edit_field` mutation** is the only in-place mutation of a piece; it must be rewritten once the
   pieces are frozen. All other setters already construct fresh pieces.
3. **`files.Resource` mixin** on the `EmbedResource` family — same slots/abstract-property concern as
   `Attachment`/`MediaResource`; do not resolve independently.
4. **`EmbedField.is_inline` loses its setter** — a public-API change (previously `field.is_inline =
   x`). External code that mutated a field directly must switch to `Embed.edit_field`; note in the
   breaking-changes catalog (`../11-rollout/03-breaking-changes-and-changelog.md`).
5. **`Embed.__eq__`/`__hash__`** — `Embed` keeps its hand-written all-slots `__eq__` and stays
   unhashable (`# noqa: PLW1641`); the frozen pieces gain msgspec's default field `eq` (fine, they are
   immutable scalar/record values), which changes piece equality from attrs' all-field eq to msgspec's
   all-field eq (equivalent for these value objects).

--------------------------------------------------------------------------------------------------

## 7. Verification

- Round-trip: decode a received embed payload → `deserialize_embed` returns an `Embed` whose `image`
  is a frozen `EmbedImage`, `fields` a sequence of frozen `EmbedField`; `serialize_embed(embed)`
  reproduces the outbound dict.
- `Embed().add_field("a", "b", inline=True).edit_field(0, "c")` yields a field `(name="c", value="b",
  inline=True)` — i.e. `edit_field` replaces, preserving unspecified attributes.
- Setting `embed_field.inline` raises (frozen); `embed_field.is_inline` reads it.
- `EmbedImage(resource=some_resource).url == some_resource.url` (computed property survives frozen).
- Grep proves no `attrs` decorators remain on the pieces and `Embed` is unchanged in mutability.

--------------------------------------------------------------------------------------------------

## 8. Open questions / decisions

Cross-link `../00-overview/05-decisions-log.md`:

- **`Embed` stays mutable** — confirm the maintainer accepts the asymmetry (frozen pieces, mutable
  container). Recommended; matches the builder exemption in conventions §2/§9.
- **`EmbedField.is_inline` setter removal** — public breaking change; confirm and changelog.
- **Resource mixin** — resolved in `03-emojis-and-files-resources.md`; this module consumes it.
