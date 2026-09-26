# Roadmap

The single place that says what's being worked on, what's next, and what order actually
matters. Update it when an initiative changes column — not per issue. Issue membership lives on
GitHub (one `epic:*` label or milestone per initiative); ordering and rationale live here.

Last reviewed: 2026-09-26

## How to choose what to work on

1. **Interrupts jump the queue.** A bug hurting a real house (yours or a user's), or a CI flake
   blocking merges, goes first. Fix it, then return to Now.
2. **Otherwise, work the one Now initiative.** Only one. Finishing it is what earns the next one
   the slot.
3. **Between PRs, waiting on CI, or low energy:** pull one small issue from a bucket.
4. **New idea?** File it and leave it in Later. Don't promote it mid-initiative.

## Follow-up issues: scope is frozen when an initiative starts

Every initiative has a **Done when** line, fixed when it enters Now. Work that spawns out of it
(review findings, "while I was in here", edge cases) gets triaged with one question:

**Does the Done-when fail without it?**

- **Yes** → it's part of the initiative: give it the initiative's `epic:*` label or milestone.
- **It's a bug in code this initiative just shipped** → fix it in the current or next PR; it
  doesn't need its own issue unless it's big.
- **No** → file it **without** the epic label, into a bucket (code quality, architecture, docs,
  correctness) or the icebox. It does not extend the initiative.

So a PR that raises five issues usually adds zero to the initiative. The initiative finishes when
its Done-when is true, not when its label goes empty. Leftover labeled issues that turned out not
to be needed get unlabeled at close-out, not worked.

## Now

| Initiative | Tracker | Done when |
|---|---|---|
| **HACS companion v0.1** | `epic:hacs`, #45, `design/specs/113-hacs-companion-integration/brief.md`, `design/specs/114-hassette-client/brief.md` | Integration installed from a HACS custom repo on the maintainer's HA, managing real apps |

Order (spec 114 first; everything after it depends on it):

1. #2384 uv workspace with empty `hassette-wire` / `hassette-client`
2. #2385 wire models and enums → `hassette-wire`
3. #2386 async transport + typed methods in `hassette-client`
4. #2387 CLI moves into `hassette-client[cli]`; #2388 named remote targets
5. hass-hassette repo: config flow, coordinator, platforms, HACS release (its own spec)
6. Pinned integration in system-test/demo HA + one end-to-end system test + docs page

#2381, #2382 can land any time alongside.

## Next

Ordered. Only the first row is committed; the rest can swap.

| Initiative | Tracker | Done when / why here |
|---|---|---|
| **Testing API redesign** | Milestone *Testing API Redesign*, tracker #1336 | #1336's checklist is done or explicitly deferred. Breaking changes to `hassette.testing` belong before 1.0 |
| **Runtime correctness sweep** | `epic:correctness` | High-priority runtime bugs (#1798, #1797, #1716, #1224) plus the `wait_for` races (#2302–#2309). Any of these can be pulled forward as an interrupt |
| **DB retention** | `epic:db-retention` | Self-contained, no dependencies |
| **HACS v0.2** | `epic:hacs` | WS topic subscriptions, per-instance + app-declared entities, `self.entities` (#1449) |

## Later

| Initiative | Tracker | Blocked on / note |
|---|---|---|
| **HA add-on** | `epic:ha-addon`, #71 | #1850 (mounted `/apps` don't load) and #616 (`hassette build`); Supervisor discovery arrives with HACS v0.4 |
| **HACS v0.3+** | `epic:hacs` | Webhooks (#594), `@template` (#46), HACS default store |
| **v1.0 release** | `release:v1.0.0` | Tag after the testing redesign and every planned breaking change (client split, HACS v0.2 app API) |
| **Frontend visual system alignment** | Milestone *Frontend Visual System Alignment* (#1427) | Lower priority by choice: frontend is the least familiar area. Needs a very concrete spec before starting |
| **Frontend quality & facelift** | Milestone *Frontend Quality & Facelift* | Same. Individual UI *bugs* can still come in as interrupts |
| **Feature ideas** | unlabeled `type:enhancement` | The icebox. Promote an idea by making it an initiative, not by starting it |

## Dependency chains

These are the only forced orderings. Anything not on a chain can go in any order.

```
spec 114 client split ──> hass-hassette v0.1 ──> HACS v0.2 ──> v0.3 webhooks ──> v0.4 add-on discovery
#1850 + #616 Docker fixes ──────────────────────────────────────────────────────> HA add-on (#71)
testing redesign + all breaking changes ──> v1.0 tag
```

## Buckets (never "done", never in Now)

| Bucket | Tracker | Use for |
|---|---|---|
| Correctness | `epic:correctness` | Runtime bugs; also a Next initiative when it's time for a sweep |
| Code quality | Milestone *Code Quality*, `topic:code-quality`, `source:quality-scanner` | Small mechanical fixes |
| Architecture | Milestone *Architecture*, `topic:architecture` | Structural work; promote to an initiative if a cluster grows (e.g. restart hardening: #1689, #1767, #1721) |
| Docs | `type:documentation` | Followability and accuracy fixes |
| Test/CI infra | `area:testing`, `type:CICD` | Flakes (#2363, #2364) become interrupts when they block merges |
