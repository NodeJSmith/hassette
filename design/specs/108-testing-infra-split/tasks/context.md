# Context: Separate Public and Internal Testing Infrastructure

## Problem & Motivation

App authors writing hassette automations cannot distinguish which test helpers are supported public API vs internal framework plumbing. The module name `test_utils` reads as repository tooling, and 76 symbols are importable from the root even though only 17 are in `__all__`. The public API (`AppTestHarness`, `RecordingApi`, `HassetteHarness`, etc.) is tangled with internal-only helpers (web-layer factories, seed scenario infrastructure, codegen templates) in a single namespace with no structural boundary. Three downstream issues in the Testing API Redesign milestone are hard-blocked on this restructuring.

## Visual Artifacts

None.

## Key Decisions

1. **Two-package split.** Tier 1 public API goes to `hassette.testing` (ships in wheel). Tier 2 internal helpers go to `tests/support/` (outside `src/`, absent from wheel). The boundary is namespace clarity and `__all__`, not wheel size reduction — private implementation modules that Tier 1 depends on (`_harness.py`, `_simulation.py`, etc.) remain in the wheel as `_`-prefixed modules.
2. **21 Tier 1 symbols.** `make_mock_hassette` demoted, `EventCapture`/`HassetteHarness`/`wait_for`/`build_harness`/`make_full_state_change_event` promoted. The complete list is in the design doc's `### Tier 1 symbol set` section.
3. **No shim period.** Every `hassette.test_utils` import must be rewritten in the same PR. No temporary re-exports, no deprecation warnings.
4. **Codemod is throwaway.** The libcst migration script and symbol manifest are working tools, not committed artifacts. Only the results land in the PR.
5. **One-way dependency.** `hassette.testing/` must never import from `tests/support/`. Enforced by a new AST rule in `check_module_boundaries.py`.
6. **Breaking change.** This PR ships as `feat!:` with a `BREAKING CHANGE:` footer.
7. **helpers.py split.** 8 Tier 1 factory functions move to `hassette.testing._factories.py`. Two event builder functions (`create_component_loaded_event`, `create_service_registered_event`) fold into `_simulation.py`. Everything else goes to `tests/support/helpers.py`, which re-exports the event builders from `hassette.testing._simulation`.
8. **fixtures.py split.** Tier 1 fixtures (`dummy_cache`, `event_capture`, `build_harness`) go to `hassette.testing.fixtures`. Tier 2 fixtures go to `tests/support/fixtures.py`.

## Constraints & Anti-Patterns

- Do NOT create any compatibility shim, re-export alias, or deprecation wrapper for `hassette.test_utils`.
- Do NOT commit the codemod script or symbol manifest — only the rewritten files.
- Do NOT add `from tests.support` imports inside `src/hassette/testing/` — this violates FR#6.
- Do NOT change any helper's behavior, signature, or return type — this is a pure location change.
- Do NOT update historical design docs, research files, or CHANGELOG entries — these are frozen records.
- Do NOT rename `hassette.test_utils` to `hassette.testing` in the `docs/pages/testing/factories.md` `make_mock_hassette` section — delete it instead (demoted to internal).
- The actual test file count with `test_utils` imports is 261 (design doc says 255). The codemod must cover all.

## Design Doc References

- `## Architecture → Module mapping (authoritative)` — the single source of truth for where each source module goes
- `## Architecture → Tier 1 symbol set` — the 21 symbols in `hassette.testing.__all__`
- `## Architecture → pytest_plugins registration change` — before/after for `tests/conftest.py`
- `## Architecture → Codemod strategy` — import transformation rules table
- `## Architecture → String reference cleanup` — file-by-file list of non-Python references
- `## Edge Cases` — mixed-tier imports, private modules, pytest_plugins resolution, conftest cascade, circular imports, string references
- `## Test Strategy` — unit tests only; existing `test_public_api_surface.py` adapts; new `wheel_smoke` nox session
- `## Documentation Updates` — complete list of docs files needing import path updates

## Convention Examples

### `__all__` with tier comment

**Source:** `src/hassette/test_utils/__init__.py:91-110`

```python
__all__ = [
    # Tier 1 only
    "ApiCall",
    "AppConfigurationError",
    "AppTestHarness",
    # ... remaining symbols
]
```

New `hassette.testing/__init__.py` follows the same shape with `__all__` defining the public surface.

### Pytest plugin registration

**Source:** `tests/conftest.py:58-65`

```python
pytest_plugins: list[str] = [
    "hassette.test_utils.fixtures",
    "hassette.test_utils.resource_tracker",
    "tests.coverage_integrity",
]
```

The existing `tests.coverage_integrity` entry demonstrates rootdir-based resolution already working. New `tests.support.fixtures` uses the same mechanism.

### Public API surface test

**Source:** `tests/unit/test_public_api_surface.py`

```python
TIER1_SYMBOLS = {
    "ApiCall",
    "AppConfigurationError",
    # ...
}

def test_tier1_in_all() -> None:
    assert set(test_utils.__all__) == TIER1_SYMBOLS
```

Updated to verify `hassette.testing.__all__` instead.

## BREAKING CHANGE Footer Draft (for `/mine-create-pr`)

Captured at ship-time challenge (2026-09-03) so the exhaustive symbol mapping doesn't have to be
re-derived from `design/research/2026-09-02-testing-infra-split/research.md:213` when the PR body
is written. Copy this into the PR body's `BREAKING CHANGE:` footer, adjusting wording as needed.

```
BREAKING CHANGE: `hassette.test_utils` no longer exists. Test infrastructure is split into
`hassette.testing` (public API, ships in the wheel) and `tests.support` (internal, hassette
contributors only, not shipped). No compatibility shim or deprecation period — every import must
be updated in the same release that adopts this version.

#### Known external-consumer symbol mapping

The following symbols move from `hassette.test_utils` (package-root or submodule-qualified) to
`hassette.testing` (package-root import only — the new private submodule homes below are not a
supported import path):

- `AppTestHarness` — `from hassette.testing import AppTestHarness`
- `HassetteHarness` — `from hassette.testing import HassetteHarness` (was importable from
  `hassette.test_utils.harness`; new home `_harness.py` is private — do not import
  `hassette.testing.harness` or `hassette.testing._harness` directly)
- `wait_for` — `from hassette.testing import wait_for` (same private-submodule caveat as
  `HassetteHarness` above)
- `build_harness` — `from hassette.testing import build_harness`
- `make_sensor_state_dict` — `from hassette.testing import make_sensor_state_dict`
- `make_state_dict` — `from hassette.testing import make_state_dict`
- `make_full_state_change_event` — `from hassette.testing import make_full_state_change_event`

#### Full Tier 1 surface

All 21 symbols in `hassette.testing.__all__` are importable directly from `hassette.testing` —
see the design doc's `### Tier 1 symbol set` section for the complete list. Any other symbol
previously importable from `hassette.test_utils` (e.g. `make_mock_hassette`) is gone; hassette
contributors can find its new home in `tests/support/`, but it is not part of the public API.
```
