---
task_id: "T04"
title: "Refactor structural invariant tests to pure functions"
status: "planned"
depends_on: ["T01", "T02"]
implements: ["FR#5", "FR#6", "AC#2"]
---

## Summary
Refactor 4 structural invariant tests to call `topological_levels()` and `topological_sort()` directly instead of reading `hassette_instance._init_waves` and `hassette_instance._init_order`. This trades direct attribute verification for pure-function testability — the same trade-off `test_init_order_has_no_cycles` already makes.

## Target Files
- modify: `tests/integration/test_resource_deps.py`
- modify: `tests/integration/test_core.py`

## Prompt
### In `tests/integration/test_resource_deps.py`:

Add imports at the top:
```python
from hassette.utils.service_utils import topological_levels
```

Refactor these 3 tests to compute waves from `children` instead of reading `_init_waves`:

**`test_init_waves_cover_all_children`** (line 10-14):
```python
async def test_init_waves_cover_all_children(hassette_instance: Hassette) -> None:
    """topological_levels() covers every registered child type."""
    child_types = list(dict.fromkeys(type(c) for c in hassette_instance.children))
    waves = topological_levels(child_types)
    wave_types = {t for wave in waves for t in wave}
    assert wave_types == set(child_types), "Waves must include every registered child type"
```

**`test_init_waves_have_no_duplicates`** (line 17-20):
```python
async def test_init_waves_have_no_duplicates(hassette_instance: Hassette) -> None:
    """Each type appears in exactly one wave."""
    child_types = list(dict.fromkeys(type(c) for c in hassette_instance.children))
    waves = topological_levels(child_types)
    all_types = [t for wave in waves for t in wave]
    assert len(all_types) == len(set(all_types)), "Each type must appear in exactly one wave"
```

**`test_init_waves_respect_dependency_ordering`** (line 23-34):
```python
async def test_init_waves_respect_dependency_ordering(hassette_instance: Hassette) -> None:
    """Every depends_on type appears in an earlier wave than its dependent."""
    child_types = list(dict.fromkeys(type(c) for c in hassette_instance.children))
    waves = topological_levels(child_types)
    type_set = {t for wave in waves for t in wave}
    wave_index = {t: i for i, wave in enumerate(waves) for t in wave}

    for t in type_set:
        for dep in t.depends_on:
            if dep in type_set:
                assert wave_index[dep] < wave_index[t], (
                    f"{t.__name__} (wave {wave_index[t]}) depends on {dep.__name__} "
                    f"(wave {wave_index[dep]}), but dep is not in an earlier wave"
                )
```

### In `tests/integration/test_core.py`:

Verify that `topological_sort` is already imported (line 33: `from hassette.utils.service_utils import topological_sort, validate_dependency_graph`). No new import needed.

Refactor **`test_init_order_contains_all_children`** (line ~392-396):
```python
def test_init_order_contains_all_children(hassette_instance: Hassette) -> None:
    """topological_sort() contains exactly the same types as the registered children."""
    child_types = list(dict.fromkeys(type(c) for c in hassette_instance.children))
    init_order = topological_sort(child_types)
    assert set(init_order) == set(child_types)
```

Note: `test_init_order_has_no_cycles` (line ~399-404) already calls `topological_sort()` directly — no change needed.

## Focus
- `topological_levels` is at `src/hassette/utils/service_utils.py:114`. `topological_sort` is at line 16.
- The `dict.fromkeys(type(c) for c in hassette_instance.children)` pattern preserves insertion order while deduplicating — matching what `wire_services()` does at `core.py:222`.
- These two tests still need `hassette_instance` (for `children`) — they can't be fully standalone pure-function tests because they validate the real service graph that `wire_services()` creates.
- `test_service_with_depends_on_waits_for_dep` and `test_service_without_depends_on_proceeds_immediately` in `test_resource_deps.py` use `hassette_instance.add_child()` which is a public method — no changes needed for those.

## Verify
- [ ] FR#5: test_resource_deps.py uses no private-attr service access (structural tests use `children` + pure functions)
- [ ] FR#6: All 4 structural tests call `topological_levels()` or `topological_sort()` directly — no `_init_waves` or `_init_order` access anywhere in the 3 test files
- [ ] AC#2: `test_init_waves_cover_all_children`, `test_init_waves_have_no_duplicates`, `test_init_waves_respect_dependency_ordering`, and `test_init_order_contains_all_children` call pure functions directly
