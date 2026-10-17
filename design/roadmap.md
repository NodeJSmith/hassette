# Roadmap

The single place that says what's being worked on, what's next, and what order actually
matters. Update it when an initiative changes column — not per issue.

Last reviewed: 2026-10-17

## How the pieces fit

| Piece | Means |
|---|---|
| **Milestone** | An initiative. Its description holds the **Done when** line. Being in the milestone means the Done-when needs it |
| **`epic:*` label** | Topic only ("related to HACS"). Apply freely; it never adds scope |
| **`topic:*` / `epic:correctness` labels** | Buckets. Never in a milestone unless an initiative's Done-when needs them |
| **Tracker issue** | Optional — only where there's a brief or discussion to hang off it (#71, #1336, #1540, #1427) |
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

| Initiative | Milestone | Note |
|---|---|---|
| **HA add-on v0.1** | *HA Add-on v0.1* (umbrella #71) | Design: `design/specs/129-ha-addon-v01/design.md`. Spans three repos: hassette, `hassette-addon` and `hass-hassette`. All the code has shipped, including discovery pairing in hass-hassette v0.2.0, except #2711 (service restart retry). When it lands, close #71 and the milestone and promote the first Next row |

## Next

Ordered. Only the first row is committed to start next; the rest can swap.

| Initiative | Milestone / pool | Why here |
|---|---|---|
| **Testing API redesign** | *Testing API Redesign* (tracker #1336) | Breaking changes to `hassette.testing` belong before 1.0 |
| **Standalone CLI** | *Standalone CLI* (tracker #1540) | Unblocked (#2386 shipped). Moves the CLI onto `hassette-client[cli]` and deletes `HassetteCLIClient`, so a laptop can drive a remote server without the framework installed |
| **Runtime correctness sweep** | pool: `epic:correctness` | High-priority runtime bugs (open `epic:correctness` + `priority:high`) plus the remaining `wait_for` races (#2302, #2304). Any can be pulled forward as an interrupt |
| **DB retention** | pool: `epic:db-retention` | Self-contained, no dependencies |
| **HACS app entities** | pool: #1449, #2439, #2611 (`epic:hacs`) | WS topic subscriptions, per-instance + app-declared entities, `self.entities` (#1449), WS wire-compat check (#2439), per-element list parsing so one bad app doesn't blank the integration (#2611) |

## Later

| Initiative | Milestone / pool | Blocked on / note |
|---|---|---|
| **HACS webhooks & templates** | pool: #594, #46 (`epic:hacs`) | Webhooks (#594), `@template` (#46), HACS default store |
| **DB as source of truth** | *DB as Source of Truth* | Design: `design/specs/132-db-source-of-truth/design.md`. #2695 lands first; the tail (WS invalidations, snapshot mode) is frontend-heavy. Makes the seed scripts servable to the UI |
| **v1.0 release** | pool: `release:v1.0.0` | Tag after the testing redesign and every planned breaking change (client split, HACS app-entities API) |
| **Frontend visual system alignment** | pool: tracker #1427 (lists all 15 child issues) | Lower priority by choice: frontend is the least familiar area. Needs a very concrete spec before starting. Recreate the milestone from #1427's list when promoted |
| **Frontend quality & facelift** | pool: `area:ui` | Same. Rescope from scratch into a milestone with a Done-when if promoted. Individual UI *bugs* can still come in as interrupts |
| **Feature ideas** | unlabeled `type:enhancement` | The icebox. Promote an idea by making it an initiative, not by starting it |

## Dependency chains

These are the only forced orderings. Anything not on a chain can go in any order.

```
#2387 CLI into hassette-client[cli] ──> #2388 named remote targets
HACS app entities ──> HACS webhooks & templates
testing redesign + all breaking changes ──> v1.0 tag
#2695 required DB ──> #2992 WebContext ──> #2994 status from DB
#2695, #2990 write path, #2938 service_status scope ──> #1446 projector ──> #2806 issues registry ──> #2994 status from DB ──> #2995 WS invalidations ──> #2996 snapshot mode
#2992, #1446, #2991 job timing, #2555 apps cleanup ──> #2993 apps from DB ──> #2996 snapshot mode
#1446 projector ──> #2890 mixed-instance scenario ──> #2996 snapshot mode
#2989 seed anchor ──> #2996 snapshot mode
```

Remove a chain once every step on it has closed.

## Buckets (never "done", never a milestone)

| Bucket | Label | Use for |
|---|---|---|
| Correctness | `epic:correctness` | Runtime bugs; becomes a milestone when a sweep is promoted to Now |
| Code quality | `topic:code-quality`, `source:quality-scanner` | Small mechanical fixes |
| Architecture | `topic:architecture` | Structural work; promote to an initiative if a cluster grows (e.g. restart hardening: #1689, #1767, #1721) |
| Docs | `type:documentation` | Followability and accuracy fixes |
| Test/CI infra | `area:testing`, `type:CICD` | Flakes (e.g. #2364) become interrupts when they block merges |
