# Model modules — per-module migration recipes

Purpose: this folder holds the concrete, module-by-module migration recipes that turn hikari's
26 `attrs`-based model modules into frozen, strict-enum, app-less `msgspec.Struct` hierarchies.
Each file below covers one module (or a tightly-coupled group) and applies the locked decisions
from `../00-overview/05-decisions-log.md` and the conventions contract to that module's actual
classes, with `file:line` anchors and code sketches. Read this README first: it defines the
wire-vs-internal classification, the dependency order the modules must be migrated in, and the
shared recipe shape every module file follows.

--------------------------------------------------------------------------------------------------

## 1. Objective

Reproduce, per module, the four cross-cutting constraints on the real classes:

- **(a) app-less** — drop the `app: traits.RESTAware` field and every `self.app.rest.*` /
  `self.app.cache.*` helper (plus the `self.user.app.(rest|cache)` helpers `guilds.Member` reaches
  through its wrapped user — a `self\.app` grep misses these); callers move to bare `rest.*` /
  `cache.*` (see `../03-app-removal-and-helpers/00-strategy.md`). Verify removal with the broadened
  `grep -rnE "self\.(user\.)?app\.(rest|cache)" hikari/` → 0.
- **(b) strict enums** — keep hikari's fast custom `internal/enums.py` `Enum`/`Flag` and adopt
  upstream PR hikari-py/hikari#2770; type enum fields as the bare custom enum/flag, drop
  `Enum | int` / `Enum | str` tolerance unions. Forward-compat comes from #2770's `is_unknown`
  pseudo-members, decoded through the shared `dec_hook`
  (`../02-enums/00-strategy-and-forward-compat.md`,
  `../01-foundations/02-custom-scalar-types-and-hooks.md`), not union widening.
- **(c) frozen** — `frozen=True, kw_only=True, eq=False`, id-only identity inherited from
  `snowflakes.Unique` (`../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md`).
- **declarative-first, transform-residual** — state per class whether it is declarative-decodable
  or needs a residual transform in the slimmed entity_factory
  (`../05-entity-factory/00-architecture-and-decode-strategy.md`).

--------------------------------------------------------------------------------------------------

## 2. Wire-vs-internal classification (dossier 03 §4)

Every model class was cross-referenced against instantiation in `hikari/impl/entity_factory.py`
(module import aliases at `entity_factory.py:33-62`). Three buckets drive the per-class strategy:

| Bucket | Count | What it is | Struct strategy |
|---|---:|---|---|
| **WIRE data models** | **158** | Deserialized from Discord JSON by `deserialize_*` | Frozen app-less `Struct`; the primary target |
| **Abstract / intermediate bases** | **15** | Subclassed by wire models, never constructed directly | Frozen `Struct` bases (config inherited) OR non-Struct mixins where they only carry methods |
| **Builders / outbound-only** | **3** | User-constructed, serialized TO Discord, not parsed back | `colors.ColorGradient`, `presences.Activity`, `auto_mod.AutoModBlockMemberAction` — Structs but no dec path |

Totals: 175 `@attrs.define` classes in the 26 model modules split **157 wire-decorated + 18 (15
abstract + 3 builder)**. The wire *model* census is **158**, not 157: `channels.GuildNewsThread`
(`channels.py:1776`, covered in [`04-channels.md`](04-channels.md)) is deserialized by
`entity_factory.deserialize_guild_news_thread` yet carries **no own `@attrs.define`** — it is an empty
subclass of `GuildThreadChannel` that inherits its parent's config, so it counts as a constructed wire
model but not among the 175 decorated classes. The 273-class whole-repo total minus 175 = 98 classes
in non-model lanes (errors, files readers, special_endpoints builders, cache cells, config, routes)
that are covered by their own plan files and are **not** frozen wire Structs (conventions §2, final
bullet).

### 2.1 Classes that are NOT mechanical attrs→Struct swaps (dossier 03 §5)

These appear across the module files with dedicated handling; do not assume a field-for-field port:

| Class | Module file | Hazard |
|---|---|---|
| `messages.Attachment`, `components.MediaResource`, `embeds.EmbedImage`/`EmbedVideo`/`EmbedResource*` | `03-emojis-and-files-resources.md`, `06-messages.md`, `07-embeds.md` | Simultaneously data **and** `files.Resource` (Struct + non-Struct ABC mixin, slots/abstract-property clash) |
| `emojis.UnicodeEmoji(str, Emoji)`, `emojis.CustomEmoji(Unique, Emoji)` | `03-emojis-and-files-resources.md` | Scalar/`Unique` nature **and** the `WebResource` mixin must both survive |
| `embeds.Embed` (hand-written builder, `from_received_embed`) | `07-embeds.md` | Not attrs; classmethod-constructed on decode |
| `audit_logs.AuditLog(typing.Sequence)` | `19-audit-logs.md` | Struct subclassing the `Sequence` ABC |
| `components.ActionRowComponent(Generic)` | `08-components.md` | Generic + one of 2 non-`kw_only` classes |
| `guilds.Member(users.User, eq=False)`, `applications.TeamMember(users.User, eq=False)` | `05-guilds-members-roles.md`, `09-applications-and-oauth.md` | `eq` delegated to the wrapped user base |

--------------------------------------------------------------------------------------------------

## 3. Dependency ordering (migrate leaves first)

Wire Structs reference each other. Migrate bottom-up so every referenced type is already a Struct
when a referrer is converted. The file numbering in this folder encodes that order:

```
01 scalars      snowflakes, colors/colours, permissions, locales   (no model deps; hooks + enums)
02 users        AvatarDecoration, PrimaryGuild, User hierarchy      (deps: scalars)
03 emojis+files UnicodeEmoji/CustomEmoji/KnownCustomEmoji, Resource (deps: scalars, users)
04 channels     PartialChannel → 9-deep hierarchy, overwrites, tags (deps: scalars, users, emojis, permissions)
05 guilds       PartialGuild/Guild/GatewayGuild, Member, Role       (deps: all the above)
06 messages     Attachment, PartialMessage, Message                 (deps: users, channels, emojis, embeds, components, stickers)
07 embeds       Embed + pieces                                      (deps: files, scalars)
08 components    action rows, selects, v2 layout                    (deps: emojis, channels)
09..20          applications, commands, interactions, invites, webhooks, presences,
                stickers, polls, scheduled-events, auto-mod, audit-logs, monetization/stage/voices/templates/sessions
```

Rationale for the first five (this cluster): `snowflakes.Snowflake` / `colors.Color` /
`permissions.Permissions` / `locales.Locale` are leaf scalars every model field is typed against,
so their `dec_hook` routing and the #2770 strict-enum adoption must land first. `users` is referenced by `emojis.KnownCustomEmoji.user`,
`guilds.Member`, and virtually every actor field. `emojis` is referenced by `channels.ForumTag`,
`guilds.Role.unicode_emoji`, reactions, and components. `channels` and `guilds` sit at the top of
the reference graph and pull in all the leaves.

--------------------------------------------------------------------------------------------------

## 4. Shared recipe shape (every module file follows this)

Each module file is written to the per-file spec (conventions §11) and, inside "Target design",
walks its classes through the same fixed checklist so nothing is missed:

1. **attrs → Struct field-by-field notes.** Reproduce each `attrs.field(...)` as a Struct field:
   drop `eq=`/`hash=`/`repr=` per-field kwargs (no msgspec analog), keep `default=` /
   `factory=`→`default_factory=`, move `converter=` coercion into the `dec_hook` or the residual
   factory (`../01-foundations/02-custom-scalar-types-and-hooks.md`), map JSON-key≠field-name via
   `msgspec.field(name=...)`.
2. **Identity.** Wire models keep `snowflakes.Unique` + `eq=False` (id-only `__eq__`/`__hash__`,
   `snowflakes.py:127-132`). Value objects (not `Unique`) decide per-class between default all-field
   `eq` and `eq=False`. See `../01-foundations/01-base-struct-conventions.md`.
3. **Enum fields → strict.** List each enum-typed field, drop its `| int` / `| str` arm; the field
   is typed as the bare custom enum/flag and decoded through the shared `dec_hook`, with unknown
   Discord values becoming `is_unknown` pseudo-members (#2770, `../02-enums/`).
4. **app removal.** Name the `app` field declaration(s) removed and cross-link the helper-method
   inventory that re-homes the `self.app.*` (and, for `guilds.Member`, `self.user.app.*`) calls.
5. **Polymorphism.** State whether the module contributes to a tagged union (channels, threads,
   webhooks, stickers, components, interactions, scheduled events, auto-mod) and cross-link
   `../05-entity-factory/01-polymorphism-and-tagged-unions.md`.
6. **Hard cases.** Flag re-keying, flattening, sibling-typed values, context injection, computed
   fields, classmethod construction, epoch datetimes — cross-link
   `../05-entity-factory/02-hard-cases-and-transforms.md`.

--------------------------------------------------------------------------------------------------

## 5. Decode-classification legend

Each class in a module file is tagged with one of:

| Tag | Meaning |
|---|---|
| **D** (declarative) | `msgspec.json.decode`/`convert` straight into the public Struct; only `field(name=...)` + scalar hooks needed |
| **T** (transform) | Needs a residual entity_factory pass: re-keying, flatten, sibling-typing, context injection, computed field, or classmethod construction |
| **P** (polymorphic) | Member of a tagged union (or presence-discriminated set); decoded via the union then possibly transformed |
| **B** (builder) | Outbound-only; no decode path, `enc_hook`/builder concern only |

The split roughly follows dossier 05 §9: the flat leaf models are **D**, and the ~13 hard-case
categories force **T**. This folder does not decide the one-layer-vs-two-layer question — that is
settled in `../05-entity-factory/00-architecture-and-decode-strategy.md` (recommended: two-layer,
wire Struct → public Struct). Module files describe the **public** Struct shape and note which
fields force a transform, agnostic to whether the transform reads a wire Struct or a `msgspec.Raw`.

--------------------------------------------------------------------------------------------------

## 6. Files in this folder

| File | Module(s) | Notable content |
|---|---|---|
| `01-scalars-snowflakes-colors-permissions-locales.md` | snowflakes, colors/colours, permissions, locales | Int/str-subclass scalar hooks, `Permissions` stays custom `Flag`, `Locale` stays custom `(str, Enum)`, `ColorGradient`→Struct |
| `02-users.md` | users | `PartialUser`→`User`→`OwnUser`, `AvatarDecoration`/`PrimaryGuild`, 4 `self.app` helpers, 34 properties |
| `03-emojis-and-files-resources.md` | emojis, files (types) | `UnicodeEmoji`/`CustomEmoji`/`KnownCustomEmoji`, the `files.Resource` multiple-inheritance hazard |
| `04-channels.md` | channels | 9-deep polymorphic hierarchy → tagged unions, `PermissionOverwrite`/`ForumTag`, 16 `self.app` helpers |
| `05-guilds-members-roles.md` | guilds | Largest module (22 classes), `GatewayGuild` lazy def, `Member(User, eq=False)`, `Role` color/colors, 55 helpers (45 `self.app` + 10 `self.user.app` on `Member`) |
| `06-messages.md` … `20-…` | remaining 21 modules | authored in sibling clusters |

--------------------------------------------------------------------------------------------------

## 7. Open questions / decisions

All per-module decisions defer to `../00-overview/05-decisions-log.md`. The ones this folder
repeatedly surfaces:

- **D2 (strict enums):** keep the fast custom `Enum`/`Flag` and adopt #2770 (pseudo-member instance
  on unknown values, `is_unknown`, strict field typing) — settled in
  `../02-enums/00-strategy-and-forward-compat.md`; module files assume value-preserving pseudo-members
  decoded via the shared `dec_hook`.
- **D5 (UNDEFINED vs UNSET):** whether decoded-entity tri-state fields keep `undefined.UNDEFINED`
  as the Struct default or adopt `msgspec.UNSET` — settled in
  `../01-foundations/03-undefined-and-unset.md`; module files write `undefined.UNDEFINED` defaults
  pending the VERIFY gate.
- **eq=False + inherited `Unique` dunders VERIFY** (conventions §2) — the foundations author proves
  msgspec `frozen=True, eq=False` keeps `Unique.__hash__`/`__eq__`; every wire Struct here relies on it.
