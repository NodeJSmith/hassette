"""Allow reference sections by :ref: role using its title."""

import re

from docutils.nodes import Text
from sphinx.addnodes import pending_xref
from sphinx.util import logging

logger = logging.getLogger(__name__)

# Exact remap table: "public target" -> "canonical target"
REMAP_EXACT: dict[str, str] = {
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
    # add more explicit mappings here
}

REMAP_REFTYPE: dict[str, str] = {
    "hassette.types.types.JobCallable": "type",
    "hassette.types.types.ScheduleStartType": "type",
    "hassette.models.states.base.StateT": "type",
    "hassette.models.states.base.StateValueT": "type",
    "hassette.models.entities.base.EntityT": "type",
}

# Regex remaps: (pattern, replacement)
# Useful for bulk rewrites, replacement can use group references
REMAP_REGEX: list[tuple[re.Pattern[str], str]] = []


def resolve_aliases(app, doctree):  # noqa
    pending_xrefs = doctree.traverse(condition=pending_xref)
    for node in pending_xrefs:
        alias = node.get("reftarget", None)
        if alias is not None and alias in REMAP_EXACT:
            real_ref = REMAP_EXACT[alias]
            node["reftarget"] = real_ref

            if real_ref in REMAP_REFTYPE:
                node["reftype"] = REMAP_REFTYPE[real_ref]

            text_node = next(iter(node.traverse(lambda n: n.tagname == "#text")))
            text_node.parent.replace(text_node, Text(real_ref))


def setup(app):
    app.connect("doctree-read", resolve_aliases)
    return {
        "version": "0.1",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
