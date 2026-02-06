<p align="center">
  <img src="https://raw.githubusercontent.com/NodeJSmith/hassette/main/docs/_static/hassette-logo.svg" />
</p>


# Hassette

[![PyPI version](https://badge.fury.io/py/hassette.svg)](https://badge.fury.io/py/hassette)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Documentation Status](https://readthedocs.org/projects/hassette/badge/?version=stable)](https://hassette.readthedocs.io/en/latest/?badge=stable)
[![codecov](https://codecov.io/github/NodeJSmith/hassette/graph/badge.svg?token=I3E5S2E3X8)](https://codecov.io/github/NodeJSmith/hassette)

A simple, modern, async-first Python framework for building Home Assistant automations.

**Documentation**: https://hassette.readthedocs.io

## ✨ Why Hassette?

- **Type Safe**: Full type annotations with Pydantic models and comprehensive IDE support
- **Async-First**: Built for modern Python with async/await throughout
- **Dependency Injection**: Clean handler signatures with FastAPI style dependency injection
- **Persistent Storage**: Built-in disk cache for storing data across restarts, intelligent rate-limiting, and more
- **Simple & Focused**: Just Home Assistant automations - no complexity creep
- **Developer Experience**: Clear error messages, proper logging, hot-reloading, and intuitive APIs

See the [Getting Started guide](https://hassette.readthedocs.io/en/latest/pages/getting-started/) for detailed instructions.

## 🤔 Is Hassette Right for You?

**New to automation frameworks?**
- [Hassette vs. Home Assistant YAML](https://hassette.readthedocs.io/en/latest/pages/getting-started/hassette-vs-ha-yaml/) - Decide if Hassette is right for your needs

**Coming from AppDaemon?**
- [AppDaemon Comparison](https://hassette.readthedocs.io/en/latest/pages/appdaemon-comparison/) - See what's different and how to migrate

## 📖 Examples

Check out the [`examples/`](https://github.com/NodeJSmith/hassette/tree/main/examples) directory for complete working examples:

**Based on AppDaemon's examples**:
- [Battery monitoring](https://github.com/NodeJSmith/hassette/tree/main/examples/apps/battery.py) - Monitor device battery levels
- [Presence detection](https://github.com/NodeJSmith/hassette/tree/main/examples/apps/presence.py) - Track who's home
- [Sensor notifications](https://github.com/NodeJSmith/hassette/tree/main/examples/apps/sensor_notification.py) - Alert on sensor changes

**Real-world apps**:
- [Office Button App](https://github.com/NodeJSmith/hassette/tree/main/examples/apps/office_button_app.py) - Multi-function button handler
- [Laundry Room Lights](https://github.com/NodeJSmith/hassette/tree/main/examples/apps/laundry_room_light.py) - Motion-based lighting

**Configuration examples**:
- [Docker Compose Guide](https://hassette.readthedocs.io/en/latest/pages/getting-started/docker/) - Docker deployment setup
- [HassetteConfig](https://hassette.readthedocs.io/en/latest/reference/hassette/config/config/) - Complete configuration reference

## 🛣️ Status & Roadmap

Hassette is under active development. We follow [semantic versioning](https://semver.org/) and recommend pinning a minor version (e.g., `hassette~=0.x.0`) while the API stabilizes.

Development is tracked in our [GitHub project](https://github.com/users/NodeJSmith/projects/1). Open an issue or PR if you'd like to contribute!

### What's Next?

- 🔐 **Enhanced type safety** - Fully typed service calls and additional state models
- 🏗️ **Entity classes** - Rich entity objects with built-in methods (e.g., `await light.turn_on()`)
- 🔄 **Enhanced error handling** - Better retry logic and error recovery
- 🧪 **Testing improvements** - More comprehensive test coverage and user app testing framework

## 🤝 Contributing

Contributions are welcome! Whether you're:

- 🐛 Reporting bugs or issues
- 💡 Suggesting features or improvements
- 📝 Improving documentation
- 🔧 Contributing code

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on getting started.

## ⭐ Star History

[![Star History Chart](https://api.star-history.com/svg?repos=NodeJSmith/hassette&type=Date)](https://star-history.com/#NodeJSmith/hassette&Date)

## 📄 License

[MIT](LICENSE)
