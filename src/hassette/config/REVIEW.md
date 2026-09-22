# REVIEW.md — config/

## Cross-Group Validators
Does every new config field that references another group's field have a
cross-group validator? `src/hassette/config/config.py` has
`validate_log_retention_days` ensuring `logging.log_retention_days <=
database.retention_days`, and `src/hassette/config/models.py` has
`validate_framework_retention_days` and `validate_sync_executor_shutdown_budget`.
Is there a similar invariant missing for the new field?

## Dev-Mode Overrides
Does `src/hassette/config/defaults.py` include a dev-mode override for the new
field when it has different dev/prod semantics? `model_post_init` in
`src/hassette/config/config.py` applies dev defaults from `get_defaults_dict()`
only when the field is not in `model_fields_set` — a field with no dev default
silently uses the production value in development.

## SecretStr Leakage
When a new nested group field is added to `src/hassette/config/models.py`, does
`ExcludeExtrasMixin` in `src/hassette/config/classes.py` correctly exclude it from
serialization (e.g. `model_dump` for the `GET /api/config` endpoint)? A
`SecretStr` value in a nested group that isn't excluded leaks to the API.

## json_schema_extra on Nested Groups
If a new field in `src/hassette/config/models.py` carries a
`json_schema_extra={"ui": ...}` annotation, is the annotation on the model's
`model_config` (for nested groups) or on the `Field()` (for scalar fields)?
Putting a `ui` block on a `$ref`-emitted nested group `Field()` silently loses it
(documented at `WebApiConfig` in `src/hassette/config/models.py`).
