# Helper Removal — `hikari/templates.py`, `hikari/presences.py`, `hikari/commands.py`

Removal recipe for 11 helper methods across three small modules: `templates.py` (4, `rest.*`),
`presences.py` (2, `rest.*`), `commands.py` (5, `rest.*`). No `cache.*` helpers here; all delegations
are pure or `arg-default`, so every replacement is Strategy 1 (direct `rest.*`).

See [`00-README.md`](00-README.md) for the shared legend.

## 1. Objective

Delete these modules' `app`-delegating helpers, each replaced by a direct `rest.*` call reproducing
the id/`self`-forwarding the helper hid. Serves constraint (a) / D9.

## 2. Current state

### 2.1 `hikari/templates.py` — class `Template` (dossier 04 §3.1)

`Template` (`templates.py:151`) is the canonical `app`-field declaration cited in
[`../01-app-field-removal.md`](../01-app-field-removal.md) (`templates.py:151-153`).

| Line | Method | async | Delegates to | Extra logic |
|---:|---|:--:|---|---|
| 183 | `fetch_self` | yes | `rest.fetch_template(self.code)` | pure |
| 205 | `edit(*, name, description)` | yes | `rest.edit_template(self.source_guild, self, name=, description=)` | passes `self` |
| 241 | `delete` | yes | `rest.delete_template(self.source_guild, self)` | passes `self` |
| 260 | `sync` | yes | `rest.sync_guild_template(self.source_guild.id, self.code)` | pure |

### 2.2 `hikari/presences.py` — class `MemberPresence` (dossier 04 §3.2)

`MemberPresence` (`presences.py:423`).

| Line | Method | async | Delegates to | Extra logic |
|---:|---|:--:|---|---|
| 447 | `fetch_user` | yes | `rest.fetch_user(self.user_id)` | pure |
| 469 | `fetch_member` | yes | `rest.fetch_member(self.guild_id, self.user_id)` | pure |

### 2.3 `hikari/commands.py` — class `PartialCommand` (dossier 04 §3.7)

`PartialCommand` (`commands.py:220`). All five methods `arg-default` the guild:
`undefined.UNDEFINED if self.guild_id is None else self.guild_id`.

| Line | Method | async | Delegates to | Extra logic |
|---:|---|:--:|---|---|
| 269 | `fetch_self` | yes | `rest.fetch_application_command(self.application_id, self.id, <guild>)` | `arg-default` |
| 295 | `edit(*, name, description, options)` | yes | `rest.edit_application_command(self.application_id, self.id, <guild>, …)` | `arg-default` |
| 346 | `delete` | yes | `rest.delete_application_command(self.application_id, self.id, <guild>)` | `arg-default` |
| 367 | `fetch_guild_permissions(guild, /)` | yes | `rest.fetch_application_command_permissions(application=self.application_id, command=self.id, guild=)` | pure |
| 400 | `set_guild_permissions(guild, permissions)` | yes | `rest.set_application_command_permissions(application=…, command=…, guild=, permissions=)` | pure |

## 3. Target design — replacements (all Strategy 1)

### 3.1 `templates.py`

Two helpers pass `self` (the whole `Template`) to `rest`; the caller passes the template object it
already holds:

| Removed helper | Caller now writes |
|---|---|
| `template.fetch_self()` | `await rest.fetch_template(template.code)` |
| `template.edit(name=..., description=...)` | `await rest.edit_template(template.source_guild, template, name=..., description=...)` |
| `template.delete()` | `await rest.delete_template(template.source_guild, template)` |
| `template.sync()` | `await rest.sync_guild_template(template.source_guild.id, template.code)` |

`rest.edit_template`/`rest.delete_template` accept a `SnowflakeishOr[Template]`, so passing the object
is fine; no data is lost.

### 3.2 `presences.py`

| Removed helper | Caller now writes |
|---|---|
| `presence.fetch_user()` | `await rest.fetch_user(presence.user_id)` |
| `presence.fetch_member()` | `await rest.fetch_member(presence.guild_id, presence.user_id)` |

### 3.3 `commands.py`

The `arg-default` on guild is trivially reproduced at the call site with the same expression:

```python
# before: await command.fetch_self()
# after:
guild = undefined.UNDEFINED if command.guild_id is None else command.guild_id
await rest.fetch_application_command(command.application_id, command.id, guild)
```

| Removed helper | Caller now writes |
|---|---|
| `command.fetch_self()` | `await rest.fetch_application_command(command.application_id, command.id, <guild>)` |
| `command.edit(...)` | `await rest.edit_application_command(command.application_id, command.id, <guild>, ...)` |
| `command.delete()` | `await rest.delete_application_command(command.application_id, command.id, <guild>)` |
| `command.fetch_guild_permissions(g)` | `await rest.fetch_application_command_permissions(command.application_id, command.id, g)` |
| `command.set_guild_permissions(g, perms)` | `await rest.set_application_command_permissions(command.application_id, command.id, g, perms)` |

where `<guild> = undefined.UNDEFINED if command.guild_id is None else command.guild_id`.

## 4. Step-by-step migration

1. Remove `app` fields: `Template` (`templates.py:151`), `MemberPresence` (`presences.py:423`),
   `PartialCommand` (`commands.py:220`) per
   [`../01-app-field-removal.md`](../01-app-field-removal.md).
2. Delete all 11 helpers; rewrite docstrings/examples to the direct `rest.*` form (§3).
3. For `commands.py`, provide the guild `arg-default` snippet in the migration guide so callers do not
   forget the `guild_id is None → UNDEFINED` coercion.
4. Catalog the 11 removed public methods in
   `../../11-rollout/03-breaking-changes-and-changelog.md`.

## 5. Affected files & symbols

| Path | Anchor | Change |
|---|---|---|
| `hikari/templates.py` | 151, 183, 205, 241, 260 | remove `app` field + 4 helpers |
| `hikari/presences.py` | 423, 447, 469 | remove `app` field + 2 helpers |
| `hikari/commands.py` | 220, 269, 295, 346, 367, 400 | remove `app` field + 5 helpers |
| `hikari/impl/entity_factory.py` | template/presence/command deserialize | drop `app=self._app` |

## 6. Risks / gotchas

- **`commands.py` guild coercion is easy to drop.** All five helpers translate
  `guild_id is None → UNDEFINED`; a caller who passes `command.guild_id` raw (which may be `None`)
  would send `None` where `UNDEFINED` is meant. Provide the coercion snippet explicitly (§3.3).
- **`Template.edit`/`delete` pass the whole object.** The replacement passes the object too; make sure
  the migration example uses the template object, not just `template.code`, where `rest` expects the
  `SnowflakeishOr[Template]` (it accepts either, but the object carries `source_guild`).
- Small modules, low individual blast radius, but still public/documented API — include in the break
  catalog.

## 7. Verification

1. `grep -n "self\.app" hikari/{templates,presences,commands}.py` → 0 after the pass.
2. A migrated `command.fetch_self()` call with `guild_id is None` sends `UNDEFINED` (global command),
   and with a set `guild_id` sends the guild id (guild command) — matches
   `rest.fetch_application_command` behavior.
3. `rest.edit_template(template.source_guild, template, ...)` round-trips the same request body as the
   old `template.edit(...)`.

## 8. Open questions

None module-specific. General app-removal decision is D9 in
`../../00-overview/05-decisions-log.md`.
