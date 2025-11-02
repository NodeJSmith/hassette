"""
Sphinx extension to remap documented references to their canonical locations.

This is to deal with AutoApi missing certain indirections and not handling types well.
And sphinx.ext.autodoc not handling TYPE_CHECKING.
And autodoc_type_hints not working well with complex type aliases.
And autodoc2 not working well at all.

Nothing works well - so this is my bandaid for now. If anyone else has a better suggestion
I would *LOVE* to hear it.
"""

from docutils.nodes import Text
from sphinx.addnodes import pending_xref
from sphinx.util import logging

logger = logging.getLogger(__name__)


FOUND_PATH_TO_CANONICAL_MAP = {
    "hassette.events.HassStateDict": "hassette.events.hass.raw.HassStateDict",
    "hassette.models.states.BaseState": "hassette.models.states.base.BaseState",
    "hassette.TaskBucket": "hassette.task_bucket.TaskBucket",
    "hassette.Hassette": "hassette.core.Hassette",
    "hassette.HassetteConfig": "hassette.config.core_config.HassetteConfig",
    "hassette.bus.Listener": "hassette.bus.listeners.Listener",
    "hassette.bus.Bus": "hassette.bus.bus.Bus",
    "hassette.types.JobCallable": "hassette.types.types.JobCallable",
    "hassette.types.ScheduleStartType": "hassette.types.types.ScheduleStartType",
    "hassette.models.states.StateT": "hassette.models.states.base.StateT",
    "hassette.models.states.StateValueT": "hassette.models.states.base.StateValueT",
    "hassette.models.entities.EntityT": "hassette.models.entities.base.EntityT",
    "hassette.types.KnownTypeScalar": "hassette.types.types.KnownTypeScalar",
    "hassette.types.HandlerType": "hassette.types.handlers.HandlerType",
    "hassette.types.AsyncHandlerType": "hassette.types.handlers.AsyncHandlerType",
    "hassette.types.ComparisonCondition": "hassette.types.types.ComparisonCondition",
    "hassette.types.Predicate": "hassette.types.types.Predicate",
    "hassette.types.ChangeType": "hassette.types.types.ChangeType",
    "hassette.models.states.StateUnion": "hassette.models.states.base.StateUnion",
    "EntityT": "hassette.models.entities.base.EntityT",
    "StateT": "hassette.models.states.base.StateT",
    "StateValueT": "hassette.models.states.base.StateValueT",
    "hassette.Api": "hassette.api.api.Api",
    "hassette.api.Api": "hassette.api.api.Api",
    "hassette.scheduler.Scheduler": "hassette.scheduler.scheduler.Scheduler",
    "hassette.app.App": "hassette.app.app.App",
}

CANONICAL_TYPE_MAP = {
    "hassette.types.types.JobCallable": "type",
    "hassette.types.types.ScheduleStartType": "type",
    "hassette.models.states.base.StateT": "type",
    "hassette.models.states.base.StateValueT": "type",
    "hassette.models.entities.base.EntityT": "type",
    "hassette.types.handlers.HandlerType": "type",
    "hassette.types.handlers.AsyncHandlerType": "type",
    "hassette.types.types.KnownTypeScalar": "type",
    "hassette.types.types.ComparisonCondition": "type",
    "hassette.types.types.Predicate": "type",
    "hassette.types.types.ChangeType": "type",
}


def resolve_aliases(app, doctree):  # noqa
    """Remap documented references to their canonical locations and types."""
    pending_xrefs = doctree.traverse(condition=pending_xref)
    for node in pending_xrefs:
        alias = node.get("reftarget", None)

        # if we've defined this in our remap table, swap it out
        if alias is not None and alias in FOUND_PATH_TO_CANONICAL_MAP:
            real_ref = FOUND_PATH_TO_CANONICAL_MAP[alias]
            node["reftarget"] = real_ref

            # if real ref is a different reftype, swap that too
            if real_ref in CANONICAL_TYPE_MAP:
                node["reftype"] = CANONICAL_TYPE_MAP[real_ref]

            text_node = next(iter(node.traverse(lambda n: n.tagname == "#text")))
            text_node.parent.replace(text_node, Text(real_ref))


def setup(app):
    app.connect("doctree-read", resolve_aliases)
    return {
        "version": "0.1",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
