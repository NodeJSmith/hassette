# Context: Move the wire models and wire enums into hassette-wire

## Problem & Motivation
Hassette's HTTP/WebSocket wire contract lives inside the `hassette` package: response and WS message models in `src/hassette/web/models.py`, WS payloads and served telemetry models in `src/hassette/schemas/`, and the enums/Literals those models use in `hassette.types`. The upcoming `hassette-client` (#2386) and the HA companion integration need the same definitions without installing the framework. `hassette-wire` exists so server, client, and integration use ONE definition of the contract and can't drift; hassette's own code uses that definition too (Music Assistant pattern). The move also removes in-repo duplication: `SystemStatus`/`ServiceInfo`/`BootIssue` are near copies of their `*Response` twins joined by a field-copying mapper. The empty `hassette-wire` workspace package (#2384) already exists at `wire/`.

## Visual Artifacts
None.

## Key Decisions
1. **One definition, no copies.** Every served model, WS payload, and the enums/Literals they use (`ResourceStatus`, `ManifestStatus`, `ExecutionMode`, `BackpressurePolicy`, `ExecutionStatus`, `SourceTier`, `LOG_LEVEL_TYPE`, `QuerySourceTier`, plus `CliFormat`/`CliFormatStyle`) are defined only in `hassette_wire`. No mirror enum, parity test, or converter.
2. **Public API = the `hassette` root only.** `hassette` re-exports `ExecutionMode`, `BackpressurePolicy` (existing), `ResourceStatus`, `ExecutionStatus` (new) — identity, not copies. `hassette.types`, `hassette.types.enums`, `hassette.types.types`, and `hassette.schemas` stop exporting every moved name. This is a breaking change (PR `!` + one `BREAKING CHANGE:` footer naming `from hassette import ResourceStatus` / `ExecutionStatus`).
3. **Internal code imports from the `hassette_wire` root** (`from hassette_wire import JobSummary`) — the one cycle-free path. A one-off, uncommitted script rewrites imports over `src/`, `tests/`, `scripts/`. Docs are hand-edited.
4. **Layout:** domain submodules in `wire/src/hassette_wire/` (`enums`, `literals`, `cli_format`, `health`, `apps`, `telemetry`, `logs`, `auth`, `config`, `ws`), every public name re-exported from the root `__init__.py` `__all__`. Keep the `hassette-wire` name.
5. **`SystemStatus`/`ServiceInfo`/`BootIssue` collapse** into `SystemStatusResponse`/`ServiceInfoResponse`/`BootIssueResponse`; `get_system_status()` builds the wire models and sets `version=get_version()`.
6. **Validated construction:** `to_listener_with_summary` and `enrich_jobs_with_live` build via constructors, not `model_copy(update=...)`. `to_listener_with_summary` raises on bad data; `enrich_jobs_with_live` keeps its existing per-job `except (AttributeError, TypeError, ValueError)` fallback to the DB row (a `ValidationError` is a `ValueError`).
7. **Completions built per event:** `on_execution_completed` builds `ExecutionCompletedData` and accumulates typed models; `flush_completions` only dumps them, so one bad completion can't drop the whole batch.
8. **Open Literals stay `Literal`** (byte-identical schemas are the pin; #2386 owns lenient parsing).
9. **Boundary checker:** add rule `no-hassette-client` (every layer). The issue's "rule 1" wire-import allowlist is dropped.
10. **Wire-compat check:** `tools/check_wire_compat.py` runs oasdiff 1.32.1 twice against the latest `v*` tag's `frontend/openapi.json` (reversed run for new-client/old-server, forward run for old-client/new-server), with an `--err-ignore` override file `tools/wire_compat_ignore.txt` for deliberate breaks.
11. Tradeoffs accepted: enum values are published by construction; hassette depends on `hassette_wire` for core types (lockstep releases); no structural guard against internal types leaking onto the wire (the schema pin catches it); validated construction may coerce `int`→`float` (explain any diff in the PR).

## Constraints & Anti-Patterns
- **Never retype moved code.** Move exact line ranges (cut/paste, `git mv` for whole files). Docstrings, field order, defaults, and attribute docstrings stay byte-exact — the generated schemas are the pin (`uv run python scripts/export_schemas.py --types` then `git diff --exit-code` on the five generated artifacts must be clean).
- Moved StrEnums switch from `auto()` to explicit string values equal to today's values (lowercased member name). Docstrings unchanged.
- `hassette_wire` imports nothing from `hassette` and depends on `pydantic` only. Wire models that defaulted to `DEFAULT_OVERLAP_MODE`/`DEFAULT_BACKPRESSURE_POLICY` use `ExecutionMode.SINGLE` / `BackpressurePolicy.BLOCK` directly.
- No re-exports anywhere except the `hassette` root (for the four names above). Do not add convenience re-exports in `hassette.types` or `hassette.schemas`.
- `DEFAULT_OVERLAP_MODE`, `DEFAULT_BACKPRESSURE_POLICY`, `TERMINAL_STATUSES`, `ACTIVE_STATUSES` and non-contract enums (`RestartType`, `Topic`, `ConnectionState`, ...) stay in `hassette.types.enums`.
- Non-goals: no lenient/UNKNOWN parsing, no CLI move onto `hassette-client`, no Literal→StrEnum conversion, no change to `events/hassette.py` payload dataclasses, no `ListenerSummary` collapse, no deletion of unserved telemetry models, no package rename, no frontend source change.
- Do not edit `CHANGELOG.md`. No `from __future__ import annotations`; no blanket `# type: ignore`.
- Run pytest with `-n 4`, never `-n auto`. Frontend tooling needs `cd frontend && npm install` once per worktree before `export_schemas.py --types`.

## Design Doc References
- `## Problem` / `### What is one thing, and what is two` — what moves and what stays
- `## Functional Requirements` / `## Acceptance Criteria` — FR#1–FR#16, AC#1–AC#15
- `## Edge Cases` — enum identity, removed import paths, enum descriptions, attribute docstrings, `version`, defaults, docs cross-references
- `## Key Constraints` — no copies, re-exports only at the public root, mechanical moves
- `### Package layout` — which name goes in which submodule
- `### Enums and Literals: one definition, re-exported only at the public root`
- `### SystemStatus collapse`, `### Validated construction (FR#11)`, `### Completion broadcast (FR#12)`
- `### Boundary checker`, `### Wire-compatibility check (FR#16)`, `### Import rewrite`
- `## Replacement Targets` — what gets deleted/replaced
- `## Test Strategy` — test files to adapt, create, remove
- `## Documentation Updates` — every doc/docstring touch
- `## Impact` — changed files, behavioral invariants

## Convention Examples

### Wire response model

**Source:** `src/hassette/web/models.py`

```python
class ActionResponse(BaseModel):
    """Response for app mutation endpoints (start/stop/reload).

    ``instance_index`` is the server-confirmed instance the action ran against — ``None`` for
    an app-level action, the validated index for an instance-scoped one. ...
    """

    status: Literal["accepted"] = "accepted"
    app_key: str
    action: str
    instance_index: int | None
```

### Domain-to-wire mapper (kept for `app_snapshots`)

**Source:** `src/hassette/web/mappers.py`

```python
def app_manifest_response_from(manifest: AppManifestInfo) -> AppManifestResponse:
    """Convert an ``AppManifestInfo`` snapshot to ``AppManifestResponse``."""
    return AppManifestResponse(**manifest_response_fields(manifest))
```

### StrEnum whose docstring becomes the OpenAPI description

**Source:** `src/hassette/types/enums.py`. It moves with its docstrings unchanged and gets explicit values instead of `auto()`.

```python
class ManifestStatus(StrEnum):
    """Enumeration for app manifest status values (manifest-scoped, distinct from ``ResourceStatus``)."""

    DISABLED = auto()
    ...
```

### Public re-export surface

**Source:** `src/hassette/__init__.py`, the one public surface. Its enum import changes source to `hassette_wire` and gains `ResourceStatus` and `ExecutionStatus` (added to `__all__`).

```python
from .types.enums import BackpressurePolicy, BlockingIOBehavior, ExecutionMode, ForgottenAwaitBehavior, Topic
# becomes
from hassette_wire import BackpressurePolicy, ExecutionMode, ExecutionStatus, ResourceStatus
from .types.enums import BlockingIOBehavior, ForgottenAwaitBehavior, Topic
```

### Boundary rule and its test

**Source:** `tools/check_module_boundaries.py`, `tests/unit/tools/test_check_module_boundaries.py`

```python
Rule(
    name="test-helpers-isolation",
    applies=applies_outside("testing"),
    forbids=forbids_package("testing"),
    reason="production code must not import test helpers from hassette.testing",
),
```

### WS envelope test

**Source:** `tests/unit/test_ws_models.py`

```python
MESSAGE_ADAPTER = TypeAdapter(WsServerMessage)

def validate_envelope(msg_type: str, data: object) -> WsServerMessage:
    return MESSAGE_ADAPTER.validate_python({"type": msg_type, "data": data, "timestamp": TEST_TIMESTAMP})
```
