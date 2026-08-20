---
task_id: "T01"
title: "Fix mise.toml java vendor prefix so the duplicate-code checker can run locally"
status: "done"
depends_on: []
implements: ["FR#1", "AC#1"]
---

## Target Files

- modify: `mise.toml`

## Prompt

`mise.toml` currently pins `java = "21.0.12+8.0.LTS"` (line ~5, with a comment noting it's for PMD CPD / `tools/check_duplicate_code.py`). This is missing the required vendor prefix — mise's java plugin needs a vendor-prefixed version string, not a bare version. Without it, `mise install java` fails with "no metadata found for version".

Change the line to:

```toml
java = "temurin-21.0.12+8.0.LTS" # PMD CPD (tools/check_duplicate_code.py) is a JVM tool
```

Verify `mise ls-remote java | grep temurin-21.0.12` shows `temurin-21.0.12+8.0.LTS` as a valid version before assuming this is correct — don't guess at the vendor name.

## Verify

- [ ] FR#1: `mise.toml`'s `java` line reads `java = "temurin-21.0.12+8.0.LTS"`.
- [ ] AC#1: `mise install java` completes successfully, and `mise which java` resolves to a path containing `temurin-21.0.12`.
- [ ] AC#1: `uv run python tools/check_duplicate_code.py` runs to completion (it will report duplication clusters as ERROR exit — that's expected at this point; the goal here is just that it *runs*, not that it's clean).
