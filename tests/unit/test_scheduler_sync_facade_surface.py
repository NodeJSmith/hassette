"""Surface guard for the generated Scheduler sync facade.

The facade is generated into two modules — ``scheduler/sync.py`` holds the core scheduling
API, ``scheduler/sync_convenience.py`` holds the ``run_*`` convenience wrappers that
``SchedulerSyncFacade`` inherits — so that neither file crosses the repo's file-size threshold.
Callers only ever see the merged surface via ``scheduler.sync``, and these tests pin it: every
public ``Scheduler`` method has a facade counterpart, and the wrappers really do arrive by
inheritance.
"""

import inspect

from hassette_codegen.sync_facade import INTERNAL_METHODS, LIFECYCLE_METHODS, SCHEDULER_CONVENIENCE_METHODS

from hassette.resources.base import Resource
from hassette.scheduler.scheduler import Scheduler
from hassette.scheduler.sync import SchedulerSyncFacade
from hassette.scheduler.sync_convenience import SchedulerSyncConvenience


def public_scheduler_methods() -> set[str]:
    """Every public method defined on Scheduler (or a Scheduler-side base) that the facade mirrors.

    Walks the MRO up to ``Resource`` so the check stays valid if ``Scheduler`` is later split
    into mixins.
    """
    names: set[str] = set()
    for cls in Scheduler.__mro__:
        if cls is Resource:
            break
        names.update(
            name
            for name, obj in vars(cls).items()
            if inspect.isfunction(obj)
            and not name.startswith("_")
            and name not in LIFECYCLE_METHODS
            and name not in INTERNAL_METHODS
        )
    return names


def test_facade_mirrors_every_public_scheduler_method() -> None:
    """No Scheduler method is lost when the facade is split across two generated modules."""
    missing = sorted(name for name in public_scheduler_methods() if not hasattr(SchedulerSyncFacade, name))
    assert not missing, f"SchedulerSyncFacade is missing Scheduler methods: {missing}"


def test_convenience_methods_are_inherited_not_duplicated() -> None:
    """The run_* wrappers live on the base class only — a copy in sync.py would drift silently."""
    assert issubclass(SchedulerSyncFacade, SchedulerSyncConvenience)
    not_on_base = sorted(name for name in SCHEDULER_CONVENIENCE_METHODS if name not in vars(SchedulerSyncConvenience))
    on_facade = sorted(name for name in SCHEDULER_CONVENIENCE_METHODS if name in vars(SchedulerSyncFacade))
    assert not not_on_base, f"SchedulerSyncConvenience is missing wrappers: {not_on_base}"
    assert not on_facade, f"SchedulerSyncFacade redefines wrappers it should inherit: {on_facade}"
