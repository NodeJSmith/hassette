# Context: Migrate hassette_instance fixture to public API

## Problem & Motivation
34 integration tests across `test_core.py`, `test_fatal_shutdown.py`, and `test_resource_deps.py` access Hassette services through private attributes like `hassette_instance._database_service` and `hassette_instance._session_manager`. When `Hassette.wire_services()` changes, these tests silently drift from the real API. The fixture teardown also reaches into private stream state, creating a second fragile surface. Hassette already exposes public property accessors for 12+ services, but tests use private attributes even for services with existing public properties.

## Visual Artifacts
None.

## Key Decisions
1. Add only 3 new public properties to `Hassette` (`session_manager`, `event_stream_service`, `bus`) — justified by behavioral test usage. The remaining 5 services (`service_watcher`, `file_watcher`, `web_api_service`, `web_ui_watcher`, `scheduler`) have zero behavioral test consumers outside one type-assertion test that will be rewritten.
2. Rewrite `test_constructor_registers_background_services` to assert type-membership via `hassette_instance.children` instead of per-service isinstance checks, eliminating the need for 5 unnecessary properties.
3. Refactor 4 structural invariant tests to call `topological_levels()`/`topological_sort()` pure functions directly with `[type(c) for c in hassette.children]` instead of reading `_init_waves`/`_init_order`. This trades direct attribute verification for pure-function testability — indirect coverage via startup/shutdown tests remains.
4. Keep fixture teardown as a test-only helper function in `tests/integration/conftest.py` (not on the production `Hassette` class) to avoid a live-instance hazard.
5. HassetteHarness is unchanged — it reads AND writes private slots as part of lifecycle control; making reads indirect while writes stay direct would be asymmetric.
6. `# coordinator-internal` annotations for remaining private-access sites (~30) are CI-enforced via a lint script extending `tools/check_internal_patches.py` or a sibling.

## Constraints & Anti-Patterns
- Do NOT add properties to `Hassette` for `service_watcher`, `file_watcher`, `web_api_service`, `web_ui_watcher`, or `scheduler` — these have zero production or behavioral-test consumers.
- Do NOT modify `src/hassette/test_utils/harness.py` — HassetteHarness delegation is out of scope.
- Do NOT add `cleanup_streams()` to the production `Hassette` class — it has a live-instance hazard.
- New properties follow the exact pattern of existing ones: guard `None`, raise `_service_not_wired_error()`, return typed instance, one-line docstring.
- The `# coordinator-internal` annotation must be enforceable — not just a comment convention.

## Design Doc References
- `## Architecture` — describes the 3 new properties, stream cleanup helper, structural test refactoring, and HassetteHarness rationale.
- `## Functional Requirements` — FR#1-FR#8, the 8 requirements.
- `## Acceptance Criteria` — AC#1-AC#7, verification criteria.
- `## Convention Examples` — Hassette property pattern, HassetteHarness pattern, pure function test pattern.
- `## Test Strategy` — per-file breakdown of what changes.
- `## Replacement Targets` — what gets removed/replaced.

## Convention Examples
### Hassette service property pattern

**Source:** `src/hassette/core/core.py:349-354`

```python
@property
def database_service(self) -> DatabaseService:
    """DatabaseService instance for SQLite telemetry storage."""
    if self._database_service is None:
        raise _service_not_wired_error("DatabaseService")
    return self._database_service
```

### Pure function test (existing pattern)

**Source:** `tests/integration/test_core.py:407-424`

```python
def test_graph_validation_catches_missing_type() -> None:
    class _GhostDep(Resource):
        """A resource type absent from the registered child list."""

    class _StubService(DatabaseService):
        restart_spec = RestartSpec()
        depends_on: ClassVar[list[type[Resource]]] = [_GhostDep]

    with pytest.raises(ValueError, match="_GhostDep"):
        validate_dependency_graph([_StubService])
```
