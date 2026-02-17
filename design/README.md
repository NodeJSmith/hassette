# design/

Internal project design artifacts. Not published to readthedocs — that lives in `docs/`.

## Structure

```
design/
├── adrs/                  Architecture Decision Records
├── interface-design/      Design system (tokens, layout, component specs)
└── research/              Feasibility analysis and implementation planning
```

## What goes where

### `adrs/`

Architecture Decision Records — one file per significant decision. Created when a technical direction is chosen (not when it's still being explored). Numbered sequentially: `001-short-name.md`, `002-short-name.md`.

ADRs record: context, decision, consequences, and alternatives considered. They are append-only — superseded decisions get a `Superseded by: ADR-NNN` status, not deleted.

### `interface-design/`

Design system specification for the web UI. Tokens (colors, spacing, typography), component patterns, and layout rules. Referenced by frontend code and UI-related issues.

### `research/`

Feasibility analysis, implementation planning, and technical exploration. Organized by date and topic:

```
research/
└── YYYY-MM-DD-topic-name/
    ├── research.md           Main research brief
    ├── prereq-01-name.md     Prerequisite breakdowns (if applicable)
    └── ...
```

Research briefs are created when evaluating a proposed change — before committing to an approach. They may feed into an ADR (when a decision is reached) or be abandoned (if the approach is rejected).

## Relationship between research and ADRs

1. **Research** explores the problem space and evaluates options
2. **ADR** records the chosen option and why
3. Research prereqs then guide the implementation of that decision

A research brief without a corresponding ADR means the work is still exploratory. An ADR without a research brief means the decision was straightforward enough not to need one.
