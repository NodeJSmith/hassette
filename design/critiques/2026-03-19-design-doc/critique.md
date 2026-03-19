# Design Critique: 008-ui-rebuild Design Doc

**Date**: 2026-03-19
**Target**: `design/specs/008-ui-rebuild/design.md`
**Method**: Three independent critics (Senior Engineer, Systems Architect, Adversarial Reviewer)

## Findings

### 1. `hx-trigger="intersect once"` never fires on `x-show` hidden elements — CRITICAL
**What's wrong**: The lazy-load pattern uses `hx-trigger="intersect once"` inside an `x-show` container. `x-show` sets `display: none`, giving zero layout area. IntersectionObserver never fires. The `once` modifier means it's never re-armed.
**Raised by**: Senior + Adversarial
**Better approach**: Trigger HTMX fetch from Alpine.js `@click` handler, or use `hx-trigger="revealed"`.

### 2. `format_handler_summary()` parses unstable Python repr — HIGH
**What's wrong**: `predicate_description` is stored as `repr(listener.predicate)`. Complex predicates produce unparseable output with memory addresses.
**Raised by**: Senior + Architect
**Better approach**: Add `summarize()` method to predicate classes. Populate `human_description` at registration time.

### 3. Deferred features have no actual placeholder design — HIGH
**What's wrong**: Five deferred features say "leave a placeholder" but specify no template elements, no disabled states, no endpoint URLs.
**Raised by**: Architect + Adversarial
**Better approach**: Specify template element, disabled state, and future endpoint URL for each deferred feature.

### 4. Invocation counts go stale during diagnostic use — HIGH
**What's wrong**: `app_status_changed` only fires on lifecycle transitions, not invocations. Running apps never broadcast it.
**Raised by**: Senior
**Better approach**: Add `hx-trigger="every 5s"` polling on handler section, or add `telemetry_updated` WS event.

### 5. No deployment strategy for big-bang rewrite — HIGH
**What's wrong**: No mention of feature branch, minimum viable milestone, or production state during development.
**Raised by**: Adversarial
**Better approach**: State: "Work on a feature branch. Old UI serves on main until rebuild is merged atomically."

### 6. Untyped dict pipeline from SQL to templates — MEDIUM
**What's wrong**: `TelemetryQueryService` returns `list[dict]`. Column renames cause silent render failures.
**Raised by**: Architect
**Better approach**: Add Pydantic models for `ListenerSummary`, `JobSummary`, `HandlerInvocation`.

### 7. CSS estimate likely low (~1,200 → ~1,500-1,800) — MEDIUM
**Raised by**: Adversarial
**Better approach**: Accept higher estimate. Dark mode tokens are separate but component styles are shared.

### 8. `el.offsetParent` unreliable as visibility gate — MEDIUM
**Raised by**: Senior
**Better approach**: Use IntersectionObserver or skip the optimization entirely.

## Appendix: Individual Critic Reports

- Senior Engineer: `/tmp/claude-mine-challenge-fjWfnv/senior.md`
- Systems Architect: `/tmp/claude-mine-challenge-fjWfnv/architect.md`
- Adversarial Reviewer: `/tmp/claude-mine-challenge-fjWfnv/adversarial.md`
