---
task_id: "T04"
title: "Extract credential/auth test classes from tests/unit/cli/test_client.py"
status: "planned"
depends_on: []
implements: ["FR#4", "AC#4"]
---

## Target Files

- modify: `tests/unit/cli/test_client.py`
- create: `tests/unit/cli/test_client_credentials.py`

## Prompt

`tests/unit/cli/test_client.py` currently exceeds the repo's 800-line file threshold (closes
issue #1581 — note the issue text cites 893 lines, current is ~851; the threshold is exceeded
either way, so proceed regardless of the exact current count). It has 18 test classes covering
`HassetteCLIClient` from `src/hassette/cli/client.py`, plus one unrelated `SimpleModel` Pydantic
helper class (not a test class — leave it where it is unless the classes that use it all move to
the new file, in which case move `SimpleModel` alongside its consumers).

Before starting, read `tests/unit/cli/CLAUDE.md` for this directory's testing conventions —
in particular the "Credential tests: prefer the hermetic factory" section, which governs how
these specific tests should be built.

Read the full current file, then move these credential/auth-related classes into a new
`tests/unit/cli/test_client_credentials.py`:
- `TestCredentialAttachment`
- `TestNoLiteralWebApiTokenArgument`
- `TestVerifySslPassthrough`
- `TestVerifySslWarning`
- `TestNonLoopback401Message`
- `TestRequestIssuedDespiteNoCredential`

Preserve the hermetic-config-factory pattern (`make_cli_config`/`make_test_config`) these tests
already use per `tests/unit/cli/CLAUDE.md`. If `test_env_var_populates_config_and_attaches_bearer_header`
(the deliberate real-env exception documented in that CLAUDE.md, tracked as issue #1552) is among
the moved tests, preserve its full env-clearing setup exactly as-is — do not simplify or drop the
blanket `monkeypatch.delenv` loop over ambient `HASSETTE__*` vars.

Keep shared fixtures/helpers used by both files (e.g. `SimpleModel`, shared constants) importable
from `test_client.py` or promote them to `tests/unit/cli/conftest.py` if that's cleaner — check
`tests/unit/cli/conftest.py` first for what's already there (`CommandRunner`, `CLIClientFactory`,
`MockTransportBuilder`, `GetSpy`, etc. are already documented as living there).

This is a pure move — no logic, assertion, or fixture behavior changes. Give the new file a short
module docstring (3-5 lines) noting it split out of `test_client.py`.

## Verify

- [ ] FR#4: The six credential/auth test classes listed above live in `test_client_credentials.py`; the remaining 12 test classes stay in `test_client.py`. No test dropped or duplicated.
- [ ] AC#4: `uv run pytest tests/unit/cli/test_client.py tests/unit/cli/test_client_credentials.py -v` passes. Test count matches what the original single file reported before the split. Both files are under 800 lines.
