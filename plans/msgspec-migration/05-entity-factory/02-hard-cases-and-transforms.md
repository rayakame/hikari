# Entity factory: hard cases and the residual transform layer

The 13 hard-case categories (dossier 05 §6) that msgspec cannot decode declaratively, and the
layer-2 transform design for each. These are what keeps a residual `entity_factory` alive after the
declarative-first rewrite; everything here runs on already-decoded wire Structs (or `msgspec.Raw`),
never inside a frozen struct's `__post_init__`.

Parent: [`00-architecture-and-decode-strategy.md`](./00-architecture-and-decode-strategy.md).
Siblings: [`01-polymorphism-and-tagged-unions.md`](./01-polymorphism-and-tagged-unions.md),
[`03-serialize-methods.md`](./03-serialize-methods.md).

---

## 1. Objective and the frozen constraint

Constraint (c) makes models frozen. msgspec **does** call `__post_init__` on a frozen Struct, but
assignment there raises — mutation requires `msgspec.structs.force_setattr` / `object.__setattr__`.
Leaning on `__post_init__` to re-key, flatten, or tolerate enums fights the frozen rule and is
fragile. **Decision (confirmed):** all transforms live *outside* the struct — either in the global
`dec_hook` (scalar-level) or in an explicit layer-2 transform function (structural). No hard-case
transform uses in-struct field mutation. This is the structural justification for the two-layer
architecture and is cross-referenced by
[`../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md`](../04-frozen-and-cache/00-frozen-structs-and-copy-removal.md).

Where a public field genuinely must be computed from other fields at construction, prefer a
**classmethod constructor** or building the public Struct directly in layer 2 with all fields
supplied — not `force_setattr` in `__post_init__` (reserve `force_setattr` for the rare cache-edit
path, [`../04-frozen-and-cache/01-cache-data-layer-and-mutation.md`](../04-frozen-and-cache/01-cache-data-layer-and-mutation.md)).

---

## 2. Array → keyed-Mapping re-keying

Discord sends JSON **arrays**; hikari re-keys many of them into `Mapping[Snowflake, T]` model fields
(dossier 05 §3f). msgspec decodes an array to a `list[Struct]`; the dict-ification is a post-decode
transform. Affected fields include guild `roles`/`emojis`/`stickers`, message `user_mentions`/
`channel_mentions`, resolved interaction data (6 sub-maps), and group-DM `recipients`.

**Transform design.** Type the wire field as `list[T]`; build the Mapping in layer 2:

```python
class _WireGuild(msgspec.Struct, frozen=True, kw_only=True):
    roles: list[_WireRole]                 # array on the wire
    emojis: list[_WireKnownEmoji]

def _to_rest_guild(w: _WireGuild) -> RESTGuild:
    return RESTGuild(
        roles={r.id: _to_role(r, guild_id=w.id) for r in w.roles},      # re-key + context (§5)
        emojis={e.id: _to_known_emoji(e, guild_id=w.id) for e in w.emojis},
        ...,
    )
```

The re-keying and the parent→child context injection (§5) almost always co-occur, so they share one
comprehension. Where no context is threaded (e.g. resolved-data users), the transform is a bare
`{x.id: x for x in wire_list}`. Reference sites: guild `channels()`/`members()`/`roles()` in the lazy
definition (`hikari/impl/entity_factory.py:404-448`), resolved option data
(`_deserialize_resolved_option_data`, `2958`).

---

## 3. Flattened / unwrapped nested JSON

msgspec cannot pull a grandchild field up to a parent field declaratively (dossier 05 §3h). Five
representative sites:

| Site | Anchor | Shape |
|---|---|---|
| Role tags | `2201-2213` | 6 id/bool fields hoisted out of `payload["tags"]`; three are **key-presence booleans** (`premium_subscriber`, `available_for_purchase`, `guild_connections` → `True` when the key exists) |
| Integration account | `_set_partial_integration_attributes` `2247-2251` | `IntegrationAccount` lifted from `payload["account"]` |
| Message snapshot | `deserialize_message_snapshot` `3824-3825` | `payload = payload["message"]` — the inner object *is* the whole payload |
| Auto-mod action metadata | `4766`, `4774` | `payload["metadata"]["channel_id"]` / `["duration_seconds"]` |
| Scheduled external event | `4285` | `location` lifted from `payload["entity_metadata"]["location"]` |

**Transform design.** Two viable patterns:

1. **Nested wire Struct + transform (preferred for readability).** Model the nesting faithfully in
   the wire Struct, then flatten in layer 2:

   ```python
   class _WireRoleTags(msgspec.Struct, frozen=True, kw_only=True):
       bot_id: snowflakes.Snowflake | None = None
       integration_id: snowflakes.Snowflake | None = None
       subscription_listing_id: snowflakes.Snowflake | None = None
       # key-presence flags: Discord sends the key with a JSON `null` value when present (never a
       # bool), and omits it when absent. Type the present-value as `None` and absence as UNSET, and
       # test "key present" via UNSET, NOT the value — a `bool | UnsetType` arm would reject the null.
       premium_subscriber: None | msgspec.UnsetType = msgspec.UNSET
       available_for_purchase: None | msgspec.UnsetType = msgspec.UNSET
       guild_connections: None | msgspec.UnsetType = msgspec.UNSET

   def _to_role(w: _WireRole, *, guild_id) -> Role:
       t = w.tags or _WireRoleTags()
       return Role(
           is_premium_subscriber_role=t.premium_subscriber is not msgspec.UNSET,
           is_available_for_purchase=t.available_for_purchase is not msgspec.UNSET,
           is_guild_linked_role=t.guild_connections is not msgspec.UNSET,
           bot_id=t.bot_id, integration_id=t.integration_id, guild_id=guild_id, ...,
       )
   ```

   The **key-presence flag** is the subtle part: Discord sends `"premium_subscriber": null` to
   mean *true*, and omits the key to mean *false* — the present value is always JSON `null`, never a
   bool. The current code tests `if "premium_subscriber" in tags_payload` (`2206`). Under msgspec,
   "key present with null value" vs "key absent" is exactly the UNSET-vs-default distinction (D5) —
   model the field as `None | UnsetType = UNSET` (a `bool | UnsetType` arm would raise
   `ValidationError` on the incoming null) and test `is not UNSET`, never the value.

2. **`dec_hook` on the parent** for the trivial one-level lift (message snapshot) — decode
   `payload["message"]` directly with the message decoder.

---

## 4. Sibling-dependent value typing

The type/parse of one field depends on the *value* of a sibling (dossier 05 §3j) — msgspec has no
mechanism for this. Four sites, all handled in layer 2:

| Site | Anchor | Rule |
|---|---|---|
| Command-option value | `_deserialize_interaction_command_option` `2853-2868` | `value: str\|int\|float\|bool\|Snowflake` selected by sibling `type` via `_interaction_option_type_mapping` (`81`); autocomplete variant (`2871`) only casts when `is_focused` |
| Audit-log change value | `deserialize_audit_log_entry` `987-1001` | `new_value`/`old_value` run through a converter keyed on change `key` (`_audit_log_entry_converters`, `487`, 40+ target types) |
| Forum-tag emoji | `1425-1431` region | `Snowflake(emoji_id)` XOR `UnicodeEmoji(emoji_name)` by which sub-key is truthy |
| Role color / colors | `2220-2223` | uses `colors` gradient object if present, else builds a `ColorGradient` from the flat `color` int |

**Transform design.** Decode the ambiguous field as `msgspec.Raw` (or `str | int | float | bool`)
on the wire Struct, then resolve in layer 2:

```python
class _WireCommandOption(msgspec.Struct, frozen=True, kw_only=True):
    name: str
    type: int
    value: msgspec.Raw | None = None       # defer typing until sibling `type` is known
    options: list[_WireCommandOption] | None = None

def _to_command_option(w) -> CommandInteractionOption:
    otype = commands.OptionType(w.type)
    value = None if w.value is None else _decode_option_value(otype, w.value)   # Snowflake for USER/…
    return CommandInteractionOption(name=w.name, type=otype, value=value,
                                    options=[_to_command_option(s) for s in (w.options or ())])
```

The audit-log change converter table (`487`) stays as a layer-2 dict keyed on `AuditLogChangeKey`;
it is not class polymorphism (see [`01-polymorphism-and-tagged-unions.md`](./01-polymorphism-and-tagged-unions.md)
§4.3) and mixes Snowflake / timedelta / Permissions / Color / ColorGradient / bool / int / enum
converters that no single hook can express.

---

## 5. Parent → child context injection

Discord omits `guild_id` (and similar) on nested objects; hikari threads it down from the parent.
**36** `deserialize_*` methods take `UndefinedOr` context kwargs (`guild_id`/`user_id`/`member`/
`user`/`thread_id`) that are **not** in the child JSON (dossier 05 §6 item 11, §9). msgspec has no
way to pass per-node context into a nested decode.

**Transform design.** The wire Struct omits the injected field; layer 2 supplies it when building the
public Struct. The context kwargs **stay on the `deserialize_*` signatures** — they encode a data
flow msgspec cannot supply.

```python
def deserialize_member(self, data, *, guild_id=UNDEFINED, user=UNDEFINED) -> Member:
    w = _member_decoder.decode(data)                      # wire has no guild_id on nested member
    gid = guild_id if guild_id is not UNDEFINED else w.guild_id
    role_ids = list(w.roles)
    if gid not in role_ids:
        role_ids.append(gid)                              # the @everyone role, see §6
    return Member(guild_id=gid, role_ids=role_ids, user=_resolve_user(user, w.user), ...)
```

Threading map (representative): `deserialize_member`/`deserialize_role`/`deserialize_voice_state`/
thread channels take `guild_id`; the lazy guild definition (§8) injects `guild_id=self.id` and
`user_id=self._user_id` into every child accessor (`hikari/impl/entity_factory.py:404-448`);
`deserialize_voice_state` also accepts a pre-built `member`. There is a near-duplicate
`_deserialize_interaction_member` (`2894`, carries a `# TODO: deduplicate` comment) that adds a
required `permissions` field — fold both onto one wire Struct + two thin transforms.

---

## 6. Computed / transformed fields

Fields whose value is derived, not a direct wire value (dossier 05 §3i). None can be a declarative
field mapping:

| Computed field | Anchor | Rule |
|---|---|---|
| `StandardSticker.tags` | `3378` region | `payload["tags"].split(",")` → `list[str]`; but `GuildSticker.tag` keeps the raw string (same JSON key, two transforms) |
| `Application.public_key` | `759` | `bytes.fromhex(payload["verify_key"])` |
| `Member.role_ids` @everyone | `2154-2156` region (see §5) | append `guild_id` if absent — a value not in the payload |
| `afk_timeout`, `rate_limit_per_user` | `199`, `1273` | `datetime.timedelta(seconds=…)` (per-field unit; D4) |
| `burst_colors` | `3726` | `[Color.from_hex_code(c) for c in payload.get("burst_colors", ())]` — hex strings, not the int-`Color` path |

**Transform design.** Scalar-level derivations (`bytes.fromhex`, `Color.from_hex_code`, per-field
timedelta) go through a **field-specific** `dec_hook` driven by `typing.Annotated` metadata (D4;
[`../01-foundations/02-custom-scalar-types-and-hooks.md`](../01-foundations/02-custom-scalar-types-and-hooks.md)),
e.g. `Annotated[timedelta, "seconds"]`, `Annotated[list[Color], "hex"]`. Structural derivations
(tag split, @everyone append) go in the layer-2 transform. The sticker case shows why the wire
Struct must stay generic: `StandardSticker` and `GuildSticker` decode the same `"tags"` key
differently, so each gets its own transform.

---

## 7. Classmethod / factory construction

msgspec constructs via `__init__`. Two models are built via classmethods that bypass or wrap the
normal constructor (dossier 05 §6 item 7):

- **`Embed.from_received_embed`** (`hikari/embeds.py:275`) — a classmethod that distinguishes
  received embeds from user-built ones, called by `deserialize_embed` (`1786`). `Embed` is a
  hand-written `__slots__` class (not attrs, `embeds.py:257`); it is **not** in the 157 wire Structs
  (dossier 03 §4.1 note). Keep `Embed` as-is; `deserialize_embed`'s layer-2 body decodes the sub-parts
  (`EmbedImage`/`EmbedFooter`/…) as wire Structs and calls the classmethod. See
  [`../06-model-modules/07-embeds.md`](../06-model-modules/07-embeds.md).
- **`ColorGradient.of(...)`** (`hikari/colors.py:597`) — used for role colors (§4). `ColorGradient`
  becomes a frozen Struct (D4); the `.of()` smart-parse stays a classmethod called from the role
  transform, not the decode path.

**Transform design.** Keep these classmethods; call them from layer 2 after the wire sub-parts are
decoded. Do not try to make msgspec call a classmethod during decode.

---

## 8. The lazy `GatewayGuildDefinition`

`deserialize_gateway_guild` (`hikari/impl/entity_factory.py:2463`) returns a **lazy**
`_GatewayGuildDefinition` (`hikari/impl/entity_factory.py` region around `140` in dossier numbering;
accessors at `404-448` in this checkout) that stores the raw payload and deserializes
channels/members/roles/emojis/presences/threads/voice-states **on demand**, injecting
`guild_id=self.id` / `user_id=self._user_id` per accessor. It exists specifically to avoid eagerly
deserializing huge `GUILD_CREATE` payloads. This is antithetical to msgspec's decode-everything-now
model and has no declarative equivalent (dossier 05 §6 item 10). The lazy contract is baked into the
**public** API: `GatewayGuildDefinition(abc.ABC)` (`hikari/api/entity_factory.py:63`) declares 8
abstract accessors.

**Transform design (preserve laziness).** Keep `_GatewayGuildDefinition` as a small non-frozen
holder of `msgspec.Raw` slices:

```python
class _GatewayGuildDefinition(entity_factory.GatewayGuildDefinition):
    __slots__ = ("id", "_raw", "_user_id", "_roles", ...)   # cached decoded maps, MUTABLE holder
    def roles(self) -> Mapping[Snowflake, Role]:
        if self._roles is UNDEFINED:
            wire = _roles_decoder.decode(self._raw_roles)    # decode the array slice on demand
            self._roles = {r.id: _to_role(r, guild_id=self.id) for r in wire}
        return self._roles
```

- The holder is **not** a frozen wire Struct — it is deliberate mutable lazy-cache plumbing (like
  builders and `RefCell`, it is exempt from constraint (c)).
- The top-level guild scalar fields still decode eagerly into a `_WireGuild`; only the large
  sub-collections stay as `msgspec.Raw` until first access.
- The `unfetched` marker uses `default=UNDEFINED` (the current sentinel at `entity_factory.py`
  lazy-cache fields; D5).
- The child-accessor tolerance (`threads()` swallows `UnrecognisedEntityError`, `404-448`) stays.

---

## 9. `UNDEFINED` tri-state, enum leniency, epoch datetimes, enum-keyed dicts

These four remaining hard-case categories are foundations-level and are only *applied* here; the
mechanisms are specified in the foundations files.

- **`UNDEFINED` tri-state** (dossier 05 §3c; 111 `undefined.UNDEFINED` sites). Partial payloads
  (`deserialize_partial_message`, `3888`) distinguish absent vs null vs value. Modeled as
  `default=UNDEFINED` fields (D5); `UndefinedNoneOr` becomes `T | None | UndefinedType` with
  `default=UNDEFINED`. Spec: [`../01-foundations/03-undefined-and-unset.md`](../01-foundations/03-undefined-and-unset.md).
- **Enum leniency** (constraint (b); D2). Unknown enum values mint a value-preserving pseudo-member
  via the shared `_missing_` classmethod, so fields stay the bare strict enum. Spec:
  [`../02-enums/02-int-and-str-enums-migration.md`](../02-enums/02-int-and-str-enums-migration.md).
- **Number-epoch datetimes** (dossier 05 §3b; 4 sites). Activity/voice timestamps are JSON *numbers*,
  not RFC3339; they bypass native datetime decode via a field-specific hook and keep
  `time.unix_epoch_to_datetime` with its `datetime.max/min` clamping. Spec:
  [`../01-foundations/02-custom-scalar-types-and-hooks.md`](../01-foundations/02-custom-scalar-types-and-hooks.md).
- **Enum-keyed dicts** (dossier 05 §6 item 13). `authorizing_integration_owners`
  (`3039-3043`: `{ApplicationIntegrationType(int(k)): Snowflake(v)}`) and `integration_types_config`
  (`736-746`) key on an int-enum parsed from a string JSON key. Model as `dict[IntEnum, V]` (msgspec
  parses string keys to int) with the int-enum port; if the string→int-enum key path is unsupported,
  transform in layer 2 — this is consolidated probe **V8**
  ([`../12-appendices/01-open-questions-and-verifications.md`](../12-appendices/01-open-questions-and-verifications.md) §5).

---

## 10. Step-by-step migration

1. Confirm the frozen-mutation rule (§1) and land the foundations (hooks, UNDEFINED, enums) first.
2. For each residual method, define the private `_Wire*` Struct(s) that mirror the raw JSON.
3. Implement the layer-2 transform: re-key (§2), flatten (§3), resolve sibling-typed values (§4),
   inject context (§5), compute derived fields (§6), call classmethods (§7).
4. Preserve the lazy guild holder (§8) as mutable `msgspec.Raw`-backed plumbing.
5. Keep the 36 context kwargs on the `deserialize_*` signatures; do not delete them.
6. Route scalar derivations through `Annotated` field-specific `dec_hook`s; keep structural
   derivations in layer 2.
7. Delete the corresponding hand-parse code once the wire Struct + transform is proven equivalent.

---

## 11. Affected files and symbols

| Path | Anchor | Category |
|---|---|---|
| `hikari/impl/entity_factory.py` | `2192-2244` `deserialize_role` | flatten (tags), sibling color, context |
| `hikari/impl/entity_factory.py` | `2140-2190` `deserialize_member`, `2894` `_deserialize_interaction_member` | context inject, @everyone append, dedupe |
| `hikari/impl/entity_factory.py` | `2853-2892` command/autocomplete option | sibling-typed value |
| `hikari/impl/entity_factory.py` | `975-1035` audit log entry | sibling-typed change values |
| `hikari/impl/entity_factory.py` | `3824-3825` message snapshot | flatten |
| `hikari/impl/entity_factory.py` | `2958` resolved option data | array→Mapping (6 sub-maps) |
| `hikari/impl/entity_factory.py` | `2463` + accessors `404-448` | lazy GatewayGuild |
| `hikari/impl/entity_factory.py` | `3039-3043`, `736-746` | enum-keyed dicts |
| `hikari/impl/entity_factory.py` | `1786` `deserialize_embed` | classmethod construction |
| `hikari/embeds.py` | `257`, `275` | `Embed` class + `from_received_embed` |
| `hikari/colors.py` | `597` | `ColorGradient.of` |

---

## 12. Risks and gotchas

- **Key-presence booleans (role tags).** Getting the UNSET-vs-value logic wrong silently flips
  `is_premium_subscriber_role` etc. Test both `"key": null` and key-absent explicitly.
- **Same JSON key, different transforms.** `StandardSticker.tags` (split) vs `GuildSticker.tag`
  (raw) — a shared wire Struct must not bake in one interpretation.
- **Lazy guild eagerness regression.** If the wire Struct decodes `members`/`channels` eagerly, large
  `GUILD_CREATE` payloads regress; keep them as `msgspec.Raw`.
- **Context-kwarg loss.** Dropping a `guild_id` kwarg to "simplify" breaks nested objects that never
  carry it on the wire. The 36 kwargs are load-bearing.
- **Frozen mutation temptation.** Any `force_setattr`/`object.__setattr__` in a wire or public
  Struct's `__post_init__` is a red flag — push it into layer 2 or a classmethod.
- **Epoch clamping.** Dropping `time.unix_epoch_to_datetime`'s max/min clamp changes behavior on
  out-of-range epochs; keep it (dossier 09 §2.2).

---

## 13. Verification

1. **Field-by-field parity** on real payloads for every residual method (shared corpus with
   [`00`](./00-architecture-and-decode-strategy.md) §10).
2. **Re-keying:** assert `Mapping` fields are keyed by the right `Snowflake` and preserve all
   elements.
3. **Flatten + key-presence:** targeted role-tag fixtures for each of the 3 key-presence booleans
   (present-null vs absent).
4. **Sibling typing:** command options of each `OptionType` decode `value` to the right runtime type;
   audit-log changes hit every converter in the table.
5. **Context injection:** nested member/role/voice-state carry the injected `guild_id`; @everyone
   role id is appended exactly once.
6. **Lazy guild:** decoding a `GUILD_CREATE` does not eagerly build the member/channel maps; accessing
   an accessor builds and caches it; a bad thread is skipped.

---

## 14. Open questions and decisions

Consolidated in the master gate
[`../12-appendices/01-open-questions-and-verifications.md`](../12-appendices/01-open-questions-and-verifications.md);
the hard-case items map onto it as follows:

- **Lazy guild:** **resolved** — preserve laziness via the `msgspec.Raw` holder (recommended over
  eager decode); see §8 and [`00-architecture-and-decode-strategy.md`](./00-architecture-and-decode-strategy.md) §11.
- **Frozen transforms:** **resolved** — no `__post_init__` field mutation; all transforms live in
  layer 2 or classmethods. `force_setattr` reserved for the cache-edit path only.
- **Enum-keyed dict string keys:** consolidated probe **V8** — confirm msgspec parses a string JSON
  key into an int-enum key type; else transform in layer 2.
- **Epoch clamping:** **resolved** — keep `time.unix_epoch_to_datetime`'s max/min clamp (part of D4;
  see the V5 fallback), rather than dropping it.
