# Comparisons

Two main contenders exist in the Home Assistant Python automation ecosystem: **AppDaemon** and **Pyscript**.

AppDaemon is closest in spirit to Hassette and was the original inspiration. It runs as its own process (self-hosted or as a Home Assistant add-on) and ships with a huge feature set, including a web dashboard. The trade-offs are that it shows its age, prioritizes synchronous code, and has limited typing. The inheritance-heavy design can make debugging harder than it needs to be.

Pyscript runs inside Home Assistant itself. It “implements a Python interpreter using the AST parser output” and executes within HA’s event loop. It offers AppDaemon-like capabilities but leans on stringly-typed magic, limited IDE support, and substantial runtime patching. Pyscript’s authors have a [great comparison with AppDaemon](https://github.com/custom-components/pyscript/wiki/Comparing-Pyscript-to-AppDaemon) that’s worth reading.

I’ve written a detailed comparison between AppDaemon and Hassette, but not yet for Pyscript (I haven’t used it deeply enough to do it justice, and its design is fundamentally different). Start with the [AppDaemon comparison](appdaemon.md) if you’re evaluating Hassette.
