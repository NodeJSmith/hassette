# Exemplar Selections

## Concept Exemplar: Bus Overview

**Page:** `docs/pages/core-concepts/bus/index.md`

**Why this page:**
- Introduces multiple related terms (Bus, subscriptions, handlers, topics, events)
- Sends readers to three sibling depth pages (handlers, filtering, dependency-injection)
- Clear new-reader audience — the bus is the first thing an app-author interacts with after App itself
- Hardest voice mode — system-as-subject, no "you," no imperative. If this page works, everything downstream works

## Recipe Exemplar: Motion-Activated Lights

**Page:** `docs/pages/recipes/motion-lights.md`

**Why this page:**
- Classic automation pattern — universally relatable
- Exercises the "How It Works" prose pattern (Rule 21) which is the most commonly violated recipe pattern
- Uses multiple Hassette features (bus subscription, scheduler, dependency injection, named jobs) — good for demonstrating cross-linking
- Has a natural verification step (trigger motion sensor, check lights)

## Reference Exemplar: Dependency Injection Annotations

**Page:** `docs/pages/core-concepts/bus/dependency-injection.md`

**Why this page:**
- The canonical DI page (FR#5) — must be authoritative and complete
- Naturally tabular: `D.*` annotations map to types and behaviors
- Must demonstrate terse/functional voice distinct from concept narrative
- High cross-link traffic — every page that mentions DI points here
