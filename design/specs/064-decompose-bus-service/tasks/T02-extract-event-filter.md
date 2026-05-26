---
task_id: "T02"
title: "Extract EventFilter to core/event_filter.py"
status: "done"
depends_on: []
implements: ["FR#3", "AC#3", "AC#4"]
---

## Summary
Create `src/hassette/core/event_filter.py` containing the `EventFilter` class. This extracts event skip logic (`_setup_exclusion_filters` and `_should_skip_event`) from BusService into a standalone utility with no Resource/Service inheritance. Note: `_should_log_event` stays on BusService due to mixed caching semantics.

## Prompt
1. Create `src/hassette/core/event_filter.py` with:
   - Module docstring (one line, same pattern as `registration_tracker.py`)
   - `EventFilter` class with `__init__` accepting config values:
     - `excluded_domains: tuple[str, ...] | None`
     - `excluded_entities: tuple[str, ...] | None`
     - `logger: logging.Logger`
   - `__init__` calls `self.setup(excluded_domains, excluded_entities)` to parse into exact/glob sets
   - `setup(domains, entities)` method — logic from `bus_service.py:820-841` (`_setup_exclusion_filters`), storing `_excluded_domains_exact`, `_excluded_domain_globs`, `_excluded_entities_exact`, `_excluded_entity_globs`, `_has_exclusions`
   - `should_skip(topic, event)` method — logic from `bus_service.py:843-882` (`_should_skip_event`)

2. Imports needed:
   - `from hassette.events import Event, HassPayload`
   - `from hassette.utils.glob_utils import matches_globs, split_exact_and_glob`
   - Type imports: `EventPayload`

3. Constants to move (used only by `_should_skip_event`):
   - `_SYSTEM_LOG_SKIP_EVENT_TYPE = "call_service"`
   - `_SYSTEM_LOG_SKIP_DOMAIN = "system_log"`
   - `_SYSTEM_LOG_SKIP_LEVEL = "debug"`

4. Write unit tests in `tests/unit/core/test_event_filter.py`:
   - Test `should_skip` returns False for non-HassPayload events
   - Test `should_skip` returns False for events with no payload
   - Test system_log debug filtering (returns True)
   - Test entity exclusion (exact match and glob)
   - Test domain exclusion (exact match and glob)
   - Test `_has_exclusions=False` short-circuits (no entity/domain → returns False)
   - Construct EventFilter directly with config values — no BusService dependency

5. Do NOT modify `bus_service.py` yet — that happens in T04.

## Focus
- The existing `_setup_exclusion_filters` is at `src/hassette/core/bus_service.py:820-841`
- The existing `_should_skip_event` is at `src/hassette/core/bus_service.py:843-882`
- `split_exact_and_glob` is at `src/hassette/utils/glob_utils.py` — separates exact strings from glob patterns
- `matches_globs` is at `src/hassette/utils/glob_utils.py` — checks if a string matches any glob in a tuple
- EventFilter snapshots config at construction — document this with a one-line note in the class docstring
- Do NOT move `_should_log_event` — it stays on BusService (see design doc)

## Verify
- [ ] FR#3: `EventFilter` class exists in `src/hassette/core/event_filter.py` with `should_skip(topic, event)` method
- [ ] AC#3: `uv run pyright` reports no new type errors
- [ ] AC#4: `uv run pytest tests/unit/core/test_event_filter.py` passes (confirms no circular imports)
