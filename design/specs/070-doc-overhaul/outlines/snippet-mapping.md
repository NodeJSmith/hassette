# Snippet Mapping

Total snippet files: **355** (260 .py, 30 .sh, 28 .toml, 18 .yml, 14 .txt, 2 .yaml, 1 .mmd, 1 .md, 1 .dockerfile)

---

## Claimed — Staying in Place

Snippets already in the correct location for their new-nav page. Voice polish and content review during Phase 3 writing tasks.

| Directory | Files | Claimed by |
|---|---|---|
| `getting-started/snippets/` | 13 of 15 | Quickstart, HA Token, First Automation |
| `getting-started/docker/snippets/` | 62 | Docker Setup, Dependencies, Image Tags, Docker Troubleshooting |
| `core-concepts/bus/snippets/` (top-level) | ~12 | Bus overview (3 rewritten in T03), Handlers, Filtering |
| `core-concepts/bus/snippets/dependency-injection/` | ~14 | DI page (7 rewritten in T03), Custom Extractors |
| `core-concepts/bus/snippets/filtering/` | ~2 (after moves) | Filtering page |
| `core-concepts/bus/snippets/handlers/` | 3 | Handlers page |
| `core-concepts/apps/snippets/` | 15 | Apps overview, Lifecycle, Configuration, Task Bucket |
| `core-concepts/scheduler/snippets/` | 22 | Scheduler overview, Methods, Management |
| `core-concepts/states/snippets/` | 4 | States overview |
| `core-concepts/api/snippets/` | 14 | API overview, Entities, Services, Utilities |
| `core-concepts/cache/snippets/` | 9 | Cache overview, Patterns |
| `core-concepts/snippets/database-telemetry/` | 3 | Database & Telemetry |
| `core-concepts/snippets/` (top-level .py) | 2 | Architecture (depends_on), Internals (restart_spec) |
| `testing/snippets/` | 34 | Testing overview, Time Control, Concurrency, Factories |
| `migration/snippets/` | 27 | Migration pages (all 8) |
| `recipes/snippets/` | 9 | Recipe pages (motion-lights rewritten in T03) |

**Subtotal: ~285 files staying in place**

---

## Claimed — Moving

Snippets moving from `advanced/snippets/` (being eliminated) or between subsections.

| Source | Destination | Files | Reason |
|---|---|---|---|
| `advanced/snippets/custom-states/` | `core-concepts/states/snippets/` | 14 | Custom States page moves to States section |
| `advanced/snippets/state-registry/` | `core-concepts/states/snippets/` | 18 | State Registry page moves to States section |
| `advanced/snippets/type-registry/` | `core-concepts/states/snippets/` | 24 | Type Registry page moves to States section |
| `advanced/snippets/managing-helpers/` | `core-concepts/api/snippets/` | 5 | Managing Helpers page moves to API section |
| `advanced/snippets/log-level-tuning/` | `operating/snippets/` | 5 | Log Level Tuning moves to Operating section |
| `core-concepts/bus/snippets/dependency-injection/` (4 files) | `core-concepts/states/snippets/` | 4 | Type conversion snippets → Type Registry page |
| `core-concepts/bus/snippets/filtering/custom_accessors.py` | `core-concepts/bus/snippets/` (custom-extractors) | 1 | Custom Accessors → Custom Extractors page |
| `core-concepts/bus/snippets/filtering/` (state-specific) | `core-concepts/states/snippets/` | ~5 | State-change filtering → States/Subscribing page |
| `core-concepts/snippets/states_import.py` | `core-concepts/states/snippets/` | 1 | States import example |

**Subtotal: ~77 files moving**

### DI conversion snippets moving to Type Registry:
- `builtin_conversions_explicit.py`
- `builtin_conversions_implicit.py`
- `bypass_conversion_any.py`
- `bypass_conversion_custom.py`

### Filtering snippets moving to States/Subscribing:
- `filtering_simple_start.py`
- `filtering_simple_stop.py`
- `filtering_state_from_to.py`
- `filtering_increased_decreased.py`
- `changed_false.py`

---

## Unclaimed — Candidates for Deletion

Snippets not referenced by any outline. Review before deleting — some may be needed by pages not yet identified.

| File | Location | Reason |
|---|---|---|
| `first_automation_step3_raw.py` | `getting-started/snippets/` | Raw handler example — superseded by DI-first approach. **Possible claim:** Bus/Handlers page could use for raw handler example, but has its own `handlers_no_data.py`. |
| `typed_handler.py` | `getting-started/snippets/` | Redundant — DI is default from step 3. |
| `web-ui/snippets/disable-ui.toml` | `web-ui/snippets/` | May be absorbed into Web UI overview inline. Review. |
| `web-ui/app-detail/snippets/handler_registration.py` | `web-ui/app-detail/snippets/` | Old app-detail page being consolidated. Review — may be claimed by Debug Handler page. |

**Subtotal: 2–4 files, pending review**

---

## New — Snippets to Create

| Proposed path | Page | What it demonstrates |
|---|---|---|
| `states/snippets/subscribing_attribute_change.py` | States/Subscribing | `on_attribute_change` with predicate |
| `states/snippets/subscribing_combined_predicates.py` | States/Subscribing | `&`/`|` composition in state context |
| `states/snippets/domain_state_access.py` | DomainStates Reference | Accessing typed attributes from LightState |
| `states/snippets/sensor_state_example.py` | DomainStates Reference | SensorState with numeric value and unit |
| `bus/snippets/handlers_service_call.py` | Handlers | `on_call_service` handler example |
| `bus/snippets/handlers_raw_topic.py` | Handlers | `on("event_triggered")` raw topic subscription |
| `bus/snippets/handlers_internal_events.py` | Handlers | Hassette internal events / HA lifecycle events |
| `bus/snippets/custom_extractors_annotation_details.py` | Custom Extractors | AnnotationDetails usage |

**Subtotal: ~8 new files**

---

## Summary

| Category | Count |
|---|---|
| Staying in place | ~285 |
| Moving (Advanced → new locations) | ~77 |
| Unclaimed (deletion candidates) | 2–4 |
| New (to create) | ~8 |
| **Total after Phase 3** | **~370** |

The `advanced/snippets/` directory (66 files) is fully mapped — every file moves to its new location. The `advanced/` section can be deleted after all moves are complete.

The `web-ui/app-detail/` directory (1 snippet + 6 old pages) is being consolidated — review the 1 snippet during Web UI writing.
