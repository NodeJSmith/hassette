---
topic: "Choosing the released-client baseline for cross-version compat checks"
date: 2026-10-08
status: Draft
---

# Prior Art: Choosing the "released" baseline for old-client vs HEAD-server checks

## The Problem

A cross-version gate tests "the client users have" against HEAD's server, so it has to decide which version counts as released. There are three candidate sources: git tags, the package registry, and the release workflow's outcome. They disagree in the window after a tag is created and before its publish finishes, after a failed publish, when a prerelease is tagged, and when a branch is behind the newest release. Picking the wrong source turns those disagreements into red builds that aren't the PR's fault, or into checks against a client nobody runs.

## How We Do It Today

All three hassette checks take the highest `v*` tag reachable from HEAD (`tools/check_wire_compat.py:81-97`, `git tag --merged HEAD --sort=-v:refname`).

- **`check_wire_compat`** chose this on purpose (`:84-85`): it runs as an offline pre-push hook (`prek.toml:264-270`).
- **`check_client_floor`** walks the same tag list. It errors on prerelease tags.
- **`client_compat`** reuses the resolver (commit 51b64667). Nothing records that choice as deliberate, and the design research says "latest PyPI" (`design/research/2026-10-02-hassette-client-transport/research.md:337`). The tag sets the version and PyPI is only where the client is installed from.

release-please creates the tag before the serial wire → client → hassette publish chain runs (`.github/workflows/release-please.yml:21-37`, `:262/:319/:336`). The gap is acknowledged in `noxfile.py:161-162`.

## Patterns Found

### Pattern 1: Registry as source of truth for "released"
**Used by**: cargo-semver-checks (crates.io by default), japicmp (latest non-SNAPSHOT from Maven), gorelease (`-base=latest` via the module proxy), buf (BSR module form).
**How it works**: The tool asks the registry for the newest installable version. Git is an explicit opt-in (`--baseline-rev`, `.git#tag=`).
**Strengths**: The baseline is always something a user can install. A tag whose publish failed is never picked, so the publish window and a failed publish can't turn the check red. Yanked versions drop out if the resolver follows pip's semantics.
**Weaknesses**: A naive max over registry versions picks up prereleases and yanked versions. It also needs the registry to be reachable, and it ignores branch position.
**Example**: https://github.com/obi1kenobi/cargo-semver-checks

### Pattern 2: Explicit "release recorded" event
**Used by**: Pact Broker (`record-release`, then `can-i-deploy --to-environment`).
**How it works**: The release pipeline records the release only after the artifact is available. Checks query that record.
**Strengths**: Nothing is inferred from tags. Several supported releases can be checked at once.
**Weaknesses**: It needs a state store. A GitHub Release created after publishing would be the lightweight equivalent; no source documents that substitution.
**Example**: https://docs.pact.io/record-release

### Pattern 3: Publish first, tag last
**Used by**: xcookie's release workflow design.
**How it works**: The workflow builds, publishes, then tags. Its reasoning is that "A bad or incomplete PyPI publication cannot be replaced, while a Git tag … can be repaired". Once a tag exists, the package exists too.
**Strengths**: It removes the race at its source, and tag-based selectors become correct.
**Weaknesses**: It needs control over tag creation. release-please creates the tag itself, so this would mean restructuring the release workflow.
**Example**: https://xcookie.readthedocs.io/en/latest/manual/release_workflow_design.html

### Pattern 4: Git-ref baseline (newest tag reachable from the branch)
**Used by**: buf `--against .git#tag=…`, cargo-semver-checks `--baseline-rev`, oasdiff workflows.
**How it works**: The baseline is read from the checkout's history.
**Strengths**: It works offline, gives the same answer for the same commit, and compares a stale branch against the release it was cut from.
**Weaknesses**: The tag may not match anything published. The branch can lag the client users actually run.
**Example**: https://buf.build/docs/breaking/quickstart/

### Pattern 5: Exact pin or pattern filter on top of "latest"
**Used by**: japicmp (`oldVersionPattern`; only SNAPSHOT is excluded by default), cargo-semver-checks `--baseline-version`, Pact (prefers an exact `--version` over `--latest`, which it says avoids race conditions).
**How it works**: "Latest" is the default, with an exact-version or regex override. That override is how rc versions get excluded.
**Example**: https://docs.pact.io/can_i_deploy

## Anti-Patterns

- **The compat job keys on a tag that is pushed before its publish.** The job is red until the publish finishes, and stays red if it fails. This consequence is inferred from xcookie's rationale for its ordering.
- **"Latest" is taken as the max over all registry versions**, which includes yanked versions and prereleases (https://adamj.eu/tech/2021/09/20/how-to-fix-pip-yanked-version-warnings/).
- **A gate uses a floating `--latest`** where an exact, recorded version would do (Pact).

## Relevance to Us

The tools whose job matches `client_compat` ("does what users install still work?") default to the registry. The tools that default to git refs (buf's git form, `--baseline-rev`) are schema diffs that have to run offline, which is `check_wire_compat`'s situation. So the two checks don't need to share a resolver. Each tool's default suits its own purpose.

`client_compat` has one wrinkle the registry tools lack: it types its fixtures with the release's `openapi.json`, which it reads from the matching git tag. A PyPI-chosen version still has to map to `v<version>`. That works whenever the tags are fetched, even when the tag isn't reachable from HEAD.

On question 4 (a branch behind the newest release), registry tools ignore branch position, and no source discusses the trade-off. Applied to us, ignoring branch position has a concrete cost: a branch cut before release N+1 would fail on N+1's routes that HEAD can't yet serve, which is a false red. Limiting the choice to tags reachable from HEAD avoids that. No tool documents that combination, but it is the intersection of patterns 1 and 4.

Pattern 3 fixes the problem at its source, but it means fighting release-please's tag-then-publish model. Patterns 1 and 5 give most of the benefit without touching the release workflow.

## Recommendation

For `client_compat`, the baseline should be **the newest PyPI version of `hassette-client` that is a final release, not yanked, and has a `v<version>` tag reachable from HEAD.** When PyPI has a newer final whose tag the branch can't reach, or a reachable tag isn't on PyPI yet, print a notice rather than failing.

- **Pattern 1** (the registry is the source of truth) fixes the publish window and failed publishes.
- **Pattern 4**'s reachability bound keeps stale branches from going falsely red.
- **The prerelease/yanked filter** is explicit, per pattern 5 and the anti-patterns.

`check_wire_compat` stays tag-based and offline, as its purpose calls for. It should still adopt PEP 440 sorting that drops prereleases, so git's refname sort can't rank an rc above its final release.

Two gaps in the research:

- Prior art says nothing about re-running a check when a release ships (Q5).
- Nothing was found on falling back to the previous version when the newest tag is unpublished.

Both pieces of this proposal are reasoned from the patterns, not copied from a documented tool.

## Sources

Not live-verified.

### Reference implementations
- https://github.com/obi1kenobi/cargo-semver-checks — registry-default baseline, git opt-in
- https://pkg.go.dev/golang.org/x/exp/cmd/gorelease — `-base=latest` via the module proxy
- https://raw.githubusercontent.com/siom79/japicmp/master/src/site/markdown/MavenPlugin.md — latest non-SNAPSHOT, `oldVersionPattern`
- https://buf.build/docs/breaking/quickstart/ — git-ref or registry baseline
- https://prow.k8s.io/view/gcs/kubernetes-jenkins/logs/ci-kubernetes-e2e-gce-new-master-gci-kubectl-skew/1290907818873851904 — scheduled skew jobs (weak evidence)

### Blog posts and writeups
- https://xcookie.readthedocs.io/en/latest/manual/release_workflow_design.html — publish first, tag last
- https://adamj.eu/tech/2021/09/20/how-to-fix-pip-yanked-version-warnings/ — yanked-version semantics

### Documentation and standards
- https://docs.pact.io/record-release — release recorded after the artifact is available
- https://docs.pact.io/can_i_deploy — exact version over `--latest`, which avoids races
