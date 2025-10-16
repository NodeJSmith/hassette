Comparisons
===========

There are two main contenders in the Home Assistant Python automation ecosystem: ``appdaemon`` and ``pyscript``.

AppDaemon is the most similar to Hassette and was, in fact, the inspiration for it. It runs as it's own process, either self-hosted or as a Home Assistant add-on. It has an absolute ton of features, including a web dashboard, and is very mature.
It does show its age a bit these days, is synchronous first, and is not very strongly typed. It also has a lot of layers of indirection, which can make it hard to debug.

Pyscript is a Home Assistant integration that runs your Python inside of Home Assistant itself. It is actually a pretty brilliant bit of software, as it "implements a Python interpreter using the AST parser output"
and runs that interpreter inside the Home Assistant event loop. It has similar features to AppDaemon, but does suffer (in my opinion) from being stringly typed, limited IDE support, and too much magic. Pyscript has
it's own `AppDaemon comparison page <https://github.com/custom-components/pyscript/wiki/Comparing-Pyscript-to-AppDaemon>`__, which is worth a read.

I have spent some time writing up a detailed comparison between AppDaemon and Hassette. At this time, however, I have not done a similar comparison for Pyscript. This is partially because I have not used it enough to feel
comfortable doing so, and partially because Pyscript's design is fundamentally different from both AppDaemon and Hassette.

.. toctree::
   :maxdepth: 1

   AppDaemon Comparison <appdaemon>
