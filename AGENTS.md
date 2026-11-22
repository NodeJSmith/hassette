# AGENTS.md

Hassette is an async Python framework for Home Assistant automations. Project conventions for
writing code live in `CLAUDE.md` and `.claude/rules/`; this file holds the rules for Codex code
review.

## Code Review Rules

### Module review questions

Many packages have a `REVIEW.md` listing invariants that past changes have broken, written as
questions. When a change touches a package, read the nearest `REVIEW.md` at or above each changed
file. Comment only where the diff breaks one of those invariants, and quote the question. Don't
report questions the diff satisfies.

- Safe path: a change that keeps each invariant, or that updates the `REVIEW.md` question alongside
  a deliberate change to the invariant.

### Scheduled runs and matched events are never silently lost

A job run that is due, or an event already matched to a handler, must either run or be recorded
as dropped: an `if_exists` skip, a `DROP_NEWEST` backpressure drop, an execution-mode
`Outcome.DROPPED`, or another counter or status the app author can query, or a WARNING log. Flag
a path that discards due or matched work without recording it. Pay particular attention to
decisions based on wall-clock time ("its fire time has passed") rather than dispatch state ("it
has been popped and dispatched"): a run whose time has passed but that is still queued behind a
slow event loop has not run yet. Treat these as P1 even when the window is short.

Changes to predicates and filters that decide what matches in the first place are out of scope.

- Safe path: base the decision on whether the work was dispatched, or record the drop.

### Interleaving across awaits

In `src/hassette/` runtime code (not `testing/`, `cli/`, or tests), bus handlers, scheduler
callbacks and service loops run concurrently on one event loop. A check followed by an action
with an `await` between them can see the state change underneath it. Flag check-then-act
sequences across an `await` where another task can mutate the same job, listener, cache or
registry entry, and say which task does it.

- Safe path: re-check after the await, do the check and the action without an await between
  them, or hold the lock that guards that state.

### Public API and breaking changes

The public API is anything an app author imports or reaches through an `App` attribute: the names
in `src/hassette/__init__.py`'s `__all__`, the documented submodules (`hassette.testing`,
`hassette.events`, `hassette.models`, `hassette.scheduler`), and `self.bus`, `self.scheduler`,
`self.api` and `self.states`. Releases come from PR titles through release-please. Flag any of
these when the PR title has no `!`:

- a public name removed or renamed;
- a changed default on a public function, method or setting;
- a changed signature on a public function or method.

- Safe path: keep the old name or behavior, or mark the PR title as breaking (`feat!:`, `fix!:`,
  `refactor!:`) and end the PR body with a `BREAKING CHANGE:` footer.
