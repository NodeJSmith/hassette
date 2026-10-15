# How Hassette Is Built

Hassette is written with AI coding agents, mostly [Claude Code](https://claude.com/claude-code). Nearly all of the code, tests, docs and design specs start as agent output. The design decisions in them are mine.

## Who decides what

An agent drafts the spec for a change and lists the design questions it raises. I answer them: what goes into the framework, how a feature behaves at the edges, which trade-off to take. For larger changes, no code gets written until every open question has an answer. The answers are recorded in [`design/`](https://github.com/NodeJSmith/hassette/tree/main/design) or in the issue.

The public API stays small on purpose. A convenience method has to save real boilerplate without adding new ways to fail.

## What every change has to pass

The `main` branch is protected. A pull request can't merge until these checks pass, whether a person or an agent wrote it:

- Pyright type checking, plus linting and formatting.
- Unit and integration tests on Python 3.11, 3.12, 3.13 and 3.14.
- System tests against a real Home Assistant running in Docker, including restarts and injected failures.
- End-to-end browser tests of the web UI.
- Drift checks. The generated entity models must match the pinned Home Assistant release, and the HTTP API must stay compatible with clients that have already been released.

## Running it at home

Hassette also runs my own house. My automation suite of a couple dozen apps tracks Hassette's `main` branch rather than releases, so new code runs in a real home before it ships. It uses most of the framework day to day: the bus, scheduler, API, state manager, cache and testing harness.

## Contributing with AI

AI-assisted pull requests are welcome. The [contributing guide](https://github.com/NodeJSmith/hassette/blob/main/CONTRIBUTING.md#ai-assisted-contributions) covers what I ask of them.
