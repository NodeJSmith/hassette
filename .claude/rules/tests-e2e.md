---
paths:
  - "tests/e2e/**"
---

# E2E Tests (Playwright)

Browser tests against a mock-backed server. Excluded from the default `pytest` run (`addopts` in `pyproject.toml` deselects `e2e`); CI runs them via `nox -s e2e`, so don't run them locally unless you're debugging one.

```bash
# One-time browser install (system deps need sudo; if it fails: sudo uv run playwright install-deps chromium)
uv run playwright install --with-deps chromium

uv run nox -s e2e                                 # what CI runs
uv run pytest -m e2e -v -n 4                      # e2e only, parallel
uv run pytest -m e2e --headed                     # debug with a visible browser
uv run pytest -m e2e --headed --tracing on -k test_sidebar_navigation
```

**SPA build:** `ensure_spa_built()` in `conftest.py` and the `e2e` nox session rebuild the frontend when `spa/index.html` is missing or older than any frontend source or the root `pyproject.toml` (`tools/frontend/spa_build.py`), so local runs exercise the current UI. Builds are serialized across xdist workers and nox sessions by a per-checkout file lock in the temp dir.

**Ingress prefix:** `test_ingress_prefix.py` runs the UI behind `tests/support/ingress_proxy.py`, an HA-ingress-shaped aiohttp proxy that 404s anything outside the prefix. A frontend URL built from an absolute path fails it.

For visual QA of real behavior, use the demo stack instead (`.claude/rules/demo-and-screenshots.md`).
