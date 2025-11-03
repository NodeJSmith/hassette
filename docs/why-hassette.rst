Why Hassette?
==============

.. note::

    This page is just a short blurb on why I built Hassette, as a way of explaining its focus and goals. If you're not interested, you can hit the Back button, there's nothing
    here you'll be missing out on.

Background
___________

I was a python developer way before I had ever heard of Home Assistant, so when I did discover HA I was more interested in writing automations in Python than in YAML or via the UI. The automations
felt clunky and limited - I'm not sure if they were, but I couldn't wrap my head around them the way I could simple Python code. I found AppDaemon almost immediately and have done almost all of my
automations in it since then, with only simple sequences and other small items in HA.

ApDaemon wasn't the experience I'd been hoping for though. The most frustrating part to me were the required signatures and the lack of type annotations. I'd have to add logs to each of my methods
just to know what they were receiving - after figuring out why the callback wasn't firing in the first place (more on that later). Too many times I'd be debugging just to find out I had assumed a type
was something other than it was, or I had my method signature wrong and AD was silently ignoring my method.

The logs were their own frustration - AD has a ``log`` method on the app, but it gets wrapped by AD and doesn't behave like a normal logger. You can't use ``%`` formatting, it doesn't include the line
and function of the error, there isn't a traceback. I also had a frustrating time figuring out how to get the app level logging to work properly to actually see stdout logs in my terminal when debugging.
I did, at one point, have the bright idea of using whatever test fixtures AD used internally to add tests to my apps and save myself some headache - but at that point AD `didn't actually have tests <https://github.com/AppDaemon/appdaemon/issues/2142>`_,
unless you count `this one <https://github.com/AppDaemon/appdaemon/blob/a9dadb7003562dd5532c6d629c24ba048cfd1b2d/tests/test_main.py>`_.

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


Focus
______

I developed Hassette with a few key goals in mind.

- I wanted it to be as type safe as I could make it, to help catch mistakes early and provide a better developer experience. I *never* want to be stepping through code just to figure out what type my arguments are or what fields are available on an object.
    - This is why Pydantic is used heavily for configuration and data models, we have an overly complex definition for a :type:`~hassette.types.types.HandlerType <HandlerType>`, and pyright is a required pre-push hook.
- I wanted it to be async-first (I initially didn't plan on supporting sync at all, but that immediately bit me on my own projects).
    - It's much easier to work with async code if everything else is already async, much more so than the other way around. And with async becoming the de facto standard for Python web frameworks and libraries, it just made sense.
- I wanted it to be simple to understand and to focus only on Home Assistant automations: no dashboards, no structure for adding in other services, just HA automations (I suspect MQTT will be added though).
    - I think part of the complexity of AD is that it is extensible - but it doesn't really need to be. It does HA and MQTT but has a framework for adding other services that I've never seen implemented. I wanted to avoid that complexity creep.
- I wanted test coverage for the core framework itself, just because I can't imagine shipping something without that. But I also *very* much wanted test fixtures for myself to use, for testing my own apps.
    - Hassette has decent test coverage now, although it still needs more. There is also a decent test harness for internal use - cleaning this up and making it public is very high on my priority list.
- I wanted logging to be boring stdlib logging and errors to be visible and obvious.
    - This one is pretty simple - the loggers attached to every class are just normal loggers. Exceptions do not crash anything, AD did have that right, but Hassette does include tracebacks where appropriate, and the logs include line numbers and function names.

I have plans on adding more - it needs a basic web UI, testing fixtures, an HA Addon, probably MQTT, etc. I'm using Dozzle for logging right now, which is fine but I don't
expect everyone to want to set that up just to see logs. But for writing automations it is already a much more pleasant experience than either HA yaml automations or AppDaemon.


Comparison with AppDaemon
-------------------------

If you're coming from AppDaemon, see our :doc:`detailed comparison <comparisons/index>` to understand the differences and migration path.
