# Design: Auto-generate `_RecordingSyncFacade` from `RecordingApi`

**Date:** 2026-04-10
**Status:** approved
**Issue:** [#500](https://github.com/anthropics/hassette/issues/500)
**Spec:** N/A — issue body + planner brief serve as spec
**Research:** N/A — investigation conducted inline by `mine.design`
**Challenge:** 24 findings, all resolved. See the Architecture subsections below and the Open Questions section for the Decided block on the runtime-proxy alternative.

## Problem

`src/hassette/test_utils/sync_facade.py` defines `_RecordingSyncFacade` by hand. Every public method on `ApiSyncFacade` (which is itself auto-generated from `Api` via `tools/generate_sync_facade.py`) must have a corresponding entry on `_RecordingSyncFacade`, or the test recording surface silently misses calls.

The existing safeguard at `tests/unit/test_recording_sync_facade_drift.py` checks **method-name parity only** — not method bodies, not signatures. Three failure modes survive that test:

1. **Body drift.** A reviewer hand-edits `_RecordingSyncFacade.turn_on` and forgets to mirror an attribute change made in `RecordingApi.turn_on`. Both sides have a `turn_on`, the test passes, but the sync facade records different data than the async side.
2. **Signature drift.** `ApiSyncFacade.set_state` gains a new keyword-only argument; `_RecordingSyncFacade.set_state` doesn't. `inspect.isfunction` says the names match, the test passes, and the mismatch surfaces as a `TypeError` at call time in user tests.
3. **Property drift.** `inspect.isfunction` is False for properties — any property added to `ApiSyncFacade` is invisible to the drift test.

The hand-maintained file is currently 393 lines: most of it is mechanical mirroring of `RecordingApi`'s body content with `self.X` rewritten as `self._parent.X`, plus 24 `NotImplementedError` stubs that exist solely to satisfy the drift test. Code review on this file is strictly busy-work — there is no human judgment call to make on a sync wrapper that body-copies an async source.

The goal is to make `_RecordingSyncFacade` 100% generated, with structural drift impossible by construction. The drift test is replaced by a CI check that the committed file matches generator output; method name, signature, body, and docstring parity become guarantees instead of test assertions.

## Non-Goals

- **Rewriting `tools/generate_sync_facade.py` from scratch.** The existing wrapper-based path for `Api` → `ApiSyncFacade` keeps working as-is. The new path is a sibling code path inside the same script.
- **Generating `RecordingApi` itself.** The async test double remains hand-written — only its sync mirror is generated.
- **Changing the public surface of `_RecordingSyncFacade`.** Generated output must be byte-equivalent to (or behaviorally identical with) the current hand-written file. No new methods, no removed methods, no behavior changes — except where dictated by the prerequisite refactor of `get_entity_or_none` / `get_state_or_none` (see Architecture, WP1).
- **Generalizing the codegen to arbitrary class pairs.** The body-copy AST rewriter is built specifically for the `RecordingApi` → `_RecordingSyncFacade` shape. Generalization is out of scope.
- **Moving the source-of-truth.** `ApiSyncFacade` (generated from `Api`) remains the canonical method list. `_RecordingSyncFacade` is downstream of it.

## Architecture

### Source-of-truth model

The new generation pass uses **`ApiSyncFacade` as the source of truth for which methods must exist** on `_RecordingSyncFacade`. For each public method on `ApiSyncFacade`, the generator looks up the corresponding async method on `RecordingApi`:

- **Match found** (RecordingApi has an `async def` with the same name) → emit a body-copied sync version with `self.X` → `self._parent.X` rewriting and `await` stripping.
- **No match** → emit a `NotImplementedError` stub. The error message is tiered:
  - Names in `RecordingApi._STATE_CONVERSION_METHODS` (currently `get_state_value`, `get_state_value_typed`, `get_attribute`) get the "Call `harness.api_recorder.sync.get_state(...)` and read directly" message.
  - All other unmatched names get the generic "Seed state via `AppTestHarness.set_state()` or use a full integration test" message.

This eliminates the need for a `RECORDING_SKIP_METHODS` frozenset entirely. Assertion helpers (`assert_called`, `get_calls`, `reset`, …) and internals (`_get_raw_state`, `_convert_state`) are filtered automatically because they are not on `ApiSyncFacade`. Drift becomes structurally impossible: every name on `ApiSyncFacade` produces exactly one entry in the generated facade, and the only choice is which of the two emit paths to use.

**Signature handling for body-copied methods**: The generator body-copies **both** the signature and the body from `RecordingApi`'s `AsyncFunctionDef` node — the signature is not re-synthesized from `ApiSyncFacade`. For body-copied methods, the signature (including defaults) therefore comes from `RecordingApi`, **not** `ApiSyncFacade`. This is an intentional divergence: existing tests depend on `_RecordingSyncFacade.get_entity(entity_id)` working without an explicit `model` argument, which requires the `model: type[Any] = BaseState` default that `RecordingApi` carries and `ApiSyncFacade` does not. To prevent silent surprises, the generator additionally walks both signatures during generation and emits a **warning** (stderr, not fatal) if defaults differ between the two sources on any matched method — developers can then decide whether to harmonize them or accept the divergence as intentional.

**Scope of structural guarantees**: The iterate-ApiSyncFacade strategy makes **method-name and method-body drift** structurally impossible for methods that originate from `Api` (which is walked to produce `ApiSyncFacade`). It does **not** cover:

- **Properties defined in `CLASS_HEADER`** (currently `config_log_level`) — these are hardcoded on `ApiSyncFacade` rather than derived from `Api`, so they are not walked by the generator. A caller invoking `harness.api_recorder.sync.config_log_level` hits the `__getattr__` fallback and receives `NotImplementedError`. This is acceptable because no test exercises `config_log_level` on the sync facade today, but future additions to `CLASS_HEADER` require manual review.
- **New write methods added to `Api` that are not in `RecordingApi`** — covered separately by a new unit test (see Test Strategy) that compares `Api`'s write-method set against `RecordingApi`'s, independent of the deleted drift test.

### AST body rewriter

The existing wrapper generator (`gen_wrapper`) emits `return self.task_bucket.run_sync(self._api.NAME(args))`. The new path needs `gen_recording_method`, which produces a sync `def` whose body is the rewritten async source.

The rewriter is an `ast.NodeTransformer` subclass whose transforms are **scoped to nodes under `FunctionDef.body` only** — default argument expressions (`node.args.defaults`, `node.args.kw_defaults`) and signature annotations are left untouched. The transformer is dispatched explicitly on `node.body` subtrees rather than the whole function definition, so `def foo(self, x=self.CONST)` keeps `self.CONST` intact in the signature while the body is rewritten. The generator unit tests pin this behavior with an explicit case for default-argument self-references.

The three transforms (applied only within `body`):

1. **`self.X` → `self._parent.X`**: Visit every `ast.Attribute` node. If `node.value` is `ast.Name(id='self')`, replace `node.value` with `ast.Attribute(value=ast.Name(id='self'), attr='_parent', ctx=ast.Load())`. Only the **outermost** `self` reference rewrites — `self.hassette.state_registry.try_convert_state(...)` becomes `self._parent.hassette.state_registry.try_convert_state(...)`, exactly one rewrite at the leftmost `self`.
2. **Strip `async`/`await`**: Replace each `ast.Await(value=expr)` with `expr` directly. Convert the enclosing `ast.AsyncFunctionDef` to `ast.FunctionDef` (same fields except for the node type itself).
3. **Drop coroutine-only return type ornaments**: not needed for the current method set, but trivial to add later.

After rewriting, the body is walked once more in invariant-check mode: if any `ast.Await` survives, the generator raises `SystemExit` with the offending method name and a remediation hint.

**Input imports for body-copied methods** (Finding 10 resolution). The generator **dynamically derives** the import block for the generated facade by walking the rewritten body's `ast.Name` and `ast.Attribute` references against a known map of symbol → import path built from `recording_api.py`'s own import block. Any name referenced in a body-copied method that isn't resolvable through this map causes generation to fail with a clear error — "Method `foo` uses symbol `Bar` with no known import path; extend the import map in generate_sync_facade.py or add `Bar` to `recording_api.py`'s imports". This closes the "hardcoded header goes stale" failure mode at generation time and keeps the generator zero-touch as new symbols flow through `RecordingApi`. The dynamic derivation adds ~20 lines to the generator but eliminates the manual header-maintenance surface entirely.

### Async-call safety net (generator-time static check + runtime smoke test)

The await-strip invariant catches `await` keywords but cannot prove the rewritten body is genuinely sync. If `RecordingApi.foo` calls `self.bar()` where `bar` is `async def` (no `await`, just the call producing a coroutine), the await-strip pass leaves the call alone — and the generated `_RecordingSyncFacade.foo` returns a coroutine instead of the expected value.

Two complementary guards:

1. **Generator-time static check** (primary line of defense — Findings 15, 17). Before emitting each body-copied method, the generator parses `RecordingApi` once and builds a set of async-method names. It then walks the rewritten body's `ast.Call` nodes. If any call resolves to an attribute on `self._parent` whose final `.attr` matches an async-method name in the set, the generator raises `SystemExit` with:
   - The method name being body-copied
   - The offending call site
   - Remediation hint: "Refactor `RecordingApi.<name>` to call a sync helper (e.g. `_get_raw_state`, `_convert_state`) directly, or document why this method should be in the NotImplementedError stub tier."

   This is the same mechanism that closes the "hidden authoring constraint" (Finding 15) — any future developer who writes idiomatic async calling peer async methods will hit a loud, actionable generation-time error. It also closes the "`_convert_state` silently becomes async" risk (Finding 17) — if a sync helper is later converted to `async def`, all body-copies that depend on it fail at generation time, not test time. The check is not perfect (dynamic dispatch and aliasing still escape), but it catches the common case at the cheapest point.

2. **Runtime smoke test** at `tests/unit/test_recording_sync_facade.py` (belt-and-suspenders — Findings 18, 21). Construct a `_RecordingSyncFacade` against a stub `RecordingApi` with seeded state, invoke every body-copied method with stub args, and assert each return value is neither a `types.CoroutineType` **nor** an `types.AsyncGeneratorType` (both must be checked — the first covers `async def`, the second covers `async def` with `yield`). The assertion is a named check that includes the method name and closes leaked coroutines to suppress `RuntimeWarning: coroutine was never awaited`:

   ```python
   if isinstance(result, (types.CoroutineType, types.AsyncGeneratorType)):
       if isinstance(result, types.CoroutineType):
           result.close()  # suppress "coroutine was never awaited" warning
       raise AssertionError(
           f"{method_name}() returned a {type(result).__name__} — "
           f"body-copy produced hidden async call"
       )
   ```

   The explicit method name and `result.close()` make test failures diagnostic instead of a bare `assert not True`.

The static check is strictly redundant with the runtime test for call-site-visible violations, but fires at generation time (cheaper to debug) and produces a clearer error. The runtime test remains as the safety net for anything the static walk missed.

**Authoring constraint on `RecordingApi`** (Finding 15 docs portion). The class docstring of `RecordingApi` is updated to document the constraint: "Methods on this class must not call other `async def` methods on `self` directly; use sync helpers (`_get_raw_state`, `_convert_state`) instead. Violating this constraint will fail the `_RecordingSyncFacade` generator with a clear error pointing at the offending call site."

### Prerequisite refactor (WP1)

`RecordingApi.get_entity_or_none` and `RecordingApi.get_state_or_none` currently call other async methods on `self`:

```python
async def get_entity_or_none(self, entity_id: str, model: type[Any] = BaseState) -> BaseState | None:
    try:
        return await self.get_entity(entity_id, model)   # internal await
    except EntityNotFoundError:
        return None
```

After body-copying with the rewriter, the `await` is stripped but the call to `self._parent.get_entity(...)` remains — and `RecordingApi.get_entity` is `async def`. The runtime smoke test would fire on this method.

The fix is to inline the body so it depends only on private sync helpers (`_get_raw_state`, `_convert_state`):

```python
async def get_entity_or_none(self, entity_id: str, model: type[Any] = BaseState) -> BaseState | None:
    try:
        raw = self._get_raw_state(entity_id)
    except EntityNotFoundError:
        return None
    if model is not BaseState and issubclass(model, BaseEntity):
        return cast("BaseState", model.model_validate({"state": raw}))
    return self._convert_state(raw, entity_id)
```

`_get_raw_state` and `_convert_state` are sync and already exist. The `async def` signature stays (callers use `await`); only the body changes. After rewriting for the sync facade, the resulting body becomes `self._parent._get_raw_state(...)` + `self._parent._convert_state(...)` — fully sync.

`get_state_or_none` gets an analogous refactor.

### Generator CLI structure

`tools/generate_sync_facade.py` extends the existing `argparse` setup with new flags. Default behaviour generates **both** facades:

```
generate_sync_facade.py
  [--api-path PATH]                # default: src/hassette/api/api.py
  [--out PATH]                     # default: alongside api.py as sync.py
  [--recording-api-path PATH]      # default: src/hassette/test_utils/recording_api.py
  [--recording-out PATH]           # default: src/hassette/test_utils/sync_facade.py
  [--target {api,recording,both}]  # default: both
  [--check]                        # exit non-zero if generated content differs from --out / --recording-out
```

`main()` dispatches to `generate_sync_api(...)` and/or `generate_sync_recording(...)` based on `--target`. In `--check` mode, neither path writes to the target — they read the current file content, generate fresh content, run both through the same ruff binary for normalization, and `sys.exit(1)` with an actionable error message if the comparison fails:

```
_RecordingSyncFacade is out of date.
Re-run: uv run tools/generate_sync_facade.py --target recording
```

**`--check` mode format-normalization protocol** (Findings 5, 6). The existing `run_ruff()` post-write step is shared: both facades go through `ruff format` + `ruff check` after writing. In `--check` mode, comparison is **format-version-agnostic** — both sides are normalized through the same ruff binary before diffing:

1. Write the freshly-generated output to a `tempfile.NamedTemporaryFile(suffix=".py", delete=True)` **outside the repository** (cleaned up on exit). This keeps `git diff --exit-code` uncontaminated.
2. Run `ruff format` on the temp file.
3. Read the committed target file and run it through `ruff format --stdin-filename=<path>` via stdin (same binary, same version — no on-disk mutation of the committed file).
4. Byte-compare the two formatted outputs.

Using the same ruff binary for both sides eliminates spurious drift from version skew between pre-commit's ruff pin and CI's ruff binary. The temp file lives outside the worktree so a failed `--check` run never leaves files inside the repo that would confuse `git diff --exit-code`.

**Robustness improvements to `run_ruff()`** (Findings 4, 22, 23, 24, shared by both generation paths):

- Add `check=True` to the `subprocess.run(["ruff", "format", str(path)])` call — currently silent, which lets malformed generator output slip through to the commit.
- Add `timeout=30` to both `subprocess.run` calls; catch `subprocess.TimeoutExpired` and re-raise as `SystemExit("ruff timed out after 30s — check for filesystem stall")`.
- Wrap the calls in `try/except FileNotFoundError` raising `SystemExit("ruff not found on PATH. Install with: uv tool install ruff")` so a missing ruff produces an actionable error instead of a raw Python traceback.
- Wrap `ast.parse()` calls in `try/except SyntaxError` raising `SystemExit(f"Syntax error in {path}: {e}")` so malformed source files produce clean error messages instead of raw Python tracebacks.

These changes are localized to `run_ruff()` and the generator's top-level parse call; they apply to both `Api` and `RecordingApi` generation paths automatically.

### Output file template

The generator's output for `_RecordingSyncFacade` is a complete file with three sections:

1. **Module header** — import block **dynamically derived** from `recording_api.py`'s imports, filtered to the symbols actually referenced by the generated bodies (Finding 10 fix — no hardcoded header to drift).
2. **Class header** — `_RecordingSyncFacade` declaration, `_parent` annotation, `__init__`, and the `__getattr__` fallback. Hardcoded as a string constant `_RECORDING_CLASS_HEADER` in the generator. The exact text of this constant is pinned verbatim in the **Class header template (pinned)** subsection below so reviewers can diff the first generator output against it character-for-character (Finding 12 fix).
3. **Generated method bodies** — emitted in the order ApiSyncFacade methods are walked. Each method is either a body-copy (from `RecordingApi`) or a NotImplementedError stub.

The single-file decision (user-locked) means **no hand-written sections**. The `__getattr__` fallback is in the static class header; everything below it is fully generated.

**Stub message templates as named constants** (Finding 19). The NotImplementedError message strings are defined as module-level constants at the top of `generate_sync_facade.py`:

```python
_STUB_MSG_STATE_CONVERSION = (
    "RecordingApi.sync.{name} is not implemented on the test facade. "
    "Call `harness.api_recorder.sync.get_state(entity_id)` and read the returned state directly."
)
_STUB_MSG_GENERIC = (
    "RecordingApi.sync.{name} is not implemented. "
    "Seed state via AppTestHarness.set_state() for read methods, "
    "or use a full integration test for methods requiring a live HA connection."
)
```

The existing tests at `tests/unit/test_recording_sync_facade.py` that assert on exact substrings of these messages are updated to import and reference the constants, so any message change requires editing one location and test breakage is localized. The `__getattr__` fallback in the class header template interpolates the same constants.

**Class header template (pinned — exact text for first-merge diff review):**

```python
class _RecordingSyncFacade:  # pyright: ignore[reportUnusedClass]
    """Synchronous recording facade for RecordingApi.

    Instances are created by RecordingApi.__init__ and share the parent's
    `calls` list via the `_parent` reference. Users access it via `harness.api_recorder.sync`
    (which is `RecordingApi.sync`).

    This file is generated by tools/generate_sync_facade.py — do not edit by hand.
    """

    _parent: "RecordingApi"

    def __init__(self, parent: "RecordingApi") -> None:
        self._parent = parent

    # NOTE: __getattr__ raises AttributeError for names starting with `_`, including `_parent`.
    # If `_parent` lookup falls through here (e.g., during mock construction before __init__
    # completes, or in a subclass that skips super().__init__), the error will be
    # AttributeError: _parent — which is by design; partial construction is an error.
    def __getattr__(self, name: str) -> Any:
        """Raise NotImplementedError for public attributes not defined on _RecordingSyncFacade.

        Private attributes fall through to the default AttributeError so that Python
        machinery works correctly. All known public methods from ``ApiSyncFacade``
        are explicitly generated (either body-copied from RecordingApi or stubbed
        with NotImplementedError). This fallback catches any public attribute that
        is not a generated method — typically a typo or a brand-new method on
        ``ApiSyncFacade`` that the CI drift gate is about to flag.
        """
        if name.startswith("_"):
            raise AttributeError(name)

        raise NotImplementedError(_STUB_MSG_GENERIC.format(name=name))
```

This template is the first-merge review anchor: when WP3 runs the generator and commits the output, the class header must exactly match this text. Any divergence is either a template bug or an intentional wording change that requires a design doc update.

### Pre-commit and CI integration

The repo's `.pre-commit-config.yaml` already runs `tools/generate_sync_facade.py` at the `pre-push` stage, gated on changes to `src/hassette/api/api.py`. Changes:

1. **Update the existing first entry** to pass `--target api` explicitly so the two hooks have non-overlapping responsibilities.
2. **Add a second hook entry** for `--target recording` with a broad `files:` pattern covering **all three** sources that can cause the recording facade to go stale (Findings 2, 20):

   ```yaml
   - id: generate_recording_sync_facade
     name: Generate _RecordingSyncFacade
     language: python
     entry: python tools/generate_sync_facade.py --target recording
     pass_filenames: false
     files: (src/hassette/test_utils/recording_api\.py|src/hassette/api/api\.py|tools/generate_sync_facade\.py)
     stages: [pre-push]
   ```

   The `files:` regex covers:
   - `recording_api.py` — direct source for body-copied methods
   - `api.py` — via `ApiSyncFacade`, the source of the method list that drives generation
   - `tools/generate_sync_facade.py` — the generator itself; active generator development re-runs the hook so the committed output stays current

   This closes the silent-staleness window from either upstream-source change.

**CI drift gate** (Finding 7). `.github/workflows/lint.yml` already runs `pre-commit run --all-files --hook-stage pre-push` — both hooks execute. The lint job gains a new step immediately after the pre-commit step:

```yaml
- name: Fail if generators produced drift
  run: |
    if ! git diff --exit-code; then
      echo ""
      echo "ERROR: generated files are out of date. Re-run locally and commit:"
      echo "  uv run tools/generate_sync_facade.py --target both"
      echo ""
      exit 1
    fi
```

Local DX stays the same — pre-push hooks auto-fix, developers commit the rewrite as part of their change. CI catches stale committed files with an actionable remediation command. The Option α / Option β tradeoff is resolved in favor of Option α: auto-fix locally, fail loud in CI.

**WP sequencing** (Findings 7, 8, 11). The CI drift gate must land **in the same WP as — or before — the drift test deletion**. The required ordering inside that WP is:

1. Add the `git diff --exit-code` step to `lint.yml`.
2. Run the generator, commit the generated `sync_facade.py`, diff-review against the hand-written file.
3. Add the required subprocess regression test (see Test Strategy).
4. Delete `test_recording_sync_facade_drift.py`.

The drift test stays alive until the new file is diff-reviewed and the CI gate is confirmed working. No window exists where neither guard is active.

### Drift test retirement

`tests/unit/test_recording_sync_facade_drift.py` becomes redundant the moment `_RecordingSyncFacade` is generated:

- Method-name parity is structurally guaranteed by the generator (we iterate ApiSyncFacade method names directly).
- Body-level correctness is guaranteed because the bodies come from the same source AST.
- Signature parity within the body-copied method set is guaranteed because `format_signature_and_call` (existing) emits the signature verbatim from `RecordingApi`'s AST.

The file is **deleted**, not converted — but only after the replacement guards are in place (see WP sequencing above). The required replacement test at `tests/unit/test_recording_sync_facade_generation.py` invokes the generator in `--check` mode via subprocess and asserts exit code 0, surfacing drift in `pytest` output for developers who don't push frequently. This test is **required** (Finding 11), not optional — it's the local-pytest signal that bridges the gap between the deleted drift test and the CI gate, so developers get instant feedback on drift without needing to push.

## Alternatives Considered

### Iterate `RecordingApi` + `RECORDING_SKIP_METHODS` frozenset (the planner's original proposal)

Walk `RecordingApi` async methods, skip via a hand-maintained frozenset of names that should not be body-copied (assertion helpers, internals, NotImplementedError stubs), then run a second pass over `ApiSyncFacade` to fill in stubs for any names missed. This was the planner's original suggestion and what the user initially confirmed.

**Rejected because** it creates two failure modes the chosen approach avoids:

1. **Skip-list maintenance burden**. Every assertion helper or internal added to `RecordingApi` must also be added to `RECORDING_SKIP_METHODS` or it gets incorrectly body-copied. The skip list is hand-edited and lives in the generator, not next to the methods it filters — easy to forget.
2. **Drift can re-emerge between RecordingApi and ApiSyncFacade**. If `RecordingApi` doesn't have a method that `ApiSyncFacade` does, the second pass catches it, but the symmetry is implicit. The chosen approach makes ApiSyncFacade the **single** source-of-truth for the method list.

The user re-confirmed the iterate-ApiSyncFacade approach during Phase 3 of design after weighing both.

### Decorator-based skip list (`@_no_sync_facade`)

Tag methods on `RecordingApi` directly with a decorator that the generator inspects. **Rejected** in the user's open-questions answers — the user prefers in-generator control over decorating production code with codegen metadata. Moot under the chosen approach since no skip list exists at all.

### Static dataflow analysis instead of runtime smoke test

Walk the rewritten body's AST looking for `ast.Call` nodes whose target name matches a known-async method on `RecordingApi`. **Rejected as the primary safeguard** because:

- It misses aliasing (`f = self.foo; f()`) and dynamic dispatch.
- It produces false positives when an async method genuinely returns a coroutine that the caller passes to a sync sink.
- The runtime smoke test catches every case it would catch, plus the cases it misses, at a tiny cost (one test run).

It could still be added as a **belt-and-suspenders** check in the generator, but is not on the critical path. Listed here for completeness; not in the WP plan.

### Multiple inheritance for the recording side

Make `_RecordingSyncFacade` inherit from `ApiSyncFacade` and override only the methods that need recording, falling through to the parent's wrapper-based implementations for everything else. **Rejected** because `ApiSyncFacade.__init__` requires a real `Api` instance and the wrapper methods route through `task_bucket.run_sync(self._api.X(...))` — `_RecordingSyncFacade` has no `_api`, only a `_parent` pointing back at `RecordingApi`. The two facades have incompatible base contracts; inheritance is the wrong tool.

### Runtime delegation proxy (`__getattr__`-based)

Replace the entire generator + body-copy strategy with a ~30-line class whose `__getattr__` intercepts every call, looks up the method on `_parent` (a `RecordingApi`), and either calls it directly (sync) or runs it to completion synchronously (for async methods). Raised by the Adversarial critic during the post-design challenge as a structural alternative.

**Rejected** (see Open Questions → Decided, "Runtime delegation proxy alternative rejected" for the full rationale). Summary: static analyzability, behavioral isolation, and per-method NotImplementedError guidance all require a real class with real methods. A runtime proxy produces an opaque `Any`-typed surface that IDEs and pyright can't introspect. The cost of the body-copy generator is front-loaded; the cost of a runtime proxy is amortized across every test writer who has to guess what methods exist and what they return.

The runtime proxy remains a valid **fallback** if WP2's AST rewriter hits a structural impasse. WP2 should escalate rather than fight the rewriter for multiple days.

## Test Strategy

### Existing test infrastructure

- `tests/unit/test_recording_api.py` — exercises the RecordingApi async surface. Already exists; updated where the prerequisite refactor changes behavior (it should not change behavior, but the test gets a fresh run as a regression baseline).
- `tests/unit/test_recording_sync_facade.py` — exercises the sync facade contract. Already exists; gains the runtime smoke test (see below) and existing test cases continue to validate behavior.
- `tests/unit/test_recording_sync_facade_drift.py` — **deleted** after the WP sequencing above.

### New tests (all required — nothing in this list is optional)

1. **WP1 BaseEntity regression test** in `tests/unit/test_recording_api.py` (Finding 16). Call `get_entity_or_none(entity_id, model=SomeLightEntity)` with seeded state and assert the returned object is an instance of `SomeLightEntity`. Pins the behavioral equivalence of the WP1 inline refactor against the previous `await self.get_entity(...)` implementation. Added in WP1 so the refactor is protected from day one.
2. **Runtime smoke test** in `tests/unit/test_recording_sync_facade.py` (Findings 17, 18, 21). Construct a `_RecordingSyncFacade` against a stub `RecordingApi` with seeded state. For each body-copied method (write methods + read methods), invoke with stub args and assert:

   ```python
   if isinstance(result, (types.CoroutineType, types.AsyncGeneratorType)):
       if isinstance(result, types.CoroutineType):
           result.close()
       raise AssertionError(
           f"{method_name}() returned a {type(result).__name__} — "
           f"body-copy produced hidden async call"
       )
   ```

   Covers both `CoroutineType` and `AsyncGeneratorType`. Includes method name in failure message. Closes leaked coroutines to suppress `RuntimeWarning` noise.
3. **Generator unit test** at `tests/unit/test_generate_sync_facade.py` (new file). Feed synthetic `ClassDef` ASTs to `gen_recording_method` and assert:
   - Rewritten body has no `ast.Await` nodes
   - `self._parent` rewrite applies only under `body`, not in `args.defaults` (explicit test case for `def foo(self, x=self.CONST)`)
   - Nested attribute chains (`self.hassette.registry.foo`) rewrite at the outermost `self` only
   - Lambdas referencing `self` inside the body rewrite correctly
   - The generator-time static check (Findings 15/17) raises `SystemExit` when a body-copied method calls a peer async method
4. **Subprocess regression test** at `tests/unit/test_recording_sync_facade_generation.py` (Finding 11 — **required**, not optional). Invoke `tools/generate_sync_facade.py --target recording --check` via `subprocess.run` and assert exit code 0. Provides an instant local pytest signal for generation drift — the bridge between the deleted drift test and the CI gate. Runs on every local `pytest` invocation.
5. **Api-vs-RecordingApi write-method parity test** (Finding 14). A new unit test — not in the deleted drift test file — that compares `Api`'s public write-method set against `RecordingApi`'s method list. Fires when `Api` gains a write method that `RecordingApi` should record but doesn't. This re-establishes the signal that the deleted drift test was incidentally providing for the recording direction.
6. **CI drift gate** in `.github/workflows/lint.yml`. After `uvx pre-commit run --all-files --hook-stage pre-push`, add the `git diff --exit-code` step with the actionable error message shown in the Pre-commit and CI integration section above.

### Behavioral parity verification (one-shot, manual)

After the first generator run replaces `sync_facade.py` (inside WP3), compare the new file against the hand-written original (git diff or `difftool`). Any **non-whitespace** difference is either (a) a real bug in the generator that must be fixed before merge, or (b) a behavioral change that must be approved by review. Whitespace-only differences (ruff reformatting) are accepted. The committed class header must exactly match the "Class header template (pinned)" subsection above — this is the review anchor.

## Open Questions

None blocking. All architecture decisions resolved during Phase 3 and the post-challenge revision pass.

### Decided (post-challenge)

- **Method-source strategy**: iterate `ApiSyncFacade` (no `RECORDING_SKIP_METHODS` frozenset).
- **CI integration**: pre-commit hook auto-fixes locally, `git diff --exit-code` in `lint.yml` fails loud in CI.
- **Async safety**: generator-time static check (walk `ast.Call` for async peer calls) + runtime smoke test (`CoroutineType` + `AsyncGeneratorType`).
- **Runtime delegation proxy alternative rejected** (from the challenge TENSION finding). The Adversarial critic proposed replacing the entire body-copy generator with a ~30-line `__getattr__`-based runtime delegation proxy that calls into `RecordingApi` and runs coroutines synchronously. Rejected in favor of body-copy because:
  1. **Static analyzability**. Body-copy produces a real class with real method definitions that pyright and IDEs can inspect. A `__getattr__` proxy surfaces every method as a generic `Any` callable — no signature hints, no parameter discovery, no return type for users writing test assertions.
  2. **Behavioral isolation**. Body-copy keeps the sync path fully independent of the async path at test time. A runtime proxy conflates the two — a bug in `RecordingApi`'s async method shows up as a sync-facade test failure, making root-cause analysis harder.
  3. **Explicit NotImplementedError stubs** with tailored messages per method tier (state-conversion vs generic) are preserved. A `__getattr__` proxy would produce the same message for every missing method, losing the per-method guidance the current file provides.
  4. **The other four critics** (Senior, Architect, Contract & Caller, Operational Resilience) accepted body-copy and found specific implementation issues within it — all of which are resolved in this revision. No specialist flagged body-copy itself as wrong.

  The runtime proxy approach is the **correct fallback** if body-copy proves unworkable at implementation time (e.g., if the AST rewriter runs into a structural edge case that can't be cleanly solved). WP2 should escalate rather than spend multiple days fighting the rewriter.
- **Signature source for body-copied methods**: signatures come from `RecordingApi`, not `ApiSyncFacade`. Generator emits a warning (stderr, non-fatal) if defaults differ between the two sources so divergence is visible at generation time.
- **Import block**: dynamically derived from `recording_api.py` imports, filtered to symbols actually referenced in the generated bodies.
- **WP sequencing**: CI drift gate lands in the same WP as (or before) the drift test deletion. Required subprocess regression test lands alongside.
- **Authoring constraint**: documented in `RecordingApi` docstring **and** enforced by the generator-time static check — belt and suspenders.

### Deferred to implementation

- The exact error-message wording for generator `SystemExit` messages (cosmetic; first pass can iterate).
- Whether the pinned class header template text in the design doc matches the implemented `_RECORDING_CLASS_HEADER` constant byte-for-byte — the first-merge diff review is the verification.

## Impact

**Files added:**
- `tests/unit/test_recording_sync_facade_generation.py` — subprocess regression test (**required**, runs `--check` via subprocess)
- `tests/unit/test_generate_sync_facade.py` — generator AST rewriter unit tests (new file)
- A new test in an existing or new file for the `Api`-vs-`RecordingApi` write-method parity check (Finding 14)

**Files modified:**
- `tools/generate_sync_facade.py` — extended with `gen_recording_method`, `generate_sync_recording`, AST body rewriter (scoped to `body`), dynamic import derivation, stub message constants (`_STUB_MSG_*`), `_RECORDING_CLASS_HEADER` constant, `--check` mode with tempfile-based ruff normalization, `--target` flag, `--recording-*` paths, generator-time static check for async peer calls, robustness fixes to `run_ruff()` (check=True, timeout=30, FileNotFoundError, SyntaxError handling)
- `src/hassette/test_utils/recording_api.py` — refactor `get_entity_or_none` and `get_state_or_none` to use private sync helpers directly; add class docstring comment documenting the authoring constraint
- `src/hassette/test_utils/sync_facade.py` — replaced with generated output (functionally equivalent to the current hand-written file)
- `tests/unit/test_recording_sync_facade.py` — add runtime coroutine + async-generator smoke test; update message-string assertions to import constants from the generator
- `tests/unit/test_recording_api.py` — add WP1 BaseEntity regression test for the inlined `get_entity_or_none`
- `.pre-commit-config.yaml` — existing hook gets `--target api`; new hook for `--target recording` with broad `files:` regex covering `recording_api.py | api.py | generate_sync_facade.py`
- `.github/workflows/lint.yml` — `git diff --exit-code` step with actionable error message after pre-commit

**Files deleted:**
- `tests/unit/test_recording_sync_facade_drift.py` — superseded by generator + CI gate + subprocess regression test + API-vs-RecordingApi parity test (deleted in the same WP as the CI gate lands)

**Blast radius:** narrow. All changes live in `tools/`, `src/hassette/test_utils/`, `tests/unit/`, and CI config. No production runtime code changes. The single behavioral change in `recording_api.py` (the prerequisite refactor) is functionally equivalent to the current implementation — it just inlines logic that was previously routed through async helpers.

**Dependencies that will need updates:** none. No new third-party dependencies. Standard library `ast` module powers the entire rewriter.

**Risk profile:**
- **Low** — generator AST rewrite (well-trodden territory in this repo; the existing `gen_wrapper` does similar work)
- **Low** — pre-commit hook addition (mechanical)
- **Medium** — first replacement of the hand-written `sync_facade.py` (must be diff-reviewed before merge to confirm behavioral equivalence)
- **Low-Medium** — CI drift gate (`git diff --exit-code` is well-understood; the only failure mode is forgetting to commit a regenerated file)
