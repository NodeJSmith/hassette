---
task_id: "T03"
title: "Implement HA source resolution and startup checks"
status: "planned"
depends_on: ["T02"]
implements: ["FR#8", "FR#19", "FR#21", "AC#8", "AC#17"]
---

## Summary
Implements the HA core source resolution module — accepts either a local path or a release tag (with auto-clone), validates the Python version against HA's requirements, and discovers core entity domains by scanning for `CACHED_PROPERTIES_WITH_ATTR_` in component `__init__.py` files.

## Prompt
Create `codegen/src/hassette_codegen/ha_source.py`:

**Source resolution:**
- Accept `--ha-core-path PATH` (validate directory exists, contains `homeassistant/components/`)
- Accept `--ha-release-tag TAG` (shallow clone with `git clone --depth 1 --branch TAG` to a `tempfile.mkdtemp()` path, with 120s subprocess timeout). On `TimeoutExpired`: raise error with URL + elapsed time. Cleanup clone dir in `finally` block.
- Return a `HASource` dataclass with: `path: Path`, `version: str` (tag or git describe), `cleanup: Callable` (no-op for local, rmtree for clone)

**Startup checks (before any extraction):**
- Parse `REQUIRED_PYTHON_VER` from `homeassistant/const.py` via AST (look for the assignment, extract the tuple)
- Compare against `sys.version_info` — if generator Python is older, raise a clear error: "Generator requires Python X.Y.Z+ to parse HA core files (HA requires X.Y.Z, running X.Y.Z)"
- Verify `ruff` is available (`subprocess.run(["ruff", "--version"])`) — clear error if missing

**Domain discovery (FR#21):**
- Scan `homeassistant/components/*/` directories
- For each, check if `__init__.py` contains `CACHED_PROPERTIES_WITH_ATTR_` (fast grep/read)
- For qualifying domains, verify an Entity/ToggleEntity subclass exists (AST check on the class bases)
- Return list of `DiscoveredDomain(name: str, path: Path, has_services_yaml: bool, has_const_py: bool)`

Unit tests in `codegen/tests/test_ha_source.py`:
- Test version check raises on Python < required (mock `sys.version_info`)
- Test domain discovery finds light, fan, sensor (using real HA core at ~/source/core as test fixture)
- Test invalid tag raises clear error (mock subprocess)
- Test timeout raises with URL in message (mock subprocess)

Tests that use `~/source/core` must be guarded with `pytest.mark.skipif(not Path("~/source/core").expanduser().exists(), reason="HA core checkout not available")`. This is a LOCAL dev convenience only — the codegen CI job (T11) always provides the HA checkout, so these tests never skip in CI.

## Focus
- `homeassistant/const.py` has `REQUIRED_PYTHON_VER: Final[tuple[int, int, int]] = (3, 14, 2)` — parse the tuple literal via AST
- There are 30 core entity domains in HA core (verified by grep)
- `services.yaml` exists for most but not all domains (sensor has none — read-only)
- `const.py` exists for most but not all domains (fan defines IntFlag in `__init__.py`)
- Clone of HA core at depth 1 is ~100-200MB — the 120s timeout is generous for this

## Verify
- [ ] FR#8: Tool accepts `--ha-core-path` (local) or `--ha-release-tag` (auto-clone) and resolves to a usable HA source path
- [ ] FR#19: Running on Python < HA's REQUIRED_PYTHON_VER produces a clear startup error naming both versions
- [ ] FR#21: Domains are discovered automatically by scanning for CACHED_PROPERTIES_WITH_ATTR_ + Entity subclass — no manual list
- [ ] AC#8: `--ha-release-tag` mode shallow-clones and generates without a pre-existing checkout
- [ ] AC#17: Running on Python < 3.14 against current HA core produces a startup error, not silent skips
