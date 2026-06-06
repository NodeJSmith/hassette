---
topic: "Health, status, and lifecycle modeling for a service with a droppable dependency"
date: 2026-06-05
status: Draft
---

# Prior Art: Health, Status & Lifecycle for a Service Whose Core Dependency Can Drop

## The Problem

Hassette is a long-running process that connects to Home Assistant over a WebSocket and stays alive across HA outages, reconnecting when HA returns. Its `/api/health` endpoint reports a 3-value status (`ok`/`degraded`/`starting`) that conflates two very different situations — "never finished booting" and "booted fine, then lost HA" — into the same `starting`/503 result. External restart tooling (a Docker healthcheck driving `willfarrell/autoheal`) reads that 503 as "restart me," and because restarting cannot make HA come back, it loops.

The underlying question is one the broader ecosystem has answered repeatedly: how do you model a service's health so that losing an upstream dependency does not get mistaken for the service itself being broken?

## How We Do It Today

One `/api/health` endpoint returns a `SystemStatus` with `status ∈ {ok, degraded, starting}`, computed in `RuntimeQueryService.get_system_status()`: `ok` if the WS is connected, `degraded` if the WS is down but `StateProxy` is ready, else `starting` (503). The `degraded` branch is effectively dead during real outages because `StateProxy.on_disconnect()` clears its cache and marks not-ready, so a disconnected-but-booted instance falls through to `starting`. Separately, hassette already has a mature OTP-style supervision layer — `RestartSpec` (PERMANENT/TRANSIENT/TEMPORARY, sliding-window `intensity`/`period` budget, `EXHAUSTED_COOLING`/`EXHAUSTED_DEAD` terminal states) and a per-`Resource` readiness machinery (`ready_event`, no "ever ready" flag) — plus a WS `ConnectionState` machine (DISCONNECTED/CONNECTING/CONNECTED).

## Patterns Found

### Pattern 1: Liveness / Readiness / Startup Separation (three-axis probe model)

**Used by**: Kubernetes (native), Spring Boot Actuator, ASP.NET Core.
**How it works**: Three independent signals answer three different questions. **Liveness** = "is the process irrecoverably stuck — restart it?" and checks only in-process invariants. **Readiness** = "should work be routed to me now?" and is the *only* place dependency state belongs. **Startup** = "has the slow boot finished?" and suppresses the other two during boot. These are orthogonal axes, not stages — "alive but not ready" (process fine, dependency unreachable) is a normal, expected state in which the orchestrator keeps the container running and just stops sending traffic. Frameworks expose distinct endpoints (`/health/live`, `/health/ready`; `/actuator/health/liveness`, `/actuator/health/readiness`), usually derived from one check registry via tags or groups.
**Strengths**: Cleanly prevents dependency outages from causing restarts; one registry backs many endpoints; slow starts handled without weakening liveness timeouts.
**Weaknesses**: Easy to misconfigure (the #1 mistake is dependency checks in liveness); more endpoints; assumes something external consumes the signals.
**Example**: https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/ , https://learn.microsoft.com/en-us/aspnet/core/host-and-deploy/health-checks

### Pattern 2: Graded Status Vocabulary with Per-Dependency Checks

**Used by**: ASP.NET Core (`Healthy`/`Degraded`/`Unhealthy`), Spring Boot (`UP`/`DOWN`/`OUT_OF_SERVICE`/`UNKNOWN`), IETF health+json (`pass`/`warn`/`fail`).
**How it works**: Status is a small ordered set with a load-bearing middle tier (`Degraded`/`warn`/`OUT_OF_SERVICE`) meaning "works, but something is off." The overall status aggregates from per-component `checks`: the IETF `application/health+json` format nests a `checks` object where each dependency carries its own status plus `affectedEndpoints`. The middle tier is what lets a dependency outage be reported without escalating to a restart — ASP.NET maps `Degraded`→200 and `Unhealthy`→503; Spring's `OUT_OF_SERVICE` explicitly names "up but refusing traffic."
**Strengths**: Expresses "dependency down but I'm fine" as a first-class state; per-dependency checks give precise diagnostics; IETF standardizes the payload.
**Weaknesses**: Requires disciplined status→HTTP-code→action mapping; a mis-mapped `Degraded→503` reintroduces the loop.
**Example**: https://datatracker.ietf.org/doc/html/draft-inadarei-api-health-check-06

### Pattern 3: Bounded Restart Budget (sliding-window supervision with give-up)

**Used by**: Erlang/OTP supervisors (`intensity`/`period`), systemd (`StartLimitBurst`/`StartLimitIntervalSec`), Akka strategies.
**How it works**: Auto-restart is allowed, but only N times within rolling window T; exceed it and the supervisor terminates and gives up (`shutdown`/`failed`) rather than looping. The guidance explicitly separates burst tolerance (a few rapid retries that may succeed) from sustained-rate tolerance (don't spin forever).
**Strengths**: Turns "restart forever" into "give up after a bounded burst" — auditable and alertable.
**Weaknesses**: Tuning intensity/period is a judgment call; give-up needs a higher-level actor to react.
**Example**: https://www.erlang.org/doc/system/sup_princ.html
**Note for us**: hassette already implements this internally via `RestartSpec` — this pattern validates the existing supervision design rather than proposing new work.

### Pattern 4: Supervision Directive Vocabulary (beyond binary restart)

**Used by**: Akka (`Resume`/`Restart`/`Stop`/`Escalate`), OTP restart types (`permanent`/`transient`/`temporary`).
**How it works**: On failure the supervisor picks among several responses, not a single restart reflex. `Resume` keeps state and continues (transient blip); `Restart` clears state (corrupted-state fault); `Stop` terminates (unrecoverable); `Escalate` defers to a higher level. For a dependency drop, "restart" is usually the *wrong* directive — `Resume` (wait for the dependency to return) fits, because recreating a unit whose dependency is still down just repeats the failure.
**Strengths**: Distinguishes "wait it out" from "recreate me" from "above my pay grade."
**Weaknesses**: More directives, more ways to choose wrong; needs failures to carry enough info to pick.
**Example**: https://doc.akka.io/docs/akka/current/general/supervision.html
**Note for us**: hassette's WS service already treats an HA drop as `Resume` (TRANSIENT, reconnect). The bug is that the *aggregate health signal* escalates that Resume-level event into a Restart-level 503.

### Pattern 5: Graceful Degradation — Soft Dependencies and Circuit Breakers

**Used by**: AWS Well-Architected (REL05-BP01), circuit-breaker libraries, Kubernetes microservice practice.
**How it works**: Treat dependency loss as a degraded-mode condition handled in application code, not as a health/lifecycle event. "Transform hard dependencies into soft dependencies": serve cached data / defaults / reduced function while the dependency is gone, report `Degraded`/200, stop routing dependent work via readiness, retry on backoff. The probe and supervision layers never see a restart-worthy fault.
**Strengths**: Service stays alive and partially useful; backoff prevents amplifying the outage; fully decouples dependency state from lifecycle state.
**Weaknesses**: Real fallback logic per feature is work; stale fallbacks can be wrong.
**Example**: https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/rel_mitigate_interaction_failure_graceful_degradation.html
**Note for us**: hassette stays up during an HA outage, but `StateProxy` *clears* its cache on disconnect — a hard degradation. Retaining last-known state would be a softer degradation (a deeper, optional design question).

## Anti-Patterns

- **Dependency check in the liveness probe → restart storm.** A dependency outage fails liveness, the orchestrator restarts, the restart still can't reach the dependency, CrashLoopBackOff — across a fleet, each restart sheds load onto survivors that then also fail. The fix is unanimous: liveness checks only the process; dependency awareness lives in readiness + in-code circuit breakers. **This is exactly hassette's reboot loop** (autoheal acting on a 503 that means "HA is down"). https://blog.colinbreck.com/kubernetes-liveness-and-readiness-probes-how-to-avoid-shooting-yourself-in-the-foot/ , https://oneuptime.com/blog/post/2026-02-09-liveness-probes-avoid-false-positives/view
- **Liveness timeout too short turns latency into a restart.** A GC pause or brief slowness trips the probe and restarts a healthy container. https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/
- **Unbounded auto-restart with no give-up.** Restarting a unit whose dependency is permanently gone spins forever. OTP/systemd cap it with a sliding window. (hassette already does this internally; the *container* layer via autoheal does not.) https://www.erlang.org/doc/system/sup_princ.html

## Emerging Trends

Framework defaults are shifting toward "dependency checks off in liveness by default" — recent Spring Boot enables liveness/readiness probes out of the box and adds no external-dependency indicators to the liveness group unless explicitly opted in, codifying the anti-pattern guidance into defaults rather than operator discipline. https://spring.io/blog/2020/03/25/liveness-and-readiness-probes-with-spring-boot/

## Relevance to Us

Three of the five patterns hassette already embodies internally (Pattern 3 = `RestartSpec`; Pattern 4 = TRANSIENT WS reconnect; partial Pattern 5 = apps stay loaded). The gap is entirely at the **aggregate health / endpoint layer**, where hassette has *one* endpoint that mixes the liveness question ("should you restart me?") with the readiness question ("are you connected to HA?"). The ecosystem's unanimous answer — keep dependency state out of the restart signal — maps directly:

- **The reboot loop is the textbook anti-pattern**, not a hassette-specific quirk. autoheal is consuming a readiness signal as a liveness signal. Every source says this is the mistake to design out.
- hassette's `Resource` lifecycle already has the raw material to compute both axes: a liveness reduction over child statuses (is any PERMANENT service `EXHAUSTED_DEAD`/fatally `CRASHED`?) and a readiness reduction (are critical services RUNNING and is the WS `CONNECTED`?).
- The missing primitive for distinguishing `starting` from `degraded` is an **"ever ready / ever connected" latch** — the one piece of state the readiness machinery deliberately lacks today.

## Recommendation

Adopt **Pattern 1 (liveness/readiness split) + Pattern 2 (graded vocabulary with per-dependency checks)**, backed by the lifecycle state hassette already has. Concretely:

1. **Split the endpoint by question, not by adding status words:**
   - `/api/health/live` — **liveness**. Returns 200 unless the process is genuinely unrecoverable (a PERMANENT service in `EXHAUSTED_DEAD`, or the event loop wedged). HA being down never fails this. **This is what the Docker healthcheck + autoheal should target.**
   - `/api/health/ready` — **readiness**. 503 when still starting or HA is disconnected. This is the "should I route traffic / is it fully functional" signal.
   - Keep `/api/health` as the rich aggregate (current `SystemStatusResponse`), 200 unless dead, carrying the full picture.

2. **Fix the status taxonomy by separating two axes** (boot vs dependency) rather than overloading `starting`:
   - Add a one-way **ever-connected latch** so a booted instance that loses the WS reports `degraded` (200), never `starting`. (This is also the standalone hotfix.)
   - Reserve `starting` for "has never reached ready since process start."
   - Optionally adopt an IETF-style `checks` map in the payload: `home_assistant_ws: {status: down}`, `database: {...}`, per-service — so the overall status is a reduction and operators see *which* dependency is impaired.

3. **Map the `Resource` lifecycle to the aggregate explicitly** so the two endpoints are computed, not hand-written: liveness = `not any(svc.permanent and svc.status in {EXHAUSTED_DEAD, CRASHED_fatal})`; readiness = `ever_connected and ws.state == CONNECTED and all(critical svc ready)`; degraded = `ever_connected and not ws_connected`.

4. **Document the user-facing guidance** (the thing peer frameworks lack): point restart-on-unhealthy automation at `/api/health/live`, and traffic/routing decisions at `/api/health/ready`. AppDaemon exposes no structured health model at all — a deliberate liveness/readiness contract is a genuine differentiator.

What *not* to do: don't add a fourth status word like `reconnecting` (ripples through models, mappers, frontend types, tests, docs for little gain), and don't put the HA-connection check anywhere near the liveness endpoint.

## Sources

(URLs surfaced via web search; not live-verified.)

### Documentation & standards
- https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/ — K8s probe semantics (orthogonal axes)
- https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/ — configuring the three probes
- https://learn.microsoft.com/en-us/aspnet/core/host-and-deploy/health-checks — ASP.NET Healthy/Degraded/Unhealthy + live/ready tags
- https://spring.io/blog/2020/03/25/liveness-and-readiness-probes-with-spring-boot/ — Spring health groups, dependency checks off liveness by default
- https://docs.spring.io/spring-boot/reference/actuator/endpoints.html — Actuator status values incl. OUT_OF_SERVICE
- https://datatracker.ietf.org/doc/html/draft-inadarei-api-health-check-06 — IETF health+json (pass/warn/fail, checks, affectedEndpoints)
- https://www.erlang.org/doc/system/sup_princ.html — OTP restart intensity/period + give-up
- https://doc.akka.io/docs/akka/current/general/supervision.html — Akka Resume/Restart/Stop/Escalate
- https://packet-radio.net/systemd-restartsec-startlimitinterval-startlimitintervalsec/ — systemd StartLimit burst limiting
- https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/rel_mitigate_interaction_failure_graceful_degradation.html — graceful degradation / soft dependencies

### Blog posts & writeups
- https://blog.colinbreck.com/kubernetes-liveness-and-readiness-probes-how-to-avoid-shooting-yourself-in-the-foot/ — the authoritative restart-storm writeup
- https://oneuptime.com/blog/post/2026-02-09-liveness-probes-avoid-false-positives/view — DB-down → fleet CrashLoopBackOff walkthrough
- https://medium.com/@mani.saksham12/graceful-degradation-in-a-microservice-architecture-using-kubernetes-d47aa80b7d20 — "dumb probes," circuit breakers in code
- https://dimitri.codes/actuator-health-probes/ — Spring actuator probe defaults

### Peer frameworks (thin)
- https://community.home-assistant.io/t/appdaemon-disconnected-from-home-assistant-retrying-in-5-seconds/127631 — AppDaemon reconnect-with-retry; no structured health model [forum only]
