# REVIEW.md — cli/

## Response Model Deserialization
Does `HassetteCLIClient` in `src/hassette/cli/client.py` correctly deserialize
every response model it uses from `src/hassette/web/models.py`? Missing required
fields raise `ValidationError` (caught by `_handle_malformed_response`), so
those aren't silent. The silent risk is *extra* fields the server adds that the
CLI model ignores, or *optional* fields whose defaults mask a semantic change.

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
