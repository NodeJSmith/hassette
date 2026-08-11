# Research: UI-Editable App Config Overrides

**Date:** 2026-08-11
**Design:** `design/specs/095-ui-config-overrides/design.md`

Three investigations backing that design. Each answered a question that would otherwise have been
settled by instinct, and two of them refuted the instinct.

## Briefs

| Brief | Question | Outcome |
|---|---|---|
| `config-precedence-prior-art.md` | Where do comparable systems store UI-set config, and how do they resolve file-vs-UI conflicts? | Almost none write back to the user's config file. The read-only-mount problem that had blocked this twice was a false constraint. |
| `form-library-prior-art.md` | Adopt a JSON Schema form library or hand-roll the editable renderer? | Benchmarked, not read about. `@rjsf/shadcn` adopted; the objection that killed the obvious alternative was not the one expected. |
| `cli-config-set-prior-art.md` | What argument shape should `hassette app config set` use? | Refuted the helm-style recommendation this author started with, for a specific reason. |

## What each one changed

### Config precedence, provenance, persistence

The finding that reframed the problem: **systems that rewrite the user's own config file are the
outliers, and they are the ones with the worst documented failures.** systemd writes drop-ins to a
separate directory; Home Assistant writes `.storage/*.json`; HA add-ons write `/data/options.json`;
Sentry, Paperless, django-constance, and Immich write database rows. Only Zigbee2MQTT and Frigate
rewrite the user's YAML, and both carry long-standing read-only-mount bug reports.

That dissolved the constraint that had blocked #489/#490: hassette's `data_dir` is already separate
from `config_dir`, already writable, and already holds an atomically-written credential sidecar.

Two mechanisms were adopted from this survey. Sentry's per-key option registry supplies the
provenance model — one predicate feeding the read descriptor, the write rejection, and the CLI
presenter, because Grafana's UI-only guard was routinely bypassed via raw API calls. Frigate's
invalidation rule (editing the file drops the override) was the only staleness rule found that is
not itself a documented pain point — though adversarial review later showed value-equality was the
wrong test for it, and the design uses a generation fence instead.

The cautionary tale worth keeping: Zigbee2MQTT re-applies environment variables immediately before
persisting, so a UI edit to an env-controlled field is reverted *and the reverted value written to
disk in the same save that was meant to store the edit* — two individually reasonable features
composing into silent data loss.

### Form library

The agent installed each candidate against React 19, fed it real `pydantic.model_json_schema()`
output, and measured marginal gzip cost. That mattered: `uniforms` fails `npm install` on React 19
outright, and JSONForms rendered 6 of 13 fields with no markup and no error for the rest.

`@rjsf/shadcn` was better than expected on theming — all 15 shadcn tokens it emits already resolve
in `global.css` — and worse on bundle size, at +108.6 kB gzip against ~8 kB of headroom. The
resolution came from a constraint the research surfaced rather than from the comparison itself: the
size budget applies to the **entry chunk only**, so lazy-loading the edit renderer removes the
objection entirely.

One finding applies regardless of library choice: pydantic's `X | None` renders as a spurious
"option 1 / option 2" selector with the null branch preselected, and fixed tuples render no controls
at all. A ~20-line normalizer fixes both.

### CLI argument shape

This one refuted the starting hypothesis. helm's `--set`/`--set-json`/`--set-string` family looked
like the safest precedent — until the research established *why* those flags accreted: helm has no
schema and must guess types. Hassette already ships `config_schema` on the wire and discards it.

Two constraints were found by probing rather than by reading docs: `--json` is already a global
*output* flag, which kills npm's input-mode design; and cyclopts 4.15.0 cannot accept JSON into a
`dict[...]` parameter in any tested configuration, which disqualifies the cyclopts-native shape.

The deciding pattern: every surveyed tool that supports batched writes uses variadic `key=value`,
and zero batch with positional `key value`. The tools that force one-at-a-time (git, gcloud, aws)
are exactly the ones with no per-write side effect to amortize. Hassette restarts an app per write.

## Caveat

These briefs were written before the design went through adversarial review, and the design
supersedes them where they disagree. Two specifics: the staleness rule moved from `base_value`
equality to a generation fence after an A→B→A reactivation trap was found, and the concurrency token
moved from hash+mtime to a per-instance counter. Read the briefs for evidence and reasoning, and the
design for what was actually decided.
