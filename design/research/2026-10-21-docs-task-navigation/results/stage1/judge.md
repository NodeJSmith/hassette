## n01

**Question:** I run Hassette in Docker and my app needs the apprise Python package, which isn't in the image. How do I get it installed in the container?

**Expected:** Put apprise in requirements.txt at config/requirements.txt (mounted as /config/requirements.txt, or inside the apps directory) and set HASSETTE_DOCKER_INSTALL_DEPS: "1" in the compose environment block, then restart the container. Alternative: pyproject.toml plus uv.lock in config/apps/ (no env var needed).

**Given answer:**

```json
{
  "answer": "Put apprise in config/requirements.txt on the host (maps to /config/requirements.txt in the container; a requirements.txt in the apps directory also works), e.g. a line 'apprise>=1.9'. Add environment HASSETTE_DOCKER_INSTALL_DEPS: \"1\" to the hassette service in the compose file, and keep the uv_cache volume (uv_cache:/uv_cache) so downloads are cached. Restart with 'docker compose restart hassette'; the install runs at startup on every start. Alternative: a pyproject.toml plus uv.lock (run 'uv lock') in config/apps/ lists dependencies and installs automatically without the env var.",
  "confidence": "high",
  "found_on": [
    "pages/getting-started/docker/dependencies/"
  ],
  "gave_up": false
}
```

## n02

**Question:** I renamed my app's section in hassette.toml from [hassette.apps.weather] to [hassette.apps.weather_station] and now the values it saved between restarts are gone. How do I get the old stored data back?

**Expected:** Set cache_key on the renamed app's section to the old cache location, e.g. cache_key = "weather/0" (old app_key/index); Hassette uses it as-is with no index appended, so the app reuses the old cache.db under data_dir.

**Given answer:**

```json
{
  "answer": "The cache lives at {data_dir}/{app_key}/{index}/cache/cache.db, so renaming the section changed the path and the old data was orphaned (not deleted). Set cache_key on the renamed section to the old location: [hassette.apps.weather_station] with cache_key = \"weather/0\" (old app_key plus instance index, e.g. weather/0). Hassette uses cache_key as-is with no index appended. Restart and the old cache.db is picked up. Only apply this to one app, since apps resolving to the same cache_key share a file and trigger a startup warning (unless cache_shared = true).",
  "confidence": "high",
  "found_on": [
    "pages/core-concepts/cache/"
  ],
  "gave_up": false
}
```

## n03

**Question:** I want my app to ask Home Assistant for the daily weather forecast for weather.home and use the data it sends back, not just fire off the request. How do I do that?

**Expected:** await self.api.call_service("weather", "get_forecasts", target={"entity_id": "weather.home"}, return_response=True, type="daily"). With return_response=True it returns a ServiceResponse whose .response dict holds the payload (and .context the HA event context); without it call_service returns None. weather.get_forecasts is response-only, so HA rejects the call if return_response is omitted.

**Given answer:**

```json
{
  "answer": "Call `response = await self.api.call_service(\"weather\", \"get_forecasts\", target={\"entity_id\": \"weather.home\"}, return_response=True, type=\"daily\")`. return_response=True is required because weather.get_forecasts is a response-only service (HA rejects the call without it); without it call_service returns None. It returns a ServiceResponse with `.response` (the payload dict holding the forecast data) and `.context` (HA event context). A typed alternative exists: WeatherEntity.get_forecasts(type=...).",
  "confidence": "high",
  "found_on": [
    "pages/core-concepts/api/methods/",
    "reference/hassette/models/entities/"
  ],
  "gave_up": false
}
```

## n04

**Question:** I want to temporarily switch off one of my apps without deleting its section from hassette.toml. How?

**Expected:** Set enabled = false in that app's [hassette.apps.<key>] block (app never loads; shows as disabled). Alternative: autostart = false keeps it registered but not started automatically (start on demand from UI/CLI).

**Given answer:**

```json
{
  "answer": "In hassette.toml, set `enabled = false` in the app's registration block, e.g. [hassette.apps.my_app] filename = \"my_app.py\", class_name = \"MyApp\", enabled = false. The app never loads or starts but stays registered and is listed as disabled in the apps dashboard. Set it back to true to re-enable. Alternative: `autostart = false` registers the app but doesn't start it at boot (it can be started on demand from the UI), and `hassette run --app <key>` runs only the named app(s) for one process.",
  "confidence": "high",
  "found_on": [
    "pages/core-concepts/apps/configuration/",
    "pages/core-concepts/apps/"
  ],
  "gave_up": false
}
```

## n05

**Question:** In my app I want to check right away whether anyone in the household is home before turning on light.porch, without making a call to Home Assistant. What's the simplest way?

**Expected:** self.states.anybody_home() (synchronous, no await, reads person entities from local cache; falls back to device_tracker). Related: everybody_home(), nobody_home(), is_home("person.x").

**Given answer:**

```json
{
  "answer": "Use self.states.anybody_home() on the StateManager. It is synchronous (no await) and reads the local state cache, so it makes no call to Home Assistant. Example: `if self.states.anybody_home(): await self.api.turn_on(\"light.porch\", domain=\"light\")`. It reads the person domain and falls back to device_tracker if no person entities are configured. Related: everybody_home(), nobody_home(), and is_home(\"person.name\") for a single entity.",
  "confidence": "high",
  "found_on": [
    "pages/core-concepts/states/#presence"
  ],
  "gave_up": false
}
```

## n06

**Question:** I'm writing a test for an app that has a job scheduled for 07:00. How do I make that job run in my test without actually waiting until 7 am?

**Expected:** With AppTestHarness: harness.freeze_time(<Instant/ZonedDateTime>) (sync), harness.advance_time(hours=...) to move the clock, then await harness.trigger_due_jobs() to fire due jobs (advance_time alone does not run jobs).

**Given answer:**

```json
{
  "answer": "Use AppTestHarness time control: async with AppTestHarness(MyApp, config={}) as harness: harness.freeze_time(Instant.from_utc(...) or ZonedDateTime(..., tz=...)) to a point before 07:00 (from whenever); harness.advance_time(hours=..., minutes=..., seconds=...) to move the frozen clock to/past 07:00 (does not run jobs); then count = await harness.trigger_due_jobs() to fire all jobs due at or before the frozen clock (returns number dispatched). Then assert, e.g. harness.api_recorder.assert_called(...). Use await harness.drain_task_bucket() if handlers triggered via the bus need to finish. Clock unfreezes on exiting the harness block.",
  "confidence": "high",
  "found_on": [
    "pages/testing/time-control/"
  ],
  "gave_up": false
}
```

## n07

**Question:** I'm moving from AppDaemon. I used self.cancel_timer(handle) to stop a timer I created with run_in. What do I do in Hassette?

**Expected:** Keep the Job returned by the scheduler call (e.g. job = await self.scheduler.run_in(...)) and call job.remove().

**Given answer:**

```json
{
  "answer": "Hassette has no cancel_timer(handle). Every scheduling call (e.g. job = await self.scheduler.run_in(cb, 30)) returns a Job object; call job.remove() on it to stop the job. Keep the returned job instead of an AppDaemon handle.",
  "confidence": "high",
  "found_on": [
    "pages/migration/scheduler/"
  ],
  "gave_up": false
}
```

## n08

**Question:** My Zigbee hallway button (event.hallway_button) automation fires once every time Home Assistant restarts, as if someone pressed it. How do I stop that?

**Expected:** Add where=P.EventEntityFresh(max_age=10) (from hassette import P) to the bus.on_state_change subscription for the event.* entity; it drops events whose state timestamp is older than max_age seconds relative to last_changed (restart replays).

**Given answer:**

```json
{
  "answer": "Add the P.EventEntityFresh predicate to the listener: await self.bus.on_state_change(\"event.hallway_button\", handler=self.on_button_pressed, where=P.EventEntityFresh(max_age=10), name=\"hallway_button_pressed\") (from hassette import P). HA restores event.* entity state on restart and broadcasts it as a state_changed event; the predicate drops events where the state's timestamp is more than max_age seconds older than last_changed, so real presses pass and restart replays are ignored. A few seconds of max_age is plenty. It fails open for unknown/unavailable states.",
  "confidence": "high",
  "found_on": [
    "pages/core-concepts/bus/filtering/#ignoring-restart-replays-pevententityfresh",
    "reference/hassette/event_handling/predicates/#hassette.event_handling.predicates.EventEntityFresh"
  ],
  "gave_up": false
}
```

## n09

**Question:** My app uses its own logging.getLogger("my_app.notify") in a helper module. Its info messages never show up in the Hassette logs or the web UI log view. How do I make Hassette pick up that logger?

**Expected:** List the logger name in extra_loggers under [hassette.logging] in hassette.toml (e.g. extra_loggers = ["my_app.notify"]); it then uses the same handlers, level, formatter and telemetry DB as the hassette logger, keeping its own name.

**Given answer:**

```json
{
  "answer": "Add the logger name to the extra_loggers setting in hassette.toml: [hassette.logging] extra_loggers = [\"my_app.notify\"]. This attaches it to the same pipeline as hassette (same handlers, level, formatter, console, database and web UI log view), and it keeps its own name in log lines. No renaming needed.",
  "confidence": "high",
  "found_on": [
    "pages/operating/log-levels/",
    "reference/hassette/config/"
  ],
  "gave_up": false
}
```

## n10

**Question:** I want a function in my app to run every weekday at 7:00 in the morning, but not on Saturday or Sunday. How do I schedule that?

**Expected:** await self.scheduler.run_cron(self.handler, "0 7 * * 1-5", name="...") - a 5-field cron expression (minute hour day-of-month month day-of-week; 1-5 = Monday-Friday). Alternative: self.scheduler.schedule(handler, Cron("0 7 * * 1-5")). run_daily alone cannot skip weekends.

**Given answer:**

```json
{
  "answer": "In on_initialize, call: await self.scheduler.run_cron(self.my_func, \"0 7 * * 1-5\", name=\"weekday_morning\"). The 5-field cron expression is minute hour day-of-month month day-of-week, so \"0 7 * * 1-5\" fires at 7:00 Monday through Friday (day of week 0-6 with Sunday=0, 1-5 = weekdays). name= is required; it must be awaited.",
  "confidence": "high",
  "found_on": [
    "pages/core-concepts/scheduler/methods/"
  ],
  "gave_up": false
}
```
