# Security scan follow-ups (2026-08-06)

An external security scan of the tree at `4a20fb95` (the merge commit for #1531) reported six
findings: 2 high, 3 medium, 1 low, all at high confidence. Each was verified against the code
before any work started. None were false positives, but three write-ups were imprecise about
severity or location, and two missed a variant of the defect they described. Those corrections are
recorded below, because the original report will outlive this note and should not be trusted
uncritically on those points.

## Disposition

| # | Finding | Severity | Resolution |
|---|---------|----------|------------|
| 1 | Pre-login route buffers request bodies with no size ceiling | high | #1532 |
| 2 | Failed-login accounting can overwhelm the shared event loop | high | #1532 |
| 3 | Container-shaped app secrets bypass configuration masking | medium | #1534 |
| 4 | Generated Python can inherit executable structure from upstream strings | medium | this PR |
| 5 | Recovery callbacks can bypass event-dispatch concurrency limits | medium | open — issue #573 |
| 6 | Generated module names can replace hand-written package files | low | this PR |

Findings 1 and 2 shipped together because both are unauthenticated resource consumption on the same
pre-auth path. The rest were split so each PR title describes one coherent change, per
`.claude/rules/changelog-quality.md`.

## Where the report was wrong

**Finding 2's severity is overstated.** The per-source attempt list was genuinely rebuilt on every
call, but cross-source growth was already bounded — `MAX_TRACKED_SOURCES = 1024` with
least-recently-touched eviction, plus expiry of stale sources. The unbounded part was one list
inside a live window. For a self-hosted single-user tool that is medium, not high. The fix was cheap
enough that the severity argument did not change what was done.

**Finding 3 leaks two shapes the report does not mention.** It described "arrays, tuples, or
mappings" of secrets. `list[NestedModel]` where the model has a `SecretStr` field also leaked, as
did `dict[str, list[SecretStr]]`. An implementation handling only flat scalar containers would have
passed the report's own description and still leaked. The masker has to recurse through container
nodes into object nodes and back out again.

**Finding 4 points at the wrong worst site.** The report cited `generators/constants.py` and the two
templates. Those were real, but the sharpest instance was one it never named:
`build_method_docstring()` in `generators/entities.py`, which wraps Home Assistant's own
`services.yaml` description in `"""…"""` and hands the result to the template as raw source lines. A
description containing `"""` closed the docstring and landed the remainder in executable position.

**Finding 5 is partly remediated already.** `invoke_error_handler` does enforce
`error_handler_timeout_seconds`, so the report's "finite timeouts" ask was already satisfied. The
missing piece is the concurrency bound, which is what #573 tracks. The code carries `FIXME(#573)` at
the spawn sites.

## Facts worth not re-deriving

### The JSON Schema shapes Pydantic emits for container secrets

Established by probing `deref_schema` + `mask_values` against real models rather than by reading
code. This is why `config_view.py`'s masker co-walks schema nodes with values instead of walking
`properties` alone.

```
list[SecretStr]:
  {"type": "array", "items": {"type": "string", "format": "password", "writeOnly": true}}

tuple[SecretStr, SecretStr] | None:
  {"anyOf": [{"type": "array", "maxItems": 2, "minItems": 2,
              "prefixItems": [{...password...}, {...password...}]},
             {"type": "null"}]}

dict[str, SecretStr]:
  {"type": "object", "additionalProperties": {...password...}}

list[NestedModel]:
  {"type": "array", "items": {"type": "object", "properties": {...}}}

dict[str, list[SecretStr]]:
  {"type": "object", "additionalProperties": {"type": "array", "items": {...password...}}}
```

Two details drive the design. An optional container is wrapped in `anyOf`, so container detection
has to look inside union branches. And `prefixItems` is positional while `items` is homogeneous —
different keys, different semantics.

### Where the finding-3 exposure actually was

Not the global config endpoint. `HassetteConfig`'s typed fields are serialized by Pydantic, which
masks `SecretStr` in JSON mode before the masker ever runs. The leak was in app config, because
`app_config` is typed `dict[str, Any]` holding raw TOML that never passed through a `SecretStr`
field. What crossed the boundary was an app author's third-party credential — a cloud API key, a
broker password — handed to a caller who was only ever granted Hassette access.

### Every unsafe interpolation in `entity_wrapper.py.j2` appears four times

The template renders four service blocks: async and sync-facade variants, each with and without
params. A fix applied to one block looks correct and silently misses three quarters of the surface.

### `is_owned()` already existed

`codegen/manifest.py` defined and tested the exact ownership predicate finding 6 needed, and nothing
in production ever called it. Most of that fix was wiring up a function that was already there.

## Scope decisions taken deliberately

**The AST allowlist for finding 4 was skipped.** The report proposed validating generated modules
structurally before atomic replacement. That is a large amount of machinery for a threat gated
behind an already-compromised upstream checkout. Centralizing literal and identifier rendering
(`codegen/rendering.py`) gets nearly all of the value at a fraction of the cost. This was a choice,
not an oversight.

**Findings 4 and 6 are not live vulnerabilities in a deployed instance.** Both require an attacker
who already controls the Home Assistant checkout that codegen reads, which is a developer-machine or
release-pipeline compromise. They were fixed anyway because finding 4 is simultaneously a plain
correctness bug: any HA constant or service description containing a quote produced broken or wrong
output, with no attacker involved.

**Masking stays type-driven, never name-driven.** Reading schema markers rather than field names is
a standing constraint stated in `config_view.py`'s module docstring, and the reason the earlier
regex deny-list was removed. #708's "incomplete deny-list" bullets describe that older design and
no longer apply.

## Still open

- **#573** — per-listener rate limiting for error-handler task spawns (finding 5). Roughly half a
  day, independent of everything above.
- **#1533** — on-demand reveal for masked config secrets in the web UI. This is the surviving half
  of #708, which was closed once #1534 landed. It is not a security fix: masking is server-side, so
  a reveal toggle needs a backend endpoint that serves unmasked third-party credentials to any
  Hassette-token holder. That is a security decision in its own right, which is why the issue gates
  the UI behind it rather than assuming it.
