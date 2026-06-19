---
task_id: "T08"
title: "Reword spec tokens in remaining test areas, scripts, and codegen"
status: "done"
depends_on: ["T02", "T03"]
implements: ["FR#8", "AC#7"]
---

## Summary
Reword the remaining ~156 leaked spec tokens not covered by T04–T07: the e2e/system/pyright-probe suites, the smaller `tests/unit/` areas (cli, task_bucket, resources, web, conversion), the standalone root-level `tests/unit/test_*.py` files not handled in T06, and `codegen/`. This is the catch-all spec-token slice that, with T04–T07, drives the whole tree to zero. (The named buckets below under-sum the total — the full-scope checker pass in the prompt is the authoritative list.)

## Target Files
Run `check_spec_tokens.check_file` over the paths below for the live list. Reconnaissance buckets:
- modify: `tests/e2e/**/*.py` — ~60 tokens (`test_url_routing.py` ~58, plus 1–2 in others).
- modify: `tests/system/**/*.py` — ~8 tokens (`test_cli_smoke.py`, `test_shutdown.py`).
- modify: `tests/pyright_probes/**/*.py` — ~4 tokens (`forgotten_await_probe.py`).
- modify: `tests/unit/task_bucket/**/*.py` — ~26 tokens.
- modify: `tests/unit/cli/**/*.py` — ~5 tokens.
- modify: `tests/unit/resources/**/*.py` — ~4 tokens.
- modify: `tests/unit/conversion/**/*.py` — ~1 token.
- modify: `tests/unit/test_sync_entity_facade.py` (~20), and other root-level `tests/unit/test_*.py` with 1–4 tokens each (test_pyright_probe, test_source_tier_propagation, test_config_models, test_exceptions, test_model_types, test_recording_api, test_recording_sync_facade_generation, test_scheduler_resource, test_schema_migration, test_source_tier_models, test_web_utils, test_config_token_optional, test_recording_api_write_parity — run the checker for the exact set).
- modify: `codegen/**/*.py` — ~3 tokens.

## Prompt
For every hit reported by `check_spec_tokens.check_file` over the paths in Target Files, reword the surrounding comment or docstring to describe what the test/code does and drop the planning code, per the design doc (`design/specs/077-extend-linter-scope/design.md`, FR#8 and `## Key Constraints`).

This task is the catch-all: its scope is **every spec-token hit outside the areas owned by T04 (`tests/unit/bus`, `tests/integration/bus`), T05 (`tests/unit/core`), T06 (scheduler + the named coroutine/sync-executor/forgotten-await files), and T07 (`tests/integration` excl. bus)**. To be safe, after rewording, run `check_spec_tokens.check_file` over the **entire** widened scope (`["tests","scripts","tools","codegen","docs"]`) and confirm zero remain — any straggler outside T04–T07's areas is yours to fix here.

- Keep sentences accurate and readable; do not invent behavior; no suppression.

Verify via the imported `check_spec_tokens.check_file` over the full widened scope → zero hits. Run `uv run pytest tests/unit/task_bucket/ tests/unit/cli/ tests/unit/resources/ -q` and a representative subset of the root-level files; e2e/system suites may be verified by the checker import plus targeted runs (note any not executed).

Production `SCAN_DIRS` stays `["src"]` here — verification is via the imported `check_file`. Widening happens in T09.

## Focus
- `tests/e2e/test_url_routing.py` (~58) and `tests/unit/test_sync_entity_facade.py` (~20) and `tests/unit/task_bucket/` (~26) are the dense spots here.
- Because this is the catch-all, the final verification runs over the **whole** widened scope, not just this task's named paths — this is the gate that guarantees T09 (the scope flip) will find zero spec tokens.
- `scripts/` had 0 spec tokens in reconnaissance (its debt was dividers, handled in T02) — confirm via the checker; nothing expected here.
- Files here are disjoint from T04–T07.
- Do not touch `tests/unit/tools/` string-literal fixtures.

## Verify
- [ ] FR#8: every reworded docstring/comment in the remaining areas describes verified behavior, not a planning ID (spot-check 3).
- [ ] AC#7: importing `check_spec_tokens.check_file` and running it over the **entire** widened scope (`["tests","scripts","tools","codegen","docs"]`) reports zero hits.
