# Hassette Example Apps

Five example automations to copy as templates for your own apps. Together they exercise 27+ framework patterns. They are designed to run against Home Assistant's built-in `demo:` integration, which provides synthetic entities (lights, sensors, device trackers, covers, climate, locks, binary sensors) — no real hardware required.

## Apps

### motion_lights.py — Motion-activated lights with a hold delay

Demonstrates: multi-instance config, `on_state_change` with `changed_to`, `duration`, `entities.LightEntity`, state cache access.

Watches a binary sensor and turns a light on when motion is detected, off once the sensor has stayed clear for `off_delay` seconds (`duration=`, so returning motion cancels the turn-off). Configured for two instances in `hassette.toml` (kitchen lights and ceiling lights), both watching the same backyard motion sensor with different brightness settings.

### climate_controller.py — Temperature monitoring with glob patterns

Demonstrates: glob patterns (`sensor.*temperature*`), `C.Increased()` / `C.Decreased()`, `on_attribute_change`, dependency injection (`D.StateNew`, `D.StateOld`, `D.EntityId`), `A.get_attr_new`, `run_every` with job groups.

Monitors all temperature sensors via a single glob subscription and controls an AC switch when the temperature crosses a threshold. Also watches the HVAC entity's `current_temperature` attribute directly.

### cover_scheduler.py — Cron/daily scheduling for blinds

Demonstrates: `run_cron`, `run_daily`, `run_hourly`, `run_in`, `if_exists="skip"`, jitter, `once=True` on bus listeners, cache read/write, `on_shutdown` lifecycle hook.

Opens covers on weekday mornings and closes them at night using cron and daily triggers. Logs positions hourly with jitter and persists the last-known positions to the app cache across restarts.

### presence_tracker.py — Dynamic subscription management

Demonstrates: multi-instance config, `D.MaybeStateOld`, `api.set_state` (custom sensor creation), dynamic `bus.on_state_change` subscribe/cancel, `Subscription` object, job groups.

Tracks a person's device tracker and creates a custom presence sensor entity. When a person leaves home, dynamically subscribes to zone occupancy changes; cancels the subscription when they return. Configured for two instances (Paulus and HomeBoy).

### security_monitor.py — Synchronous app with throttle

Demonstrates: `AppSync`, `on_initialize_sync`, `on_call_service` with domain filter, throttle, synchronous state iteration.

Monitors lock service calls (lock, unlock) and moisture sensor alerts using synchronous patterns (`AppSync`). The moisture handler is throttled to fire at most once per 5 minutes.

## Running the Demo Environment

```bash
mise run demo
```

This starts Home Assistant (Docker), the hassette backend, and the Vite frontend dev server. All three URLs are printed when the environment is ready. Press Ctrl+C to tear everything down.

The demo environment uses a pre-seeded long-lived access token for API authentication — no login required. The hassette frontend at the reported URL is the primary interface.

The demo also loads the fixture apps in [`scripts/demo_apps/`](../scripts/demo_apps/), which put the web UI into specific states (failing jobs, crashed instances, a blocked event loop) for visual QA and docs screenshots. They are framework dev tooling, not templates; `scripts/demo_apps/hassette.toml` is the config that loads both sets.

## App Registry

`hassette.toml` configures 5 apps, for 7 instances in total:

| Instance | App | Key patterns |
|---|---|---|
| `backyard_kitchen` | MotionLights | duration, state cache |
| `backyard_ceiling` | MotionLights | multi-instance |
| *(single)* | ClimateController | glob, attribute change |
| *(single)* | CoverScheduler | cron, daily, cache |
| `paulus` | PresenceTracker | dynamic subscribe |
| `home_boy` | PresenceTracker | multi-instance |
| *(single)* | SecurityMonitor | AppSync, throttle |
