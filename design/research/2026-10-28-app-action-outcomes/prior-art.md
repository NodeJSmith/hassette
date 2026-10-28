---
topic: "How synchronous multi-target lifecycle actions report per-target outcomes"
date: 2026-10-28
status: Draft
---

# Prior Art: Per-Target Outcomes from Synchronous Multi-Target Actions

## The Problem

Hassette's app action endpoints (`POST /api/apps/{key}/start|stop|reload`, and the per-instance variants) are
moving from a 202 "accepted" with a registry read-back to a synchronous answer that reports each instance's
outcome (spec 140, implementing spec 134 D15). One request can act on several instances, and some may
succeed while others fail or are refused. An instance can also be flagged needs-restart: a teardown that
couldn't cancel its work leaves it possibly still running, and only a process restart recovers it. This brief
asks how peers shape per-target results, map mixed results to one HTTP status, treat already-broken targets,
and report an unexpected failure partway through.

Already covered elsewhere and not repeated here: Home Assistant's single config-entry reload/unload, in
`2026-10-18-lifecycle-outcomes/prior-art.md` and `2026-10-27-needs-restart-ship-findings/prior-art.md` (Q2).
HA answers synchronously, refuses `FAILED_UNLOAD` with a 403, returns `require_restart`, and lets removal
proceed with `require_restart` true.

## How We Do It Today

The six action routes await an `AppHandler` method that returns `None`. They then read
`get_failed_instance_infos()` after the per-app-key lock is released, and raise a 500 `action_failed` for the
lowest-indexed failure, or otherwise answer 202 `{"status": "accepted", ...}`. A stop never reports a
failure. An index flagged needs-restart makes every later stop or reload of that app answer 500. The
needs-restart gate (#3110) logs the refusal and returns without raising.

## Answers by Question

### Q1 (D2): per-target result shape

- **systemd** reports one result per job (`JobRemoved(id, job, unit, result)`): `done`, `canceled`,
  `timeout`, `failed`, `dependency`, `skipped`. The internal enum adds `invalid`, `assert` and `unsupported`.
  Precondition outcomes are separate values, not kinds of `failed`.
- **AWS SQS batch** returns `Successful[{Id}]` and `Failed[{Id, Code, Message, SenderFault}]`. `SenderFault`
  separates caller-caused from service-caused failures.
- **AWS EC2 StopInstances** returns a per-instance `{InstanceId, PreviousState, CurrentState}`: a state change,
  not a result.
- **apt / needrestart** keep "a restart is needed" (`/var/run/reboot-required`, needrestart's report) separate
  from the operation's own exit status.
- **Kubernetes** has one `Status` with `details.causes[]`; there's no per-action result for a Deployment.
- **HA Supervisor** actions target one add-on and return `{"result": "ok" | "error", "message"}`, with errors
  answered as 400.
- **RFC 9457** allows an extension member that carries several problems (e.g. an `errors` array).

**Takeaway for D2:** keeping refused separate from failed is common (systemd's `dependency`/`skipped`, SQS's
`SenderFault`). "Restart needed" sits beside the result as its own flag (needrestart), not as a value of it.
That supports `result` + `needs_restart`.

### Q2 (D3, status mapping): mixed results and already-broken targets

- **SQS** answers 200 even when items failed, and its docs warn callers to check for batch errors on a 200.
  4xx is reserved for whole-request faults.
- **Google AIP-233/234:** a synchronous batch must be atomic. Partial success belongs to async long-running
  operations.
- **207 Multi-Status** is contested: it breaks generic clients' 2xx/4xx/5xx handling, and JSON:API maintainers
  discourage it.
- **RFC 9457:** when there are several problems of different types, the most relevant or urgent one should be
  represented. This is the closest standard backing for worst-outcome-wins.
- **Docker** answers 304 for stopping a container that isn't running ("already in the desired state", not an
  error).
- **systemd** documents `failed` as "similar to inactive", so stop on a failed unit returns at once. A hang
  there was a bug. A separate verb, `reset-failed`, clears the failed state.
- No peer was found that fails a group action because one member was already failed (consistent with the
  earlier brief).

**Takeaway for D3:** peers treat stopping an already-stopped or already-failed target as a no-op success.
In every one of those cases, though, the target's work has actually ended: Docker's container isn't running,
and systemd's failed unit has no process. The only peer with a "work may still be running" state is HA's
`FAILED_UNLOAD`, and HA refuses unload (the stop equivalent) and reload of it, letting only removal proceed.
A hassette flagged index is that state, not systemd's `failed`.

### Q3 (D4): 202 to synchronous

- AIP-233 defines both shapes per method. The synchronous one returns the result message, and the async one
  returns an `Operation`. Synchronous bodies carry no "accepted" status, and neither do SQS, EC2 or the
  Supervisor.
- No example of an API migrating from 202 to synchronous was found. The one migration found (Bird SMS) goes
  the other way.

**Takeaway for D4:** synchronous bodies report results only. Drop `status: "accepted"`.

### Q4 (D5): unexpected failure partway through

- Partial-success APIs (SQS, EC2, AIP partial) report the items they handled and list the rest as failed.
  They return a whole-request error only for request-level faults.
- Atomic synchronous APIs (AIP-233) return one error with nothing applied.
- Kubernetes `DeleteCollection` timing out with a bare 504 and no progress was filed as a bug (#90743).
- Node-RED's deploy keeps going on a node close timeout, logs it, and leaves the HTTP body without per-node
  results.

**Takeaway for D5:** a non-atomic operation, which hassette's is, reports what it handled plus failures for
the rest. A bare error was treated as a defect.

## Patterns Found

### Pattern 1: Always-200 with Successful/Failed lists
**Used by**: AWS batch APIs (SQS DeleteMessageBatch and siblings)
**How it works**: request-level faults get a 4xx; item outcomes go in the body, split into successes and
failures, each failure with a code, a message and a caller-vs-service fault bit.
**Strengths**: every item is reported; simple status logic.
**Weaknesses**: the status class doesn't reflect the outcome, so AWS has to warn callers to inspect the body.
**Example**: https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_DeleteMessageBatch.html

### Pattern 2: Worst-outcome-wins status with a problem-details extension
**Used by**: no named peer found; backed by RFC 9457's "represent the most urgent problem" guidance and the
207 critiques.
**How it works**: the top-level status and problem type come from the most urgent per-item problem, and an
extension member lists every item.
**Strengths**: generic clients and toasts that branch on the status class behave correctly.
**Weaknesses**: other targets' successes sit inside an error body.
**Example**: https://www.rfc-editor.org/rfc/rfc9457.html

### Pattern 3: Result enum with precondition outcomes kept apart from failure
**Used by**: systemd job results
**How it works**: one enum per target, where "didn't run because a precondition failed" (`dependency`,
`skipped`) is its own value beside `failed` and `timeout`.
**Strengths**: callers can tell "retry won't help" from "it broke".
**Weaknesses**: the enum grows over time (systemd added `invalid`, `assert`, `unsupported`), so consumers
must accept unknown values.
**Example**: https://www.freedesktop.org/wiki/Software/systemd/dbus/

### Pattern 4: "Restart needed" as an orthogonal signal
**Used by**: apt's `/var/run/reboot-required`, needrestart; HA's `require_restart`
**How it works**: the operation reports its own result; a separate marker says the system needs a restart to
fully apply or recover.
**Strengths**: a successful operation and a pending restart can both be true.
**Weaknesses**: outside HA, the marker lives outside the operation's response.
**Example**: https://manpages.debian.org/unstable/needrestart/needrestart.1.en.html

### Pattern 5: Idempotent stop of a target whose work has ended
**Used by**: Docker (304 on a non-running container), systemd (`failed` ≈ `inactive`)
**How it works**: stopping something already stopped or dead is a no-op success.
**Strengths**: stop converges; scripts can stop unconditionally.
**Weaknesses**: only sound when the target's work has really ended.
**Example**: https://github.com/docker/docker/blob/master/daemon/stop.go

### Pattern 6: Don't bother
**Used by**: Node-RED's flow deploy, the HA Supervisor, AppDaemon's app service calls, Docker Compose's
aggregate exit code
**How it works**: one result or error for the whole request, with per-target problems in logs or the UI.
**Strengths**: no response contract to maintain.
**Weaknesses**: callers can't tell what happened to each target; Compose users asked for an aggregate exit
code (compose#10225).
**Example**: https://nodered.org/docs/api/admin/methods/post/flows/

## Anti-Patterns

- 207 Multi-Status for JSON APIs outside WebDAV: it breaks status-class handling and isn't core HTTP.
- A bare timeout or 500 partway through a multi-target operation, with no progress (Kubernetes #90743).

## Relevance to Us

- **D2** (`result` + `needs_restart`) matches Patterns 3 and 4 directly. A four-value enum that folds "needs
  restart" into the result has no peer, and loses failed-vs-refused for flagged instances.
- **D3:** Pattern 5 argues that stop of an already-broken target succeeds. But its premise, that the work has
  ended, is exactly what a flagged index lacks. The one peer with hassette's state, HA's `FAILED_UNLOAD`,
  refuses unload and reload. HA's *removal* proceeding with `require_restart` is the closest support for
  "stop succeeds with `needs_restart`". Peers back both refusing and succeeding-with-a-flag. None backs
  treating it as a plain success.
- **Status mapping:** the parent's worst-outcome-wins is Pattern 2. No peer uses it verbatim, but RFC 9457
  backs it, and it avoids Pattern 1's "check the body on a 200" trap. Google's atomic-sync rule doesn't fit,
  because hassette's per-instance actions can't be rolled back.
- **D4:** dropping `status: "accepted"` matches every synchronous peer.
- **D5:** reporting what was handled plus failures for the rest matches the partial-success peers. The
  Kubernetes bug shows the cost of the alternative.
- Hassette is already past Pattern 6, which its local peers (Node-RED, Supervisor, AppDaemon) all use. That
  is the parent's ratified D15, not something this pickup reopens.

## Recommendation

Keep D2's `result` + `needs_restart`, worst-outcome-wins, D4's removal of `status`, and D5's
report-what-was-handled. They each match a peer pattern or a standard. For D3, peers don't settle it.
Docker/systemd's no-op stop doesn't apply, because a flagged index's work hasn't ended. That leaves HA's two
behaviors: refuse unload/reload, or let removal succeed with `require_restart`. Either is defensible. The
deciding question is whether a hassette "stop" is closer to HA's unload or its removal.

Coverage gaps: EC2's exact behavior on already-stopped instances, NetDaemon and pyscript, and systemctl's
multi-unit exit code were not verified.

## Sources

(Not live-verified.)

### Reference implementations
- https://github.com/systemd/systemd/blob/d0168f4d/src/core/job.h — systemd `JobResult` enum
- https://github.com/docker/docker/blob/master/daemon/stop.go — 304 for an already-stopped container
- https://github.com/AppDaemon/appdaemon/blob/dev/appdaemon/adapi.py — app service calls return nothing
- https://github.com/home-assistant/supervisor/blob/7e1b179cdd2c0f99a632097bd41749e68ecb00d9/API.md — Supervisor result envelope

### Blog posts & writeups
- https://gist.github.com/dehora/409a14c52eece610c501 — "Batch 207 Arcana", against 207
- https://github.com/json-api/json-api/issues/787 — JSON:API discourages 207
- https://github.com/kubernetes/kubernetes/issues/90743 — DeleteCollection timeout with no progress
- https://github.com/docker/compose/issues/10225 — no aggregate failed-service exit code
- https://github.com/systemd/systemd/issues/32312 — stop of a failed unit expected to return at once
- https://lists.freedesktop.org/archives/systemd-devel/2019-March/042242.html — `reset-failed` semantics
- https://discourse.nodered.org/t/error-stopping-node-close-timed-out/46075 — Node-RED close timeout logged, deploy continues

### Documentation & standards
- https://www.freedesktop.org/wiki/Software/systemd/dbus/ — systemd job results
- https://www.freedesktop.org/software/systemd/man/latest/systemctl.html — `failed` is "similar to inactive"
- https://docs.aws.amazon.com/AWSSimpleQueueService/latest/APIReference/API_DeleteMessageBatch.html — Successful/Failed, 200
- https://docs.aws.amazon.com/AWSEC2/latest/APIReference/API_StopInstances.html — per-instance state change
- https://google.aip.dev/233 , https://google.aip.dev/234 , https://google.aip.dev/193 — batch atomicity, errors
- https://www.rfc-editor.org/rfc/rfc9457.html — problem details extension members; most urgent problem
- https://mailarchive.ietf.org/arch/msg/httpapi/beB6wnvbWk4P6RqQv1hp7ZJH0uA/ — multiple problems discussion
- https://manpages.debian.org/unstable/needrestart/needrestart.1.en.html — restart-needed as a separate report
- https://nodered.org/docs/api/admin/methods/post/flows/ — deploy response
- https://kubernetes.io/docs/reference/kubernetes-api/definitions/status-cause-v1-meta/ — StatusCause
