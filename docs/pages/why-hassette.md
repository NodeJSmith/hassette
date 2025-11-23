# Why Hassette?

!!! note
    This page explains the motivation, focus, and goals behind Hassette. If you just want to build something, feel free to skip it.

## Background

I was a Python developer long before I discovered Home Assistant, so the moment I did I wanted to write automations in Python—not YAML or the UI. The built-in automations felt clunky and limited (maybe they weren’t, but I couldn’t reason about them as easily as straight Python). I found AppDaemon almost immediately and have done most of my automations there ever since, with only simple sequences left in HA.

AppDaemon still wasn’t the experience I hoped for. Specific signature requirements and the lack of type annotations slowed me down. I had to add log statements everywhere just to see what callbacks were receiving—after figuring out why a callback wasn’t firing in the first place. Too often I was debugging to discover I assumed the wrong type or signature and AppDaemon silently ignored my method.

Logging brought its own frustrations: AppDaemon’s `log` helper is wrapped and doesn’t behave like a normal logger. `%` formatting doesn’t work, log lines omit where errors occurred, and tracebacks are missing. Getting stdout from my apps while debugging also took more effort than it should have. At one point I tried to find AppDaemon’s test fixtures so I could write tests for my own apps—turns out [AppDaemon didn’t actually have tests](https://github.com/AppDaemon/appdaemon/issues/2142) at the time, unless you count [this single file](https://github.com/AppDaemon/appdaemon/blob/a9dadb7003562dd5532c6d629c24ba048cfd1b2d/tests/test_main.py).

Maybe some of that was on me, but I did my homework: read the docs, searched Reddit and the HA forums, and dug through the source. The code base has solid ideas, but the layers of inheritance and indirection made it tough to follow.

After a year of frustration I built my own small tool that did just what I needed. Mostly I wanted to query HA for states, occasionally call a service, nothing fancy. Naturally the “small tool” grew—scheduling, event bus listeners, hot reloading. Before long the framework was larger than the repo containing my AppDaemon apps.

I split Hassette into its own private project and kept iterating. I wasn’t ready to show it publicly until I felt I could support it properly and offer something comparable to AppDaemon. Now Hassette still isn’t as feature-complete, but it covers the core features I rely on daily and has been running my production automations for months. Hopefully it gives you a smoother experience too.

## Focus

Based on these experiences, Hassette was built with a few principles:

- **Type safety first.** I never want to step through code to discover basic type information. That’s why Pydantic powers configuration and data models, pyright is required pre-push hook, and every public method is fully typed.
- **Async by default.** Async everywhere makes it simpler to work with modern Python libraries. Sync is available through a bridge for the cases that need it.
- **Keep scope tight.** Hassette is about Home Assistant automations - not dashboards, not arbitrary services. AD’s extensibility is impressive but adds complexity most users don’t need. MQTT will probably land eventually, but it will likely not be a first-class citizen and instead be available as methods on the existing resources/services.
- **Ship with tests.** The core framework has decent coverage (always room for more). There’s also an internal test harness I plan to publish so you can test your own apps easily.
- **Boring logging, visible errors.** Every class gets a plain stdlib logger. Exceptions don’t crash the system (AppDaemon got that right) but you still get tracebacks, line numbers, and function names where it matters.

The roadmap includes a simple web UI, public test fixtures, an HA add-on, and more. I currently use Dozzle for logs; it works but I don’t expect everyone to set it up just to see output. However, even today Hassette already feels more pleasant than HA YAML automations or AppDaemon for most day-to-day work.

## Comparison with AppDaemon

If you're coming from AppDaemon, see our [detailed comparison](appdaemon-comparison.md) to understand the differences and migration path.
