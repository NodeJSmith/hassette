# Known Issues

Durable issues discovered during orchestration that were intentionally not fixed in this run.

## KI-001: `live_server_ws_inject` fixture still duplicates the uvicorn bring-up/teardown logic extracted into `uvicorn_server.py`

Status: resolved (commit 83ecc630 — "refactor(test-utils): migrate live_server_ws_inject onto shared uvicorn helper", not filed as a separate issue since the fix already landed on this branch)
Run: 54
Source: T07
Reason not fixed now: needs-decision
Observed in: T07
Affected files:
- tests/e2e/conftest.py:406-480
- src/hassette/test_utils/uvicorn_server.py:20-72

Issue:
T07's fixer passes extracted the shared live-uvicorn-server bring-up/teardown sequence
(free-port bind, `uvicorn.Config`/`uvicorn.Server` construction, daemon-thread start,
connection-poll loop, `should_exit`/`thread.join` teardown) into
`src/hassette/test_utils/uvicorn_server.py` (`get_free_port`, `start_uvicorn_server`,
`stop_uvicorn_server`), and migrated three of the four `tests/e2e/conftest.py` fixtures that
previously hand-rolled it (`live_server`, `live_server_starting`, `live_server_ws`). The fourth,
`live_server_ws_inject` (lines 406-480), was left un-migrated: it still inlines the identical
free-port + `uvicorn.Config`/`Server` + thread-start + poll-loop (lines 422-460, byte-for-byte the
same poll logic as `start_uvicorn_server`) and the identical stop sequence (lines 474-478,
byte-for-byte the same as `stop_uvicorn_server`). A future change to the poll timeout, the
connection-refused backoff, or the startup error message — all now centralized in
`uvicorn_server.py` — will silently miss this fixture, and the two implementations can drift
independently. Both the code reviewer (MEDIUM, iteration N) and the integration reviewer (HIGH,
iteration 3 final) independently flagged this as the same underlying gap.

Why deferred:
This fixture also patches `server.startup` to capture the server's running event loop before
starting the thread (`broadcast_sync`'s `asyncio.run_coroutine_threadsafe` needs a live loop
reference), which `start_uvicorn_server()` has no hook for today — that need is a legitimate
reason it couldn't call the shared helper as-is. Closing the gap requires an actual API decision
between two shapes reviewers proposed (add an `on_startup: Callable | None` hook to
`start_uvicorn_server()` that's invoked from inside the patched `server.startup`, vs. extract just
the "wait until accepting connections" poll loop into its own reusable helper e.g.
`wait_for_server_ready(port)` that both `start_uvicorn_server()` and this fixture call), and the
findings-fix loop's fixer-pass budget for T07 is exhausted. This is test-infrastructure
duplication only — the production auth-check code in `web/routes/ws.py` this task actually
implements is unaffected and independently verified correct by both reviewers.

Recommended follow-up:
Pick one of the two shapes above, apply it to `start_uvicorn_server()`, and migrate
`live_server_ws_inject` to call the shared helper the same way the other three fixtures do —
removing the duplicated poll-loop and stop-sequence code from `tests/e2e/conftest.py`.

Acceptance criteria:
- `live_server_ws_inject` no longer hand-rolls `uvicorn.Config`/`Server` construction, the
  connection-poll loop, or the stop sequence — it calls `start_uvicorn_server()` /
  `stop_uvicorn_server()` (or their extended signatures) like `live_server_ws`.
- The event-loop capture (`broadcast_sync`'s requirement) still works via whichever hook
  mechanism is added.
- No behavior change to the `broadcast_sync` API or any test that depends on this fixture.

## KI-002: `test_missing_token_401_gives_clear_hint` is not isolated from ambient machine state

Status: resolved (commit 77600aa4 — "test(cli): use shared client factory and isolate data_dir test", not filed as a separate issue since the fix already landed on this branch)
Run: 54
Source: T09
Reason not fixed now: out-of-scope
Observed in: T09
Affected files:
- tests/unit/cli/test_client.py:589-597

Issue:
`test_missing_token_401_gives_clear_hint` (tests/unit/cli/test_client.py:589-597) builds its
config with the module-level `_make_config()` helper (line 53), which does not set `data_dir`.
`HassetteConfig.data_dir` defaults to `default_data_dir()`
(src/hassette/config/helpers.py:81-89), which resolves — in order — the
`HASSETTE__DATA_DIR`/`HASSETTE_DATA_DIR` env var, `/data` (Docker convention), or
`platformdirs.user_data_path`: a real, shared, machine-global directory, not an isolated
per-test path. `HassetteCLIClient` reads the persisted token from
`config.data_dir / TOKEN_FILENAME` (src/hassette/cli/client.py:74). If that resolved directory
happens to contain a real `.web_api_token` file — e.g. a developer who has run `hassette run`
locally, or a persistent `/data` volume in a dev container — the test's assumption that no
token resolves would be violated, and its assertion that `"has hassette been started"` appears
in stderr output would fail, not because the feature is broken but because the test wasn't
isolated from ambient machine state. Its sibling test
`test_resolved_token_401_omits_missing_token_hint` (line 599) correctly uses
`_make_config_for_auth(tmp_path, ...)` (line 501) for the same feature area, confirming this is
an inconsistency/oversight in this one test rather than a deliberate choice.

Why deferred:
This is a test-isolation flakiness issue only — the shipped `client.py` bearer-token-attachment
and 401-hint behavior is correct and already covered by passing regression tests (including the
sibling test above, which uses proper isolation). The fix is a one-line swap
(`_make_config()` → `_make_config_for_auth(tmp_path)`) but T09's fixer-pass budget for this run
is exhausted.

Recommended follow-up:
In `test_missing_token_401_gives_clear_hint`, replace `config = _make_config()` with
`config = _make_config_for_auth(tmp_path)` and add the `tmp_path: Path` fixture parameter to the
test signature, matching `test_resolved_token_401_omits_missing_token_hint`.

Acceptance criteria:
- `test_missing_token_401_gives_clear_hint` no longer relies on `HassetteConfig`'s default
  `data_dir` resolution — it passes an isolated `tmp_path`-backed `data_dir` explicitly.
- The test still passes and still exercises the "no token resolves, 401 gets the missing-token
  hint" behavior.

## KI-003: The demo auth token `"demo-token"` is hardcoded independently in three files with no single source of truth

Status: filed (#1523)
Run: 54
Source: clean-code
Reason not fixed now: out-of-scope
Observed in: clean-code review (lazy-checker + nitpicker, batch A)
Affected files:
- scripts/docker/ha-demo.yml:36
- scripts/capture_screenshots.py:59
- .mise/tasks/demo-verify:18

Issue:
The literal `"demo-token"` is declared independently in three files spanning three languages —
YAML (`HASSETTE__WEB_API__AUTH_TOKEN` in the docker-compose env block), Python
(`DEMO_AUTH_TOKEN` in `capture_screenshots.py`), and bash (`AUTH_HEADER` in `demo-verify`). Each
site carries a hand-written comment telling the reader to keep the other two in sync ("Must match
X in Y"), which is a tell that this is comment-based synchronization rather than a real single
source of truth. If one is changed without the other two, the demo stack / screenshot capture /
demo-verify pipeline breaks — the failure mode is a 401 against the demo stack, not a compile-time
or type error, so it would only surface at CI/demo-run time.

Why deferred:
Unifying these three requires introducing a new shared mechanism that crosses process/language
boundaries (e.g. a `.env` file docker-compose auto-loads that the Python and bash scripts also
read, with new path-resolution logic in both), not a same-language rename or constant extraction.
That is an infrastructure change to the demo-stack tooling, not a style/hygiene fix, and carries a
real risk of silently breaking `mise run demo`/`capture_screenshots.py` if the interpolation or
path resolution doesn't behave identically across all three consumers — out of scope for a
clean-code pass.

Recommended follow-up:
Introduce a single source of truth for the demo token — e.g. a `scripts/docker/.env` file (or
similar) that docker-compose loads automatically for `ha-demo.yml`, with `capture_screenshots.py`
and `demo-verify` reading the same file/path explicitly — and delete the three independent
literals plus their cross-referencing comments.

Acceptance criteria:
- The demo auth token is defined in exactly one place.
- `mise run demo`, `scripts/capture_screenshots.py`, and `.mise/tasks/demo-verify` all
  authenticate successfully against the demo stack using the single source.
- Changing the token in the one place changes it for all three consumers with no other edit.

## KI-004: `web/auth.py` and its two dedicated test files exceed the project's 400-line "typical" file-size guideline

Status: filed (#1520)
Run: 54
Source: clean-code
Reason not fixed now: needs-decision
Observed in: clean-code review (nitpicker, batch A + batch B)
Affected files:
- src/hassette/web/auth.py (627 lines)
- tests/unit/web/test_auth.py (~550 lines)
- tests/integration/web_api/test_auth.py (~575 lines)

Issue:
`web/auth.py`'s own module docstring already enumerates three independent concerns it bundles:
token resolution/persistence, `trusted_proxies` peer/hostname matching, and bearer/cookie session
auth primitives. At 627 lines it sits well under the 800-line hard cap but comfortably past the
200-400 "typical" guidance in `CLAUDE.md`'s Coding Style section, and each of its three concerns
is independently testable. Its two dedicated test files have grown in step (~550 and ~575 lines),
tracking the same three-concern shape.

Why deferred:
Splitting `web/auth.py` into per-concern modules (e.g. `auth/tokens.py`,
`auth/trusted_proxies.py`, `auth/session.py`) is a real structural refactor: it touches every
importer (`middleware.py`, `routes/auth.py`, `routes/ws.py`, `core/web_api_service.py`,
`cli/client.py`, and all three test files), and choosing the split boundary and re-export shape is
an architectural decision, not a mechanical rename — exactly the kind of judgment call this
clean-code pass is scoped to flag, not perform. Attempting it now, on top of the file-size-driven
edits already made in this same pass, would meaningfully raise the risk of a merge conflict or a
missed import site.

Recommended follow-up:
When `web/auth.py` needs its next substantive addition, split it along the boundary its own
docstring already names (token resolution, trusted-proxy matching, session/cookie auth), splitting
the two test files along the same lines, and update every importer in one dedicated PR.

Acceptance criteria:
- `web/auth.py` is split into per-concern modules, each within the 200-400 line typical range.
- Every existing importer is updated to the new module paths; no behavior change.
- The two test files are split to mirror the new module boundaries.

## KI-005: Repeated trusted-peer/renewal request-building sequence in `test_auth.py` is not extracted to a helper

Status: filed (#1524)
Run: 54
Source: clean-code
Reason not fixed now: out-of-scope
Observed in: clean-code review (lazy-checker, batch B)
Affected files:
- tests/integration/web_api/test_auth.py:282-291, 433-497, 546-578

Issue:
The "build a trusted-peer app, wrap it in an `ASGITransport`, open an `AsyncClient`, issue one
request" sequence (5-7 lines) is repeated near-verbatim across at least 6 tests in the
trusted-proxy/renewal/cookie sections, differing only in the peer IP, `trusted_proxies` args, and
the asserted status code.

Why deferred:
This is a security-relevant test file (the default-deny auth middleware) that already received a
substantial mechanical diff in this same clean-code pass (constant renames, an `_addrinfo`
consolidation). Extracting a shared request-building helper here is a real test refactor —
choosing the helper's parameter shape affects every one of the 6+ call sites — and stacking it on
top of the renames already applied raises the risk of a subtle test-behavior change going
unnoticed in a file whose entire job is proving the auth gate is correct. Better done as its own
reviewed, standalone change.

Recommended follow-up:
Add a small helper (e.g. `_request_from_peer(hassette, peer, trusted_proxies=..., **app_kwargs)`)
that builds the trusted-peer app + transport + client + request in one call, and migrate the 6+
call sites in the trusted-proxy/renewal/cookie sections to use it.

Acceptance criteria:
- The repeated app/transport/client/request sequence is extracted to one helper.
- All 6+ affected tests use the helper and still pass with no behavior change.
- No net increase in test file line count beyond what the helper itself adds.
