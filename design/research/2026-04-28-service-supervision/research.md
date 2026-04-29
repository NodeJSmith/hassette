---
topic: "Service supervision and restart management patterns"
date: 2026-04-28
status: Draft
---

# Prior Art: Service Supervision and Restart Management

## The Problem

When a long-running async service fails, the framework must decide: restart it? how quickly? how many times? when has it "recovered enough" to forgive past failures? Hassette's current ServiceWatcher applies a single global policy to all services — same restart budget, same backoff curve, same readiness timeout. This breaks down when services have fundamentally different failure modes (a WebSocket connection with multi-layer retries vs a stateless worker), and the fixed 10-second readiness timeout is incompatible with services whose legitimate recovery path takes minutes.

The deeper question: should supervision be something the framework imposes on services, or something services participate in and configure?

## How We Do It Today

The `ServiceWatcher` is a passive event listener that monitors service status transitions. When a service enters FAILED, it applies exponential backoff (2s base, 2x multiplier, 60s cap) and restarts up to 5 times. When a service enters RUNNING, the watcher waits 10 seconds for `mark_ready()` — only then does it reset the restart counter. All five configuration knobs are global; no per-service overrides exist.

Services like WebsocketService already implement their own layered retry logic internally (early-drop detection, connection retries, stable-window tracking), creating two independent retry budgets that don't know about each other. The service has the most context about what's recoverable, but the framework doesn't ask.

## Patterns Found

### Pattern 1: Sliding-Window Restart Budget

**Used by**: Erlang/OTP supervisors, systemd (StartLimitBurst/StartLimitIntervalSec), Kubernetes CrashLoopBackOff

**How it works**: Instead of a monotonically increasing counter that requires explicit reset, the supervisor tracks restart timestamps in a sliding window of the last N seconds. Only restarts within the window count toward the budget. Old restarts silently expire — "forgiveness" is automatic and requires no special signal.

The window serves as both a burst limiter and a sustained-rate limiter. With intensity=5 and period=30s, the system allows bursts of 5 rapid restarts but caps sustained rate to ~1 per 6 seconds. The period should reflect how fast a human could intervene if the service is genuinely broken.

Erlang implements this as a timestamp list filtered on each restart. systemd uses a counter with an interval. Kubernetes uses exponential backoff with a 10-minute successful-run reset.

**Strengths**: Self-healing (old failures expire automatically), no manual reset needed, prevents infinite restart loops while tolerating transient bursts.

**Weaknesses**: Window size is a trade-off between responsiveness and tolerance — too small and transient failures exhaust the budget, too large and broken services restart too many times. The "right" window depends on deployment context.

**Example**: https://www.erlang.org/doc/system/sup_princ.html

### Pattern 2: Service-Declared Error Retryability

**Used by**: Temporal (non_retryable_error_types), supervisord (autorestart=unexpected + exitcodes), systemd (Restart=on-failure, RestartPreventExitStatus), Python backoff library (giveup predicate)

**How it works**: The service declares which errors should trigger restart, using one of three approaches:

1. **Denylist** (Temporal): everything retried except declared non-retryable errors. Safest — unknown new errors default to retryable.
2. **Allowlist** (backoff): only declared retryable errors trigger retry. Risks missing new transient errors.
3. **Exit code classification** (supervisord, systemd): specific codes indicate retryable vs permanent failure.

The denylist approach is generally preferred because transient failures (network, rate limits) are more common than permanent ones (invalid config, missing resource), and new error types should default to "try again."

**Strengths**: The service has the most context about recoverability. Prevents wasting budget on errors that will never succeed. Reduces futile restart noise.

**Weaknesses**: Requires service authors to correctly classify errors. Under-classification wastes resources; over-classification prevents recovery.

**Example**: https://docs.temporal.io/encyclopedia/retry-policies

### Pattern 3: Readiness vs Liveness Separation

**Used by**: Kubernetes (three-probe model), systemd (Type=notify + WatchdogSec), supervisord (startsecs)

**How it works**: The supervisor distinguishes three states with different responses:

- **Starting**: supervisor waits for readiness signal. K8s startup probe disables other checks. systemd Type=notify waits for sd_notify("READY=1"). supervisord's `startsecs` uses a time-based heuristic.
- **Liveness**: periodic check that the service is alive. Failure triggers restart. K8s liveness probes; systemd WatchdogSec (periodic heartbeat).
- **Readiness**: check that the service can accept work. Failure does NOT trigger restart — service is marked unavailable but left running.

The key insight: "not ready" and "not alive" require different responses. Restarting a service that is alive but temporarily unable to serve (warming caches, waiting for a dependency) resets its progress and may make things worse.

K8s readiness probes have `successThreshold` — the service must pass N consecutive checks to be re-admitted after failure. This is a forgiveness probe, not a binary flag.

**Strengths**: Prevents unnecessary restarts during init and transient unavailability. Catches stuck processes that exit-code-based restart cannot detect (liveness heartbeat).

**Weaknesses**: Three probes are more complex than one. Aggressive liveness probes can kill healthy-but-slow services. Service authors must understand the distinction.

**Example**: https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/

### Pattern 4: Per-Child Restart Specifications (Two-Level Policy)

**Used by**: Erlang/OTP (child specs), systemd (per-unit configuration), Kubernetes (per-container)

**How it works**: Each child declares its own restart behavior as part of its specification. In Erlang, each child spec includes:

- `restart`: permanent (always restart), transient (restart only on abnormal exit), temporary (never restart)
- `shutdown`: timeout for graceful shutdown before kill
- `type`: worker or supervisor (enables supervision trees)

The supervisor combines per-child specs with its own restart strategy and budget. This creates a two-level policy: **the child declares WHEN** it should be restarted, and **the supervisor declares HOW** restarts are coordinated and budgeted.

In systemd, each unit file declares its own Restart=, RestartSec=, and exit code classification, while StartLimitBurst/StartLimitIntervalSec provide the budget.

**Strengths**: Services self-describe their restart semantics. Stateless services declare `permanent`; batch jobs declare `temporary`. The supervisor doesn't need to know each child's semantics.

**Weaknesses**: Requires service authors to correctly declare semantics. The supervisor still needs a global budget to prevent cascading failures.

**Example**: https://www.erlang.org/doc/system/sup_princ.html

### Pattern 5: Structured Concurrency with Layered Supervision

**Used by**: Trio nurseries, asyncio.TaskGroup, aiotools PersistentTaskGroup, Kotlin supervisorScope

**How it works**: The concurrency framework provides a basic guarantee — no task outlives its scope, failures propagate to the scope boundary. Restart logic is NOT built in; it's layered on top by the application.

Standard task groups (asyncio.TaskGroup) cancel all siblings when one fails — correct for fan-out/gather, wrong for long-running services. PersistentTaskGroup (aiotools) and supervisorScope (Kotlin) keep siblings alive when one fails. Restart logic is an exception handler or done callback: on failure, the handler decides whether to spawn a replacement task.

This separation means the concurrency framework handles cleanup and lifetime (the hard part), while the application handles restart policy (the domain-specific part).

**Strengths**: Clean separation of concerns. Different tasks in the same group can have different restart policies. No orphaned tasks.

**Weaknesses**: No built-in restart support means every application reinvents it. The gap between "task group" and "service supervisor" is a recognized design space in Python async — still actively debated.

**Example**: https://discuss.python.org/t/revisiting-persistenttaskgroup-with-kotlins-supervisorscope/18417

### Pattern 6: Circuit Breaker State Machine (Controlled Forgiveness)

**Used by**: Resilience4j, Polly (.NET), Hystrix (deprecated)

**How it works**: Three states: CLOSED (normal), OPEN (failing fast, rejecting all attempts), HALF_OPEN (probing). After a cooldown in OPEN, a limited number of probe requests determine whether to return to CLOSED (forgiven) or OPEN (still failing). Time-based sliding windows use a circular buffer of per-second buckets for efficient forgiveness of old failures.

The HALF_OPEN state is a controlled forgiveness mechanism — rather than blindly resetting after a timer, the system tests whether recovery is real before committing.

**Strengths**: Probe-based forgiveness is more reliable than timer-based. Prevents cascade failures via fast-fail in OPEN state.

**Weaknesses**: Adds complexity. Probe mechanism can cause thundering herd. Threshold tuning requires operational experience.

**Example**: https://resilience4j.readme.io/docs/circuitbreaker

## Anti-Patterns

- **One-size-fits-all restart policy**: Applying the same strategy to all services ignores that different services have different failure modes. Erlang's per-child specs exist because this matters. *(Source: Erlang/OTP docs)*

- **Restarting "alive but not ready" services**: When a service is alive but temporarily unable to serve (warming caches, waiting for a dependency), restarting resets progress and may worsen the situation. K8s addresses this by separating liveness from readiness. *(Source: Kubernetes docs)*

- **Infinite restart without backoff**: Restart=always without rate limiting allows a failing service to consume all system resources in a tight loop. *(Source: Stapelberg blog)*

- **Counter-based budget without forgiveness**: A monotonically increasing restart counter that never resets (or only resets on explicit signal) means the system carries the burden of past transient failures forever, eventually exhausting its budget for genuine recovery attempts. *(This is hassette's current design.)*

## Emerging Trends

**Structured concurrency driving supervision redesign**: Python's adoption of asyncio.TaskGroup (3.11) is forcing a rethink. The standard task group cancels everything on first failure — correct for short-lived fan-out, wrong for long-running services. The community is actively debating PersistentTaskGroup/SupervisorScope semantics (Python Discuss, 2023-2024), and aiotools has a working implementation. The gap between "task group" and "service supervisor" is now a recognized design space.

**Service-declared retryability as default-allow**: Temporal's denylist approach (declare non-retryable errors) is gaining adoption over the traditional allowlist. The insight: new/unknown errors should default to retryable because most failures are transient.

## Relevance to Us

Hassette's current ServiceWatcher maps directly onto two documented anti-patterns: **one-size-fits-all restart policy** and **counter-based budget without forgiveness**. The 10-second readiness timeout also conflates liveness with readiness — a service that is alive and making progress toward ready (WebSocket reconnecting through its multi-layer retry) gets penalized the same way as a service that is stuck.

The strongest alignment with hassette's async Python architecture:

1. **Sliding-window restart budget** (Pattern 1) replaces the monotonic counter and solves issue #630's counter-reset problem by making forgiveness automatic. This is the most impactful single change.

2. **Per-child restart specs** (Pattern 4) — Erlang's two-level model maps cleanly to hassette's Resource/Service class hierarchy. Services could declare restart specs via class attributes or a `restart_policy()` method, while ServiceWatcher maintains the global budget.

3. **Service-declared error retryability** (Pattern 2) — the WebsocketService already classifies errors internally (early-drop vs connection failure vs stable failure). The framework should formalize this: services declare non-retryable errors, and the watcher skips restart for those.

4. **Readiness/liveness separation** (Pattern 3) — hassette already has `mark_ready()` as a readiness signal. The missing piece is distinguishing "not yet ready" (don't restart, keep waiting) from "failed" (restart). The current design treats readiness timeout as a failure signal, which is the anti-pattern K8s probes were designed to avoid.

The structured concurrency patterns (Pattern 5) are less directly applicable — hassette already has its own service lifecycle management rather than relying on raw task groups. The circuit breaker (Pattern 6) is more relevant at the call-site level than the supervision level, but HALF_OPEN probing is a useful concept for the readiness recovery path.

## Recommendation

The highest-impact changes, in order:

1. **Replace the monotonic restart counter with a sliding-window budget** (Erlang model). This directly solves #630 and eliminates the need for explicit counter reset logic. Implementation: track restart timestamps, filter to window, compare count vs intensity.

2. **Let services declare restart specs** — at minimum: restart type (permanent/transient/temporary), non-retryable error types, and optional backoff overrides. The watcher becomes a coordinator that respects per-service declarations rather than imposing global policy.

3. **Separate readiness from liveness in the watcher's response** — a readiness timeout should NOT increment the restart counter or contribute to budget exhaustion. "Alive but not yet ready" is a distinct state that requires patience, not punishment.

4. **Consider a startup-probe equivalent** — services with known long initialization (WebSocket with multi-layer retry) could declare a startup timeout that suspends normal liveness/readiness checks until the service has had a chance to complete its first connection.

These four changes are complementary and could be implemented incrementally. Pattern 1 alone solves the immediate issue; patterns 2-4 address the deeper "too dumb/naive" concern.

## Sources

### Reference implementations
- https://www.erlang.org/doc/system/sup_princ.html — Erlang/OTP supervisor principles (restart strategies, child specs, intensity/period)
- https://github.com/erlang/otp/pull/8261 — OTP supervisor restart calculation optimization (sliding window internals)
- https://resilience4j.readme.io/docs/circuitbreaker — Resilience4j circuit breaker (sliding windows, HALF_OPEN probing)
- https://github.com/litl/backoff — Python backoff library (decorator-based retry with giveup predicates)
- https://aiotools.readthedocs.io/en/latest/aiotools.taskgroup.html — aiotools PersistentTaskGroup (async Python supervisor primitive)

### Blog posts & writeups
- https://learnyousomeerlang.com/supervisors — Practical Erlang supervisor tuning (intensity/period trade-offs)
- https://michael.stapelberg.ch/posts/2024-01-17-systemd-indefinite-service-restarts/ — systemd indefinite restart trade-offs
- https://www.redhat.com/en/blog/systemd-automate-recovery — systemd self-healing services (notify, watchdog)
- https://temporal.io/blog/failure-handling-in-practice — Temporal failure handling best practices

### Documentation & standards
- https://manpages.debian.org/testing/systemd/systemd.service.5.en.html — systemd service unit configuration
- https://kubernetes.io/docs/concepts/configuration/liveness-readiness-startup-probes/ — Kubernetes probe model
- https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/ — Kubernetes pod lifecycle and CrashLoopBackOff
- https://supervisord.org/configuration.html — supervisord configuration (startsecs, startretries, autorestart)
- https://supervisord.org/subprocess.html — supervisord subprocess state machine
- https://docs.temporal.io/encyclopedia/retry-policies — Temporal retry policy specification

### Design discussions
- https://github.com/python-trio/trio/issues/569 — Trio: alternative supervision logic / custom nurseries
- https://discuss.python.org/t/revisiting-persistenttaskgroup-with-kotlins-supervisorscope/18417 — PersistentTaskGroup design
- https://discuss.python.org/t/server-oriented-task-scope-design/53903 — Server-oriented task scope design
