---
topic: "async/sync dual facade patterns for Python libraries"
date: 2026-05-02
status: Draft
---

# Prior Art: Async/Sync Dual Facade Patterns

## The Problem

An async-first Python library needs to serve sync callers (scripts, legacy code, REPL usage, blocking app contexts) without maintaining two separate implementations or degrading the async API. The challenge: how do you bridge sync callers into an async runtime cleanly, handle re-entrancy (calling sync facade from inside an existing event loop), and keep the two surfaces in sync as the API evolves?

## How We Do It Today

Hassette uses **AST-based code generation** (`tools/generate_sync_facade.py`) to produce `ApiSyncFacade` from the async `Api` class. Each async method gets a generated sync wrapper that calls `self.task_bucket.run_sync(self._api.method(args))`. The bridge uses `asyncio.run_coroutine_threadsafe()` — submits the coroutine to the event loop thread and blocks the caller with `fut.result(timeout=...)`.

A `RecordingSyncFacade` (test double) is also generated using AST body-copy — async method bodies are rewritten to sync by stripping `await` keywords and adjusting `self` references. CI runs the generator in `--check` mode to detect drift.

Key constraint: calling `run_sync()` from inside the event loop raises `RuntimeError` immediately — prevents deadlock by failing fast.

## Patterns Found

### Pattern 1: Parallel Implementations with Shared Base

**Used by**: HTTPX (`Client` / `AsyncClient`), Anthropic SDK, OpenAI SDK

**How it works**: Two separate client classes inherit from a common base class. The base contains shared logic (request building, validation, serialization). Each variant plugs in its own transport (`httpx.Client` vs `httpx.AsyncClient`). The sync and async classes have identical method signatures but different I/O implementations.

Anthropic/OpenAI use Stainless (code generator) to produce both variants from an API spec. The shared base (`BaseClient`) handles auth, headers, retry logic. The split happens only at the HTTP transport boundary.

**Strengths**: No runtime bridging overhead. Each variant is natural in its context. No threading complexity. Testing each variant independently is straightforward. The async version is fully native (no greenlet, no thread pool).

**Weaknesses**: Two classes to maintain (even if generated). Shared logic must be carefully factored to the base. Changes must be reflected in both. Risk of drift if not generated.

**Example**: https://www.python-httpx.org/async/

### Pattern 2: Token/Regex-Based Code Generation (Unasync)

**Used by**: HTTPCore (via unasync), urllib3, older HTTPX versions

**How it works**: Write the library in async, then mechanically transform to sync via string substitution: `async def` → `def`, `await ` → ``, `async with` → `with`, `async for` → `for`, class renames (`AsyncClient` → `Client`). The `unasync` tool does this as a build step.

The transformation is purely textual — no understanding of semantics. Works well when the async and sync versions are structurally identical except for async/await keywords.

**Strengths**: Zero maintenance of sync code (it's derived). No runtime overhead. Simple conceptually. Build-time transformation means no import-time cost.

**Weaknesses**: Brittle on complex code (conditional awaits, async generators with complex yields, overloaded names). Cannot handle cases where sync and async implementations legitimately differ. Error messages reference the generated file, confusing during debugging.

**Example**: https://github.com/python-trio/unasync

### Pattern 3: AST-Based Code Generation

**Used by**: Psycopg 3, Playwright Python, hassette

**How it works**: Parse async source code into an AST, apply semantic transformations (remove await nodes, convert async function definitions, adjust type annotations), then unparse back to source. More robust than regex because it understands Python's syntax tree.

Psycopg processes 27 files, generating ~25% of the codebase. Handles edge cases (type annotations in strings, qualified names, conditional branches with async-only paths). Playwright generates both sync and async API modules from a shared `_impl` package.

**Strengths**: Handles complex code that token substitution cannot. Semantic understanding enables validation (detect surviving `await` nodes, flag unmapped types). Build-time — no runtime cost. CI can verify generated code matches source.

**Weaknesses**: More complex tooling to maintain. AST transformations are framework-specific (not a generic tool). Edge cases (dynamic attribute access, string annotations) require special handling. Generated code is not human-readable as source-of-truth.

**Example**: https://www.psycopg.org/articles/2024/09/23/async-to-sync/

### Pattern 4: BlockingPortal / Dedicated Event Loop Thread

**Used by**: AnyIO (`BlockingPortal`), some internal service frameworks

**How it works**: A background thread runs an event loop. The sync facade submits coroutines to that loop via `BlockingPortal.call()` and blocks the calling thread until the result is ready. The portal manages the thread lifecycle and provides both `call()` (blocking) and `start_task_soon()` (fire-and-forget from sync).

AnyIO's `BlockingPortalProvider` reuses portals across calls for efficiency. The portal handles thread-safety internally.

**Strengths**: Zero code duplication (the async implementation IS the implementation). No generation needed. Works with any async code unchanged. Thread-safe by design.

**Weaknesses**: Thread creation overhead. Can't be called from inside the event loop thread (deadlock). Adds threading complexity to debugging. Stack traces cross thread boundaries (confusing). Background thread must be managed (start/stop lifecycle).

**Example**: https://anyio.readthedocs.io/en/stable/threads.html

### Pattern 5: Greenlet-Based Bridging

**Used by**: SQLAlchemy 2.0, Playwright (internal), gevent ecosystem

**How it works**: Greenlets provide cooperative coroutines that can switch between sync and async execution contexts without threads. SQLAlchemy keeps its entire core engine synchronous and uses greenlet to transparently bridge to async database drivers — when sync code hits an I/O point, the greenlet switches to an async fiber that performs the await, then switches back.

`AsyncSession.run_sync()` runs user sync code inside a greenlet where I/O calls are automatically awaited. This inverts the typical relationship: async is the thin wrapper, sync is the core.

**Strengths**: Zero code duplication. No code generation. Minimal performance overhead (greenlet switches are fast). The sync core remains simple and testable. Async is transparent — existing sync code works without modification.

**Weaknesses**: Requires greenlet C extension (platform compatibility issues, no wheel for all platforms). Complex to understand and debug. Stack introspection is confusing. Not pure Python. SQLAlchemy makes greenlet optional, falling back to sync-only if unavailable.

**Example**: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html

### Pattern 6: asyncio.run() Wrapper

**Used by**: Small libraries, CLI tools, one-off scripts

**How it works**: The simplest approach — each sync method calls `asyncio.run(self.async_method(...))`. Creates a new event loop per call, runs the coroutine to completion, then closes the loop.

**Strengths**: Trivially simple. No dependencies. No threads. No generation.

**Weaknesses**: Creates/destroys an event loop per call (expensive). Cannot be called from inside an existing event loop (raises RuntimeError). Cannot share state across calls (connection pools, sessions). Anti-pattern for library code — only appropriate for scripts.

**Example**: [no source found — too trivial for dedicated documentation]

### Pattern 7: External Code Generation from API Spec

**Used by**: OpenAI/Anthropic (via Stainless), Stripe, Cloudflare, gRPC

**How it works**: Both sync and async variants are generated from an external specification (OpenAPI, gRPC proto, custom DSL). Neither is derived from the other — both are first-class outputs. The spec is the source of truth; code in both variants is mechanically produced.

**Strengths**: Perfect parity guaranteed by construction. Spec changes automatically propagate. No manual maintenance of either variant. Can generate for multiple languages from the same spec.

**Weaknesses**: Requires maintaining a spec (additional artifact). Generated code may not be idiomatic. Customization requires spec-level changes. Lock-in to the generation tool.

**Example**: https://deepwiki.com/anthropics/anthropic-sdk-python/4.2-synchronous-and-asynchronous-clients

## Anti-Patterns

- **asyncio.run() inside an existing event loop**: Causes RuntimeError. Library code must never assume it's the only event loop user. Use `run_coroutine_threadsafe` or BlockingPortal instead.

- **Maintaining sync code by hand alongside async**: Drift is inevitable. Any dual-surface that isn't generated or derived will diverge. If you have both, one must be the source of truth for the other.

- **Sync wrapper that silently creates background threads**: If the sync facade spawns threads without the caller's knowledge, resource management becomes unpredictable. Threads should be explicit or managed by a portal with clear lifecycle.

## Emerging Trends

- **AST generation becoming the Python standard**: Psycopg, Playwright, and now hassette all use AST-based generation. The pattern is maturing — tooling exists, CI validation is straightforward, and the approach handles edge cases that regex/token substitution cannot.

- **Greenlet as optional accelerator**: SQLAlchemy's approach of "works without greenlet, faster with it" is a pragmatic model. Libraries that need maximum performance offer greenlet bridging; others can fall back to thread-based portals.

## Relevance to Us

Hassette's approach (**Pattern 3: AST-based code generation** with `asyncio.run_coroutine_threadsafe` as the bridge) aligns with industry best practice:

**What we do well:**
- AST-based generation (most robust transformation approach)
- CI `--check` mode catches drift automatically
- Fast-fail on re-entrant calls (RuntimeError if already in event loop)
- Generated test double (RecordingSyncFacade) from same tooling
- Body-copy for test facades avoids maintaining separate test implementations

**Where we're already aligned with best practice:**
- Generation over hand-maintenance (Patterns 2/3/7 consensus)
- Thread-safe bridge via `run_coroutine_threadsafe` (equivalent to BlockingPortal's approach)
- Source-of-truth is the async implementation

**Minor considerations:**
- The `asyncio.run_coroutine_threadsafe` bridge requires the event loop to already be running. This is fine for hassette (the framework IS the event loop owner), but would be a limitation if the sync facade were used in contexts where no loop exists yet.
- Timeout on `fut.result()` prevents deadlock but may surprise callers with `TimeoutError` on slow operations.

## Recommendation

Hassette's dual facade approach is well-aligned with industry patterns. No significant changes needed — this is a solved problem in the codebase. The AST-based generation + CI check is the same approach used by Psycopg (the most mature Python implementation of this pattern).

One consideration for the future: if hassette ever needs sync usage *without* a running framework (e.g., a standalone `hassette-client` package for scripting), the current `run_coroutine_threadsafe` bridge won't work. In that case, the AnyIO `BlockingPortal` pattern (spawn a background loop thread) would be the upgrade path.

## Sources

### Reference implementations
- https://www.python-httpx.org/async/ — HTTPX parallel client classes
- https://deepwiki.com/anthropics/anthropic-sdk-python/4.2-synchronous-and-asynchronous-clients — Anthropic SDK dual clients
- https://deepwiki.com/microsoft/playwright-python/1.2-api-design — Playwright Python codegen
- https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html — SQLAlchemy greenlet bridging
- https://github.com/anthropics/anthropic-sdk-python/blob/main/src/anthropic/_client.py — Anthropic SDK source

### Documentation & design
- https://anyio.readthedocs.io/en/stable/threads.html — AnyIO BlockingPortal
- https://www.psycopg.org/articles/2024/09/23/async-to-sync/ — Psycopg AST-based generation
- https://github.com/sqlalchemy/sqlalchemy/discussions/8482 — SQLAlchemy greenlet rationale
