# Is Hassette Right for You?

Home Assistant ships with two built-in automation systems: UI-created automations and YAML automations. Hassette is a third option — Python code running alongside Home Assistant as a separate process. This page helps you decide whether Hassette is worth the extra setup.

## Quick comparison

| | HA UI / YAML | Hassette |
|---|---|---|
| **Setup** | None — built in | ~30 min install + config |
| **Language** | YAML + Jinja2 templates | Python 3.11+ |
| **Programming knowledge needed** | None | Basic Python |
| **Editor support** | HA UI or any text editor | Full IDE autocomplete, type checking |
| **Testing** | Manual; limited tooling | `AppTestHarness`, event simulation, time control |
| **Complex logic** | Awkward in YAML/Jinja2 | Native Python: loops, functions, libraries |
| **Code reuse** | Copy-paste across automations | Shared functions, base classes, modules |
| **Persistent state** | Input helpers, custom scripts | Built-in app cache with TTL support |
| **Runs alongside existing automations** | — | Yes — Hassette connects via the same WebSocket API; your YAML automations keep working |
| **Debugging** | HA logbook, traces | Structured logs, web UI, Python debugger |

## HA UI / YAML automations

YAML automations are built into Home Assistant and work well for straightforward automation needs. You can create them from the UI without writing any code.

**When YAML is the right choice:**

- Simple trigger-action patterns (turn on lights when motion detected, send a notification at sunrise)
- Quick prototyping — iterate fast without leaving the Home Assistant UI
- You prefer visual tools over writing code
- Your automations are stable and don't need testing

**Where YAML becomes painful:**

- Complex conditions that need nested logic or state tracking across multiple events
- Reusing the same logic across several automations (there is no real "import" in YAML)
- Jinja2 templates get unwieldy past a few lines
- Debugging requires reading trace logs rather than running code interactively

## Hassette

Hassette brings Python's full power to Home Assistant automations. Your automations become ordinary Python classes — you can test them, refactor them, and share code between them.

**When Hassette is the right choice:**

- Your YAML automations have grown hard to read or maintain
- You want to write tests for your automations
- You need persistent state without workarounds (input helpers, MQTT retain, etc.)
- You're comfortable with Python — or willing to learn it
- You want IDE support: autocomplete, type checking, and inline documentation

**What you're committing to:**

- **Python knowledge** — basic understanding is enough to start; you'll learn more as you go
- **Setup time** — around 30 minutes from install to your first running app ([Local Setup](index.md))
- **Dependency management** — you own the Python environment and any library dependencies
- **A separate process** — Hassette runs outside Home Assistant, not as an integration

## What Hassette does not replace

Hassette does **not** replace the Home Assistant WebSocket or REST API. It uses those APIs internally. Your existing YAML automations, UI automations, scripts, and scenes continue to work exactly as before — Hassette connects as an additional client.

You can migrate automations incrementally. Start with the one that's most painful in YAML and keep everything else as-is.

## Making the call

**Stick with YAML if:**

- Your automations are simple trigger-action patterns
- You prefer the Home Assistant UI and don't want to write code
- You're new to programming and want the easiest possible path

**Start with Hassette if:**

- You're hitting YAML's limits: complex conditions, state tracking across events, or painful Jinja2
- You want to test and debug your automations like ordinary code
- You need automations to remember state across restarts without using input helpers

If you're still unsure, the [Local Setup](index.md) guide takes 30 minutes. Try building one automation in Hassette — you'll know quickly whether the model suits you.
