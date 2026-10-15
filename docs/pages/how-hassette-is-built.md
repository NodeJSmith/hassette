# How Hassette Is Built

Hassette is written by AI coding agents, mostly [Claude Code](https://claude.com/claude-code). I don't write the code, tests, docs or design specs by hand anymore. The design decisions in them are mine, and so is everything that ships: the best code in the repo, every bug, and everything in between. If it's in Hassette, I own it.

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

Hassette also runs my own house. My automation suite of a couple dozen apps tracks Hassette's `main` branch rather than releases, so new code runs in a real home before it ships. It uses most of the framework day to day: the bus, scheduler, API, state manager, cache and testing harness. I change those apps several times a week.

## Why I build it this way

Hassette is my passion project. It started in my dotfiles as a tiny Home Assistant listener, a proof of concept, and grew until it needed its own repo. The first public release came in September 2025, and I plan to keep at it for years. I also work about 60 hours a week across two jobs, so I get fewer hours on Hassette than I'd like. Agents let those hours go to the decisions instead of the typing. Claude also writes better code than I do.

My time goes to the parts an agent can't own:

- Triage. Bug reports and feature requests from other users come first.
- Tooling. When a mistake shows up twice, I add a linter or a check so it gets caught automatically next time. My [Claude Code setup](https://github.com/NodeJSmith/Claudefiles) grew out of building Hassette, and it improves every time Hassette exposes a gap in it.
- Research. Before a design decision, I look at how other projects solved the same problem.
- The backlog. An autofix pipeline turns small, well-specified issues into pull requests without me supervising each one, so simple fixes don't pile up. Its pull requests go through the same checks as everything else.
- What's next. The [Home Assistant integration](getting-started/home-assistant-integration.md) is early and will do much more, and a [Home Assistant app](https://github.com/NodeJSmith/hassette-addon) (formerly add-on) will run Hassette on Home Assistant OS.

I think about Hassette constantly, and I'm proud of it.

## Contributing with AI

AI-assisted pull requests are welcome. The [contributing guide](https://github.com/NodeJSmith/hassette/blob/main/CONTRIBUTING.md#ai-assisted-contributions) covers what I ask of them.
