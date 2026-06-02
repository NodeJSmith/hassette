# Is Hassette Right for You?

Hassette is a Python framework for writing Home Assistant automations. It runs as a separate process and connects over the WebSocket API. Your existing YAML automations, scripts, and scenes keep working. Hassette is an additional layer, not a replacement.

## When Hassette Makes Sense

Hassette fits you if you write Python and your automations have grown past what YAML handles well.

**Complex logic.** Multi-step sequences, accumulated state, and real branching are straightforward in Python. In YAML they require nested templates and workarounds.

**Testability.** Hassette apps run in a test harness. You can simulate events, advance time, and assert outcomes without a running Home Assistant instance. If you want confidence before deploying an automation that controls locks or heat, this matters.

**Code reuse.** Python lets you share logic across apps through ordinary functions, base classes, and modules. In YAML, reuse means copy-paste.

If you have ever debugged a Jinja2 template by adding `{{ "got here" }}` in the middle, that is also a sign.

## When HA YAML Is Enough

YAML automations are built into Home Assistant and need no additional setup. For simple patterns they are the right tool.

Use YAML when your automations are straightforward trigger-action rules. Turn on a light when motion is detected. Send a notification at sunrise. Run a scene when you arrive home. The Home Assistant UI can build and edit these without touching a file.

YAML also makes sense if you prefer visual tools or are new to programming. Hassette requires Python. If you do not want to write code, YAML is the better path. The [Home Assistant automation docs](https://www.home-assistant.io/docs/automation/) cover what YAML can do.

## Quick Comparison

| | HA YAML | Hassette |
|---|---|---|
| **Language** | YAML + Jinja2 | Python 3.11+ |
| **Debugging** | HA trace viewer | Structured logs, web UI, Python debugger |
| **Testing** | Manual | `AppTestHarness`, event simulation, time control |
| **Version control** | Text files | Text files |
| **Learning curve** | Low to medium | Medium (Python + async basics) |
| **Complexity ceiling** | Medium | High |

Hassette does not replace Home Assistant integrations, dashboards, or add-ons. It handles automations only. Use the HA UI for dashboards and integrations, and Hassette for the automation logic behind them. Your existing YAML automations run alongside Hassette apps with no conflicts.

## What Hassette Requires

**Python 3.11 or later.** Hassette uses modern Python features and will not run on older versions.

**A machine to run the process.** Hassette runs outside Home Assistant. The same box works fine, or you can run it in Docker. It does not run as a Home Assistant add-on yet. The [Docker Setup guide](docker/index.md) covers the recommended path.

**A long-lived access token.** Hassette connects to Home Assistant via a token you generate in your profile settings. It needs read and write access to call services and read state.

**Recommended: comfort with `async`/`await`.** Hassette apps are async Python classes. You do not need to understand the event loop deeply, but `await` and `async def` appear in every example. Hassette also offers `AppSync` for writing synchronous apps, though the async API is what the docs focus on.

## Next Steps

Ready to try it? The [Quickstart](index.md) takes about five minutes and ends with a running automation.

Coming from AppDaemon? The [Migration section](../migration/index.md) walks through the differences and shows how to convert common patterns.
