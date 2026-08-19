# Dependencies and Tooling

Packaging, lockfile, type-checker, docs, lint and CI changes required to make `msgspec`
the core model + JSON dependency and retire `attrs`/`orjson`. This is the enabling slice:
nothing else in the plan installs or type-checks until these edits land. Serves all three
constraints indirectly (the model/JSON rewrites they gate).

## 1. Objective

- Make `msgspec` a hard **core** runtime dependency (models and the JSON seam both need it;
  it has no stdlib fallback — see `04-json-data-binding.md` §"Why core").
- Remove `attrs` (core) and `orjson` (`speedups` extra); decide `ciso8601`'s fate.
- Regenerate `uv.lock` and re-baseline the type-checker / lint / stub / docs gates so CI is
  green on the first migrated module.
- These are decision D6/D7 packaging consequences; the model-layer decisions (D1–D5, D8–D11)
  ride on top. Cross-link: [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md).

## 2. Current state (file:line)

| Item | Location | Today |
|------|----------|-------|
| `attrs~=26.1` core dep | `pyproject.toml:36` | required for every model |
| `orjson~=3.11` speedups | `pyproject.toml:70` | optional fast JSON; stdlib `json` fallback |
| `ciso8601~=2.3` speedups | `pyproject.toml:69` | optional fast RFC3339 parse |
| `speedups` bundle | `pyproject.toml:65-71` | `aiohttp[speedups]`, `hikari[zstd]`, `ciso8601`, `orjson` |
| `server` / `zstd` extras | `pyproject.toml:72-73` | `pynacl~=1.6`; `backports.zstd; python<3.14` |
| `requires-python` | `pyproject.toml:33` | `>=3.10.0,<3.15` |
| build backend | `pyproject.toml:21-27` | hatchling; version regex from `hikari/_about.py` (no attrs/orjson coupling) |
| JSON engine `try/except` | `hikari/internal/data_binding.py:100-123` | orjson else stdlib json |
| date engine `try/except` | `hikari/internal/time.py:86-103` | ciso8601 else pure-python `fromisoformat` |
| `msgspec` anywhere | — | **absent** (0 hits in repo and `uv.lock`) |

Lockfile (`uv.lock`, 672 KB, authoritative; every CI job runs `--frozen`/`--locked`):

- hikari's own block: `uv.lock:1174-1273` (deps `1177-1182`; optional-deps `1184-1196`;
  `requires-dist` `1261-1272`).
- `attrs 26.1.0`: pkg `uv.lock:272-277`; hikari refs `1179`, `1264`; **transitive via `nox`**
  `uv.lock:2131`.
- `orjson 3.12.0`: pkg `uv.lock:2296+`; hikari refs `1192`, `1270`; **transitive via
  `mypy[faster-cache]`** `uv.lock:2069-2072` (`pyproject.toml:107`).
- `ciso8601 2.3.3`: pkg `uv.lock:723+`; hikari refs `1191`, `1267`.

Tooling that names attrs/orjson (grep of `pipelines/ scripts/ .github/ mkdocs.yml pyproject.toml
ruff.toml noxfile.py .readthedocs.yaml`):

| File:line | Reference | Kind |
|-----------|-----------|------|
| `pyproject.toml:180` | pyright `reportIncompatibleVariableOverride="none"` — "Cannot overwrite abstract properties using attrs" | attrs-motivated relaxation |
| `pyproject.toml:182-184` | pyright `reportUnknownMemberType="warning"` — "Attrs validators will always be unknown" (+ attrs#795 link) | attrs-motivated relaxation |
| `pyproject.toml:185` | pyright `reportUntypedFunctionDecorator="warning"` | attrs-motivated relaxation |
| `mkdocs.yml:137` | `https://www.attrs.org/en/stable/objects.inv` intersphinx inventory | docs cross-ref |

No `attrs`/`orjson` in `ruff.toml`, `noxfile.py`, `.readthedocs.yaml`, `pipelines/**`,
`scripts/**`, `.github/workflows/**`. **No `[tool.mypy] plugins` key exists** — mypy's attrs
support is its bundled plugin, auto-activated by import; there is nothing to delete.

## 3. Target design

### 3.1 pyproject.toml

```toml
# pyproject.toml:34-39  -> add msgspec, drop attrs
dependencies = [
    "aiohttp~=3.14",
    "colorlog~=6.10",
    "msgspec>=0.21.1",   # NEW core dep — verified floor; raise if cp314 wheels need a later minor (§7 VERIFY V6)
    "multidict~=6.7",
]

# pyproject.toml:65-71  -> drop orjson; ciso8601 stays in the first pass
[project.optional-dependencies]
speedups = [
    "aiohttp[speedups]",
    "hikari[zstd]",
    "ciso8601~=2.3",     # keep until native datetime decode is proven (02-custom-scalar §"datetime")
]
server = ["pynacl~=1.6"]
zstd = ["backports.zstd; python_version < '3.14'"]
```

Rationale, per dossier 14 §6.3: attrs was core because models cannot work without it; msgspec
inherits that role for both models and JSON. Unlike orjson (a speed-up over a stdlib fallback),
**msgspec has no stdlib fallback** — a `try/except ModuleNotFoundError` is not applicable. So
msgspec is core, and the JSON `try/except` (`data_binding.py:100-123`) collapses to an
unconditional import (see [`04-json-data-binding.md`](04-json-data-binding.md)).

`ciso8601` is retained in the first pass because dropping it depends on proving msgspec's native
RFC3339 decode matches ciso8601 on Discord's exact stamp variants AND on actually routing
timestamps through typed struct decode — an end-state, not a first-pass, property. See §5 step 4
and [`02-custom-scalar-types-and-hooks.md`](02-custom-scalar-types-and-hooks.md) §"datetime".

### 3.2 msgspec version floor

`msgspec 0.21.1` is the empirically-verified version behind every capability claim in this plan
(dossier 13, and the custom-enum `dec_hook`/`enc_hook` verification in dossier 15); pin the floor
there (`>=0.21.1`), not lower. 0.19/0.20 were **never** verified for the int-tag, UNSET, and
custom-enum-via-`dec_hook` behaviors this plan relies on, so they must be re-verified before any floor
below 0.21.1 is considered. The floor pin must also publish wheels
across the full support matrix (cp310–cp314 × ubuntu/macos/windows, plus any free-threaded target);
if **cp314** wheels first appear only in a minor *above* 0.21.1, raise the floor to that minor.
Treat "which minor first carried cp314 wheels" as VERIFY V6 (§7) and resolve before writing the pin.

### 3.3 Type-checker config re-baseline

The three pyright relaxations at `pyproject.toml:180,184,185` are explicitly attrs-caused. After
migration, attempt to restore each to `"error"`:

| Line | Setting | Attrs reason | Post-migration action |
|------|---------|--------------|-----------------------|
| `:180` | `reportIncompatibleVariableOverride="none"` | attrs field cannot override an abstract property | Re-tighten to `"error"` **only after** confirming a Struct field can satisfy an abstract property (the `Unique.id` / `files.Resource` pattern — see [`01-base-struct-conventions.md`](01-base-struct-conventions.md) §"Abstract `id`" and dossier 03 §5). If the pattern still trips it, keep `"none"` and note why. |
| `:184` | `reportUnknownMemberType="warning"` | attrs validators are untyped | Restore to `"error"` — msgspec has no validator callables. |
| `:185` | `reportUntypedFunctionDecorator="warning"` | attrs `@x.validator` decorators | Restore to `"error"` — msgspec has no such decorators. |

Hard gates that will *fail* on stale suppressions after the model reshape:

- mypy `warn_unused_ignores=true` (`pyproject.toml:261`) — every now-unnecessary `# type: ignore`
  fails the build.
- pyright `reportUnnecessaryTypeIgnoreComment="error"` (`pyproject.toml:175`) — same for
  `# pyright: ignore`.

So a repo-wide sweep of attrs-shaped ignores is **mandatory**, not optional. Expect the msgspec
model set to need a *different* (and probably smaller) ignore set.

`hikari/internal/enums.py` is currently pyright-excluded (`pyproject.toml:168-171`). Under decision
D2 the custom `Enum`/`Flag` are **kept** (not ported to stdlib `enum`) and only receive PR #2770's
changes (pseudo-member `__call__`, `is_unknown`, wrong-type `TypeError`), so the bespoke-metaclass
code that trips pyright remains — expect the exclusion to **stay**, not be dropped. Coordinate with
[`../02-enums/04-enums-module-and-machinery.md`](../02-enums/04-enums-module-and-machinery.md).

Q11: confirm the pinned `mypy==2.3.1` and `pyright==1.1.411` (`pyproject.toml:107`, pyright
group) understand `msgspec.Struct` natively (synthesized `__init__`, frozen-ness, field types)
with **no** `[tool.mypy] plugins` entry. Both do in recent releases; if a plugin is ever required,
`[tool.mypy]` gains its first-ever `plugins` line.

### 3.4 Docs, lint, stubs, slots

- `mkdocs.yml:137`: replace the attrs `objects.inv` with msgspec's inventory only if docstrings
  cross-reference msgspec symbols; otherwise drop the line. Griffe/mkdocstrings does the class
  introspection at build time (`scripts/docs/gen_ref_pages.py` does not touch attrs); confirm
  griffe renders `msgspec.Struct` fields + synthesized `__init__` cleanly — the `docs:` job is a
  CI gate, and `merge_init_into_class` (`mkdocs.yml:147`) + `separate_signature` (`:148`) will show
  msgspec's kw-only constructor shape.
- `ruff.toml` `select = ["ALL"]` (`ruff.toml:13`): Struct class-body field declarations will trip
  rules the attrs decorator form did not (`RUF012` mutable-default-in-class-body, several
  `PLR`/`B`/`TC` rules). Fix or add scoped ignores; import swaps (`import attrs` → `import msgspec`)
  auto-fix via isort (`ruff.toml:91-93`).
- `slotscheck` (`pyproject.toml:263-271`): msgspec Structs are always slotted, so
  `require-superclass`/`require-subclass` should keep passing; verify after the first module. The enum
  exclusion regex (`pyproject.toml:269`) needs **no change** — under decision D2 the enums keep their
  custom `enums.Enum`/`enums.Flag` bases (no reparenting to stdlib `enum`), so the base-class names the
  regex matches are unchanged.
- `generate-stubs` drift gate (`.github/workflows/ci.yml:130-137`, `pipelines/mypy.nox.py:46-69`):
  reshaping every model class and removing helper methods changes `stubgen` output. The 5 committed
  `.pyi` stubs (`hikari/__init__.pyi`, `hikari/api/__init__.pyi`, `hikari/events/__init__.pyi`,
  `hikari/impl/__init__.pyi`, `hikari/interactions/__init__.pyi`) MUST be regenerated and committed
  or the gate fails. Easy to forget.

## 4. Step-by-step migration

1. Resolve VERIFY V6 (§7): find the lowest msgspec minor with cp314 wheels on ubuntu/macos/windows
   (and free-threaded builds if targeted). Set the `dependencies` pin accordingly.
2. Edit `pyproject.toml`: add `msgspec` to `dependencies` (`:34-39`); remove `attrs~=26.1` (`:36`);
   remove `orjson~=3.11` from `speedups` (`:70`).
3. Regenerate the lockfile: `uv lock`. Do **not** hand-edit `uv.lock`. Confirm the new
   `[[package]] name = "msgspec"` block plus hikari `dependencies`/`requires-dist` references are
   written, and that hikari's `attrs`/`orjson` refs (`1179`,`1264`,`1192`,`1270`) are gone. Note
   `attrs` (via `nox`, `uv.lock:2131`) and `orjson` (via `mypy[faster-cache]`, `uv.lock:2069-2072`)
   remain as transitive **dev** deps — this is expected and cannot be removed without dropping those
   dev tools.
4. Rewrite the JSON seam (`hikari/internal/data_binding.py:100-123`) to unconditional `msgspec.json`
   — full spec in [`04-json-data-binding.md`](04-json-data-binding.md). Leave
   `hikari/internal/time.py:86-103` (ciso8601) untouched in this pass.
5. Sweep stale `# type: ignore` / `# pyright: ignore` comments (gates at `pyproject.toml:261`,
   `:175`). Run `nox -s mypy` and `nox -s verify-types`.
6. Attempt to restore pyright `:184` and `:185` to `"error"`; spike `:180` per §3.3.
7. Regenerate stubs: `nox -s generate-stubs`; commit the 5 `.pyi` files.
8. Docs: update/drop `mkdocs.yml:137`; run `nox -s mkdocs` and eyeball a migrated Struct's rendered
   page.
9. Lint/slots: `nox -s ruff` and `nox -s slotscheck`; resolve new findings.
10. Update `pipelines/config.py`/CI awareness (§6): the no-extras `pytest` run no longer exercises a
    distinct JSON engine.
11. Verify the two install smoke-tests (`ci.yml:44-51`) still pass: bare `uv pip install .` now pulls
    msgspec (core); `.[speedups]` no longer pulls orjson. Neither assertion inspects orjson today, so
    no assertion edits are needed.

## 5. Affected files and symbols

| Path | Anchor | Change |
|------|--------|--------|
| `pyproject.toml` | `:34-39`, `:65-71`, `:180`, `:184`, `:185` | add msgspec core; drop attrs+orjson; re-tighten pyright |
| `uv.lock` | regenerate (block `:1174-1273`) | `uv lock` rewrite |
| `hikari/internal/data_binding.py` | `:100-123` | orjson→msgspec (see 04) |
| `hikari/internal/time.py` | `:86-103` | unchanged first pass; revisit for ciso8601 drop |
| `mkdocs.yml` | `:137` | replace/drop attrs inventory |
| `hikari/__init__.pyi` (+ 4 more) | — | regenerate via `generate-stubs` |
| `.github/workflows/ci.yml` | `:15-23`, `:44-51`, `:130-137` | matrix stays; stub gate re-runs |
| `pyproject.toml` | `:269` | slotscheck enum-exclude regex — no change (custom enum base names unchanged, D2) |

## 6. Risks and gotchas

1. **cp314 wheels (top packaging risk).** The CI matrix runs 3.14 on all 3 OSes
   (`ci.yml:17-23`) and `requires-python <3.15`. If the pinned msgspec minor lacks a cp314 wheel for
   any OS, install fails (no Windows build toolchain assumed). Blocks the whole matrix. VERIFY V6.
2. **Free-threaded / `-OO`.** `pytest-all-features` runs under `python -OO`
   (`pipelines/pytest.nox.py:60`). Confirm msgspec Structs behave with asserts stripped, and that
   free-threaded wheels exist if 3.13t/3.14t are targeted.
3. **Transitive attrs/orjson stay.** They remain in `uv.lock` via `nox` and `mypy[faster-cache]`.
   "attrs fully gone from the tree" is unachievable without dropping/patching those dev tools; set
   expectations.
4. **Collapsed test dimension.** Today the no-extras `pytest` run is the only cell exercising the
   stdlib-json branch; that branch disappears, so `pytest` and `pytest-all-features` now share the
   same (msgspec) JSON engine. `pytest-all-features` still meaningfully covers ciso8601/pynacl/zstd.
5. **Stub drift is a silent failure.** Forgetting step 7 turns the `generate-stubs` gate red with an
   opaque "working tree dirty" message.
6. **ruff `select=["ALL"]` surprises.** New Struct-shaped findings are likely; budget time for
   triage rather than blanket-ignoring.

## 7. Verification

- **V6 (cp314 wheels):** `uv pip download msgspec==<candidate> --python-version 3.14 --only-binary
  :all:` for ubuntu/macos/windows; inspect PyPI's file list. Gate the pin on success. Owner:
  packaging.
- **Q11 (type-checker native Struct support):** migrate one small module (recommend
  `hikari/sessions.py`, 2 Structs) to msgspec, then run `nox -s mypy` and `nox -s pyright` with no
  `plugins` entry. Green = no plugin needed.
- Full local dry run: `uv lock && uv sync --frozen --only-group nox && nox -s pytest ruff slotscheck
  mypy verify-types generate-stubs mkdocs`.
- Confirm bare + speedups installs: `uv pip install .` then `uv pip install '.[speedups]'`.

## 8. Open questions / decisions

Cross-link all to [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md) and
[`../12-appendices/01-open-questions-and-verifications.md`](../12-appendices/01-open-questions-and-verifications.md):

- Q-DEP-1: msgspec version floor (blocked on V6). Is a floor higher than `>=0.21.1` needed for cp314?
- Q-DEP-2: Remove `orjson` entirely, or keep it as an *optional* alternate JSON path? Recommendation:
  remove — a dual engine re-introduces the exact `try/except` the migration deletes. Maintainer call.
- Q-DEP-3: `ciso8601` retention — keep in the first pass; drop once native datetime decode is proven
  end-to-end (owner: models/json). Tracked in
  [`02-custom-scalar-types-and-hooks.md`](02-custom-scalar-types-and-hooks.md).
- Q-DEP-4: Can pyright `:180` be restored to `"error"`, or do frozen Structs reproduce the
  abstract-property-override limitation? Spike required (see
  [`01-base-struct-conventions.md`](01-base-struct-conventions.md)).
