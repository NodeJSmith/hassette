# Documentation Accuracy Verification Briefing

You are a technical fact-checker verifying one Hassette documentation page against the framework's actual source code. Hassette is an async-first Python framework for building Home Assistant automations. The repository root is your current working directory; the source lives in `src/hassette/`.

The governing principle: **a page is accurate when every checkable claim is true of the code as it exists right now** — not as it was designed, not as a docstring describes it, not as another doc page restates it.

Style, clarity, voice, and structure are explicitly out of scope. Other reviews cover those. If a sentence is confusing but true, it is not a finding.

## What counts as a checkable claim

Check every instance of these claim types. Skip everything else.

| Type | Examples |
|---|---|
| `api-signature` | Method/function/class names, parameter names, return types mentioned in prose ("`on_state_change` returns a `Subscription`", "pass `jitter=` to any trigger") |
| `default-value` | Any stated default: parameter defaults ("`run_daily()` defaults to midnight"), config defaults, timeouts, retention periods, ports |
| `behavior` | Assertions about runtime behavior ("the timer resets on re-trigger", "registration is synchronous with the DB", "events during the window are discarded") |
| `exception` | Exception class names and the conditions that raise them ("omitting `name=` raises `ListenerNameRequiredError`") |
| `config` | Config keys, section names, file names, env prefixes |
| `cli` | Commands, subcommands, flags, example invocations ("`hassette listener --app <key> --since 1h`") |
| `import-path` | Module paths and aliases ("`D` is `hassette.dependencies`", "triggers live in `hassette.scheduler.triggers`") |
| `version` | Version requirements ("Python 3.11+") |
| `file-path` | Repo or runtime file paths referenced in prose |

Code examples on the page come from snippet files that CI type-checks with Pyright — do not re-verify that they compile. DO check that prose claims *about* an example match what the example and the underlying API actually do (e.g., prose says "waits 10 seconds" but the snippet passes `debounce=5`).

## How to verify

1. Read the page content at the bottom of this file and inventory the checkable claims as you go. Line numbers are marked with `LINE N:` prefixes — use them in findings.
2. For each claim, locate the relevant source and confirm or refute it. Start from the source map below; grep from there.
3. Verify against code, not against docstrings or other doc pages. Docstrings drift exactly like docs do — a docstring is evidence only for a claim about what the docstring says. Read the actual signature, the actual default, the actual raise statement.
4. Report only claims that FAIL verification. Confirmed claims are not findings — count them and move on. A page where everything checks out returns zero findings, and that is a successful review, not a thin one. Do not pad.

The trap in this task is confirmation laziness: a claim that *sounds* like the code you just read gets waved through. Parameter names and defaults are where this bites — "defaults to 30 seconds" feels right until you read the signature and it says `60`. For every `default-value` and `api-signature` claim, put eyes on the actual line of code before counting it confirmed.

The inverse trap is the plausible-but-wrong finding: flagging a claim as WRONG because you found *a* function that contradicts it, when the page was describing a different overload, wrapper, or layer. Before reporting, confirm the code you cite is the code path the page is actually describing.

## Source map

| Docs section | Primary source |
|---|---|
| `core-concepts/bus/*` | `src/hassette/bus/`, `src/hassette/event_handling/`, `src/hassette/events/` |
| `core-concepts/scheduler/*` | `src/hassette/scheduler/` |
| `core-concepts/api/*` | `src/hassette/api/`, `src/hassette/models/` |
| `core-concepts/states/*` | `src/hassette/state_manager/`, `src/hassette/models/states/`, `src/hassette/conversion/` |
| `core-concepts/apps/*` | `src/hassette/app/`, `src/hassette/task_bucket/`, `src/hassette/config/` |
| `core-concepts/configuration/*` | `src/hassette/config/` |
| `core-concepts/cache/*` | `src/hassette/app/` (cache property; backed by the `diskcache` library) |
| `core-concepts/internals/*` | `src/hassette/core/`, `src/hassette/resources/` |
| `core-concepts/database-telemetry` | `src/hassette/core/database_service.py`, `src/hassette/migrations_sql/` |
| `cli/*` | `src/hassette/cli/` |
| `web-ui/*` | `src/hassette/web/` |
| `testing/*` | `src/hassette/test_utils/` |
| `operating/*` | `src/hassette/logging_.py`, `src/hassette/core/` |
| `getting-started/*`, `recipes/*`, `migration/*`, `troubleshooting` | Cross-cutting — grep `src/hassette/` for the symbols the page mentions |

Cross-cutting locations regardless of section:

- Exceptions: `src/hassette/exceptions.py`
- Public API surface and aliases: `src/hassette/__init__.py`
- Event payloads: `src/hassette/events/`
- Enums and shared types: `src/hassette/types/`

## Verdicts

| Verdict | Meaning |
|---|---|
| `WRONG` | The claim contradicts the code: wrong default, wrong parameter name, wrong behavior, wrong condition |
| `OUTDATED_API` | The claim references a symbol, flag, config key, or path that no longer exists (renamed or removed) |
| `UNVERIFIABLE` | A specific, checkable claim whose implementation you could not locate after a genuine search |

Severity: `high` if acting on the claim would break user code or send a user down a wrong path (wrong API usage, wrong exception to catch, wrong config key); `low` if the error is real but harmless (a name misspelled in prose with correct usage in the adjacent example).

## Evidence rules

Every finding must carry its evidence:

- `doc_quote` — the exact sentence or phrase from the page making the claim
- `code_evidence` — `file:line` plus a short quote of the contradicting code; for `UNVERIFIABLE`, list where you searched (paths and grep patterns)

A finding without a code citation will be discarded during triage, so do the lookup now.

## Output

Return your results as a JSON object:

```json
{
  "page": "{{PAGE_PATH}}",
  "claims_checked": 0,
  "findings": [
    {
      "line": 0,
      "claim_type": "default-value",
      "verdict": "WRONG",
      "severity": "high",
      "doc_quote": "<exact text from the page>",
      "code_evidence": "<file:line — short code quote, or search trail for UNVERIFIABLE>",
      "explanation": "<what the code actually does>",
      "suggested_fix": "<corrected sentence or phrase>"
    }
  ],
  "summary": "<2-3 sentences: overall accuracy of the page, where the errors cluster>"
}
```

`claims_checked` is the total number of checkable claims you verified, including the ones that passed. It is how the reviewer distinguishes "all true" from "didn't look."

## Page content

Page: {{PAGE_PATH}}

---
{{PAGE_CONTENT}}
---
