---
task_id: "T01"
title: "Add blocking-IO behavior enum, warning, config, and resolver"
status: "done"
depends_on: []
implements: ["FR#7", "AC#6"]
---

## Summary
Build the shared spine the two detection tiers depend on, mirroring the existing forgotten-await machinery: a `BlockingIOBehavior` enum, a `HassetteBlockingIOWarning` class, the `BlockingIODetectionConfig` config model wired into `HassetteConfig`, a per-app `blocking_io_behavior` override on `AppConfig`, and an eager behavior-resolution helper (per-app → global → hardcoded default). No detection logic yet — this is the foundation T02–T05 build on.

## Prompt
Implement the shared types and config for blocking-IO detection. Follow the design doc `design/specs/074-blocking-io-detection/design.md`, sections `## Architecture` → "Shared spine" and "Config surface", and the `## Convention Examples`.

1. **Enum** — add `BlockingIOBehavior(StrEnum)` to `src/hassette/types/enums.py` with members `IGNORE`, `WARN`, `ERROR`, as a direct sibling of the existing `ForgottenAwaitBehavior`. Match its docstring style (note that `ERROR` behaves like `WARN` under normal filters and only escalates via `filterwarnings("error")`).
2. **Warning** — add `HassetteBlockingIOWarning(RuntimeWarning)` to `src/hassette/exceptions.py`, sibling to `HassetteForgottenAwaitWarning`, with a docstring noting it integrates with `-W error` / `pytest.warns` / `filterwarnings` like any `RuntimeWarning`.
3. **Config model** — add `BlockingIODetectionConfig` to `src/hassette/config/models.py` (follow the existing nested-config classes there). Fields:
   - `behavior: BlockingIOBehavior | None = None` (global default; `None` resolves to `WARN`)
   - `watchdog_enabled: bool = True`
   - `lag_threshold_seconds: float` (Tier 1 threshold; pick a documented default, ~0.1)
   - `watchdog_interval_seconds: float` (Tier 1 heartbeat interval; ~0.25)
   - `capture_stack_on_block: bool = True`
   - `deep_detection_enabled: bool | None = None` (Tier 2; `None` means "follow `dev_mode`")
   - `allow_deep_detection_in_prod: bool = False` (the prod-override flag; mirror the `allow_reload_in_prod` docstring style)
4. **Wire into `HassetteConfig`** — in `src/hassette/config/config.py`, add `blocking_io: BlockingIODetectionConfig = Field(default_factory=BlockingIODetectionConfig)` alongside the other nested-config fields (`database`, `websocket`, etc., near the top of the class).
5. **Per-app override** — add `blocking_io_behavior: BlockingIOBehavior | None = None` to `AppConfig` in `src/hassette/app/app_config.py`, sibling to the existing `forgotten_await_behavior` field (line 32), with a docstring describing the `None` → global → `WARN` resolution.
6. **Resolver** — add an eager behavior-resolution helper as a module-level function in a new `src/hassette/core/block_io_guard.py` (this is the canonical location — both the Tier 1 watchdog and the Tier 2 guard import it from here; do not put it in a separate util). It resolves: per-app `AppConfig.blocking_io_behavior` → global `HassetteConfig.blocking_io.behavior` → hardcoded `WARN`. Model it on `guard_await`'s resolution block (Convention Examples), using `contextlib.suppress(AttributeError, ValueError, TypeError)` around the attribute/enum access. Define a `DEFAULT_BLOCKING_IO_BEHAVIOR = BlockingIOBehavior.WARN` constant.

Add unit tests in the appropriate `tests/unit/` location (mirror where `forgotten_await_behavior` resolution is tested — grep for it). Cover: per-app value wins over global; global used when per-app is `None`; hardcoded `WARN` when both `None`; `ignore`/`warn`/`error` all parse.

## Focus
- `src/hassette/types/enums.py` already has `ForgottenAwaitBehavior(StrEnum)` with `IGNORE = auto()` / `WARN = auto()` / `ERROR = auto()` — copy that shape exactly.
- `src/hassette/config/config.py:167` is `asyncio_debug_mode`; `:182` is `allow_reload_in_prod` (the prod-override precedent); `:193` is `forgotten_await_behavior`. Nested-config fields (`database`, `websocket`, `logging`, ...) are near the top of `HassetteConfig` (lines 84–105) via `Field(default_factory=...)` — add `blocking_io` there.
- `src/hassette/app/app_config.py:32` is the `forgotten_await_behavior` field — add the sibling right after it.
- Config fields are Pydantic-validated at load, so the resolver's `suppress` only guards defensive attribute access and the enum constructor — keep it narrow (`AttributeError, ValueError, TypeError`), exactly like `guard_await`.
- Reverse-dep note: tests that construct `HassetteConfig`/`AppConfig` asserting on an exact field set may need the new fields. Grep `tests/` for direct construction and extend fixtures if any assert on field counts. All new fields have safe defaults, so existing call sites that don't enumerate fields are unaffected.

## Verify
- [ ] FR#7: The resolver returns the per-app value when set, the global `blocking_io.behavior` when per-app is `None`, and `WARN` when both are `None`; a unit test asserts all three paths plus `ignore`/`warn`/`error` parsing.
- [ ] AC#6: A unit test confirms that setting `blocking_io_behavior` on an app config resolves to that value (overriding the global) and that `ignore` resolves to `BlockingIOBehavior.IGNORE` for that app. (Row/warning suppression is verified end-to-end in T06.)
