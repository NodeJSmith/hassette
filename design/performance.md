# Performance: hot paths and profiling

The shared target list for performance work, plus a py-spy recipe that was run end to end. Part of #1119.

Benchmark issues that measure these paths:

- #3305: `pytest-benchmark` harness, the `benchmarks` nox session, and the scheduler job-queue benchmark
- #3306: telemetry write throughput
- #3234: parent of #3305 and #3306
- #1077: bus load/pressure harness (event dispatch is measured there, not in `tests/benchmarks/`)
- #3236: CI regression check on the most stable metric (blocked on the above)

## Hot paths

| Path | Entry point | Metric |
|---|---|---|
| Event dispatch (bus) | `BusService.dispatch` → `BusService._dispatch` per matched listener (`src/hassette/core/bus_service.py`), then `CommandExecutor.execute_handler` (`src/hassette/core/command_executor.py`) | Events per second delivered to N listeners; `BusService.dispatch_pending_count` backlog under sustained load |
| Telemetry write path | `CommandExecutor.enqueue_record` → `CommandExecutor.serve` → `execution_pipeline.drain_and_persist` / `persist_batch` (`src/hassette/core/execution_pipeline.py`) → `TelemetryRepository.persist_execution_batch` (`src/hassette/core/telemetry/repository.py`). Registration writes go through `DatabaseService.submit` / `enqueue` (`src/hassette/core/database_write_queue.py`) | Execution records persisted per second at production batch settings; `CommandExecutor.get_drop_counters` stays at zero |
| Scheduler job queue | `JobQueue.add`, `pop_due_and_peek_next`, `remove_job` (`src/hassette/scheduler/job_queue.py`), driven by `SchedulerService.serve` (`src/hassette/core/scheduler_service.py`) | Time per operation as the queue grows (N jobs) |
| Dashboard and log queries | `/api/telemetry/app-grid` and `/api/telemetry/executions` (`src/hassette/web/routes/telemetry.py`), `/api/logs/recent` (`src/hassette/web/routes/logs.py`), all backed by `TelemetryQueryService` (`src/hassette/core/telemetry/`) | p50/p95 request latency against a populated DB |
| Startup | `cmd_run` (`src/hassette/cli/commands/run.py`) → `run_server` → `Hassette.run_forever` (`src/hassette/core/core.py`); import time comes from `src/hassette/startup_clock.py` | Two numbers from the startup log: the `since hassette import` figure on `Starting Hassette...`, and the gap from that line to `Hassette is running.` |

## py-spy recipe

### Standard workload

Seed the `large-volume` scenario into a data directory, then point `hassette run` at a Home Assistant instance and that directory. The demo HA container from `scripts/docker/ha-demo.yml` works; start only its `homeassistant` service on a spare port, with `HA_CONFIG_PATH` pointing at a copy of `tests/fixtures/demo-ha-config` (`scripts/demo_stack.py` shows the copy and its ignore list).

```bash
uv run python scripts/seed_db.py --scenario large-volume --output /tmp/hassette-profile/data/hassette.db
```

Raise retention when running against the seeded DB. The seed data is anchored at `REFERENCE_INSTANT` (`scripts/seed_scenarios/base.py`), so with default retention the startup cleanup deletes every seeded execution and log row before anything gets profiled:

```bash
export HASSETTE__DATA_DIR=/tmp/hassette-profile/data
export HASSETTE__DATABASE__RETENTION_DAYS=3650
export HASSETTE__DATABASE__FRAMEWORK_RETENTION_DAYS=3650
export HASSETTE__LOGGING__LOG_RETENTION_DAYS=3650
```

The scenario's apps are not in any config file, so startup retires their listeners and jobs. Their execution and log history stays, which is what the query endpoints read.

### Use Python 3.13

py-spy 0.4.2 could not sample a Python 3.14 process. In the default blocking mode, sampling fell further behind every few seconds and hassette slowed to a crawl mid-import; with `--nonblocking`, most samples errored. Profile under 3.13, the version the `py3.13` image tags ship. Create a separate 3.13 environment instead of replacing the worktree's `.venv`:

```bash
UV_PROJECT_ENVIRONMENT=/tmp/hassette-profile/venv313 uv sync --python 3.13
```

### Local `hassette run`

Launch hassette as a child of py-spy. Attaching to an already-running PID (`py-spy dump --pid`, `py-spy record --pid`) fails with `Permission Denied` when `/proc/sys/kernel/yama/ptrace_scope` is `1` (the Ubuntu and WSL default) unless py-spy runs under `sudo`. A child process is always traceable.

```bash
mkdir -p /tmp/hassette-profile/out
py-spy record --rate 100 --duration 60 \
  -o /tmp/hassette-profile/out/hassette-large-volume.svg \
  -- /tmp/hassette-profile/venv313/bin/python -m hassette --config-file scripts/demo_apps/hassette.toml run
```

When `--duration` elapses, py-spy writes the SVG and hassette exits with it. Drive the path under study while it records; for the query path, loop `curl` over the endpoints in the table above with the web API token in an `Authorization: Bearer` header.

Write flamegraphs outside the repository (`/tmp/hassette-profile/out/` above). They are per-machine artifacts, not something to commit.

### Docker image

The image does not ship py-spy, and a non-root user runs hassette. Two things are required, both verified against `ghcr.io/nodejsmith/hassette` (py3.13 tag):

1. Start the container with `--cap-add=SYS_PTRACE`. Without it, py-spy fails with `Failed to get process executable name ... Permission denied (os error 13)` even as root.
2. Run py-spy as root inside the container: `docker exec -u root`.

py-spy's release binary is static, so mount it in (or `docker cp` it into a running container):

```bash
docker run -d --name hassette-profile --cap-add=SYS_PTRACE \
  -v "$(readlink -f "$(command -v py-spy)")":/usr/local/bin/py-spy:ro \
  ... ghcr.io/nodejsmith/hassette:<tag>
```

The image has no `ps` or `pgrep`. `tini` is PID 1 and `scripts/docker_start.sh` ends in `exec hassette run`, so hassette is tini's child. List processes from `/proc` to find it:

```bash
docker exec hassette-profile sh -c 'for p in /proc/[0-9]*; do echo "${p#/proc/} $(tr "\0" " " < $p/cmdline)"; done'
docker exec -u root hassette-profile py-spy dump --pid <pid>
docker exec -u root hassette-profile py-spy record --duration 60 --pid <pid> -o /tmp/hassette.svg
docker cp hassette-profile:/tmp/hassette.svg /tmp/hassette-profile/out/
```

The Docker check ran against a placeholder Python process that imports hassette and sleeps, not a full `hassette run` connected to HA. Recording an idle process fails with `No stack counts found`; add `--idle` when the target is mostly waiting.

### Reading the flamegraph for asyncio

By default py-spy drops idle samples, so the graph shows CPU time only. Time a coroutine spends awaiting I/O does not appear unless `--idle` is passed.

- **Event loop work** sits under `asyncio.run` → `run_forever` → `_run_once` → `_run (asyncio/events.py)`. Each frame above `_run` is the callback or coroutine step running at that moment. A coroutine's caller chain stops at the step the loop resumed, so attribute time by the topmost hassette frame, not by who awaited it.
- **SQLite work** runs on aiosqlite's own thread, under `threading.run` → `_connection_worker_thread (aiosqlite/core.py)`. Query and write cost lands here, not under the event loop.
- **Web requests** appear under the starlette/fastapi routing frames inside the event loop; the route function and the `TelemetryQueryService` method sit above them.
- **Import time** appears under `runpy` → `importlib._bootstrap` frames before the loop starts. In a short recording it can dominate the graph; lengthen `--duration` or discount it.

### Observed run

One 60-second recording on jessica-desktop (WSL2), 3.13 environment, `large-volume` DB, demo-app config, with 30 rounds of `curl` over the three query endpoints:

- Of 329 non-idle samples: about 35% in the event loop, 31% in import, 25% in the aiosqlite worker thread, 10% in web request handling.
- Query latency (curl `time_total`, mean / max): `app-grid` 12.5 ms / 28 ms, `logs/recent?limit=1000` 7.7 ms / 22 ms, `executions` 3.7 ms / 10 ms.
- Startup: about 1.0 s from `import hassette` to `Starting Hassette...`, then about 0.4 s to `Hassette is running.`

These figures are point observations from a fast machine with a small DB. They are not a baseline: the `large-volume` scenario holds about a thousand executions, far below a months-old install. Capturing a baseline on Pi-class hardware is #1119's job.
