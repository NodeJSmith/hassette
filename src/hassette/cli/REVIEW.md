# REVIEW.md — cli/

## Response Model Deserialization
Does `HassetteCLIClient` in `src/hassette/cli/client.py` correctly deserialize
every response model it uses from `src/hassette/web/models.py`? A renamed or
restructured response model breaks the CLI silently — Pydantic swallows extra
fields and drops missing ones without raising.

## JSON/Human Output Duality
When a new CLI command is added in `src/hassette/cli/__init__.py`, does it
respect the `--json` / human-mode duality? `src/hassette/cli/output.py` owns the
rendering layer — a command that prints directly to stdout bypasses structured
output and breaks script consumers.

## Server Target Resolution
Does `resolve_server_target()` in `src/hassette/cli/target.py` still fall back
correctly when `cli.server_url` is unset? It derives the target from
`web_api.host` / `web_api.port` in `src/hassette/config/models.py` — a change to
those field defaults silently changes where every CLI command connects.
