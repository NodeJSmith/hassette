# Hassette Roadmap

Organized by development priority. Items may evolve over time as architecture and needs mature.

---

## 🥇 Priority 1 – Foundation & Stability

- [x] Add more test coverage across all layers (core, services, scheduler, event bus, apps)
- [ ] More specific retry handling for known/recoverable errors
  - [x] `_Websocket`
  - [ ] `_Api`
  - [ ] `_Bus`
  - [ ] `_Scheduler`
  - [ ] `_Hassette`
- [ ] Retry limits (no infinite retries)
- [x] Switch from APScheduler to a custom scheduler
- [ ] Tighten up and test configuration classes
  - [ ] Fully document priority: environment variables > `.env` > `pyproject.toml`
- [x] Add timeouts to startup/shutdown, especially for user apps/services
- [x] Expand event bus beyond just state change events
- [ ] Improved logging configuration
- [ ] App-level logging configuration

---

## 🥈 Priority 2 – Developer Experience & Extensibility

- [ ] Allow apps to have `run_forever` tasks like services (and/or inherit from Service instead of Resource? not sure)
- [ ] Create decorators to simplify registering event handlers and/or services
- [x] Make it easier to mock calls/responses - `SimpleTestServer` in `test_utils.py`
- [ ] Document everything thoroughly
- [ ] Add ability to generate `.pyi` stubs for Home Assistant entities/services
- [ ] Add instrumentation tools for troubleshooting
- [ ] Graceful shutdown chaining (e.g. warn before timeout)
- [ ] Built-in validation for service calls and event payloads
  - [x] Event payloads
  - [ ] Service call data
- [ ] Service/app dependencies with startup/shutdown ordering
- [x] Multiple instances of the same app with separate config

---

## 🥉 Priority 3 – Distribution & External Integration

- [x] Make GitHub repo public
- [x] Publish to PyPI
- [ ] Add ability to register REST endpoints (like AppDaemon)
- [ ] Autodoc generation from decorators
- [_] Provide reference/sample apps - in progress
- [_] Docker-first deployment mode - in progress
- [ ] Plugin loader or extension system
- [ ] UI Config Editor Integration
- [ ] Web dashboard or CLI tool for app/service inspection

---

## ⭐ Stretch Goals & Nice-to-Haves

- [ ] Built-in dry run / simulation mode
- [ ] Event playback or time travel support
- [ ] Clean error reporting with suggestions and context
- [ ] Priority scheduling support in the custom scheduler
- [ ] Cron/calendar scheduling with natural language support
- [ ] Backpressure / queue overflow strategies (block, drop, error)
- [ ] Tracing context propagation across coroutines and threads
- [ ] Hot reloading for development
