# Hassette

[![PyPI version](https://badge.fury.io/py/hassette.svg)](https://badge.fury.io/py/hassette)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Documentation Status](https://readthedocs.org/projects/hassette/badge/?version=stable)](https://hassette.readthedocs.io/en/latest/?badge=stable)

A simple, modern, async-first Python framework for building Home Assistant automations.

Documentation: https://hassette.readthedocs.io

Why Hassette?
-------------
- 🌟 **Modern developer experience** with typed APIs, Pydantic models, and IDE-friendly design
- ⚡ **Async-first architecture** designed for modern Python from the ground up
- 🔍 **Simple, transparent framework** with minimal magic and clear extension points
- 🎯 **Focused mission**: does one thing well — run user-defined apps that interact with Home Assistant

## Comparison to Other Frameworks

We have detailed comparisons in the docs for the two most popular frameworks. Open an issue or PR if you'd like additional comparisons!

- [AppDaemon Comparison](https://hassette.readthedocs.io/en/latest/appdaemon-comparison.html)
- [Pyscript Comparison](https://hassette.readthedocs.io/en/latest/pyscript-comparison.html)

## 📖 Examples

Check out the [`examples/`](https://github.com/NodeJSmith/hassette/tree/main/examples) directory for more complete examples:
- Based on AppDaemon's examples:
  - [Battery monitoring](https://github.com/NodeJSmith/hassette/tree/main/examples/apps/battery.py)
  - [Presence detection](https://github.com/NodeJSmith/hassette/tree/main/examples/apps/presence.py)
  - [Sensor notifications](https://github.com/NodeJSmith/hassette/tree/main/examples/apps/sensor_notification.py)
- Cleaned up versions of my own apps:
  - [Office Button App](https://github.com/NodeJSmith/hassette/tree/main/examples/apps/office_button_app.py)
  - [Laundry Room Lights](https://github.com/NodeJSmith/hassette/tree/main/examples/apps/laundry_room_light.py)
- `docker-compose.yml` example: [docker-compose.yml](https://github.com/NodeJSmith/hassette/blob/main/examples/docker-compose.yml)
- `hassette.toml` example: [hassette.toml](https://github.com/NodeJSmith/hassette/blob/main/examples/config/hassette.toml)

## 🛣️ Status & Roadmap

Hassette is brand new and under active development. We follow semantic versioning and recommend pinning a minor version while the API stabilizes.

Hassette development is tracked in [this project](https://github.com/users/NodeJSmith/projects/1) (still a slight work-in-progress) - open an issue or PR if you'd like to contribute or provide feedback!

### Current Focus Areas

- 📚 **Comprehensive documentation**
- 🔐 **Enhanced type safety**: Service calls/responses, additional state types
- 🏗️ **Entity classes**: Include state data and service functionality (e.g. `LightEntity.turn_on()`)
- 🔄 **Enhanced error handling**: Better retry logic and error recovery
- 🧪 **Testing improvements**:
  - 📊 More tests for core and utilities
  - 🛠️ Test fixtures and framework for user apps
  - 🚫 No more manual state changes in HA Developer Tools for testing!

## 🤝 Contributing

Hassette is in active development and contributions are welcome! Whether you're:

- 🐛 Reporting bugs
- 💡 Suggesting features
- 📝 Improving documentation
- 🔧 Contributing code

Early feedback and contributions help shape the project's direction.

## 📄 License

[MIT](LICENSE)
