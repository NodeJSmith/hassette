---
task_id: "T03"
title: "Rebuild global config endpoint; delete legacy path; migrate CLI"
status: "done"
depends_on: ["T01", "T02"]
implements: ["FR#1", "FR#12", "AC#1", "AC#3", "AC#6", "AC#11"]
---

## Summary
Replace the hand-maintained global config path with the unified `{config_schema, config_values}` envelope.
`GET /api/config` returns `HassetteConfig.model_json_schema()` (deref'd) plus `model_dump(mode="json")`
(masked) via the shared builder — exposing every field and group, with `token` masked. Delete
`config_response_from` and all `*ConfigResponse` classes. Migrate the `hassette config` CLI command, which
consumes the deleted `ConfigResponse`, to the new envelope by extracting a dict-capable renderer from
`render_detail`.

## Target Files
- modify: `src/hassette/web/routes/config.py` — return `ConfigSchemaResponse` from the shared builder.
- modify: `src/hassette/web/models.py` — delete `ConfigResponse` + all `*ConfigResponse` classes; add the
  `ConfigSchemaResponse` envelope (`config_schema: dict[str, Any]`, `config_values: dict[str, Any]`).
- modify: `src/hassette/web/mappers.py` — delete `config_response_from`.
- modify: `src/hassette/cli/commands/misc.py` — `cmd_config` validates `ConfigSchemaResponse`, renders
  `config_values`.
- modify: `src/hassette/cli/output.py` — extract a dict-capable detail helper from `render_detail`.
- modify: `src/hassette/test_utils/web_helpers.py` — rework/remove `make_config_response` (builds the
  deleted model).
- modify: `tests/integration/web_api/test_endpoints.py` — invert `test_token_not_in_response`; adapt the
  config-shape tests to the new envelope and now-present groups.
- modify: `tests/unit/cli/test_commands_misc.py` — assert the new envelope rendering.
- modify: `tests/unit/web/test_mappers.py` — remove the `config_response_from` tests (lines ~542-582) and
  the now-dead `config_response_from`/`ConfigResponse` imports (the function is deleted).
- modify: `tests/system/test_cli_smoke.py` — `test_config_deserializes` (imports `ConfigResponse` at line
  23, calls it at ~97) adapts to `ConfigSchemaResponse`.
- modify: `tests/system/test_web_api.py` — `test_config_endpoint` (asserts top-level `"web_api"`/`"logging"`
  at ~65-67) adapts to the new envelope: those keys now live under `config_values`.
- read: `src/hassette/web/config_view.py` (T02), `src/hassette/config/config.py` (T01).

## Prompt
Implement the global endpoint + legacy deletion + CLI migration per the design doc's `## Architecture →
Backend: one config-view builder` (Global endpoint paragraph) and `## Architecture → CLI consumer:
hassette config`, and `## Replacement Targets`.

1. `web/models.py`: delete `ConfigResponse`, `WebApiConfigResponse`, `LoggingConfigResponse`,
   `LifecycleConfigResponse`, `AppsConfigResponse`, `SchedulerConfigResponse`, `FileWatcherConfigResponse`.
   Add `ConfigSchemaResponse(BaseModel)` with `config_schema: dict[str, Any]` and
   `config_values: dict[str, Any]`.
2. `web/mappers.py`: delete `config_response_from` (and its now-unused imports).
3. `web/routes/config.py`: build the response with `build_config_view(HassetteConfig.model_json_schema(),
   hassette.config.model_dump(mode="json"))` and return it as `ConfigSchemaResponse` via
   `response_model=ConfigSchemaResponse`. `model_dump(mode="json")` masks `SecretStr` natively; the
   builder's mask is idempotent over it.
4. `cli/output.py`: extract the human-mode rendering body of `render_detail` into a dict-capable helper
   (e.g. `render_detail_dict(data: dict, title: str, json_mode: bool)`), dropping the two model-specific
   lines (`item.model_dump(mode="json")` becomes the passed-in `data`; the
   `_resolve_cli_formatters(type(item))` lookup is dropped — the deleted `ConfigResponse` carried no
   `CliFormat` fields). `--json` mode does `json.dumps(data, indent=2)`. Keep `render_detail` for other
   callers.
5. `cli/commands/misc.py`: `cmd_config` does `client.get("/api/config", ConfigSchemaResponse)` and renders
   `result.config_values` via the new helper with title "Config".
6. `test_utils/web_helpers.py`: remove `make_config_response` (or rework it to build `ConfigSchemaResponse`
   if still used).
7. Tests: invert `test_token_not_in_response` (assert plaintext token absent, masked `token` key present);
   adapt the other config-shape tests to the envelope and the now-present `database`/`websocket`/
   `blocking_io` groups; update `test_commands_misc.py`. Also handle the consumers of the deleted symbols:
   remove the `config_response_from` tests in `tests/unit/web/test_mappers.py`; adapt
   `tests/system/test_cli_smoke.py::test_config_deserializes` to `ConfigSchemaResponse`; adapt
   `tests/system/test_web_api.py::test_config_endpoint` (the `web_api`/`logging` keys move under
   `config_values`). Run `uv run pytest -n 4 <files>`; the system tests run in CI (`nox -s system`).

Do NOT keep any compatibility shim that re-flattens or re-curates the old wire shape.

## Focus
The frontend consumers of the global endpoint shape (`endpoints.ts`, `config.tsx`, frontend test infra)
are handled in T06 — do not touch them here. `config_values` from `model_dump(mode="json")` is a nested
dict (groups → fields) plus flat fields, so `render_detail_dict` renders it with the existing section
logic. After this task the OpenAPI schema changes — frontend type regen happens in T06. `hassette config`
must keep working: validate the envelope and render values, now showing all groups with `token` masked.

## Verify
- [ ] FR#1: `GET /api/config` returns a schema + values covering every `HassetteConfig` field and nested
  group, including `database`, `websocket`, `blocking_io`.
- [ ] AC#1: the response includes `database`, `websocket`, `blocking_io` (previously omitted).
- [ ] AC#3: `token` is present as a masked placeholder; the plaintext token string is absent from the body.
- [ ] AC#6 (backend half): `ConfigResponse`/`*ConfigResponse` and `config_response_from` no longer exist
  in the codebase.
- [ ] FR#12: `hassette config` continues to display the configuration after the endpoint change, in both
  human and `--json` output.
- [ ] AC#11: `hassette config` renders `config_values` from the `ConfigSchemaResponse` envelope without
  error, shows the previously-omitted groups (`database`/`websocket`/`blocking_io`), and masks `token`.
