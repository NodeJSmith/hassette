# Security audit follow-ups (2026-08-06)

An external security audit scanned the repo at `4a20fb95` (the merge commit for #1531) and
reported six findings: 2 high, 3 medium, 1 low, all at high confidence. Every one was
independently verified against the code before this split was decided — none were false positives,
though two write-ups were imprecise about severity or location (noted in the briefs).

## Disposition

| # | Finding | Severity | Where it went |
|---|---------|----------|---------------|
| 1 | Pre-login route buffers request bodies with no size ceiling | high | **Shipped** — PR #1532 |
| 2 | Failed-login accounting can overwhelm the shared event loop | high | **Shipped** — PR #1532 |
| 3 | Container-shaped app secrets bypass configuration masking | medium | `brief-b-config-masking.md` |
| 4 | Generated Python can inherit executable structure from upstream strings | medium | `brief-c-codegen-integrity.md` |
| 5 | Recovery callbacks can bypass event-dispatch concurrency limits | medium | Existing issue **#573**, updated with audit notes |
| 6 | Generated module names can replace hand-written package files | low | `brief-c-codegen-integrity.md` |

## Why three PRs rather than one

The file sets are disjoint, so a single PR would not conflict. It was split anyway because no one
changelog line describes "DoS + info disclosure + codegen integrity" (see
`.claude/rules/changelog-quality.md` — bundle PRs are banned in titles), and because finding 5 is a
design task rather than a fix.

Findings 1 and 2 shipped together because both are unauthenticated resource-consumption on the same
pre-auth path, which is one coherent changelog entry.

## Estimated remaining effort

- Brief B: ~2h
- Brief C: ~3h
- #573: ~half a day, independent of both

## Reading order

Each brief is self-contained — read only the one you're implementing. `shared-gotchas.md` collects
verification and tooling traps that cost time during PR #1532; skim it before starting either.
