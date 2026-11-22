# AGENTS.md

Hassette is an async Python framework for Home Assistant automations. Project conventions for
writing code live in `CLAUDE.md` and `.claude/rules/`; this file holds the rules for Codex code
review.

## Code Review Rules

### Module review questions

Many packages have a `REVIEW.md` listing invariants that past changes have broken, written as
questions. For each changed file, read every `REVIEW.md` from its directory up to the repository
root: each level holds invariants for everything below it, so a scheduler change is checked
against both `src/hassette/scheduler/REVIEW.md` and `src/hassette/REVIEW.md`. Comment only where
the diff breaks one of those invariants, and quote the question. Don't report questions the diff
satisfies.

- Safe path: a change that keeps each invariant, or that updates the `REVIEW.md` question alongside
  a deliberate change to the invariant.

### Scheduled runs and matched events are never silently lost

A job run that is due, or an event already matched to a handler, must either run or be recorded
as dropped in a way the app author can see: an execution-mode `Outcome.DROPPED` or
`Outcome.SUPPRESSED`, a `DROP_NEWEST` backpressure drop, or another counter, status or WARNING
log. Flag a path that discards due or matched work without recording it. Pay particular attention
to decisions based on wall-clock time ("its fire time has passed") rather than dispatch state ("it
has been popped and dispatched"): a run whose time has passed but that is still queued behind a
slow event loop has not run yet. Treat these as P1 even when the window is short.

Changes to predicates and filters that decide what matches in the first place, and registration
decisions such as an `if_exists` skip, are out of scope.

- Safe path: base the decision on whether the work was dispatched, or record the drop.

### Interleaving across awaits

In `src/hassette/` runtime code (not `testing/`, `cli/`, or tests), bus handlers, scheduler
callbacks and service loops run concurrently on one event loop. A check followed by an action
with an `await` between them can see the state change underneath it. Flag check-then-act
sequences across an `await` on shared state another task can mutate (for example a job, listener,
cache entry or app status), and say which task does it.

- Safe path: re-check after the await, do the check and the action without an await between
  them, or hold the lock that guards that state.

### Public API and breaking changes

The public API is anything an app author imports from `hassette` or reaches through an `App`
attribute: for example the names in `src/hassette/__init__.py`'s `__all__`, submodules the docs
import from (`hassette.testing`, `hassette.events`, `hassette.models`, `hassette.exceptions`), and
attributes such as `self.bus`, `self.scheduler`, `self.api`, `self.states` and `self.cache`.
Releases come from PR titles through release-please. When the PR title has no `!`, flag a change
that would make an app that worked before fail to import or type-check, or that changes a public
function's signature, return type or raised exceptions, removes a field from a public model, or
removes an `App` attribute. A bug fix that changes behavior without changing that shape is not a
breaking change for this rule.

- Safe path: keep the old name or shape, or mark the PR title as breaking (`feat!:`, `fix!:`,
  `refactor!:`) and end the PR body with a `BREAKING CHANGE:` footer.
