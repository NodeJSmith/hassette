<p align="center">
  <img src="https://raw.githubusercontent.com/NodeJSmith/hassette/main/docs/_static/hassette-logo.svg" />
</p>


# Hassette

[![PyPI version](https://badge.fury.io/py/hassette.svg)](https://badge.fury.io/py/hassette)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/license/MIT)
[![Documentation Status](https://app.readthedocs.org/projects/hassette/badge/?version=stable)](https://hassette.readthedocs.io/en/stable/?badge=stable)
[![codecov](https://codecov.io/github/NodeJSmith/hassette/graph/badge.svg?token=I3E5S2E3X8)](https://codecov.io/github/NodeJSmith/hassette)

A simple, modern, async-first Python framework for building Home Assistant automations.

**Documentation**: https://hassette.readthedocs.io

## ✨ Why Hassette?

- **Type Safe**: Full type annotations with Pydantic models and comprehensive IDE support
- **Async-First**: Built for modern Python with async/await throughout
- **Dependency Injection**: Clean handler signatures with FastAPI style dependency injection
- **Persistent Storage**: Built-in disk cache for storing data across restarts, intelligent rate-limiting, and more
- **Simple & Focused**: Just Home Assistant automations - no complexity creep
- **Web UI**: Monitor and manage your automations from the browser
- **Developer Experience**: Clear error messages, proper logging, hot-reloading, and intuitive APIs

See the [Getting Started guide](https://hassette.readthedocs.io/en/stable/pages/getting-started/) for detailed instructions.

## 🖥️ Web UI

Hassette includes a web UI for monitoring and managing your automations: **Apps** (app status, health, and detailed per-app views), **Handlers** (registered event handlers across all apps), **Logs** (real-time log streaming with filtering), and **Config** (runtime configuration and diagnostics).

<p align="center">
  <img src="https://raw.githubusercontent.com/NodeJSmith/hassette/main/docs/_static/web_ui_apps.png" alt="Hassette Web UI — Apps page" />
</p>

The web UI is enabled by default at `http://<host>:8126/ui/`. See the [Web UI documentation](https://hassette.readthedocs.io/en/stable/pages/web-ui/) for details.

## Terminal CLI

Query a running Hassette instance from the terminal — no browser required:

```bash
# Check system health
hassette status

# List all apps and their status
hassette app

# Investigate a specific app
hassette app health my-app
hassette listener --app my-app --since 1h
hassette log --app my-app --since 1h --limit 20

# Pipe structured output to jq
hassette listener --app my-app --json | jq '.[] | select(.failed > 0)'
```

See the [CLI documentation](https://hassette.readthedocs.io/en/stable/pages/cli/) for the full command reference, scripting patterns, and shell completion setup.

## 🤔 Is Hassette Right for You?

**New to automation frameworks?**
- [Hassette vs. Home Assistant YAML](https://hassette.readthedocs.io/en/stable/pages/getting-started/hassette-vs-ha-yaml/) - Decide if Hassette is right for your needs

**Coming from AppDaemon?**
- [AppDaemon Migration Guide](https://hassette.readthedocs.io/en/stable/pages/migration/) - See what's different and how to migrate

## 📖 Examples

Check out the [`examples/`](https://github.com/NodeJSmith/hassette/tree/main/examples) directory for complete working examples:

- [motion_lights.py](https://github.com/NodeJSmith/hassette/blob/main/examples/motion_lights.py) - Motion-activated lights with debounce
- [climate_controller.py](https://github.com/NodeJSmith/hassette/blob/main/examples/climate_controller.py) - Temperature monitoring with glob patterns
- [cover_scheduler.py](https://github.com/NodeJSmith/hassette/blob/main/examples/cover_scheduler.py) - Cron/daily scheduling for blinds
- [presence_tracker.py](https://github.com/NodeJSmith/hassette/blob/main/examples/presence_tracker.py) - Dynamic subscription management
- [security_monitor.py](https://github.com/NodeJSmith/hassette/blob/main/examples/security_monitor.py) - Synchronous app with throttle

**Configuration examples**:
- [Docker Compose Guide](https://hassette.readthedocs.io/en/stable/pages/getting-started/docker/) - Docker deployment setup
- [HassetteConfig](https://hassette.readthedocs.io/en/stable/reference/hassette/config/) - Complete configuration reference

## 🛣️ Status

Hassette is under active development. We follow [semantic versioning](https://semver.org/) and recommend pinning a minor version (e.g., `hassette~=0.x.0`) while the API stabilizes.

Open an issue or PR if you'd like to contribute!

### Recent Highlights

- **Typed state models** - Generated Python models for 45+ Home Assistant entity domains
- **Entity classes** - Rich entity objects with built-in async methods (e.g., `await light.turn_on()`)
- **Test harness** - `AppTestHarness` for writing tests against your automations with simulated state and time control

## 🤝 Contributing

Contributions are welcome! Whether you're:

- 🐛 Reporting bugs or issues
- 💡 Suggesting features or improvements
- 📝 Improving documentation
- 🔧 Contributing code

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on getting started.

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=NodeJSmith/hassette&type=date&legend=top-left)](https://www.star-history.com/#NodeJSmith/hassette&type=date&legend=top-left)

## 📄 License

[MIT](LICENSE)
