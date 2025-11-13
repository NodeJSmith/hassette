# Why Hassette?

!!! note
    This page is just a short blurb on why I built Hassette, as a way of explaining its focus and goals. If you're not interested, you can hit the Back button, there's nothing
    here you'll be missing out on.

## Background

I was a python developer way before I had ever heard of Home Assistant, so when I did discover HA I was more interested in writing automations in Python than in YAML or via the UI. The automations
felt clunky and limited - I'm not sure if they were, but I couldn't wrap my head around them the way I could simple Python code. I found AppDaemon almost immediately and have done almost all of my
automations in it since then, with only simple sequences and other small items in HA.

ApDaemon wasn't the experience I'd been hoping for though. The most frustrating part to me were the required signatures and the lack of type annotations. I'd have to add logs to each of my methods
just to know what they were receiving - after figuring out why the callback wasn't firing in the first place (more on that later). Too many times I'd be debugging just to find out I had assumed a type
was something other than it was, or I had my method signature wrong and AD was silently ignoring my method.

The logs were their own frustration - AD has a `log` method on the app, but it gets wrapped by AD and doesn't behave like a normal logger. You can't use `%` formatting, it doesn't include the line
and function of the error, there isn't a traceback. I also had a frustrating time figuring out how to get the app level logging to work properly to actually see stdout logs in my terminal when debugging.
I did, at one point, have the bright idea of using whatever test fixtures AD used internally to add tests to my apps and save myself some headache - but at that point AD [didn't actually have tests](https://github.com/AppDaemon/appdaemon/issues/2142),
unless you count [this one](https://github.com/AppDaemon/appdaemon/blob/a9dadb7003562dd5532c6d629c24ba048cfd1b2d/tests/test_main.py).

I freely admit that some of these issues could have been on me, but I did do my due diligence trying to figure them out. I read the docs, searched reddit and HA forums, and tried to dig through the source code.
The source code was a frustration to me as well - I respect that AD is well built in general, but the codebase has quite a few levels of inheritance and indirection that made it hard for me to follow what was going on.

After a year or so of frustration with AD, I decided to just build my own little tool that did what I wanted. I just wanted to query HA for some states most of the time, sometimes call a service, etc. I'm sure I
don't have to explain to anyone here how quickly I outgrew that limited functionality and wanted to have scheduling, event bus listeners, etc. I had stuff to build! So I kept adding features until the code for
Hassette was larger than the little private repo I'd been using for my AD apps.

I moved Hassette over to its own private project and kept working on it. I wasn't sure if I was going to make it public but I knew I definitely wasn't going to make it public then. I didn't want anyone out there
getting wind of it and comparing my dinky little toy to AppDaemon. Not until I knew I was ready to support it as a proper open source project and had actually delivered some kind of stable application with
at least similar feature parity to AD.

And now here we are. Hassette is still not as fully featured as AD, but it has most of the core features I use daily and I've been using it in production for months now without issues. Hopefully you'll find it useful
and enjoyable to use as well.

## Focus

Hassette was built with a few principles:

- **Type safety first.** I never want to step through code to discover basic type information. That’s why Pydantic powers configuration and data models, handlers use the extra-precise [HandlerType][hassette.types.handler.HandlerType], and `pyright` is a required pre-push hook.
- **Async by default.** I originally considered skipping sync support entirely and immediately regretted it for my own projects. Async everywhere makes it simpler to work with modern Python libraries. Sync is available through a bridge for the cases that need it.
- **Keep scope tight.** Hassette is about Home Assistant automations - not dashboards, not arbitrary services. AD’s extensibility is impressive but adds complexity most users don’t need. MQTT will probably land eventually, but it will likely not be a first-class citizen and instead be available as methods on the existing resources/services.
- **Ship with tests.** The core framework has decent coverage (always room for more). There’s also an internal test harness I plan to publish so you can test your own apps easily.
- **Boring logging, visible errors.** Every class gets a plain stdlib logger. Exceptions don’t crash the system (AppDaemon got that right) but you still get tracebacks, line numbers, and function names where it matters.

The roadmap includes a simple web UI, public test fixtures, an HA add-on, and more. I currently use Dozzle for logs; it works but I don’t expect everyone to set it up just to see output. However, even today Hassette already feels more pleasant than HA YAML automations or AppDaemon for most day-to-day work.

## Comparison with AppDaemon

If you're coming from AppDaemon, see our [detailed comparison](comparisons/index.md) to understand the differences and migration path.
