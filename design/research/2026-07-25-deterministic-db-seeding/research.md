---
topic: "deterministic-db-seeding"
date: 2026-07-25
status: Draft
---

# Prior Art: Deterministic Database Seeding for Dev/Test/Demo Scenarios

## The Problem

Hassette's monitoring dashboard has no way to QA the UI in edge-case states (empty, degraded, error, large-volume) without manually orchestrating a real Home Assistant instance and waiting for apps to organically produce telemetry. The existing demo apps (`demo_stimulator`, `backpressure_demo`, etc.) take 60-90 seconds to produce data and can't reliably produce specific failure states on demand. This blocks frontend QA, CLI doc generation, visual regression screenshots, and demos.

## How We Do It Today

No DB-level seeding exists. All telemetry data comes from running real apps against a live HA instance via the demo stack (`scripts/demo_stack.py`). The screenshot capture script (`scripts/capture_screenshots.py`) polls for up to 90 seconds waiting for the demo stimulator to produce enough failure data. Test factories in `src/hassette/test_utils/factories.py` build in-memory dataclasses/mocks but none insert into SQLite.

## Patterns Found

### Pattern 1: Named-Scenario Registry

**Used by**: Grafana TestData datasource (scenario dropdown: random walk, "no data," server error); PostHog Demo 3000 (standalone generator script); Object Mother pattern (Fowler/xUnit community).

**How it works**: A registry maps scenario names to callables that produce complete datasets. Each scenario is self-contained — it knows what "degraded" means in terms of row counts, status distributions, and edge-case values — and delegates writes to a shared writer. The registry is the single source of truth for "what scenarios exist," enumerable by CLI flags or test parametrization.

**Strengths**: New scenarios are additive. "What data looks like" is separated from "how it's written." Scenario names become a stable vocabulary shared across seed code, docs, and UI tests.

**Weaknesses**: Fowler's Object Mother coupling risk — once consumers depend on a scenario's exact shape (row counts, specific error messages), evolving the scenario becomes a breaking change. Mitigation: keep scenario contracts small (documented invariants, not exact literal values).

**Example**: https://grafana.com/docs/grafana/latest/datasources/testdata/ ; https://deviq.com/design-patterns/object-mother-pattern/

### Pattern 2: Schema-Derived Generator

**Used by**: Seedfast (recommendation); Neon (blog series on seed maintenance).

**How it works**: Instead of hand-typed INSERT SQL, the generator derives column shapes from the same definitions the application uses (dataclass fields, model definitions, migration column lists). When a migration adds a column, the generator either picks it up automatically or fails loudly — drift is caught at generation time, not when a dashboard renders a blank field.

**Strengths**: Eliminates the single largest source of documented seed/schema drift. Column definitions live in one place.

**Weaknesses**: Only works if row-shape definitions (dataclasses) stay authoritative. If raw SQL migrations and models drift independently, this closes half the gap — a schema-freshness check covers the other half.

**Example**: https://seedfa.st/blog/seed-file-maintenance ; https://github.com/FactoryBoy/factory_boy/issues/46

### Pattern 3: Deterministic Seeding via Pinned RNG Seed

**Used by**: Mimesis (`seed=`), Faker (`Faker.seed(value)`), pytest-rng, pytest-randomly.

**How it works**: All synthetic-value generation is driven by one seeded PRNG instance. Same seed + same code = same rows every time. Enables reproducible large-volume scenarios without checking thousands of rows into VCS.

**Strengths**: Deterministic output enables snapshot assertions and stable screenshots. A single seed value is trivial to document and vary.

**Weaknesses**: Any non-seeded randomness (wall-clock timestamps, uuid4()) silently breaks reproducibility. The seed must be threaded through every generation call.

**Example**: https://mimesis.readthedocs.io/ ; https://faker.readthedocs.io/en/master/pytest-fixtures.html

### Pattern 4: Standalone Script, Decoupled from Runtime

**Used by**: Grafana `fake-data-gen` (separate repo); PostHog Demo 3000 (separate `seed_demo_data.py`).

**How it works**: The generator lives outside the application's runtime code path — a standalone script invoked explicitly, not bundled into application startup. Versioned independently but tracks schema changes.

**Strengths**: Keeps seed logic out of production code. Seed-only dependencies stay out of the core package. Matches hassette's existing `scripts/` convention.

**Weaknesses**: A standalone tool that duplicates DB-write logic reintroduces drift. The safest version imports the application's real write functions and orchestrates from outside.

**Example**: https://github.com/grafana/fake-data-gen ; https://github.com/PostHog/posthog-demo-3000

## Anti-Patterns

- **Mixing seed rows into schema migrations** — makes migrations non-replayable. Source: Neon
- **Hand-patched `seed.sql` drifting from schema** — missed column updates cascade into broken CI. Sources: Seedfast, Neon
- **Non-idempotent seed scripts** — a seed that fails on second run breaks CI retries. Fix: clear-and-reseed or upsert semantics. Source: Seedfast
- **Object Mother coupling** — consumers hardcoding assumptions about a scenario's exact contents makes the scenario a breaking-change surface. Sources: Fowler, colinjack
- **Environment-specific seed divergence** — dev/test/staging seeds drifting from each other makes bugs environment-specific. Source: Seedfast

## Relevance to Us

Hassette's codebase already has several of the building blocks these patterns call for:

1. **Migration runner is standalone** — `run_migrations(db_path)` is synchronous, uses stdlib `sqlite3`, needs zero hassette runtime. Pattern 4 is already half-built.

2. **Frozen dataclasses map 1:1 to DB rows** — `ExecutionRecord`, `ListenerRegistration`, `ScheduledJobRegistration` are the exact "row shape" objects Pattern 2 says to derive from. Two of three have dedicated param-builder functions (`_execution_insert_params`, `_listener_insert_params`); job inserts are inline.

3. **Test factories exist for registration types** — `make_listener_registration()` and `make_job_registration()` in `test_utils/factories.py` produce real dataclass instances with sensible defaults. No factory exists for `ExecutionRecord` yet.

4. **The fixture/seeding distinction maps to our scenarios** — `empty` and `healthy` are fixture-shaped (small, exact, hand-authored). `large-volume` is seeding-shaped (generated, volume-driven). They may warrant different generation strategies within the same registry.

**Gaps to close:**
- No `_job_insert_params` function (logic is inline in repository)
- No `ExecutionRecord` factory
- No `BlockingEvent` or `LogRecord` factories
- The param builders are module-private (`_` prefix) in `repository.py` — a seeder importing them is reaching across a boundary
- No referential integrity composition (linking executions to listeners/jobs/sessions by FK)

## Recommendation

Combine Patterns 1, 2, and 4:

- **Named-scenario registry** (Pattern 1) as the user-facing API (`--scenario healthy`)
- **Schema-derived generation** (Pattern 2) by reusing the existing frozen dataclasses and param builders, not hand-typing SQL
- **Standalone script** (Pattern 4) in `scripts/`, importing from `hassette.core` but not starting the runtime

Pattern 3 (pinned RNG) is relevant only for `large-volume` — the other scenarios should use fully deterministic, hand-authored values (no randomness at all). This avoids the fragility of threaded RNG seeds for the common cases.

The key architectural decision is whether to extract the param builders out of `repository.py` into a shared module (so both the repository and the seeder import them cleanly) or to have the seeder use raw SQL that mirrors the builder shapes. The former is cleaner but requires a small refactor; the latter is faster but introduces the drift risk Pattern 2 warns against.

## Sources

### Reference implementations
- https://github.com/PostHog/posthog-demo-3000 — PostHog's standalone demo data generator
- https://github.com/grafana/fake-data-gen — Grafana's standalone fake data generator for time-series backends

### Documentation
- https://grafana.com/docs/grafana/latest/datasources/testdata/ — Grafana TestData datasource with named scenarios
- https://grafana.com/docs/grafana-cloud/get-started/create-account/explore-demo-data/ — Grafana Cloud demo data installation
- https://polyfactory.litestar.dev/latest/usage/fixtures.html — Polyfactory ORM-agnostic factory pattern
- https://mimesis.readthedocs.io/ — Mimesis schema-based deterministic generation
- https://faker.readthedocs.io/en/master/pytest-fixtures.html — Faker pytest deterministic seeding

### Blog posts & writeups
- https://neon.com/blog/how-to-maintain-seed-data — Seed file maintenance and anti-patterns
- https://neon.com/blog/database-testing-with-fixtures-and-seeding — Fixture vs. seeding distinction
- https://seedfa.st/blog/database-seeding — Seeding methods survey
- https://seedfa.st/blog/seed-file-maintenance — Schema drift in seed files

### Pattern references
- https://deviq.com/design-patterns/object-mother-pattern/ — Object Mother pattern
- https://reflectoring.io/objectmother-fluent-builder/ — Object Mother vs. Test Data Builder
- http://colinjack.blogspot.com/2008/08/test-data-builder-and-object-mother.html — Object Mother coupling risks
- https://github.com/FactoryBoy/factory_boy/issues/46 — factory_boy without ORM

Note: URLs were not live-verified.
