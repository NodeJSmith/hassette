# Signal Discoverer Agent Memory

## Run History

### 2026-04-12 — First run
- **Sessions scanned**: 20 sessions, spanning 2026-03-13 to 2026-04-12
- **Session IDs**: 2, 152, 153, 154, 168, 182, 183, 187, 291, 302, 303, 304, 305, 307, 315, 338, 341, 368, 369, 370, 371, 373, 374, 377, 379, 381, 392, 394, 397, 398, 403, 517
- **Key worktrees covered**: docker-sha-tags, test-utils-end-users, better-testing, docs-again, new-docs, release-please, 466, additional-stuff, audit-new-stuff, next-wave-2, prettify, 469-plus-all-docs-challenge, next-wave-3, audit-findings-wave-2, 500-501, fix-db, pr-497

**Candidate counts:**
- UPDATE: 2 (project_v024_release_prep updated; docker tag reference already current)
- FILL_GAP: 6 (changelog, caplog, migration coverage, RecordingApi defaults, RecordingSyncFacade codegen, docs rewrite state)
- CONTRADICT: 0
- NOISE: 2 (viewport already in reference_demo_screenshots; /mine.build already in capabilities.md)

**Candidates accepted (written to memory):**
1. `feedback_changelog_user_facing_only.md` — FILL_GAP
2. `feedback_no_caplog_tests.md` — FILL_GAP
3. `feedback_migration_coverage.md` — FILL_GAP
4. `feedback_recording_api_defaults.md` — FILL_GAP
5. `project_recording_sync_facade_codegen.md` — FILL_GAP
6. `project_v024_release_prep.md` — UPDATE (v0.25.0 + release-please + docs rewrite WP01 state)

**Candidates discarded:**
- Docker image tag format (pr-N, main-py3.13): already captured correctly in reference_demo_screenshots.md line 63
- Screenshot viewport 1400x900: already captured in reference_demo_screenshots.md line 42
- /mine.build as caliper entry: already covered by capabilities.md routing table
