# Roadmap

The single place that says what's being worked on, what's next, and what order actually
matters. Update it when an initiative changes column — not per issue.

Last reviewed: 2026-09-26

## How the pieces fit

| Piece | Means |
|---|---|
| **Milestone** | An initiative. Its description holds the **Done when** line. Being in the milestone means committed scope |
| **`epic:*` label** | Topic only ("related to HACS"). Apply freely; it never adds scope |
| **`topic:*` / `epic:correctness` labels** | Buckets. Never in a milestone unless an initiative's Done-when needs them |
| **Tracker issue** | Optional — only where there's a brief or discussion to hang off it (#45, #1336) |
| **This file** | Which milestone is Now / Next / Later, and the forced orderings |

An initiative gets its milestone when it enters Now (or earlier, if it's first in Next and its
scope is already clear). Until then its `epic:*` label is just the candidate pool.

## How to choose what to work on

1. **Interrupts jump the queue.** A bug hurting a real house (yours or a user's), or a CI flake
   blocking merges, goes first. Fix it, then return to Now.
2. **Otherwise, work the one Now initiative.** Only one. Finishing it is what earns the next one
   the slot.
3. **Between PRs, waiting on CI, or low energy:** pull one small issue from a bucket.
4. **New idea?** File it and leave it in Later. Don't promote it mid-initiative.

## Follow-up issues: scope is frozen when an initiative starts

Work that spawns out of an initiative (review findings, "while I was in here", edge cases) gets
triaged with one question: **does the milestone's Done-when fail without it?**

- **Yes** → put it in the milestone.
- **It's a bug in code this initiative just shipped** → fix it in the current or next PR; it
  doesn't need its own issue unless it's big.
- **No** → file it with no milestone. Give it the `epic:*` label if it's on-topic, or a bucket
  label. It does not extend the initiative.

The initiative is done when its Done-when is true. At close-out, move any issues still in the
milestone that turned out not to be needed out of it, then close the milestone.

## Now

| Initiative | Milestone | Brief / tracker |
|---|---|---|
| **HACS companion v0.1** | *HACS v0.1* | #45, `design/specs/113-hacs-companion-integration/brief.md`, `design/specs/114-hassette-client/brief.md` |

Order (spec 114 first; everything after it depends on it). Dependencies follow the work-split
table in `design/specs/114-hassette-client/brief.md`, which wins if the two disagree:

1. #2384 uv workspace with empty `hassette-wire` / `hassette-client`, and #2382 RFC 9457
   problem details on the app action routes, and #2381 nested-path boundary rules
   (independent of each other; any order)
2. #2385 wire models and enums → `hassette-wire` — needs #2384 and #2381
3. #2386 async transport, error mapping, typed methods in `hassette-client` — needs #2385 and
   #2382 (the error mapping uses #2382's stable codes)
4. #2387 CLI moves into `hassette-client[cli]`, then #2388 named remote targets
5. hass-hassette repo: config flow, coordinator, platforms, HACS release (its own spec)
6. Pinned integration in system-test/demo HA + one end-to-end system test + docs page

## Next

Ordered. Only the first row is committed; the rest can swap.

| Initiative | Milestone / pool | Why here |
|---|---|---|
| **Testing API redesign** | *Testing API Redesign* (tracker #1336) | Breaking changes to `hassette.testing` belong before 1.0 |
| **Runtime correctness sweep** | pool: `epic:correctness` | High-priority runtime bugs (#1798, #1797, #1716, #1224) plus the `wait_for` races (#2302–#2309). Any can be pulled forward as an interrupt |
| **DB retention** | pool: `epic:db-retention` | Self-contained, no dependencies |
| **HACS v0.2** | pool: `epic:hacs` | WS topic subscriptions, per-instance + app-declared entities, `self.entities` (#1449) |

## Later

| Initiative | Milestone / pool | Blocked on / note |
|---|---|---|
| **HA add-on** | pool: `epic:ha-addon`, #71 | #1850 (mounted `/apps` don't load) and #616 (`hassette build`); Supervisor discovery arrives with HACS v0.4 |
| **HACS v0.3+** | pool: `epic:hacs` | Webhooks (#594), `@template` (#46), HACS default store |
| **v1.0 release** | pool: `release:v1.0.0` | Tag after the testing redesign and every planned breaking change (client split, HACS v0.2 app API) |
| **Frontend visual system alignment** | pool: tracker #1427 (lists all 15 child issues) | Lower priority by choice: frontend is the least familiar area. Needs a very concrete spec before starting. Recreate the milestone from #1427's list when promoted |
| **Frontend quality & facelift** | pool: `area:ui` | Same. Rescope from scratch into a milestone with a Done-when if promoted. Individual UI *bugs* can still come in as interrupts |
| **Feature ideas** | unlabeled `type:enhancement` | The icebox. Promote an idea by making it an initiative, not by starting it |

## Dependency chains

These are the only forced orderings. Anything not on a chain can go in any order.

```
spec 114 client split ──> hass-hassette v0.1 ──> HACS v0.2 ──> v0.3 webhooks ──> v0.4 add-on discovery
#1850 + #616 Docker fixes ──────────────────────────────────────────────────────> HA add-on (#71)
testing redesign + all breaking changes ──> v1.0 tag
```

## Buckets (never "done", never a milestone)

| Bucket | Label | Use for |
|---|---|---|
| Correctness | `epic:correctness` | Runtime bugs; becomes a milestone when a sweep is promoted to Now |
| Code quality | `topic:code-quality`, `source:quality-scanner` | Small mechanical fixes |
| Architecture | `topic:architecture` | Structural work; promote to an initiative if a cluster grows (e.g. restart hardening: #1689, #1767, #1721) |
| Docs | `type:documentation` | Followability and accuracy fixes |
| Test/CI infra | `area:testing`, `type:CICD` | Flakes (#2363, #2364) become interrupts when they block merges |
