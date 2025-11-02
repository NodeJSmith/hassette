Why Hassette?
========

Hassette is designed for home automation geeks and developers who want to write Home Assistant automations in Python.

It was developed by a fellow HA geek and Python developer who was frustrated with AppDaemon's lack of type annotations, deeply nested levels of inheritance, and its
insistence on swallowing exceptions (or at least making them hard to find).

After a few months of frustration with AD, I decided to just build my own little tool that did what I wanted. That tool was supposed to be small
and just a little thing for me to use, but as I wanted more of the features that AD does deliver well (scheduling, event bus, hot-reloading, etc.),
it grew too big to keep in my little private automation repo. So I moved it to Hassette as a private project and kept working on it. I wasn't necessarily wanting
to own an open source project of this complexity, but I do think it is a better modern alternative to AppDaemon and I don't want to keep that to myself. So here it is.

Focus
~~~~~
I developed Hassette with a few key goals in mind.

- I wanted it to be as type safe as I could make it, to help catch mistakes early and provide a better developer experience. I *never* want to be stepping through code just to figure out what type my arguments are or what fields are available on an object.
- I wanted it to be async-first (I initially didn't plan on supporting sync at all, but that immediately bit me on my own projects).
- I wanted it to be simple to understand and to focus only on Home Assistant automations: no dashboards, no structure for adding in other services, just HA automations (I suspect MQTT will be added though).
- And lastly, I wanted logging to be boring stdlib logging and errors to be visible and obvious.

I have plans on adding more - it needs a basic web UI, testing fixtures, an HA Addon, and probably more. I'm using Dozzle for logging right now, which is fine but I don't
expect everyone to want to set that up just to see logs. But for writing automations it is already a much more pleasant experience than either HA yaml automations or AppDaemon.
