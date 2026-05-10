---
task_id: "T10"
title: "Wire CLI orchestration, --check mode, and --domain filter"
status: "planned"
depends_on: ["T07", "T08", "T09"]
implements: ["FR#9", "FR#10", "FR#16", "AC#2", "AC#9", "AC#13", "AC#18"]
---

## Summary
Wires all extractors and generators together in the CLI entry point. Implements the full generation pipeline: discover domains → extract → generate → validate → write. Adds --check mode (drift detection with non-zero exit on skipped domains), --domain filter, and per-domain error handling (warn + skip + fail CI).

## Prompt
Complete `codegen/src/hassette_codegen/__main__.py`:

**Main pipeline:**
1. Parse CLI args (--ha-core-path/--ha-release-tag, --check, --domain)
2. Run startup checks (T03's ha_source module)
3. Discover domains (T03)
4. Load manifest (T06)
5. Load overrides (T06)
6. For each domain (filtered by --domain if provided):
   - Try: extract features (T04), properties (T04), base class (T04), services (T05)
   - On any extraction failure: log warning to stderr with domain name + error, mark as skipped, continue
   - Apply overrides (T06)
   - Generate state model (T07), entity wrapper (T08)
7. Generate constants (T09)
8. Generate __init__.py files (T09)
9. For each generated file: validate via `output.py` (ruff + py_compile), write if valid, skip with warning if not (T02)
10. Update manifest (T06) — detect and report orphans
11. Print summary: N domains generated, M skipped, K orphans detected

**--check mode:**
- Generate all files to temp paths (don't write to target)
- Compare each against committed file using `check_drift()` from output.py
- If any file differs: print diff summary, exit 1
- If any domain was skipped: print skipped domains, exit 1 (prevents silent staleness)
- If all match and none skipped: exit 0

**--domain filter:**
- Accept comma-separated domain names: `--domain fan,light,climate`
- Only process listed domains
- __init__.py still regenerated (scans all modules regardless of filter)
- Manifest: merge mode on filtered runs — update entries for processed domains only, leave other entries untouched. Do NOT rewrite the full manifest on filtered runs (would mark unprocessed domains as orphans)

**Error handling:**
- Startup failures (Python version, ruff missing, HA source invalid): exit 1 immediately with clear message
- Per-domain extraction failures: warn + skip + continue
- Per-file validation failures: warn + skip file + continue
- In --check mode: any skip = exit 1

Unit tests in `codegen/tests/test_cli.py`:
- End-to-end: run against fan domain, verify output files exist and pass py_compile
- --check mode: modify a committed file, verify exit 1
- --domain filter: only processes specified domains
- Skipped domain in --check mode causes exit 1

## Focus
- The pipeline must be ordered: extractors before generators before __init__.py (which needs to scan generated files)
- `--domain` filter applies to extraction+generation but NOT to __init__.py generation (which always scans all modules)
- Performance target: under 30 seconds for all 30 domains on a local checkout. AST parsing is fast; bottleneck is ruff formatting (subprocess per file). Consider batching ruff calls.
- Summary output goes to stdout; warnings/errors go to stderr
- The exit code contract is critical for CI: 0 = fresh, 1 = drift or skip, 2 = startup failure

## Verify
- [ ] FR#9: --check mode compares generated output against committed files and exits non-zero on drift
- [ ] FR#10: --domain filter generates only specified domains, leaves others untouched
- [ ] FR#16: Unparseable domains emit a warning and are skipped; in --check mode, skips cause non-zero exit
- [ ] AC#2: --check exits 0 when files match, exits 1 with diff summary when they differ
- [ ] AC#9: Running with --domain fan generates only fan files, other files untouched
- [ ] AC#13: Unparseable domain prints warning to stderr; in --check mode exit code is non-zero
- [ ] AC#18: Files that fail validation are skipped with warning; other files still written
