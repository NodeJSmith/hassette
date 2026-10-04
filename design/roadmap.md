# Roadmap

The single place that says what's being worked on, what's next, and what order actually
matters. Update it when an initiative changes column — not per issue.

Last reviewed: 2026-10-04

## How the pieces fit

| Piece | Means |
|---|---|
| **Milestone** | An initiative. Its description holds the **Done when** line. Being in the milestone means the Done-when needs it |
| **`epic:*` label** | Topic only ("related to HACS"). Apply freely; it never adds scope |
| **`topic:*` / `epic:correctness` labels** | Buckets. Never in a milestone unless an initiative's Done-when needs them |
| **Tracker issue** | Optional — only where there's a brief or discussion to hang off it (#45, #1336, #1540, #1427) |
| **This file** | Which milestone is Now / Next / Later, and the forced orderings |

An initiative gets its milestone when it enters Now, or earlier once its Done-when can be
written (a brief plus filed issues). Having a milestone doesn't mean the work has started.
Until it has one, its `epic:*` label is just the candidate pool.

## How to choose what to work on

1. **Interrupts jump the queue.** A bug hurting a real house (yours or a user's), or a CI flake
   blocking merges, goes first. Fix it, then return to Now.
2. **Otherwise, work the one Now initiative.** Only one. Finishing it is what earns the next one
   the slot.
3. **Between PRs, waiting on CI, or low energy:** pull one small issue from a bucket.
4. **New idea?** File it and leave it in Later. Don't promote it mid-initiative.

## Follow-up issues: the Done-when decides scope

Scope is whatever the Done-when needs, nothing more and nothing less. It isn't locked in when
the milestone is created or when work starts, so a requirement discovered late joins the
milestone the moment the Done-when turns out to depend on it. Work that spawns out of an
initiative (review findings, "while I was in here", edge cases) gets triaged with one question:
**does the milestone's Done-when fail without it?**

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

Order. The workspace, wire package, problem details and lenient parsing are done
(#2381, #2382, #2384, #2385, #2483, #2484). What's left, with the forced orderings in
"Dependency chains" below:

1. Fix the wire contract before anything imports it. Renames are cheap until the client and
   hass-hassette pin these names. Four ratified ledgers, one PR each:
   - #2448 (`design/specs/123-wire-vocabulary-typing/`) and #2508 (`design/specs/124-app-health-unification/`) can land in either order
   - #2509 (`design/specs/125-apps-resource-and-grid/`) needs #2508
   - #2448 (`design/specs/126-wire-naming-and-docs/`) goes last and closes #2448
2. #2386 async transport, error mapping, typed methods in `hassette-client`
3. A release that publishes `hassette-client` with #2386. After it, #2485 (cross-version CI,
   which needs that published client) and step 4 can run in parallel; neither gates the other
4. hass-hassette repo: config flow, coordinator, platforms, HACS release (its own spec). The repo
   doesn't exist yet; until it does, unit C on #45's checklist tracks this step
5. #2506 pinned integration in system-test/demo HA + one end-to-end system test + docs page

The CLI move (#2387, #2388) isn't on this path. The integration needs only the client
transport, so the standalone CLI is its own initiative in Next.

## Next

Ordered. Only the first row is committed to start next; the rest can swap.

| Initiative | Milestone / pool | Why here |
|---|---|---|
| **Testing API redesign** | *Testing API Redesign* (tracker #1336) | Breaking changes to `hassette.testing` belong before 1.0 |
| **Standalone CLI** | *Standalone CLI* (tracker #1540) | Needs #2386. Moves the CLI onto `hassette-client[cli]` and deletes `HassetteCLIClient`, so a laptop can drive a remote server without the framework installed |
| **Runtime correctness sweep** | pool: `epic:correctness` | High-priority runtime bugs (open `epic:correctness` + `priority:high`) plus the `wait_for` races (#2302, #2303, #2304, #2309). Any can be pulled forward as an interrupt |
| **DB retention** | pool: `epic:db-retention` | Self-contained, no dependencies |
| **HACS v0.2** | pool: #1449, #2439 (`epic:hacs`) | WS topic subscriptions, per-instance + app-declared entities, `self.entities` (#1449), WS wire-compat check (#2439) |

## Later

| Initiative | Milestone / pool | Blocked on / note |
|---|---|---|
| **HA add-on** | pool: `epic:ha-addon`, #71 | #1850 (mounted `/apps` don't load) and #616 (`hassette build`); Supervisor discovery arrives with HACS v0.4 |
| **HACS v0.3+** | pool: #594, #46 (`epic:hacs`) | Webhooks (#594), `@template` (#46), HACS default store |
| **v1.0 release** | pool: `release:v1.0.0` | Tag after the testing redesign and every planned breaking change (client split, HACS v0.2 app API) |
| **Frontend visual system alignment** | pool: tracker #1427 (lists all 15 child issues) | Lower priority by choice: frontend is the least familiar area. Needs a very concrete spec before starting. Recreate the milestone from #1427's list when promoted |
| **Frontend quality & facelift** | pool: `area:ui` | Same. Rescope from scratch into a milestone with a Done-when if promoted. Individual UI *bugs* can still come in as interrupts |
| **Feature ideas** | unlabeled `type:enhancement` | The icebox. Promote an idea by making it an initiative, not by starting it |

## Dependency chains

These are the only forced orderings. Anything not on a chain can go in any order.

```
#2508 app health ──> #2509 apps resource + grid ──> #2448 naming + docs (126)
#2448 vocabulary (123) ─────────────────────────> #2448 naming + docs (126)
#2448 naming + docs (126) ──> #2386 client transport ──> client release ──> hass-hassette v0.1 ──> #2506 pinned E2E
                                                     client release ──> #2485 cross-version CI
                         #2386 client transport ──> standalone CLI (#2387 ──> #2388)
hass-hassette v0.1 ──> HACS v0.2 ──> v0.3 webhooks ──> v0.4 add-on discovery
#1850 + #616 Docker fixes ──> HA add-on (#71) ──> v0.4 add-on discovery
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
