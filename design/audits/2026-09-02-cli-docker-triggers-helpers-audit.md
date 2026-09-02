# CLI, Docker Onboarding, Triggers & Helpers Audit — 2026-09-02 (run 4, mop-up)

**Scope:** The remaining territory from the run 1–3 coverage map: the `hassette` CLI end to end
(`src/hassette/cli/` + `docs/pages/cli/`), the Docker onboarding path (Dockerfile, entrypoint,
compose snippets, `docs/pages/getting-started/docker/`), project scaffolding, the scheduler
trigger layer (`scheduler/triggers.py`, `scheduler/classes.py`), and the helpers API
(`api/helpers.py`).

**Not covered this run:** `scheduler/scheduler.py`/`scheduler_service.py` dispatch internals
(run 1 territory; only the trigger-facing seams were re-read), the AppDaemon migration docs
journey, `sync.py` facades.

**Method:** Same as runs 1–3 — Fable deep read as the engine, two Sonnet reader agents for
breadth (CLI systematic pass; Docker/scaffolding docs-vs-code), every reader claim re-verified
against the actual code before making this report, and live verification for everything
probeable:

- Full CLI command + error-path matrix against the live demo stack (auth, happy paths, bad app
  keys, bad flags, server down, bad token, `--json` variants; captured in session scratchpad).
- A 200-with-non-JSON probe server to reproduce the CLI's malformed-response path.
- A raw WebSocket probe against the demo HA container (2026.8) replaying the exact payloads
  `HelperClient` sends — counter create / increment / reset with and without
  `return_response`.
- **The published Docker image (`ghcr.io/nodejsmith/hassette:latest-py3.13`) run twice against
  the demo HA, following the getting-started Docker journey file-for-file** — once exactly as
  documented (fails) and once with `HASSETTE__APPS__DIRECTORY=/apps` added (works) — proving
  both the bug and the root cause end to end.
- `whenever` DST probes for trigger construction edges (spring-forward gap, fall-back
  ambiguity).

---

## Verdict up front

Three of the four surfaces are in better shape than their age would predict: the CLI's docs
have essentially **zero drift** (every endpoint, flag, exit code, and error string checked out),
the trigger layer's DST handling is unusually careful, and the Docker image itself is solidly
built. The debt concentrates in two places, both continuations of the audit series' running
theme of **silent absence**:

1. **The documented Docker quick start does not work.** The published image never looks at the
   `/apps` mount the docs (and the Dockerfile's own `VOLUME`) advertise — a newcomer's first
   app loads zero apps with no error, no log line naming the scanned directory, and a
   troubleshooting page that actively misdiagnoses it (F1, live-confirmed on the published
   image).
2. **The counter helper shortcuts have never worked against real Home Assistant** — every
   `helpers.increment()/decrement()/reset()` call is rejected by HA with
   `service_validation_error`, invisible to the test suite because every helper test mocks
   `ws_send_and_wait` (F2, live-confirmed against HA 2026.8).

Both flagship findings share a meta-cause worth keeping: **the project's internal configs and
tests already do the right thing** (demo compose and Docker integration tests set
`HASSETTE__APPS__DIRECTORY`; helper CRUD works fine over the same WS plumbing) — the drift is
specifically between what the maintainers' own tooling knows and what ships to users.

---

## Findings

Severity reflects user impact. Every finding marked **live-confirmed** was reproduced this run.

### HIGH

#### F1. The documented Docker quick start loads zero apps — live-confirmed on the published image

Followed `docs/pages/getting-started/docker/index.md` exactly: `mkdir` project with
`config/` + `apps/`, the documented `docker-compose.yml` snippet (mounting `./apps:/apps`),
`config/.env` with token + base_url, the documented `apps/my_app.py`. Result on
`ghcr.io/nodejsmith/hassette:latest-py3.13` (0.52.0):

```
"Found 0 active apps"
"Found 0 inactive apps"
"Hassette is running."
```

No error, no warning, no log line naming the directory that was scanned. The docs' promised
`Hello from Docker!` never appears. Re-running the identical setup with one env var added —
`HASSETTE__APPS__DIRECTORY=/apps` — auto-detects and runs the app immediately.

Root cause chain (each link verified):

- `AppsConfig.directory` defaults to `Path.cwd() / "apps"` (`config/models.py:471`); the final
  image stage sets `WORKDIR /app` (`Dockerfile:79`) and nothing ever changes cwd — so the real
  default inside the container is **`/app/apps`**.
- The Dockerfile sets `ENV HASSETTE__APP_DIR=/apps` (`Dockerfile:99`) — **not a real settings
  field**. With `extra="allow"` on `HassetteConfig` (`config/config.py:55`) it is silently
  absorbed as an unused extra. Its only consumer is `docker_start.sh:29`, which uses it for the
  `requirements.txt` scan — and that subsystem's `/apps` default *works*, which is exactly what
  makes the app-loading half easy to miss.
- `docs/pages/getting-started/docker/troubleshooting.md:35` states "Hassette looks for apps at
  `/apps` inside the container" (false) and tells the user to verify the mount with
  `ls /apps` — which succeeds, actively steering the user away from the real cause.
- The project's own internal configs prove the correct spelling:
  `tests/test_docker_integration.py:36` and `scripts/docker/ha-demo.yml:32` both set
  `HASSETTE__APPS__DIRECTORY` explicitly.

**Fix shape (layered):** (a) `HASSETTE__APPS__DIRECTORY=/apps` in the Dockerfile — one line,
the published image then matches its own `VOLUME` declaration; (b) a startup INFO line
"resolved apps directory: X (N apps found)" so this class of misconfiguration is diagnosable
from logs (this also covers the scaffolding gap in F6); (c) fix troubleshooting.md's claim and
add the real failure mode to it; (d) related open question from the reader pass, worth a note
in the same issue: fixed uid-1000 container user vs. host bind-mount ownership on non-1000
hosts (unverified, NAS-style deployments).
`type:bug, area:config, size:medium, priority:high` (+ docs half).

#### F2. Counter helper shortcuts (`increment`/`decrement`/`reset`) never work against real HA — live-confirmed

`HelperClient.increment()` (`api/helpers.py:296-308`, same for `decrement`/`reset`) calls
`call_service(..., return_response=True)` — the comment says "surfaces HA errors instead of
fire-and-forget." But `_call_service` forwards `return_response` verbatim into the WS
`call_service` command (`api/api.py:590`), and `counter.increment`/`decrement`/`reset` are
`SupportsResponse.NONE` services. Real HA (2026.8, demo container) rejects the exact payload
hassette sends:

```
{"success": false, "error": {"code": "service_validation_error", "message":
"Validation error: An action which does not return responses can't be called with
return_response=True", ...}}
```

So every call to any of the three shortcuts raises `FailedMessageError`. The same probe
confirmed the control case: the identical call with `return_response=False` succeeds — and the
WS `call_service` **still returns a result envelope** (success/error + context), which is the
mechanism the fix wants.

The test suite cannot see this: every test in `tests/integration/test_api_helpers.py` mocks
`ws_send_and_wait`, so the HA-side contract (`supports_response`) is exactly at the mocked
boundary — the same blind spot run 1 flagged for core services. Helper CRUD
(`list`/`create`/`update`/`delete`) was probed too and works correctly against real HA.

**Fix shape:** send the service call through `ws_send_and_wait` *without*
`return_response` — the result envelope still surfaces HA errors (proven by the probe), which
is what the shortcuts wanted from `return_response=True` in the first place. That capability
("awaited call_service that doesn't request a service response") arguably belongs on
`call_service` itself rather than being special-cased in the shortcuts. Follow-up worth
bundling: one thin system test that exercises `HelperClient` against the system-test HA
container so this contract class stays covered.
`type:bug, area:api, size:small, priority:high`.

### MEDIUM

#### F3. `app health` reports "excellent" for apps that don't exist — live-confirmed; extends #1825

`hassette app health nonexistent_app` (and `--instance 99` on a real app) prints a full healthy
card — `health_status excellent`, exit 0, same in `--json`. Server-side:
`GET /api/telemetry/app/{app_key}/health` (`web/routes/telemetry.py:115-132`) never validates
the key against the manifest registry — it aggregates over zero rows and the zero-invocation
path classifies as "excellent" (documented at `telemetry.py:106-110` for the *known-app*
zero-invocation case, but the unknown-key case is a different problem). An operator
health-checking a typo'd key gets a green light.

Existing issue **#1825** already covers CLI-side `--app` validation for listing commands and
empty-result disambiguation. This finding extends it server-side: the health endpoint should
404 for a key the manifest registry doesn't know (the registry is queryable without telemetry),
which fixes every consumer at once. The CLI reader's related LOW — `resolve_instance()`
skips app-key validation only on the numeric-instance path (`cli/client.py:196-212`) — is the
same validation work and should ride along. Proposed disposition: scope-extending comment on
#1825 rather than a new issue (mirrors the F2/#1610 pattern from run 3).

#### F4. CLI prints a raw 25-line traceback on a 2xx response with a non-JSON or model-incompatible body — live-confirmed

Pointed the CLI at a server returning `200` with a non-JSON body: `json.decoder.JSONDecodeError`
traceback straight to the terminal, bypassing the CLI's entire designed error surface. Cause
(reader claim, verified in code and live): `client.py:135-148` only catches `ValueError` for the
`tolerate_503` path; cyclopts' `exit_on_error` guards token parsing only, and nothing in
`launcher()`/`entrypoint()` catches command-body exceptions. Realistic triggers: `-s` pointed at
the wrong service, a reverse proxy serving an HTML error page with 200, version skew between CLI
and server (`model_validate` failure takes the same unguarded path).

**Fix shape:** catch `JSONDecodeError`/`ValidationError` in `client.get()` and emit the standard
error framing ("response from {url} is not a hassette API response — check --server-url /
version skew"), non-zero exit, JSON envelope in `--json` mode.
`type:bug, area:cli, size:small`.

#### F5. The documented compose snippet sets `HASSETTE__LOG_LEVEL`, a silent no-op — and any typo'd `HASSETTE__*` var is swallowed

`docs/pages/getting-started/docker/snippets/docker-compose.yml:15` sets
`HASSETTE__LOG_LEVEL=info`. The real field is `logging.log_level`
(`config/models.py`, nested), so the correct var is `HASSETTE__LOGGING__LOG_LEVEL`; there is no
top-level `log_level` field. With `extra="allow"` the wrong var is silently absorbed — a user
bumping to `debug` for troubleshooting gets no error and no effect.

Two layers: (a) docs fix, one line (`type:documentation, size:small`); (b) the structural
version — F1 and F5 are the *same* failure mechanism (`extra="allow"` eating misspelled env
vars without a sound). An enhancement worth filing separately: at startup, WARN listing
unconsumed `HASSETTE__*` environment keys (and extra top-level TOML keys) that matched no known
field — one log line that would have caught both the Dockerfile's own dead var and every future
user typo. `type:enhancement, area:config, size:small`.

#### F6. No scaffolding story: `hassette init` doesn't exist, layout errors are silent — DISCUSS

Confirmed against the full CLI command tree: no `init`/scaffold command; both quickstarts are
manual `mkdir` + copy-paste, `hassette.toml` is never introduced in getting-started (the Docker
flow is entirely env-var-driven), and the failure modes of a mis-built layout are silent (F1's
zero-apps case; a `[hassette.apps.<name>]` entry missing `filename`/`class_name` is a WARNING
that skips the app, `config/config.py:409`).

The sharp edge (no startup echo of the resolved apps directory) is folded into F1's fix. The
open design question for Jessica: is a minimal `hassette init` wanted (write
`hassette.toml` + `apps/` + `.env` skeleton + example app — it would also give the Docker docs
a place to introduce the toml), or is the manual flow + F1's logging fix enough for a framework
this size? Not filing without that call.

### LOW

#### F7. Piped/non-TTY CLI output truncates every table at 80 columns

`stdout_console = Console(file=sys.stdout)` (`cli/output.py:31`) → Rich's 80-col non-TTY
default. Live: `hassette app | grep motion_lights` cannot match — the cell renders as
`motion…`. The log table is the worst case (multi-line tracebacks ellipsized per-line inside
table cells, plus three zero-width columns at 80 cols). `--json` is the designed escape hatch,
so LOW — but grep-ability of the human output is cheap to restore (wide fallback width or
respect `COLUMNS` when piped). `type:enhancement, area:cli, size:small`.

#### F8. `hassette log --instance` is a phantom flag

Declared as a normal parameter (`cli/commands/log.py:32-44`) so it appears in `--help` and
shell completions, but its only behavior is `error_usage("--instance is not supported on the
log command")` (live-verified: clean error, exit 1). Hide it or say "(not supported)" in its
help string. `type:enhancement, area:cli, size:small` — can ride with F7 or F13.

#### F9. Trigger API nits: `After` has no `hours=`; `timedelta=` silently wins over `seconds`/`minutes`

`After(seconds, minutes, timedelta)` (`scheduler/triggers.py:134-145`) — no `hours=` while
`Every` has it, and passing both `timedelta=` and `seconds=` silently ignores the latter
(docstring says "mutually exclusive" but nothing raises). Add `hours=` and raise on the
conflicting combination. `type:enhancement, area:scheduler, size:small, topic:dx`.

#### F10. Helper `helper_id` vs `entity_id` is a documented-nowhere distinction

`update()`/`delete()` take the storage-collection id (`record.id` — a slug for YAML-imported
helpers, opaque for UI-created ones), not the entity_id every HA user actually knows. Passing
`"input_boolean.vacation_mode"` fails with HA's generic not-found. Docstrings just say "The ID
of the helper." Cheap fixes: name the distinction in the docstrings + helpers docs page;
optionally accept an entity_id and resolve/strip. Also noted: `create()` logs INFO while
`update()`/`delete()` log DEBUG (`helpers.py:216,254,285`) — equally-mutating operations,
asymmetric levels. `type:documentation/enhancement, area:api, size:small, topic:dx`.

#### F13. CLI dead code / latent inconsistencies (pre-existing, mechanical)

From the CLI reader pass, each verified: `JsonArg` in `cli/types.py:100` defined and never
used; `run.py:62` raises bare `SystemExit` instead of routing through `error_usage` (latent —
`run` has no `--json` today, but the shape breaks the envelope convention the moment a flag is
added); `client.py:228-229` unreachable `AssertionError` after a `NoReturn` call. One
code-quality issue per `clean-code-findings.md` (`topic:code-quality`, Code Quality milestone,
`area:cli, size:small`).

### Notes (no action proposed)

- **DST disambiguation is inconsistent between `Once` and the cron-backed triggers** — `Once`
  construction resolves an ambiguous fall-back time via `whenever`'s compatible mode (earlier
  fold), while `CronTrigger._dst_safe_from_dt` deliberately picks fold=1 (later). Probed both;
  neither crashes, gaps shift +1h cleanly. A once-a-year one-hour divergence between two trigger
  types; not worth machinery.
- **`Every`/`After`/`Cron` `trigger_id()` collisions** (two `Every(hours=1)` jobs share
  `every:3600`) initially looked like heap-identity trouble given `Once`'s shadowing comment —
  verified harmless: `trigger_id` participates only in `Job.matches()` dedup, which also
  compares callable/args/group, so the collision is exactly the intended dedup semantics.
- **`parse_entity_time` + `daily=False` on a time-only entity** parks the job (`WAITING`) once
  today's occurrence passes until the entity changes — correct per the docstrings, but the
  docs page for `EntityTime` should keep steering `input_datetime`-style time-only sources to
  `daily=True` (it currently does; no drift found).

---

## Strengths (genuine, keep doing these)

- **CLI docs have zero drift.** Every documented endpoint, flag, response field, exit code, and
  error-message string was cross-checked against routes/models/implementation and matched —
  unusual, and worth calling out given how fast this surface moves.
- **The CLI's plumbing conventions are right:** exit 1 vs 2 (HTTP/usage vs network) verified
  live; `--json` mode's "stdout is exactly one JSON document" discipline holds everywhere
  probed; the `--since` error message (formats listed, compound-duration exclusion named) is a
  model error string; the credential-resolution chain's scoped `CredentialSource` design makes
  the loopback-only gate structurally hard to break.
- **The trigger layer's hard parts are handled with care:** croniter fall-back ambiguity is
  UTC-normalized and fold-disambiguated with a single summary log; catch-up is bounded
  (`MAX_CRON_ITERATIONS`) with a timezone-preserving skip-ahead; the `WAITING` sentinel design
  (typed, off-heap, three documented legs in `scheduler_service`) is exactly the "model the
  domain" shape.
- **The Docker image itself is well built** — multi-stage, non-root, tini, correct healthcheck
  guidance (`/api/health/live` vs `ready`, restart-loop warning), and the dependency-install
  entrypoint flow is accurate and documented honestly.
- **The native (non-Docker) quickstart is accurate end to end** — the cwd-relative apps default
  genuinely works there; only the Docker translation broke.

---

## Slate

| # | Severity | Finding | Proposed disposition |
|---|---|---|---|
| F1 | HIGH | Docker quick start loads zero apps (published image, live) | New issue, `priority:high` (Dockerfile + startup log + troubleshooting + compose snippet; uid-1000 note) |
| F2 | HIGH | Counter shortcuts always rejected by real HA (live) | New issue, `priority:high` (+ system-test note) |
| F3 | MEDIUM | Health endpoint 200-excellent for unknown app/instance (live) | Scope-extending comment on #1825 (server-side 404 + resolve_instance validation) |
| F4 | MEDIUM | Raw traceback on malformed 2xx response (live) | New issue |
| F5 | MEDIUM | `HASSETTE__LOG_LEVEL` no-op in docs; typo'd env vars swallowed | Two: docs one-liner + unconsumed-env-var warning enhancement |
| F6 | MEDIUM | No `hassette init` / silent layout errors | **Discuss with Jessica** (init command yes/no; logging half folds into F1) |
| F7 | LOW | 80-col truncation when piped | New issue (can bundle F8) |
| F8 | LOW | `log --instance` phantom flag | Bundle with F7 |
| F9 | LOW | `After` missing `hours=`, silent arg precedence | New issue |
| F10 | LOW | helper_id vs entity_id undocumented; log-level asymmetry | New issue |
| F13 | LOW | CLI dead code / SystemExit bypass | Code Quality issue |

Also absorbed by existing issues (no action): bare-401 wording → #1823; CLI app-table health
visibility → #1825; log-table traceback framework-frame noise → #1832.

## Meta-findings for the series

1. **Internal-vs-shipped drift** (F1, F5): the demo stack, integration tests, and maintainer
   muscle memory all carry correct configuration that the shipped Dockerfile and public docs
   lack. Anything the demo/test configs set explicitly is worth auditing for "does the public
   path get this too?"
2. **Mock-boundary contract blindness** (F2, continuing run 1's theme): both flagship bugs live
   exactly at a mocked seam. The system-test suite is the designed home for these; F2's issue
   proposes the first helper-surface system test.
