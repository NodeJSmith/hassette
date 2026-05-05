---
task_id: "T01"
title: "Bring hassette-examples apps in-repo, remove legacy examples"
status: "done"
depends_on: []
implements: ["FR#4", "FR#10", "AC#6"]
---

## Summary
Remove the 7 legacy example apps in `examples/apps/` and their config, and replace them with the 5 polished demo apps from the hassette-examples repository. These apps are designed to work with Home Assistant's `demo:` integration and collectively exercise 27+ framework patterns. Update `README.md` to reference the new apps instead of the removed ones.

## Prompt
1. **Delete legacy files:**
   - Remove `examples/apps/` directory (7 files: battery.py, laundry_room_light.py, office_button_app.py, presence.py, sensor_notification.py, sound.py, states_cache_example.py)
   - Remove `examples/config/hassette.toml`
   - Remove `examples/docker-compose.yml`

2. **Copy demo apps** from `/home/jessica/source/hassette-examples/src/hassette_examples/` into `examples/`:
   - `__init__.py` (empty)
   - `motion_lights.py`
   - `climate_controller.py`
   - `cover_scheduler.py`
   - `presence_tracker.py`
   - `security_monitor.py`

3. **Create `examples/hassette.toml`** — adapt from `/home/jessica/source/hassette-examples/config/hassette.toml`. Changes from the original:
   - Set `app_dir = "examples"` (will be overridden by env var at runtime)
   - Keep all 5 app registrations with their multi-instance configs (7 total instances)
   - Keep `db_retention_days`, `db_max_size_mb`, and log level settings
   - Remove `base_url` (will come from env var `HASSETTE__BASE_URL`)

4. **Update `README.md`** — lines 53-59 reference `examples/apps/` files that no longer exist. Replace those links with the new demo app files:
   - motion_lights.py — Motion-activated lights with debounce
   - climate_controller.py — Temperature monitoring with glob patterns
   - cover_scheduler.py — Cron/daily scheduling for blinds
   - presence_tracker.py — Dynamic subscription management
   - security_monitor.py — Synchronous app with throttle

5. **Create `examples/README.md`** — describe the 5 demo apps, what patterns each demonstrates, and mention that `uv run nox -s demo` starts the full environment.

## Focus
- The demo apps import directly from `hassette` — no package structure needed. They work because the nox session runs via `uv run` against the local project.
- The hassette.toml app registry must exactly match the app filenames and class names in the demo apps. The original hassette-examples config uses `filename = "motion_lights.py"` etc. — keep these unchanged since the files are now directly in `examples/`.
- Multi-instance apps: `motion_lights` has 2 configs (backyard_kitchen, backyard_ceiling), `presence_tracker` has 2 configs (paulus, home_boy). Total: 7 instances from 5 apps.
- Gap check found: `README.md` lines 53-59 link to `examples/apps/` — these will 404 after removal.

## Verify
- [ ] FR#4: All 5 demo app files exist in `examples/` with correct content (motion_lights.py, climate_controller.py, cover_scheduler.py, presence_tracker.py, security_monitor.py)
- [ ] FR#10: `examples/apps/` directory, `examples/config/`, and `examples/docker-compose.yml` no longer exist
- [ ] AC#6: `examples/hassette.toml` registers all 5 apps with 7 total instances, and `README.md` links point to the new app files
