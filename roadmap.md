# Hassette Roadmap

Organized by development priority. Items may evolve over time as architecture and needs mature.

---

## 🥇 Priority 1 – Foundation & Stability

- [ ] Add more test coverage across all layers (core, services, scheduler, event bus, apps)
- [ ] More specific retry handling for known/recoverable errors
- [ ] Retry limits (no infinite retries)
- [ ] Switch from APScheduler to a custom scheduler
- [ ] Tighten up and test configuration classes
  - [ ] Fully document priority: environment variables > `.env` > `pyproject.toml`
- [ ] Add timeouts to startup/shutdown, especially for user apps/services
- [ ] ~~Add a separate event bus for internal events~~ Decided against this, if HA can use a single event bus we should be able to as well
- [ ] Expand event bus beyond just state change events
- [ ] Improved logging configuration
- [ ] App-level logging configuration

---

## 🥈 Priority 2 – Developer Experience & Extensibility

- [ ] Allow user services to be registered/loaded
- [ ] Create decorators to simplify registering event handlers and/or services
- [ ] Make it easier to mock calls/responses - likely through a small `litestar` app or similar
- [x] Add additional log levels:
  - [x] `TRACE` (debugging)
  - [ ] TBD
- [ ] Document everything thoroughly
- [ ] Add ability to generate `.pyi` stubs for Home Assistant entities/services
- [ ] Add instrumentation tools for troubleshooting
- [ ] Graceful shutdown chaining (e.g. warn before timeout)
- [ ] Built-in validation for service calls and event payloads
- [ ] Service/app dependencies with startup/shutdown ordering
- [ ] Multiple instances of the same app with separate config

---

## 🥉 Priority 3 – Distribution & External Integration

- [ ] Make GitHub repo public
- [ ] Publish to PyPI
- [ ] Add ability to register REST endpoints (like AppDaemon)
- [ ] Optional integration with Prometheus or OpenTelemetry
- [ ] Autodoc generation from decorators
- [ ] Provide reference/sample apps
- [ ] Docker-first deployment mode
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
