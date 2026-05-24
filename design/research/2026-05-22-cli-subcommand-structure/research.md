---
topic: "CLI subcommand structure patterns"
date: 2026-05-22
status: Draft
---

# Prior Art: CLI Subcommand Structure Patterns

## The Problem

CLI command hierarchy is a long-term commitment — restructuring after users have muscle memory and scripts is prohibitively expensive (Docker's permanent dual-syntax problem). With ~20 read-only endpoints across domains (status, apps, logs, listeners, jobs, telemetry, config, events, services), the structure chosen now will persist for the life of the tool.

## How We Do It Today

Hassette has no CLI subcommands — just `hassette` with 3 argparse flags to start the framework. The web UI organizes data by domain (apps page, listeners page, scheduler page, telemetry dashboard). The API uses REST resource paths (`/api/apps`, `/api/bus/listeners`, `/api/scheduler/jobs`, `/api/telemetry/app/{key}/health`).

## Patterns Found

### Pattern 1: Noun-Verb (Resource-First)

**Used by**: GitHub CLI, Docker (management commands), Azure CLI, Heroku CLI, Temporal CLI, Prefect CLI, AWS CLI

**How it works**: Top-level subcommand is a noun (domain resource). Verbs underneath represent actions. `tool <resource> <action>`. Users learn resource names from the domain and verbs from a small standard set. Help text groups naturally — `tool <resource> --help` shows everything for that resource.

**Strengths**: Scales well as resources grow. Groups related operations. Matches product domain language. AI-agent-friendly. Enables verb reuse across resources.

**Weaknesses**: Can feel verbose for common operations. Requires good noun names upfront — renaming later is painful.

**Examples**: [GitHub CLI](https://cli.github.com/manual/), [Azure CLI guidelines](https://github.com/Azure/azure-cli/blob/dev/doc/command_guidelines.md)

### Pattern 2: Verb-First (Action-First)

**Used by**: kubectl, git, PowerShell

**How it works**: Top-level subcommand is a verb (action). Resource is a positional argument. `tool <action> <resource>`. Works when a small set of verbs applies uniformly to many resource types.

**Strengths**: Low learning curve for verbs. Adding resources requires no restructuring. Polymorphic commands (`kubectl get` works on anything).

**Weaknesses**: Help for a single verb lists all resources (unwieldy at scale). Harder to discover what's available for a specific resource.

**Examples**: [kubectl reference](https://kubernetes.io/docs/reference/kubectl/)

### Pattern 3: Bare Noun as Default Action (List)

**Used by**: Heroku CLI, partially GitHub CLI

**How it works**: `tool <noun>` with no verb defaults to listing. Never create a `*:list` command. Makes the most common operation the shortest to type.

**Strengths**: Reduces command count. Most ergonomic for the most common operation.

**Weaknesses**: Ambiguous if noun is also a valid action context. Doesn't work if listing isn't the most common operation.

**Example**: [Heroku CLI style guide](https://devcenter.heroku.com/articles/cli-style-guide)

### Pattern 4: Two-Level Depth Limit

**Used by**: clig.dev (recommendation), Temporal CLI, GitHub CLI, Docker

**How it works**: Max two levels for common path (`tool noun verb`). Third level only for sub-resources. clig.dev and Temporal both make this explicit.

**Strengths**: Keeps commands typeable and memorizable. Help stays manageable.

**Weaknesses**: Some domains have natural three-level hierarchies. Can create awkward compound nouns.

**Examples**: [clig.dev](https://clig.dev/), [Temporal CLI proposal](https://github.com/temporalio/proposals/blob/master/cli/000-cli-improve-commands-discoverability.md)

### Pattern 5: Domain Concept Alignment

**Used by**: Azure CLI, GitHub CLI, Prefect CLI

**How it works**: CLI noun names must match existing concepts in the product's UI, docs, and API. If the UI says "listeners," the CLI says `listener`, not `handler` or `subscription`.

**Strengths**: Zero translation cost. New users recognize concepts immediately.

**Weaknesses**: Domain names may be long. Product naming changes force CLI changes.

**Example**: [Azure CLI guidelines](https://github.com/Azure/azure-cli/blob/dev/doc/command_guidelines.md)

## Anti-Patterns

- **Starting flat, restructuring later**: Docker's permanent dual-syntax problem. Choose grouped structure before v1. ([source](https://nickjanetakis.com/blog/docker-tip-24-docker-ps-vs-docker-container-ls))
- **Inconsistent verbs across resources**: Temporal's old CLI used different words for the same operation per resource. Fixed by standardizing on a verb set. ([source](https://github.com/temporalio/proposals/blob/master/cli/000-cli-improve-commands-discoverability.md))
- **Noun as both group and action**: If a command has subcommands, it should be a grouping identifier, not an action. ([source](https://learn.microsoft.com/en-us/dotnet/standard/commandline/design-guidance))

## Relevance to Us

Hassette's CLI maps cleanly to noun-verb:
- The domain objects are clear: app, listener, job, log, event, config, service
- The API already uses resource-oriented paths (`/api/apps`, `/api/bus/listeners`, `/api/scheduler/jobs`)
- The web UI organizes by the same domains
- v1 is read-only, so the verb set is tiny: mostly bare-noun-as-list plus `show` for detail views

The telemetry per-app endpoints (`/api/telemetry/app/{key}/health`, `/api/telemetry/app/{key}/activity`) map to `hassette app health <key>` and `hassette app activity <key>` — natural two-level commands under the `app` noun.

The two-level depth limit works perfectly for v1. When mutations arrive in v2 (`hassette app start <key>`, `hassette app stop <key>`), they slot in as new verbs under existing nouns.

## Recommendation

**Noun-verb with bare-noun-as-list and two-level depth limit.** This is the dominant pattern for server query tools, validated by GitHub CLI, Prefect, Temporal, Azure CLI, and Heroku. It scales well for future mutations and WebSocket streaming.

Proposed mapping for hassette's ~20 GET endpoints:

| Command | Endpoint | Notes |
|---------|----------|-------|
| `hassette status` | `/api/health` | System overview (special — not a list) |
| `hassette app` | `/api/apps/manifests` | List all apps |
| `hassette app config <key>` | `/api/apps/{key}/config` | App config detail |
| `hassette app source <key>` | `/api/apps/{key}/source` | App source code |
| `hassette app health <key>` | `/api/telemetry/app/{key}/health` | App health metrics |
| `hassette app activity <key>` | `/api/telemetry/app/{key}/activity` | App activity feed |
| `hassette listener` | `/api/bus/listeners` | List all listeners |
| `hassette listener <id>` | `/api/telemetry/handler/{id}/invocations` | Listener invocations |
| `hassette job` | `/api/scheduler/jobs` | List all jobs |
| `hassette job <id>` | `/api/telemetry/job/{id}/executions` | Job executions |
| `hassette log` | `/api/logs/recent` | Recent logs |
| `hassette log execution <id>` | `/api/logs/by-execution/{id}` | Logs by execution |
| `hassette event` | `/api/events/recent` | Recent events |
| `hassette config` | `/api/config` | System config |
| `hassette service` | `/api/services` | HA services list |
| `hassette telemetry` | `/api/telemetry/status` | Telemetry status |
| `hassette dashboard` | `/api/telemetry/dashboard/app-grid` | Dashboard grid |

## Sources

### Reference implementations
- https://cli.github.com/manual/ — GitHub CLI command structure
- https://docs.docker.com/reference/cli/docker/ — Docker CLI (flat → grouped evolution)
- https://kubernetes.io/docs/reference/kubectl/ — kubectl verb-first pattern
- https://docs.prefect.io/v3/api-ref/python/prefect-cli-deployment — Prefect CLI (cyclopts, noun-verb)
- https://github.com/Azure/azure-cli/blob/dev/doc/command_guidelines.md — Azure CLI command guidelines

### Blog posts & writeups
- https://nickjanetakis.com/blog/docker-tip-24-docker-ps-vs-docker-container-ls — Docker flat→grouped migration cost
- https://smallstep.com/blog/the-poetics-of-cli-command-names/ — Command naming ergonomics
- https://eng.localytics.com/exploring-cli-best-practices/ — CLI structure as long-term commitment
- https://dev.to/uenyioha/writing-cli-tools-that-ai-agents-actually-want-to-use-39no — AI-agent-friendly CLI design

### Documentation & standards
- https://devcenter.heroku.com/articles/cli-style-guide — Heroku CLI style guide (bare-noun-as-list, naming)
- https://clig.dev/ — Community CLI guidelines (two-level depth limit)
- https://github.com/temporalio/proposals/blob/master/cli/000-cli-improve-commands-discoverability.md — Temporal CLI restructuring proposal
- https://learn.microsoft.com/en-us/dotnet/standard/commandline/design-guidance — .NET command design guidance
