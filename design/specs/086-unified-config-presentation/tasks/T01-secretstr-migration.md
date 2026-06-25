---
task_id: "T01"
title: "Migrate HassetteConfig.token to SecretStr"
status: "done"
depends_on: []
implements: ["FR#10", "AC#7", "AC#8"]
---

## Summary
Change `HassetteConfig.token` from `str | None` to `SecretStr | None` so secrets are masked by type at
the schema layer. This is sequenced first because it can silently break real Home Assistant auth (REST +
WebSocket) while unit tests, which mock the boundary, stay green. Update every site that reads the token
as a plain string, fix the `preserve_config` snapshot footgun, and update the test sites whose `== str`
comparisons break immediately. Verify on `nox -s system`/`e2e`, not just unit tests.

## Target Files
- modify: `src/hassette/config/config.py` — `token: SecretStr | None`; `auth_headers` + `truncated_token`
  unwrap via `.get_secret_value()`; token docstring notes it is a `SecretStr`.
- modify: `src/hassette/core/websocket_service.py` — `access_token` via `.get_secret_value()`.
- modify: `src/hassette/test_utils/harness.py` — `preserve_config` → `config.model_copy(deep=True)`.
- modify: `src/hassette/test_utils/mock_hassette.py` — token comparison for `SecretStr`.
- modify: `tests/unit/test_make_test_config.py` — `== TEST_TOKEN` comparisons (lines 16, 32).
- modify: `tests/unit/test_config_token_optional.py` — `== "env-token-value"` / `== "ha-token-value"` (36, 49).
- modify: `tests/unit/cli/test_commands_run.py` — `== "test-token"` (63).
- modify: `tests/integration/test_websocket_service.py` — `access_token` dict assertion (247).
- read: `tests/unit/test_config.py` — `truncated_token` regression guard (525-552), must stay green.
- create: `tests/integration/test_preserve_config_secretstr.py` — focused AC#8 test: `preserve_config`
  round-trips a `SecretStr` token without poisoning it to the masked value.
- read: `tests/integration/test_hot_reload.py`, `tests/integration/test_service_watcher.py` — existing
  `preserve_config` consumers; confirm they still pass after the `model_copy(deep=True)` change.
- read: `src/hassette/server.py` — line 15 `if not config.token` is safe as-is; do NOT change it.

## Prompt
Implement the `SecretStr` migration described in the design doc's `## Architecture → Backend: SecretStr
migration` section. Verified facts about Pydantic 2.12.3 `SecretStr`: it has `__len__` but not `__bool__`
(so truthiness falls back to length — `bool(SecretStr(""))` is `False`), it is not subscriptable (slicing
raises `TypeError`), it is not JSON-serializable (`json.dumps` raises), `str(SecretStr)` renders
`"**********"`, and `SecretStr(...) == "<str>"` is `False`.

1. In `src/hassette/config/config.py`: change `token` to `SecretStr | None` (keep the `AliasChoices`).
   Fix `auth_headers` (`f"Bearer {self.token}"` → `self.token.get_secret_value()`) and `truncated_token`
   (the `len()` works, but the slicing `self.token[:n]` / `[-n:]` must operate on `.get_secret_value()`).
   Update the `token` field docstring to note it is a `SecretStr`.
2. In `src/hassette/core/websocket_service.py` (around 557-564): the value sent as `access_token` must be
   `config.token.get_secret_value()`, not the `SecretStr` object.
3. Do NOT touch `server.py:15` — `if not config.token` already treats `None` and `""` as falsy correctly.
4. In `src/hassette/test_utils/harness.py` `preserve_config`: replace the `config.model_dump()` snapshot
   with `config.model_copy(deep=True)` and restore by reassigning fields from the copy. A deep copy
   preserves the `SecretStr` object and avoids restoring a masked value under `validate_assignment=True`.
5. Update the test sites that compare `config.token == "<str>"` (mock_hassette.py, test_make_test_config,
   test_config_token_optional, cli/test_commands_run, integration/test_websocket_service) to compare
   `.get_secret_value()` or construct `SecretStr` fixtures.
6. Confirm `tests/unit/test_config.py:525-552` (truncated_token) still passes unchanged.

Run the affected unit/integration tests with `uv run pytest -n 4 <files>`. Then verify real auth on the
heavy suites — `uv run nox -s system` and `uv run nox -s e2e` — or rely on CI, which runs both; do not
claim auth works from unit tests alone (they mock the WS/REST boundary).

## Focus
The danger is silent breakage: `auth_headers`, `truncated_token`, and the WS `access_token` all pass
type-check and unit tests (which mock the boundary) but break the live HA connection. `truncated_token`
is subtle — `len()` works on `SecretStr` so only the slicing breaks. `preserve_config` is used by
module-scoped reuse tests (`test_hot_reload.py`, `test_service_watcher.py`) — confirm they still pass.
Do not introduce `model_dump(mode="json")` anywhere on a path that round-trips the token, as it masks.

## Verify
- [ ] FR#10: A live Hassette authenticates to Home Assistant over REST and WebSocket with the `SecretStr`
  token (REST `auth_headers` and WS `access_token` carry the real value, not `"**********"`).
- [x] AC#7: `nox -s system` and `nox -s e2e` pass (the surfaces that exercise real auth) — not only unit tests. <!-- RESOLVED 2026-06-25: ran locally — system 5 passed (3.13+3.14, incl. WS reconnection auth), e2e 166 passed (3.11/3.13/3.14). -->
- [ ] AC#8: the new `tests/integration/test_preserve_config_secretstr.py` asserts `preserve_config`
  restores a `SecretStr` token (via `get_secret_value()`) unchanged across a scope, and the existing
  consumers (`test_hot_reload.py`, `test_service_watcher.py`) still pass.
