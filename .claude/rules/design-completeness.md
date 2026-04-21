# Design Completeness

Every design document and work package plan must include documentation and frontend changes alongside the core implementation. These are not follow-ups — they ship in the same PR.

## Documentation

A change requires documentation updates when ANY of these are true:

- A new parameter, method, or option is added to a user-facing API
- An existing method's behavior changes in a way that affects how users call it
- A new validation rule is added that users will encounter (e.g., new ValueError combinations)
- A new concept is introduced that users need to understand to use the feature (e.g., duration timers, hold predicates)

Documentation means:
- Docstrings on the changed methods (parameter descriptions, usage examples)
- Updates to the `docs/` site pages that cover the affected component
- If the feature is significant enough: a new section or page in the docs site

"The docstring is enough" is not sufficient for user-facing features — the docs site is where users discover functionality. Docstrings are reference; docs pages are learning material.

## Frontend

A change requires frontend updates when ANY of these are true:

- New fields are added to a database table that has a corresponding API endpoint and UI view (e.g., listeners, scheduled_jobs, invocations)
- An existing UI view displays data whose structure or semantics changed
- A new entity type or status is introduced that should be visible in the monitoring UI
- New validation errors are added that users might encounter through the UI

Frontend changes include:
- Backend: adding fields to the response model (e.g., `ListenerWithSummary` in `web/models.py`)
- Regenerating the OpenAPI spec and frontend types: `uv run python scripts/export_schemas.py` then `cd frontend && npx openapi-typescript openapi.json -o src/api/generated-types.ts`
- Updating the UI component to display the new data

"The field exists in the DB but isn't shown in the UI" is a bug, not a follow-up. If the data is persisted and queryable, it should be visible.


## Exceptions

A change does NOT require docs/frontend updates when:

- It is purely internal refactoring with no user-facing behavior change
- It only affects test infrastructure
- It only modifies CI/CD configuration
- The affected code has no corresponding docs page or UI view (e.g., internal framework plumbing that users never interact with directly)

When in doubt, include it. The cost of shipping unnecessary docs is near zero; the cost of shipping a feature without docs is a confused user and a follow-up PR.
