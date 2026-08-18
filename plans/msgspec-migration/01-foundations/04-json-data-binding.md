# JSON Data Binding

Rewriting `hikari/internal/data_binding.py` from `orjson` (+ stdlib fallback) to `msgspec.json`
while keeping the hand-built request-body builders unchanged. Locks decisions D6/D7. This is the
low-risk JSON-engine swap, deliberately decoupled from the higher-risk model→Struct migration.

## 1. Objective

- Replace the orjson `try/except` engine with unconditional `msgspec.json` encode/decode.
- Preserve the `(JSONArray|JSONObject) -> bytes` encoder and `(str|bytes) -> Any` decoder contracts,
  the `raises ValueError` decode contract, and `OPT_NON_STR_KEYS` behavior.
- Keep `JSONObjectBuilder`/`StringMapBuilder`/`URLEncodedFormBuilder`/`JSONPayload` **as-is** in the
  first pass (they already skip `UNDEFINED` and stringify snowflakes).
- Audit for int-subclass values leaking into builder dicts (msgspec encode `TypeError`s on them).

## 2. Current state (file:line)

`data_binding.py` is the **single** JSON abstraction module (dossier 01 §0). orjson appears only here
(`:107,111,113`); no other module imports it.

Engine select + stdlib fallback (`data_binding.py:100-123`):

```python
default_json_dumps: JSONEncoder    # :100
default_json_loads: JSONDecoder    # :103
try:
    import orjson                                                  # :107
    def default_json_dumps(obj): return orjson.dumps(obj, option=orjson.OPT_NON_STR_KEYS)  # :109-111
    default_json_loads = orjson.loads                             # :113
except ModuleNotFoundError:
    import json                                                   # :115
    _json_separators = (",", ":")                                 # :117
    def default_json_dumps(obj): return json.dumps(obj, separators=_json_separators).encode(_UTF_8)  # :119-121
    default_json_loads = json.loads                              # :123
```

Contracts (`data_binding.py:78-90`): `JSONEncoder = Callable[[JSONArray|JSONObject], bytes]`;
`JSONDecoder = Callable[[str|bytes], JSONArray|JSONObject]` raising `ValueError` on bad input
(callers depend: `net.py:52`, `interaction_server.py:446`).

- `JSONPayload(aiohttp.BytesPayload)` (`:126-131`): `dumps(value)` must be `bytes`.
- Builders (`:134-408`): `URLEncodedFormBuilder`, `StringMapBuilder` (query/headers, coerces to `str`,
  skips `UNDEFINED`), `JSONObjectBuilder` (request bodies, `put`/`put_array`/`put_snowflake`/
  `put_snowflake_array`, all skip `UNDEFINED`, snowflakes → `str(int(v))`).
- `cast_variants_array` (`:411-438`): array-decode helper that drops `UnrecognisedEntityError` items —
  today's unknown-enum-tolerance on arrays (relevant to constraint b; see
  [`../02-enums/00-strategy-and-forward-compat.md`](../02-enums/00-strategy-and-forward-compat.md)).

`OPT_NON_STR_KEYS` (`:111`) exists for **one** concrete need: **localization maps keyed by the
`Locale` enum** (dossier 01 §3). Command builders type these `Mapping[Locale | str, str]` and put them
straight into bodies (`special_endpoints.py:1496-1497,1580-1590,1610-1660`,
`rest.py:4462,4480,4501,4515,4532,4541`). orjson raises on non-str keys without the flag; the stdlib
fallback happens to accept them because `Locale` subclasses `str`.

Injection wiring (dossier 01 §2.4): 6 components carry `self._dumps`/`self._loads` defaulting to the
module callables (`RESTClientImpl`, `RESTApp`, `GatewayShardImpl`, `GatewayBot`, `InteractionServer`,
`_GatewayTransport`). This "pluggable json" is a documented public feature (`CHANGELOG.md:630`).

Call-site counts (dossier 01 §9): 6 decode sites, 14 encode sites (incl. 11 `payload_json` multipart),
`orjson` import sites: 1, stdlib `json` sites: 2 (the fallback + `errors.py:52` pretty-print).

## 3. Target design

### 3.1 Engine swap (replaces `data_binding.py:100-123`)

```python
import msgspec

_encoder = msgspec.json.Encoder()          # add enc_hook=... only if Structs are encoded directly (see 02)
_decoder = msgspec.json.Decoder()          # untyped -> dict/list/scalars, drop-in for orjson.loads

def default_json_dumps(obj: JSONArray | JSONObject) -> bytes:
    return _encoder.encode(obj)            # -> bytes, matches the JSONEncoder contract

default_json_loads = _decoder.decode       # (bytes|str) -> Any; DecodeError <: ValueError
```

Verified drop-in facts (dossier 13 §11, dossier 01 §8.1):

- `msgspec.json.encode(obj) -> bytes` — matches the `bytes` contract; the `.encode("utf-8")` dance in
  the old stdlib branch disappears.
- `msgspec.json.decode(buf)` accepts `str|bytes`, returns plain `dict`/`list`/scalars for untyped
  decode, and raises `msgspec.DecodeError` — a **subclass of `ValueError`** — so `net.py:52` and
  `interaction_server.py:446` `except ValueError` still catch malformed input. **No try/except engine
  block** (msgspec is now core; no fallback — see [`00-dependencies-and-tooling.md`](00-dependencies-and-tooling.md)).
- Reuse module-level `Encoder`/`Decoder` instances (that is where msgspec's speed lives).

### 3.2 OPT_NON_STR_KEYS parity — mostly free, one caveat

`msgspec.json.encode` natively stringifies non-`str` dict keys of type `str`/`int`/`float`/`bytes`/
`datetime`/`enum.Enum`/`uuid` (dossier 13 §11, verified `encode({1:2}) == b'{"1":2}'`). So the
`OPT_NON_STR_KEYS` need is on by default **iff** the `Locale` key is something msgspec recognizes.

Caveat and its resolution: today `Locale` uses hikari's **custom** `enums.Enum` metaclass
(`locales.py:33`), which msgspec does not recognize as an enum — but because it subclasses `str`,
msgspec encodes the *value/key* via its `str` base. After the enum migration ports `Locale` to a
stdlib `str` enum (decision D2, [`../02-enums/02-int-and-str-enums-migration.md`](../02-enums/02-int-and-str-enums-migration.md)),
msgspec's native enum-key support makes this first-class and unambiguous. **Action:** confirm msgspec
encodes the `Locale`-keyed localization maps (before and after the enum port); this is the sole
`OPT_NON_STR_KEYS` driver, so it is the whole parity check.

### 3.3 Keep the builders (decision D6/D7, recommended first pass)

Do **not** replace `JSONObjectBuilder`/`StringMapBuilder`/`URLEncodedFormBuilder`/`JSONPayload` with
encode-Structs in the first pass (dossier 01 §8.3):

- They exist specifically to **drop `UNDEFINED`** (Discord PATCH omit-vs-null semantics) and to coerce
  snowflakes→string, enums→value, and validate mutually-exclusive args.
- They already output plain `dict`s that `msgspec.json.encode` serializes directly (msgspec encodes
  `dict`/`list`/`str`/`int`/`float`/`bool`/`None` natively). So with `_dumps = msgspec.json.encode`
  they keep working with **zero changes**.
- Converting builders to encode-Structs would leak `msgspec.UNSET`/`omit_defaults` through the entire
  public `special_endpoints` builder API — a large orthogonal change, deferred
  ([`../08-builders/00-special-endpoints-builders.md`](../08-builders/00-special-endpoints-builders.md), decision D11).

### 3.4 The encode-gap audit (mandatory)

msgspec **cannot** encode `int`/`str` **subclasses** (`Snowflake`, `Color`, `Permissions`,
`UnicodeEmoji`) — `encode({"channel_id": Snowflake(5)})` raises `TypeError: Encoding objects of type
Snowflake is unsupported` (dossier 13 §11, verified). orjson silently accepted them. So any builder
dict (or gateway frame dict, or `payload_json`) that carries a **raw** int-subclass value will now
raise where it did not before.

Mitigation (already largely true): the builders lower snowflakes with `str(int(v))`
(`data_binding.py:377`), and `int(Snowflake(5))` returns a plain `int`. The audit must confirm **every**
value that reaches `msgspec.json.encode` is a plain builtin:

1. Grep body/frame construction for direct `put("key", <Color|Permissions|Snowflake|UnicodeEmoji>)`
   without lowering. Known Color/Permissions value-side puts: `rest.py:1554` (`flags`),
   `special_endpoints.py:1588` (`data["type"]`), `shard.py:1161` (`status`). Enums subclass int/str and
   encode as their base **once ported to stdlib enums** (dossier 13 §10) — but a raw `Color`/`Snowflake`
   int-subclass still fails.
2. For any leak found, either lower at the builder call site (`int(color)`, `str(int(snowflake))`) or
   register the global `enc_hook` (see [`02-custom-scalar-types-and-hooks.md`](02-custom-scalar-types-and-hooks.md) §3.1)
   on the shared `Encoder` so the gap self-heals.

Recommendation: run the audit as a test that encodes each builder's output for representative payloads
and asserts no `TypeError`.

### 3.5 Pluggable-json public API (decision to flag)

Keep the `JSONEncoder`/`JSONDecoder` typedefs and the `self._dumps`/`self._loads` plumbing; only the
**default** changes to msgspec (dossier 01 §8.6). Lowest churn; the `bytes` contract is unchanged.
Caveat for the end-state: once models decode **directly** into Structs, a user-supplied generic
`loads` cannot produce Structs, so the decode override becomes meaningless on typed paths — the encode
override can stay. This is a public-API consideration for
[`05-decode-boundary-and-decoders.md`](05-decode-boundary-and-decoders.md) and
[`../11-rollout/03-breaking-changes-and-changelog.md`](../11-rollout/03-breaking-changes-and-changelog.md).

### 3.6 Things that stay stdlib json

`errors.py:383` `json.dumps(self.errors, indent=2)` needs pretty indentation for human-readable
exception `__str__` (msgspec has no arbitrary indent). Keep stdlib `json` here (dossier 01 §8.8).

## 4. Step-by-step migration

1. Replace `data_binding.py:100-123` with the unconditional msgspec engine (§3.1); drop the
   `try/except ModuleNotFoundError` and the `_json_separators`/`_UTF_8` encode dance.
2. Confirm the `JSONEncoder`/`JSONDecoder` typedefs (`:78-90`) and `__all__` (`:25-37`) are unchanged
   (keep `default_json_dumps`/`default_json_loads` names to avoid ripple).
3. Leave all builders and `JSONPayload` untouched.
4. Run the encode-gap audit (§3.4); lower leaks or register the `enc_hook`.
5. Verify `OPT_NON_STR_KEYS` parity on the `Locale`-keyed localization maps (§3.2), before and after
   the enum port.
6. Keep the 6 `_dumps`/`_loads` injection sites; leave `errors.py:383` on stdlib json.
7. Leave `cast_variants_array` for now; its fate is decided with the strict-enum array-tolerance work
   ([`../02-enums/00-strategy-and-forward-compat.md`](../02-enums/00-strategy-and-forward-compat.md)) and the
   decode-boundary redesign ([`05-decode-boundary-and-decoders.md`](05-decode-boundary-and-decoders.md)).

## 5. Affected files and symbols

| Path | Anchor | Change |
|------|--------|--------|
| `hikari/internal/data_binding.py` | `:100-123` | orjson `try/except` → unconditional msgspec engine |
| `hikari/internal/data_binding.py` | `:78-90`, `:25-37` | typedefs + `__all__` unchanged (verify) |
| `hikari/internal/data_binding.py` | `:134-408` | builders unchanged |
| `hikari/errors.py` | `:52,382-383` | stays stdlib `json` (indent) |
| body/frame build sites | `rest.py:1554`, `special_endpoints.py:1588`, `shard.py:1161`, + audit | lower int-subclass leaks or rely on `enc_hook` |
| localization maps | `special_endpoints.py:1496-1660`, `rest.py:4462-4541` | `OPT_NON_STR_KEYS` parity check |

## 6. Risks and gotchas

1. **Int-subclass encode gap** (§3.4) — the one true behavior break vs orjson. Silent until a payload
   carries a raw `Snowflake`/`Color`/`Permissions`; then `TypeError`. The audit is mandatory.
2. **`OPT_NON_STR_KEYS` before the enum port** — the custom-metaclass `Locale` is not a msgspec-native
   enum yet; it encodes via its `str` base today, but confirm empirically rather than assume.
3. **DecodeError subclass** — relies on `msgspec.DecodeError <: ValueError`; verify against the pinned
   version so `except ValueError` sites keep catching.
4. **No fallback** — with msgspec core, a broken/absent msgspec is a hard import error, not a silent
   downgrade. Intended (dossier 14 §6.3), but changes failure modes.
5. **Pluggable decode override** erodes in the end-state (§3.5) — flag as a future public-API change,
   not a first-pass break.

## 7. Verification

- Unit: `default_json_loads(b'{"a":[1,2]}') == {"a":[1,2]}`; `default_json_loads(b'{bad')` raises
  `ValueError`; `default_json_dumps({"x":1})` returns `bytes` with compact separators.
- Non-str keys: `default_json_dumps({Locale.EN_US: "hi"})` succeeds and round-trips (before and after
  the enum port).
- Encode-gap test: encode each builder's representative output; assert no `TypeError` (or that the
  `enc_hook` resolves it).
- Integration: REST success decode (`rest.py:892-895`), 429 decode (`rest.py:1000-1019`), shard
  `receive_json` (`shard.py:193-202`), and interaction webhook decode (`interaction_server.py:441-448`)
  all still parse and raise on malformed input.
- CI: the no-extras `pytest` run (formerly the stdlib-json branch) now uses the same msgspec engine as
  `pytest-all-features` — confirm both green (see [`00-dependencies-and-tooling.md`](00-dependencies-and-tooling.md) §6).

## 8. Open questions / decisions

Cross-link [`../00-overview/05-decisions-log.md`](../00-overview/05-decisions-log.md):

- Q-JSON-1: register the global `enc_hook` on the shared `Encoder` now (self-heals the encode gap) or
  rely on builders lowering values? Ties to Q-SCALAR-1 in [`02-custom-scalar-types-and-hooks.md`](02-custom-scalar-types-and-hooks.md).
- Q-JSON-2: keep the pluggable `dumps`/`loads` public feature once typed Struct decode lands (decode
  override becomes meaningless on typed paths)?
- Q-JSON-3: `cast_variants_array` — retire in favor of msgspec tagged-union/Raw dispatch, or keep for
  soft-skip array tolerance? Decided with the enums + decode-boundary work.
