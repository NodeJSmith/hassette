---
topic: "Console identity column format: placement, author marker, short execution id"
date: 2026-10-22
status: Draft
---

# Prior Art: Console Identity Column Format

## The Problem

Spec 133's D7 replaces the console's key=value tail with one identity column: the subject's instance name (or the logger name without `hassette.`), a marker when the framework wrote a line about an app, and a short execution id when a run is in scope. D7 leaves the visual format to #3044. Three choices remain: where the column sits and whether it is padded, how the author marker looks, and how the execution id is shortened. The compact variant is read in the add-on's Supervisor Log tab, mostly on phones.

This brief extends `design/research/2026-10-18-log-identity-axes/prior-art.md`, which established that AppDaemon, HA and Celery print time, level, one identity token and the message, with no tail. It does not repeat that.

## How We Do It Today

`enable_basic_logging` in `src/hassette/logging_.py` uses stock `structlog.dev.ConsoleRenderer`, which appends every bound key as `key=value`, `None` values included. Records already carry `author`, `instance_name` and `execution_id` (`LogIdentityFilter`, `CorrelationFilter`). Execution ids are UUIDv7 strings minted in `bus_service.py`, `command_executor.py` and `scheduler_dispatch.py`; no surface (CLI, frontend) shortens them today. #3046 (closed into #3044) decided the compact variant: `log_format="compact"`, time-only timestamp, `pad_level=False`, `pad_event_to=0`, `hassette.` prefix dropped, used by `docker/addon/run.sh`.

## Patterns Found

### Pattern 1: Leading, bracketed, unpadded subject token

**Used by**: Kopf (`[namespace/name] message`), Home Assistant (`[logger.name] message`), Celery (`task_name[task_id]: message`).
**How it works**: The identity sits immediately before the message, delimited by brackets or a colon, at its natural width. Kopf adds the prefix in a formatter from a record attribute (`k8s_ref`) only for text output; JSON output carries the same value as a field instead.
**Strengths**: No width wasted on narrow screens. When the token is absent there is no gap. Greppable.
**Weaknesses**: Messages start at a floating column, so lines don't align.
**Example**: https://raw.githubusercontent.com/nolar/kopf/main/kopf/_core/actions/loggers.py, https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/util/logging.py

### Pattern 2: Fixed-width padded leading name column

**Used by**: AppDaemon (`{appname:<20}`), Docker Compose (`%-<longest+1>s | `).
**How it works**: Pad to a constant or computed width so messages align.
**Strengths**: Scannable on wide terminals.
**Weaknesses**: Padding eats narrow-screen width. Compose's width shifts as services join. No peer was found that discusses narrow or mobile viewers driving this choice; AppDaemon's changelog never revisits its width.
**Example**: https://raw.githubusercontent.com/docker/compose/main/cmd/formatter/logs.go

### Pattern 3: Framework-vs-user shown by a segment's presence, not a marker

**Used by**: Celery (worker lines lack the `task_name[id]:` segment), Prefect (`Flow run 'name' -` only on run loggers), Dagster (`system` log source, event-type string), Kopf (prefix only when an object ref is present).
**How it works**: The framework's lines and the user's lines come from different loggers, so the human line gains or loses a segment.
**Strengths**: ASCII-safe, works in any viewer.
**Weaknesses**: None of these distinguishes "the framework wrote this about task/app X" from "X wrote this" when both carry the same subject token. Hassette's D1 makes that distinction explicit; peers have no precedent for it.
**Example**: https://raw.githubusercontent.com/celery/celery/main/celery/app/defaults.py, https://docs.prefect.io/v3/advanced/logging-customization

### Pattern 4: Glyph for tool-authored lines

**Used by**: Docker Compose's watch logger (blank padding plus ` ⦿ ` in place of `service | `).
**How it works**: A distinct glyph replaces the name column for lines the tool itself wrote.
**Strengths**: Cheap visual separation.
**Weaknesses**: Non-ASCII. Documented breakage on non-UTF-8 sinks (cp1252 consoles: mxdev PR 56). No evidence either way for journald or the Supervisor Log tab.
**Example**: https://raw.githubusercontent.com/docker/compose/main/cmd/formatter/logs.go

### Pattern 5: Run identity on human lines — full id or a human name, never a truncated id

**Used by**: Celery and Dagster (full UUID), Prefect (adjective-noun run name like `'crimson-wolf'`, full id opt-in via format override).
**How it works**: No peer truncates an id in its default human format. Prefect avoids the length problem by printing a generated name instead.
**Strengths**: Full ids are joinable with no ambiguity; names are short and memorable.
**Weaknesses**: A full UUID costs ~36 characters per line, too long for a phone. Names need a generator and collision handling, and aren't joinable without a lookup.
**Example**: https://docs.prefect.io/v3/advanced/logging-customization, https://raw.githubusercontent.com/dagster-io/dagster/master/python_modules/dagster/dagster/_core/log_manager.py

### Pattern 6: Time-only timestamp in add-on log tabs

**Used by**: bashio, the de facto HA add-on logging library: `[{TIMESTAMP}] {LEVEL}: {MESSAGE}` with `%T`, ANSI color per level, no identity token (the tab is already per add-on).
**Strengths**: Confirms #3046's time-only compact variant matches add-on convention.
**Example**: https://raw.githubusercontent.com/hassio-addons/bashio/main/lib/const.sh

## Anti-Patterns

- **Prefix-truncating a UUIDv7.** Not a peer finding but a consequence of Hassette's id type: a UUIDv7's leading 48 bits are a millisecond timestamp, so its first 8 hex characters change only every ~65 seconds and are shared by every execution in that window. A short id must come from the random tail.
- **Nothing was found that peers moved away from.** AppDaemon, HA, Celery, Prefect and Dagster have no recorded changes to default console padding, thread names or tails. structlog's changes (`columns` in 23.3.0, optional level padding in 24.2.0, `pad_event_to` in 25.5.0) are API knobs without stated rationale. Airflow 3 adopted stock `ConsoleRenderer` and kept the key=value tail. "They don't bother" is the finding.

## Relevance to Us

- **Placement**: three of four bracket-style peers lead with an unpadded token, and the add-on convention is phone-first. A trailing token has no peer precedent. Padding has precedent (AppDaemon) but costs width on the compact surface. A leading unpadded `[subject]` matches the closest analogue (Kopf's per-object prefix) and keeps `console` and `compact` the same layout, as D7 requires.
- **Author marker**: Hassette is ahead of peers here; nobody marks framework-about-subject on the same token. Plain ASCII text is the safe choice given the only glyph precedent and the generic non-UTF-8 failures.
- **Execution id**: peers never truncate, but they don't target phone width either. Truncation is Hassette's own call, and it must use the UUIDv7's random suffix, not the prefix.

## Recommendation

- Lead with an unpadded bracketed identity token before the message, the same in `console` and `compact`.
- Mark framework-authored lines about an app with plain ASCII text inside the token, not a glyph.
- Shorten the execution id from the end of the UUID (random bits), not the start, and keep it short enough for phone width. If the web UI or CLI later shows a short id, it should use the same function so ids grep across surfaces.

Coverage was thin on narrow-viewer rationale and on id-truncation conventions (git/docker/OTel lengths were not verified). No peer documents a mobile-driven format decision.

## Sources

Note: these URLs were not live-verified.

### Reference implementations
- https://raw.githubusercontent.com/nolar/kopf/main/kopf/_core/actions/loggers.py — Kopf `[ns/name]` per-object prefix, text-only
- https://raw.githubusercontent.com/docker/compose/main/cmd/formatter/logs.go — Compose padded prefix and ` ⦿ ` tool-line glyph
- https://raw.githubusercontent.com/celery/celery/main/celery/app/defaults.py — Celery process and task log formats, full UUID
- https://raw.githubusercontent.com/dagster-io/dagster/master/python_modules/dagster/dagster/_core/log_manager.py — Dagster message join, `system` source, full run id
- https://raw.githubusercontent.com/dagster-io/dagster/master/python_modules/dagster/dagster/_utils/log.py — Dagster default console format
- https://raw.githubusercontent.com/apache/airflow/main/shared/logging/src/airflow_shared/logging/structlog.py — Airflow 3 stock ConsoleRenderer
- https://raw.githubusercontent.com/home-assistant/core/dev/homeassistant/util/logging.py — HA `LOG_FORMAT`
- https://raw.githubusercontent.com/hassio-addons/bashio/main/lib/const.sh — bashio add-on log format

### Blog posts & writeups
- https://github.com/mxstack/mxdev/pull/56 — emoji in logs breaking cp1252 consoles
- https://support.atlassian.com/bamboo/kb/unicode-characters-from-a-windows-console-are-not-displayed-correctly-in-bamboo-build-logs/ — non-ASCII rendering failures

### Documentation & standards
- https://docs.prefect.io/v3/advanced/logging-customization — Prefect run-name formats
- https://airflow.apache.org/docs/apache-airflow/3.1.7/administration-and-deployment/logging-monitoring/logging-tasks.html — Airflow task log format and `{file:line}`
- https://raw.githubusercontent.com/hynek/structlog/main/CHANGELOG.md — `columns`, `pad_level`, `pad_event_to` history
- https://raw.githubusercontent.com/AppDaemon/appdaemon/dev/docs/HISTORY.md — AppDaemon logging history
