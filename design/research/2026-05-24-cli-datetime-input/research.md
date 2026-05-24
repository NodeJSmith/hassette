---
topic: "CLI date/time input conventions for --since flags"
date: 2026-05-24
status: Draft
---

# Prior Art: CLI Date/Time Input Conventions

## The Problem

CLI tools that filter by time need to accept human-friendly input and convert it to whatever the backend expects. The format choices made at v1 are hard to change — scripts depend on them, users build muscle memory, and error messages become documentation. The key decisions: which formats to accept, how to handle timezone ambiguity for naive timestamps, and whether to use one flag or two.

## How We Do It Today

Hassette has no CLI date/time input parsing. The REST API endpoints accept `since` as a Unix epoch float (`since: float | None`). The `whenever` library is already a dependency for all date/time operations in the codebase, with `date_utils.py` providing timezone-aware conversion utilities. The CLI design currently specifies a `--since` flag accepting relative durations (`Nd`, `Nh`, `Nm`) and ISO 8601 timestamps, converting to epoch float before forwarding to the API. The timezone behavior for naive timestamps is unspecified.

## Patterns Found

### Pattern 1: Single Flag with Format Sniffing

**Used by**: Git (`--since`/`--after`), Docker (`--since`/`--until`), journalctl (`--since`/`--until`)

**How it works**: A single `--since` flag accepts multiple input formats. The parser detects the format automatically: duration strings, ISO timestamps, and optionally keywords. Docker tries formats in order: Go duration, then RFC 3339, then Unix epoch. Git's approxidate is far more aggressive, trying dozens of patterns including natural language. journalctl falls in between with a defined set from the `systemd.time(7)` spec.

**Strengths**: Minimal flag surface. Users don't need to remember which flag accepts which format. Covers the most common case (relative duration) with minimal typing.

**Weaknesses**: Ambiguity risk if formats overlap. Format sniffing code is harder to document exhaustively. Error messages need to list all accepted formats.

**Example**: [Docker container logs](https://docs.docker.com/reference/cli/docker/container/logs/)

### Pattern 2: Separate Flags for Duration vs. Timestamp

**Used by**: kubectl (`--since` for duration, `--since-time` for timestamp)

**How it works**: Two distinct flags — one accepts only relative durations, the other only absolute timestamps. Mutually exclusive; specifying both is an error.

**Strengths**: Zero ambiguity. Each flag has exactly one format. Documentation and error messages are trivial. Type-safe at the parser level.

**Weaknesses**: More flags. Slightly more verbose. Users must know which flag to use before typing.

**Example**: [kubectl logs](https://man.archlinux.org/man/kubectl-logs.1.en)

### Pattern 3: Short Suffix Duration Format

**Used by**: Docker, kubectl, Prometheus, Grafana, journalctl (most tools)

**How it works**: Three main conventions exist for duration strings:

1. **Go-style** (`1h30m10s`): Compact, no spaces, limited to h/m/s in stdlib. Lacks `d`/`w` units.
2. **systemd-style** (`1h 30min`, `2d 3h`): Space-separated, richer unit names. Linux-specific.
3. **Short suffix** (`1h`, `7d`, `30m`): Single value with unit. Universally understood.

The common denominator across all tools: `s` (seconds), `m` (minutes), `h` (hours), `d` (days). Week (`w`) support varies; month and year are rare and ambiguous.

**Strengths**: `7d` is immediately readable with no documentation. Short suffix is the lowest common denominator.

**Weaknesses**: `m` vs `M` ambiguity (minutes vs months). Compound durations (`1h30m`) add parser complexity for marginal benefit.

**Example**: [Prometheus duration syntax](https://prometheus.io/docs/prometheus/latest/querying/basics/)

### Pattern 4: Naive Timestamps as Local Time

**Used by**: Git, journalctl (user-facing tools); Docker, kubectl use UTC

**How it works**: The convention splits by context:
- **User-facing CLI tools** (Git, journalctl): interpret naive timestamps as **local time**
- **Server/container tools** (Docker, kubectl): interpret as **UTC**

The general rule: tools that run on a user's machine interpret naive timestamps in the user's timezone. Tools that run on servers use UTC because "local time" is meaningless in a container.

**Strengths**: Local time matches user intuition for interactive use ("show me logs since 2 PM" = 2 PM in my timezone).

**Weaknesses**: Ambiguity when the same tool is used interactively and in scripts across timezones. No universal standard.

**Example**: [journalctl](https://man7.org/linux/man-pages/man1/journalctl.1.html) (local), [Docker](https://docs.docker.com/reference/cli/docker/container/logs/) (UTC)

### Pattern 5: Progressive Omission Defaults

**Used by**: journalctl, Git

**How it works**: Partial timestamps get sensible defaults. journalctl: omit time = midnight, omit date = today, omit seconds = :00. So `--since "2024-01-15"` means midnight Jan 15, and `--since "14:30"` means today at 2:30 PM.

**Strengths**: Reduces typing for common cases. Date-only filtering without forcing `T00:00:00`.

**Weaknesses**: "Missing date = today" can surprise. Needs clear documentation.

**Example**: [journalctl](https://man7.org/linux/man-pages/man1/journalctl.1.html)

## Anti-Patterns

- **Undocumented date formats**: GitHub CLI issue [#5639](https://github.com/cli/cli/issues/5639) — users couldn't discover accepted formats because `--help` didn't list them. Every date flag must document its formats with examples in help text.

- **Natural language without boundaries**: Git's approxidate accepts "tea time" and "noon" but has no spec — the accepted set is defined by reading C source. If you support natural language, define and document the vocabulary. For focused tools, skip it entirely.

- **Go duration format without day units**: Go's `time.ParseDuration` lacks `d` and `w`. Docker claims "Go duration strings" but uses a custom parser. Document your actual format, not the format you based it on.

- **Silent misinterpretation**: Treating `1m` as 1 minute when the user meant 1 month, or guessing date format order (MM/DD vs DD/MM). Reject ambiguous input with a clear error rather than guessing.

## Relevance to Us

Hassette's CLI is a user-facing tool that runs on the user's machine — the journalctl/Git pattern applies, not the Docker/kubectl server pattern. Naive timestamps should be local time.

The design already specifies single-flag format sniffing (`--since` accepts both durations and timestamps), which matches Pattern 1 — the dominant convention. The short suffix format (`1h`, `7d`, `30m`) is already in the design and is universally understood.

The gap is:
1. **Timezone behavior** — not specified. Should be local time (Pattern 4).
2. **Compound durations** — the design says `Nd`, `Nh`, `Nm` (single value + suffix). This is sufficient — compound durations (`1h30m`) add parser complexity for marginal benefit in a log-filtering context.
3. **Progressive omission** — not specified. `--since 2026-05-22` should mean midnight May 22, not a parse error. Worth adopting (Pattern 5).
4. **Help text** — must include format examples (anti-pattern: undocumented formats).

The `whenever` library provides the timestamp parsing backbone. The `--since` converter converts to epoch float for the API. The design just needs the timezone and omission decisions pinned.

## Recommendation

**Single `--since` flag (Pattern 1) with short suffix durations and ISO 8601, local time for naive timestamps, progressive omission.**

Accepted formats for `--since`:

| Input | Interpretation | Example |
|-------|---------------|---------|
| `Ns`, `Nm`, `Nh`, `Nd`, `Nw` | Relative: now minus N units | `1h`, `7d`, `30m`, `2w` |
| `YYYY-MM-DDTHH:MM:SS±HH:MM` | Absolute: ISO 8601 with timezone | `2026-05-22T14:00:00-04:00` |
| `YYYY-MM-DDTHH:MM:SSZ` | Absolute: ISO 8601 UTC | `2026-05-22T18:00:00Z` |
| `YYYY-MM-DDTHH:MM:SS` | Absolute: naive, local time | `2026-05-22T14:00:00` |
| `YYYY-MM-DD` | Absolute: date only, midnight local time | `2026-05-22` |

No natural language. No compound durations. No `M` (months) or `y` (years) — ambiguous with minutes and rarely needed for log filtering.

Help text for `--since` should include: `"Filter by time. Accepts relative (1h, 7d, 30m) or absolute (2026-05-22, 2026-05-22T14:00:00) timestamps. Naive timestamps use local time."`

## Sources

### Reference implementations
- https://docs.docker.com/reference/cli/docker/container/logs/ — Docker --since format
- https://man.archlinux.org/man/kubectl-logs.1.en — kubectl --since vs --since-time split
- https://man7.org/linux/man-pages/man1/journalctl.1.html — journalctl --since with progressive omission
- https://git-scm.com/docs/git-log — Git --since with approxidate
- https://prometheus.io/docs/prometheus/latest/querying/basics/ — Prometheus duration syntax

### Blog posts & writeups
- https://alexpeattie.com/blog/working-with-dates-in-git/ — Git approxidate deep dive
- https://oneuptime.com/blog/post/2026-02-08-how-to-filter-docker-container-logs-by-time-range/view — Docker log filtering patterns
- https://github.com/cli/cli/issues/5639 — GitHub CLI undocumented date format issue
- https://github.com/cli/cli/issues/12901 — GitHub CLI relative date feature request

### Documentation & standards
- https://www.freedesktop.org/software/systemd/man/latest/systemd.time.html — systemd.time(7) duration and timestamp spec
- https://click.palletsprojects.com/en/stable/parameter-types/ — Click DateTime parameter type
- https://pkg.go.dev/time — Go time.ParseDuration (no day/week units)
