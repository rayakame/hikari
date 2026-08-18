# Performance Benchmarking

Purpose: define what to measure, against which baselines, and the success criteria that must hold
before `3.0.0` ships. The migration is justified partly on performance (msgspec decode speed, frozen
slotted structs, a cache read path with no copies), so those gains must be measured, not assumed —
and the incremental two-layer path (P2) must be shown not to *regress* against the orjson+attrs
baseline even before the declarative optimization (P5) lands.

---

## 1. Objective

Establish a reproducible benchmark harness that:
1. Captures a `2.5.x` orjson+attrs+ciso8601 **baseline** on representative payloads.
2. Measures each migration phase's throughput, latency, and memory against that baseline.
3. Gives go/no-go numbers per phase, so a regression is caught at the phase that introduced it rather
   than at `3.0.0`.

Constraints served indirectly: the benchmark proves (c) frozen + copy removal is a net win and that
(a)/(b) do not cost throughput.

---

## 2. Current state (what exists to measure against)

- **JSON engine** today: `orjson.loads` / `orjson.dumps(obj, OPT_NON_STR_KEYS)` behind
  `default_json_loads`/`default_json_dumps` (`hikari/internal/data_binding.py:107-113`), with a stdlib
  `json` fallback when orjson is absent (`data_binding.py:114-123`). The plain `pytest` CI cell runs
  the fallback path today; `pytest-all-features` runs orjson (dossier 14 §7.2).
- **Date parsing:** `ciso8601.parse_rfc3339` when present (`hikari/internal/time.py:91-96`), else a
  pure-python fallback.
- **Deserialization:** a hand-written traversal — 91 `deserialize_*` methods, 241
  `snowflakes.Snowflake(...)` wraps, 44 `iso8601_datetime_string_to_datetime` calls, 139 comprehension
  loops (dossier 05 §2, §3). Runs on **already-decoded dicts** (`JSONObject`-in), so decode + traverse
  are two passes today.
- **Cache reads:** entities are `copy.copy`-ied out of the cache on read (~104 sites per CONVENTIONS
  §7; `internal/cache.py:127,368-412,460,509,…`) to isolate cached objects from caller mutation.
- **Models:** mutable `@attrs.define(slots=True)` — slotted, so already `__dict__`-free.
- **No benchmark suite exists in-repo** (no `benchmarks/` directory; `pyproject.toml` has no
  benchmark tooling). The harness below is net-new.

---

## 3. What to measure

### 3.1 Decode throughput (the headline metric)

Payloads (record real ones from a live gateway/REST session, scrub tokens, commit as fixtures):

| Fixture | Why | Stresses |
|---|---|---|
| `GUILD_CREATE` (large guild: thousands of members/roles/channels/emojis) | worst-case eager decode; the lazy `GatewayGuildDefinition` exists specifically for this (dossier 05 §4) | re-keying arrays→`Mapping`, context injection, laziness |
| `MESSAGE_CREATE` (embeds + attachments + components + stickers + mentions) | the heaviest per-event decode (`deserialize_message`, `# noqa: C901,PLR0912,PLR0915`, dossier 05 §4) | nested sub-objects, polymorphic components, re-keyed mentions |
| `MESSAGE_UPDATE` (partial) | tri-state `UNDEFINED` path (`deserialize_partial_message`, ~24 UNDEFINED fields) | UNDEFINED-vs-null-vs-absent, D5 |
| `READY` | many users, own-user | flat-ish, high count |
| `INTERACTION_CREATE` (command with resolved data) | resolved sub-maps, enum-keyed dicts, sibling-typed option values | hard-case §3j |
| Batch of small events (TYPING_START, PRESENCE_UPDATE, VOICE_STATE) | steady-state hot path | epoch-number datetimes, per-event overhead |

Measure, per fixture:
- **decode-to-entity throughput** (payloads/sec and MB/sec): full bytes → public entity.
- Split into **JSON-decode** vs **entity-build** sub-timings where the two-layer design keeps them
  separable (P2: `msgspec.json.decode` → dict → `msgspec.convert`; P5: single-pass typed decode).

### 3.2 `dec_hook` / scalar-hook cost

The global `dec_hook` fires per custom-typed scalar. Snowflake is the dominant one (241 wrap sites in
the factory, one per ID field; a large `GUILD_CREATE` triggers thousands). Measure:
- per-`Snowflake` dec_hook cost vs the current `snowflakes.Snowflake(int)` call.
- `Color`, `Permissions` (str→int→flag), `UnicodeEmoji`, epoch-number `datetime` hook cost.
- whether typing an ID field as bare `Snowflake(int)` avoids the hook on the happy path (dossier 05
  §3a says int-subclass fields may not need a hook to decode — confirm and prefer the no-hook path
  where it holds; note the D4 encode gap is separate).

Reference implementations to benchmark: [`../01-foundations/02-custom-scalar-types-and-hooks.md`](../01-foundations/02-custom-scalar-types-and-hooks.md).

### 3.3 Enum `_missing_` mint cost

Strict stdlib enums with a `_missing_` classmethod mint a value-preserving pseudo-member on unknown
values (D2). Measure:
- known-value decode (map hit) — should match or beat the current metaclass `__call__`
  (`enums.py:154-156`).
- unknown-value decode (mint path) — the mint + bounded-cache insert cost; verify the bounded cache
  (mirroring `_MAX_CACHED_MEMBERS = 4096`) prevents unbounded growth under adversarial unknown values.
- `IntFlag` unknown-bit decode (KEEP boundary) vs the current pseudo-member fabrication
  (`enums.py:381-412`).

### 3.4 Memory of frozen slotted structs

- per-instance size of a frozen `msgspec.Struct` vs the equivalent `@attrs.define(slots=True)` model
  (both slotted; expect parity or a small msgspec win — no `weakref` unless requested, D3).
- steady-state cache RSS holding a large guild (members/roles/channels/presences) before vs after.
- confirm no `__dict__` regression (slotscheck already enforces `__slots__`; msgspec Structs are
  always slotted, dossier 14 §8.2).

### 3.5 Cache read path without copies (the constraint (c) payoff)

- `cache.get_*` read latency before (`copy.copy` per read) vs after (identity return). This is the
  clearest expected win — collapsing ~104 copy sites to identity returns (D8).
- bulk read (`get_members_view_for_guild`, `get_guild_channels_view_for_guild`) latency, since these
  copy every element today.
- verify identity semantics: `cache.get_member(g, u) is cache.get_member(g, u)` post-migration
  (was a fresh copy each call). This is both a perf win and a documented behavior change
  ([`03-breaking-changes-and-changelog.md`](03-breaking-changes-and-changelog.md); tests in
  [`../10-testing/02-cache-copy-and-enum-tests.md`](../10-testing/02-cache-copy-and-enum-tests.md)).

### 3.6 Encode throughput (request bodies)

The hand-built `JSONObjectBuilder` dicts are fed to `msgspec.json.encode` (D6). Measure:
- encode throughput vs `orjson.dumps(..., OPT_NON_STR_KEYS)` for representative request bodies
  (create_message with embeds/components; bulk edits).
- the `enc_hook` cost for int-subclass lowering (`Snowflake`→str, `Color`→int) and confirm no
  correctness gap (msgspec cannot encode int subclasses natively — the empirically verified D4 gap).

### 3.7 End-to-end event dispatch latency

- gateway payload bytes → dispatched event object, the full hot path
  (`impl/shard.py:200` decode → `event_factory` → dispatch). This is what a bot actually feels.
- ensure the two-layer P2 path (decode dict, then `convert`) does not regress this vs the orjson+attrs
  baseline; if it does, that is the argument for prioritizing P5 (bytes-in typed decode).

---

## 4. Baselines and comparison matrix

Capture each metric under these configurations on the same hardware and Python (pin CPython 3.12 for
the primary run; spot-check 3.10 floor and 3.14 ceiling):

| Config | JSON | Models | Date | Represents |
|---|---|---|---|---|
| **B0** | orjson | attrs (mutable, slotted) | ciso8601 | `2.5.x` release baseline |
| **B0-slow** | stdlib json | attrs | pure-python | current no-speedups CI cell |
| **P1** | msgspec.json (untyped) | attrs | ciso8601 | after J2 — decode seam only |
| **P2** | msgspec.json → dict → `convert` | frozen Struct | ciso8601 (or native, TBD) | incremental two-layer |
| **P5** | msgspec typed decode (bytes-in) | frozen Struct + tagged unions | native/hook | declarative end-state |

The important comparisons:
- **P1 vs B0**: msgspec untyped decode should be ≥ orjson decode (both C, single untyped pass).
- **P2 vs B0**: the two-layer path (decode + `convert`) is the release-blocking comparison for
  `3.0.0`. Target: no worse than B0 end-to-end; the cache-read and frozen wins should offset the
  `convert` second pass.
- **P5 vs P2**: quantifies the optimization payoff to justify (or defer) P5.

---

## 5. Harness

- Use `pyperf` (stable microbenchmarks, handles warmup/outliers) for the scalar/decode microbench,
  and a simple wall-clock loop over the fixture corpus for the macro decode/dispatch numbers.
- Memory: `tracemalloc` for per-object/allocation deltas; RSS via `resource.getrusage` /
  `/proc/self/status` for steady-state cache footprint.
- Run under both plain `python` and `python -OO` (the `pytest-all-features` mode, `pipelines/pytest.nox.py:60`)
  to confirm msgspec Structs behave with asserts stripped (dossier 14 §11.2).
- Keep fixtures under a new `benchmarks/` dir (out of the coverage `source`), payloads scrubbed of
  tokens/emails/PII before commit.
- Do **not** add benchmarks to the gating CI matrix (they are noisy); run them on-demand and record
  numbers in the PR description of J2, S1, S23, C2, and any P5 PR.

Harness sketch:

```python
import pyperf, msgspec

_decoder = msgspec.json.Decoder()  # untyped, P1
_typed = msgspec.json.Decoder(Message, dec_hook=dec_hook)  # typed, P5

def bench_p1(payload_bytes):
    return _decoder.decode(payload_bytes)          # bytes -> dict

def bench_p2(payload_bytes):
    d = _decoder.decode(payload_bytes)             # bytes -> dict
    return msgspec.convert(d, Message, dec_hook=dec_hook)  # dict -> Struct

def bench_p5(payload_bytes):
    return _typed.decode(payload_bytes)            # bytes -> Struct, one pass
```

---

## 6. Success criteria (go/no-go)

| Metric | Criterion for `3.0.0` (P2 path) | Stretch (P5) |
|---|---|---|
| Untyped decode (P1) | ≥ orjson (B0) within noise | — |
| End-to-end decode-to-entity (P2) | ≥ B0 (no regression); ideally ≥ 1.1× | ≥ 1.5× B0 |
| Cache single read | strictly faster than B0 (identity vs copy) | — |
| Cache bulk view read | strictly faster than B0 | — |
| Frozen struct memory / instance | ≤ attrs slotted (parity or better) | — |
| Steady-state cache RSS (large guild) | ≤ B0 | ≤ B0 |
| Encode (request bodies) | ≥ B0 within noise | — |
| `-OO` correctness | identical results to default mode | — |
| Enum unknown-value decode | bounded memory under adversarial unknowns (4096 cap) | — |

Hard rule: **P2 must not regress end-to-end decode-to-entity vs B0.** If the `convert` second pass
regresses the hot path, either (i) hand-construct the hottest Structs in the residual factory instead
of `convert`, or (ii) prioritize P5 bytes-in decode for the offending families (channels/messages).

---

## 7. Affected files and symbols

| Area | Anchor |
|---|---|
| JSON engine under test | `hikari/internal/data_binding.py:100-123` |
| Date engine (ciso8601 vs native) | `hikari/internal/time.py:86-103`, `unix_epoch_to_datetime:138-166` |
| Snowflake hot path | `hikari/snowflakes.py:51`; 241 wrap sites in `impl/entity_factory.py` |
| Cache copy sites | `hikari/internal/cache.py` (~104); `impl/cache.py:1538` |
| Enum `_missing_`/IntFlag | `hikari/internal/enums.py:154-156,381-412` (pre-migration behavior) |
| New harness | `benchmarks/` (net-new) |

---

## 8. Risks / gotchas

- **`ciso8601` vs native datetime.** If msgspec decodes RFC3339 timestamps natively (D4), ciso8601
  becomes redundant for entity decode — but only after verifying the `Z`/offset/6-µs edge cases and
  the epoch-number + max/min clamping fields, which msgspec native decode does **not** replicate
  (dossier 05 §3b, `time.py:160-166`). Benchmark both, but the drop decision is a correctness call
  owned by [`../01-foundations/02-custom-scalar-types-and-hooks.md`](../01-foundations/02-custom-scalar-types-and-hooks.md),
  not a perf call.
- **`OPT_NON_STR_KEYS` parity** is a correctness precondition for the encode benchmark to be
  meaningful (dossier 14 §11.3).
- **Microbench noise on shared CI runners** — run perf numbers locally / on a dedicated box; never
  gate CI on them.
- **The lazy `GatewayGuildDefinition`** means the `GUILD_CREATE` decode number is misleading if the
  benchmark forces all accessors — measure both lazy (touch nothing) and fully-realized, and keep the
  lazy contract (dossier 05 §9) or the large-guild memory story regresses.

---

## 9. Verification

- Numbers recorded in the J2, S1, S23, C2 (and any P5) PR descriptions, compared to a committed
  `benchmarks/baseline.json` captured on `2.5.x`.
- The cache-read identity win is cross-checked by the identity assertions in
  [`../10-testing/02-cache-copy-and-enum-tests.md`](../10-testing/02-cache-copy-and-enum-tests.md).
- Any regression against §6 blocks the phase that introduced it.

---

## 10. Open questions / decisions

- **Drop ciso8601?** Perf-neutral-to-positive if native datetime is adopted, but gated on correctness
  (see §8). Cross-link [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md).
- **`convert` vs hand-construction in the residual factory for hot types** — decide per family based on
  the P2-vs-B0 numbers.
- **Is P5 required for `3.0.0`?** Only if P2 fails the §6 no-regression bar. Recommended: keep P5
  post-3.0 unless the benchmark forces it (cross-link [`00-phasing-and-sequencing.md`](00-phasing-and-sequencing.md) §8).
