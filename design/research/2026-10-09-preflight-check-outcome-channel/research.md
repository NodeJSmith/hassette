---
topic: "Pre-flight config check outcome channel between a container entrypoint and the app"
date: 2026-10-09
status: Draft
---

# Prior Art: Pre-flight config check → container entrypoint outcome channel

## The Problem

A container entrypoint runs the app's own config validation before installing dependencies and `exec`ing the server. The entrypoint has to know three things from that call: did validation pass, was this call not a real check at all (`--help`/`--version`), and what should the user do when it failed. Getting any of these by inference produces silent install skips or remedies that can't work.

## How We Do It Today

`scripts/docker_start.sh` runs `hassette run --check`. On success it prints shell-quoted `CONFIG_DIR`/`CONFIG_HOME`/`APPS_DIR`; on a config error it exits 78 and prints `CONFIG_ERROR_SOURCE=environment|file`, guessed from key names in `config/checks.py`. The script reads "exit 0 with no locations" as `--help`/`--version` and skips installs; any non-78 failure gets a "fix your container arguments" banner. The challenge (Findings 1/5/6) flagged all three inferences.

## Patterns Found

### Pattern 1: Decide passthrough from argv before running anything
**Used by**: docker-library postgres (`_pg_want_help`), mysql (`_mysql_want_help`), redis/haproxy (`${1#-}`), nginx.
**How it works**: The entrypoint inspects its own arguments. A help/version-type flag skips all setup and `exec`s directly; the decision never depends on the validator's output.
**Strengths**: No ambiguity; the wrapper already knows.
**Weaknesses**: The flag list must track the CLI.
**Example**: https://raw.githubusercontent.com/docker-library/postgres/master/docker-entrypoint.sh

### Pattern 2: Exit-code handshake, fail closed on any non-zero
**Used by**: mysql `mysql_check_config`, systemd `ExecStartPre`, Kubernetes init containers, Caddy, kubeconform.
**How it works**: 0 = valid, non-zero = stop. Text is for humans only. sysexits 78 (`EX_CONFIG`) / 64 (`EX_USAGE`) separate classes.
**Strengths**: Every failure (crash, OOM, bad config) fails closed uniformly.
**Weaknesses**: Can't tell "validated OK" from "exited 0 without validating"; projects avoid that via Pattern 1.
**Example**: https://raw.githubusercontent.com/docker-library/mysql/master/8.4/docker-entrypoint.sh

### Pattern 3: Machine-readable result (JSON) alongside the exit code
**Used by**: Terraform `validate -json`, Home Assistant `check_config --json`, kubeconform `-output json`.
**How it works**: A structured `valid` boolean; Terraform's docs say unparseable output must be treated as an error.
**Strengths**: Unambiguous, versioned.
**Weaknesses**: Needs a parser in the entrypoint.
**Example**: https://developer.hashicorp.com/terraform/cli/commands/validate

### Pattern 4: In-band success sentinel (`CHECK_RESULT=ok`)
**Used by**: No documented precedent. nginx's "test is successful" and HA's "Successful config" are human text; HA's prints alongside errors.
**Strengths**: Closes "exit 0 without validating".
**Weaknesses**: A private protocol; redundant once Pattern 1 handles help/version.
**Example**: [no source found]

### Pattern 5: One generic remedy, or none
**Used by**: Grafana `run.sh`, docker-library images.
**How it works**: Errors name the offending variable/path; no surveyed entrypoint attributes env vs file or tailors restart vs recreate.
**Strengths**: Can't be wrong about the deployment mode.
**Weaknesses**: Doesn't warn about the `docker restart` keeps-old-env trap unless the text says so.
**Example**: https://raw.githubusercontent.com/grafana/grafana/main/packaging/docker/run.sh

## Anti-Patterns

- Inferring "it was --help" from absent output.
- Treating human success text as a pass signal (HA's heading appears with errors).
- Telling users `docker restart` after an env change (compose issue 4140).

## Relevance to Us

Our check already prints required data on success (the three locations), which is a stronger success signal than a sentinel: the script needs them anyway, so "exit 0 and all three present" is the success condition, and anything else fails closed. Help/version belongs to argv (Pattern 1), which removes the absence inference without a new protocol line. Single-remedy text (Pattern 5) matches the ratified Option B.

## Recommendation

Keep B's single remedy ("fix the setting, then `docker compose up -d`; `docker restart` keeps the old environment"). Drop the `CHECK_RESULT=ok` sentinel: decide help/version from argv before the check, and treat exit 0 without all three locations as a fail-closed halt. Non-78 failures get an "unexpected failure, see above" banner.

## Sources

### Reference implementations
- https://raw.githubusercontent.com/docker-library/postgres/master/docker-entrypoint.sh — argv help detection, `_is_sourced`
- https://raw.githubusercontent.com/docker-library/mysql/master/8.4/docker-entrypoint.sh — `mysql_check_config`, exit-code gating
- https://raw.githubusercontent.com/grafana/grafana/main/packaging/docker/run.sh — error naming, no remedy tailoring
- https://raw.githubusercontent.com/just-containers/s6-overlay/master/README.md — finish scripts, exit codes

### Documentation & standards
- https://developer.hashicorp.com/terraform/cli/commands/validate — JSON result, unparseable = error
- URLs not live-verified.
