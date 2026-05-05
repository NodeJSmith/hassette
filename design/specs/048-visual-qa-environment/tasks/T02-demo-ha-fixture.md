---
task_id: "T02"
title: "Create demo HA fixture and docker-compose file"
status: "done"
depends_on: []
implements: ["FR#3"]
---

## Summary
Create the Home Assistant fixture directory and docker-compose file for the demo environment. The fixture reuses the system test's pre-seeded JWT and onboarding bypass but adds the `demo:` integration for synthetic entities. The docker-compose file uses environment variable substitution for port and config path to support dynamic allocation.

## Prompt
1. **Create `tests/fixtures/demo-ha-config/`** by copying from `tests/fixtures/ha-config/`:
   - Copy all `.storage/` files unchanged: `auth`, `auth_provider.homeassistant`, `core.config`, `core.config_entries`, `onboarding`
   - Copy `.gitignore` unchanged
   - Create a new `configuration.yaml` based on the system test version but adding the `demo:` integration:
     ```yaml
     homeassistant:
       name: Hassette Demo
       unit_system: metric
       time_zone: America/New_York
     demo:
     input_boolean:
       test_toggle:
         name: Test Toggle
         initial: false
     ```
   The `demo:` line enables HA's built-in demo integration which provides synthetic entities (lights, sensors, device trackers, covers, climate, locks, binary sensors) that the demo apps interact with.

2. **Create `scripts/docker/` directory** and add `ha-demo.yml`:
   ```yaml
   services:
     homeassistant:
       image: homeassistant/home-assistant:2025.3
       container_name: "hassette-demo-ha-${HA_PORT:-8123}"
       ports:
         - "${HA_PORT:-8123}:8123"
       volumes:
         - "${HA_CONFIG_PATH}:/config"
       restart: "no"
       healthcheck:
         test: ["CMD", "curl", "-sf", "http://localhost:8123/api/", "-H", "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiIwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMyIsImlhdCI6MTczNTY4OTYwMCwiZXhwIjoyMDUxMDQ5NjAwfQ.q-p85dOe-MMnKQhSNh_LEWnWJGK-GA3xdmqb4LKvkU0"]
         interval: 5s
         timeout: 5s
         retries: 12
         start_period: 20s
   ```
   The container name includes `${HA_PORT}` to avoid collisions between concurrent instances. The JWT token is the same pre-seeded token from the system test fixtures.

## Focus
- The HA image version must match `tests/system/docker-compose.yml` (currently `homeassistant/home-assistant:2025.3`).
- The JWT token in the healthcheck must exactly match the `HA_TOKEN` constant in `tests/system/conftest.py`: `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiIwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMyIsImlhdCI6MTczNTY4OTYwMCwiZXhwIjoyMDUxMDQ5NjAwfQ.q-p85dOe-MMnKQhSNh_LEWnWJGK-GA3xdmqb4LKvkU0`
- The `.storage/` files are pre-seeded to bypass HA's onboarding wizard. The `auth` file contains the user account and refresh token; `onboarding` marks all setup phases complete.
- The `scripts/docker/` directory does not yet exist — create it.
- `restart: "no"` prevents the container from auto-restarting after teardown.

## Verify
- [ ] FR#3: `tests/fixtures/demo-ha-config/` contains `configuration.yaml` with `demo:` integration and all 5 `.storage/` files matching the system test fixtures; `scripts/docker/ha-demo.yml` uses `${HA_PORT}` and `${HA_CONFIG_PATH}` env var substitution with the pre-seeded JWT in the healthcheck and port-based container naming for uniqueness
