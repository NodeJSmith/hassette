---
topic: "Keeping a client's minimum-supported-server floor correct"
date: 2026-10-07
status: Draft
---

# Prior Art: Keeping a Client's Minimum-Server Floor Correct

## The Problem

A client library that declares "I work with servers at version X or newer" makes a promise that drifts. Every
time the client starts relying on newer server behavior (a new route, a new query parameter, a response field
it now requires), X has to move. If X doesn't move, users on an old-but-above-X server pass the version check
and then hit failures. The questions are how X gets chosen, what verifies it, and where in the release flow it
gets bumped.

For hassette-client the failure is concrete: `MIN_SERVER_VERSION` is `0.55.0`, and a v0.55.0 server's
`GET /api/apps` response doesn't parse in this client, because four fields became required since.

## How We Do It Today

- `MIN_SERVER_VERSION` in `client/src/hassette_client/version.py` is a hand-set release version. release-please
  doesn't touch it.
- `tools/check_client_floor.py` runs only on release-please PRs (the only place the next version number is
  known). It runs the request half of `client/tests/test_openapi_coverage.py` (route, method, query parameter)
  against `frontend/openapi.json` at tag `v{MIN_SERVER_VERSION}`, falling back to HEAD when the floor is the
  release being cut. Responses aren't checked.
- `tools/check_wire_compat.py` runs oasdiff on every PR in both directions, but only against the latest tag
  and with `tools/wire_compat_ignore.txt` (about 150 entries since v0.55.0) skipped. Its *reversed* run
  ("new client, old server") is exactly the response check the floor needs, aimed at the wrong tag.
- Every release publishes a Docker image tagged with its version (`build_and_publish_image.yml`), and every
  tag has `frontend/openapi.json` committed.

## Patterns Found

### Pattern 1: Hand-picked release floor, no CI at the floor

**Used by**: HA mealie (`MIN_REQUIRED_MEALIE_VERSION`), python-wled (`MIN_REQUIRED_VERSION`), docker-py
(`MINIMUM_DOCKER_API_VERSION = 1.24` while CI tests only API 1.45), aiomealie.
**How it works**: A constant names the oldest supported release; the client or integration compares the
server's reported version and refuses setup below it. A maintainer edits it, typically when dropping an old
major. Mealie's floor moved v1 → v2 in the same HA PR that bumped aiomealie, with the stated reason "we are no
longer able to support/test backward compatibility with version 1". CI runs fixtures from one recent server.
**Strengths**: Trivial; a clear user-facing error; one-line diffs.
**Weaknesses**: The constant is a promise nothing tests. python-wled adds per-feature version constants
(`SYNC_RECEIVE_BY_GROUPS_VERSION`) instead of raising the floor for every new field, which pushes gating into
code.
**Example**: https://github.com/home-assistant/core/pull/153203

### Pattern 2: Server-advertised integer API schema version

**Used by**: zwave-js-server-python (`MIN_SERVER_SCHEMA_VERSION`/`MAX_SERVER_SCHEMA_VERSION`, negotiated),
python-matter-server (`SCHEMA_VERSION`, client and server in one repo), music-assistant (`API_SCHEMA_VERSION`;
the server also advertises `min_supported_schema_version`). These are the HA-ecosystem libraries whose authors
also own the server.
**How it works**: Compatibility is one monotone integer the server reports. A developer bumps it in the same
PR that makes the wire change ("bump schema if we add new features and/or make other (breaking) changes").
The client's floor is a schema number, and integrations gate features with `schema_version >= N`.
**Strengths**: The bump happens in the feature PR that needs it, with no "which release will this be"
question, so nothing depends on the release PR. A build from main reports the right number. music-assistant
uses release-please and still hand-edits the integer, with no interplay problems.
**Weaknesses**: Relies on the author recognizing the change; none of these projects check the bump
mechanically, and their CI runs mocked fixtures at the current schema only.
**Example**: https://github.com/home-assistant-libs/zwave-js-server-python (`zwave_js_server/const/__init__.py`)

### Pattern 3: Relative floor by policy (N-1)

**Used by**: Kubernetes (`kubectl` within one minor of `kube-apiserver`); elasticsearch-py compatibility mode
(search summary only).
**How it works**: The floor is a rule over release numbers, so it moves with every release and there's no
constant to forget. Elastic goes further: the client sends `compatible-with=N` and the server shapes its
response for N.
**Strengths**: Nothing to bump.
**Weaknesses**: Needs either per-skew test jobs maintained by hand at each release (Kubernetes) or
server-side response versioning (Elastic). Kubernetes' own n-2 kubelet promise went untested for a period
(kubernetes/kubernetes#108127).
**Example**: https://kubernetes.io/releases/version-skew-policy/

### Pattern 4: Live integration matrix against real old server builds

**Used by**: opensearch-py (confirmed: 1.0.1, 1.3.20, 2.18.0, 2.19.5, 3.6.0, each secured on/off); MongoDB
drivers (search summary only).
**How it works**: A workflow matrix lists server versions; each job starts that version's container and runs
the client's integration suite, so response parsing is exercised end to end.
**Strengths**: The only pattern found that actually tests responses at the floor.
**Weaknesses**: A container per version, and the matrix is hand-listed with no link to a declared floor, so
the two can drift. Needs a runnable old server.
**Example**: https://github.com/opensearch-project/opensearch-py/blob/main/.github/workflows/integration.yml

### Pattern 5: Consumer-driven contracts (Pact)

**Used by**: Pact users generally; no HA-ecosystem project found.
**How it works**: The client's tests record the requests it makes and the response fields it reads; each
provider version verifies that record; `can-i-deploy` queries the (consumer, provider) matrix.
**Strengths**: Checks exactly what the client consumes, responses included.
**Weaknesses**: Needs a broker and a verification run per old provider build, so it still means running the
old server. Heavy for a solo monorepo.
**Example**: https://docs.pact.io/selectors

## Anti-Patterns

- **Declared floor far below the tested version.** docker-py declares API 1.24 and tests 1.45. hassette-client's
  request-only guard is a milder form: it checks half the contract.
- **Floor bumped only when it hurts.** Mealie's floor moved after a year-plus gap, once v1 became untestable.

## Not Found

- No project computes its floor from tags or releases.
- No client checks its models against an old server's OpenAPI spec. hassette's reversed oasdiff run is
  already the right direction for this (it flags `response-required-property-removed` when the old spec lacks
  a field the new one requires); the web research didn't find anyone else doing it, so it's an extension of
  hassette's own tooling, not borrowed practice.
- No recorded-fixtures-per-server-version scheme.

## Relevance to Us

Two separable choices fall out:

**What the floor is measured in.** Every HA library whose author also owns the server (zwave-js, matter,
music-assistant, the closest analogs to hassette + hassette-client) uses an integer schema version the server
advertises, bumped in the feature PR. Release-version floors (mealie, wled, docker-py) are what libraries use
for servers they don't own. Switching hassette to a schema integer would:

- move the bump to the feature PR that needs it, so the release-please-branch problem (F6) disappears;
- make "which release is the minimum" a non-question, so tag-walking (F5) is unnecessary;
- make main-branch builds report a correct number (F7) and replace D21's PEP 440 comparison with an integer
  comparison;
- add one field to the health response and a server-side constant, and reopen D20/D21/D22's shape.

Old servers that don't report the field read as schema 0, below any floor, which gives the right "upgrade
hassette" error.

**What verifies it.** The ecosystem norm is nothing. The one pattern that tests responses at the floor is a
live old-server matrix (opensearch-py). hassette could do either:

- *Spec-based:* run the coverage test's request checks plus check_wire_compat's reversed oasdiff run against
  the floor's spec, with no ignore file. Cheap, runs from committed specs, but it's our own extension.
- *Live:* start the floor version's published Docker image and run the client against it. The real thing,
  but whether a bare hassette image serves the client's routes without a Home Assistant behind it is
  unverified, and it's a much heavier job.

With a schema integer, "the floor's spec" is the oldest tag whose server reports that schema (or HEAD, when
the schema was bumped since the last release), and the guard can run on every PR instead of only release PRs.

## Recommendation

Adopt the HA same-owner pattern: a server-advertised integer API schema version, with the client's floor
expressed as a schema number and bumped in the feature PR. That's the standards-first answer and it dissolves
three of the four findings (F5, F6, F7) rather than patching them.

Back it with the spec-based guard on every PR (request checks plus reversed oasdiff against the floor schema's
oldest tag, no ignore file), which fixes F4 and goes beyond what any surveyed HA library verifies. Treat a live
floor-image job as a later option if the spec check ever misses something real.

If reopening D20's unit is too much churn this close to the first release, the fallback is Pattern 1 as built,
plus the spec-based response check (F4) and the edit-last protocol (F6). That keeps the release-PR bump and
its awkwardness.

Coverage caveats: the elasticsearch-py, MongoDB and Kubernetes skew-job details come from search summaries,
not source. The HA library evidence was read from source and from the local HA core checkout.

## Sources

URLs were not live-verified.

### Reference implementations
- https://github.com/home-assistant/core/pull/153203 — mealie floor v1 → v2, coupled to the aiomealie bump
- https://github.com/joostlek/python-mealie/blob/main/.github/workflows/tests.yaml — fixture-only CI
- https://github.com/frenck/python-wled/blob/main/src/wled/const.py — `MIN_REQUIRED_VERSION` plus feature-version constants
- https://github.com/home-assistant-libs/zwave-js-server-python — min/max schema negotiation
- https://github.com/home-assistant-libs/python-matter-server — one-repo client/server, `SCHEMA_VERSION`
- https://github.com/music-assistant/client/blob/main/music_assistant_client/constants.py — `API_SCHEMA_VERSION`, release-please plus hand-edited schema
- https://github.com/esphome/aioesphomeapi/blob/main/aioesphomeapi/client.py — per-feature `APIVersion` minimums
- https://github.com/opensearch-project/opensearch-py/blob/main/.github/workflows/integration.yml — live old-server matrix
- https://github.com/docker/docker-py/blob/main/docker/constants.py — declared 1.24, tested 1.45

### Documentation & standards
- https://kubernetes.io/releases/version-skew-policy/ — relative N-1 floor
- https://github.com/kubernetes/kubernetes/issues/108127 — untested skew promise
- https://docs.pact.io/selectors — consumer version selectors and can-i-deploy
- https://github.com/oasdiff/oasdiff — spec diffing
