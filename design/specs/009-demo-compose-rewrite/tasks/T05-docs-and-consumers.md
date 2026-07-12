---
task_id: "T05"
title: "Update documentation and consumer scripts for fixed-port demo"
status: "done"
depends_on: ["T03", "T04"]
implements: ["AC#7"]
---

## Summary

Update all documentation and consumer scripts that reference the demo stack's old dynamic-port stdout protocol. Replace with fixed-port URLs and simplified instructions. Update `demo-verify` to use fixed ports directly. Verify the combined line count target.

## Target Files

- modify: `CLAUDE.md`
- modify: `.claude/skills/ui-qa/references/harness.md`
- modify: `.claude/skills/ui-qa/SKILL.md`
- modify: `scripts/README.md`
- modify: `.mise/tasks/demo-verify`
- modify: `tools/frontend/ui_qa_capture.py` (docstring only)
- modify: `design/specs/048-visual-qa-environment/design.md` (contains `DEMO_*=` protocol references at lines 166-169, 180 — update to fixed ports)
- read: `design/specs/009-demo-compose-rewrite/design.md` (Documentation Updates section)

## Prompt

Update all files that reference the demo stack's old interface.

**CLAUDE.md** — In the "Demo Stack & Doc Screenshots" section:
- Update the description of `hassette_demo.py` to reflect it's a thin compose wrapper
- Remove references to the `DEMO_*=` protocol and dynamic ports
- Document fixed default ports (18123, 18126, 15173) and env-var overrides
- Note Docker Compose requirement
- Remove any mention of `DEMO_VITE_HOST` if present (it may not be in CLAUDE.md — verify before editing)
- Keep all existing gotchas (stale app code, stale telemetry) — they are unrelated to this change

**.claude/skills/ui-qa/references/harness.md** — Full rewrite:
- Remove the "Starting" section's stdout protocol parsing instructions
- Replace with: "Run `uv run python scripts/hassette_demo.py` — it prints URLs when ready"
- Replace dynamic `DEMO_FRONTEND_URL=http://localhost:NNNNN` with `http://localhost:15173`
- Replace `DEMO_HASSETTE_URL` with `http://localhost:18126`
- Simplify the "Teardown" gotcha: compose down handles everything; no `hassette-demo-ha-*` orphan recovery needed
- Remove `DEMO_HASSETTE_LOG` and `DEMO_VITE_LOG` references (logs are now in Docker: `docker compose -f scripts/docker/ha-demo.yml logs <service>`)
- Update the `ui_qa_capture.py` command example to use the fixed URL: `--base-url http://localhost:15173`

**.claude/skills/ui-qa/SKILL.md** — Update any references to `DEMO_FRONTEND_URL` or `DEMO_READY` to use the fixed URL `http://localhost:15173`.

**scripts/README.md** — Update the descriptions of `hassette_demo.py` and `capture_screenshots.py` to reflect the compose-based architecture.

**.mise/tasks/demo-verify** — Simplify:
- Remove the FIFO-based stdout parsing (lines 22-38) and `declare -A DEMO_VARS`
- Instead: start the demo with `uv run python scripts/hassette_demo.py &`, then poll `http://localhost:18126/api/health` until it returns 200 (or timeout). Once healthy, poll `/api/apps` at the fixed URL.
- Remove the `DEMO_VARS` references (lines 41-47)
- Keep the app-count and listener-count validation logic

**tools/frontend/ui_qa_capture.py** — Update the docstring (line 11) and help text (line 90) to reference fixed ports instead of `DEMO_FRONTEND_URL`.

## Focus

- `harness.md` is read by agent subagents during UI QA workflows — clarity matters more than brevity.
- `demo-verify` is a bash script — the FIFO/parsing code is ~20 lines that can be replaced with a simple poll loop. The app validation logic (lines 50-88) stays.
- Gap-check finding: `SKILL.md` and `scripts/README.md` reference the old protocol — update these too.
- Gap-check finding: `tools/frontend/ui_qa_capture.py` mentions `DEMO_FRONTEND_URL` in docstrings — cosmetic update.
- Design doc names `design/specs/048-visual-qa-environment/design.md` for conditional update — read it and update any demo protocol references.

## Verify

- [ ] AC#7: Combined line count of `hassette_demo.py` + `capture_screenshots.py` + `demo_stack.py` is under 250 lines (`wc -l scripts/hassette_demo.py scripts/capture_screenshots.py scripts/demo_stack.py`)
