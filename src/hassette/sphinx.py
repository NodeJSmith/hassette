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
    "hassette.types.KnownTypeScalar": "hassette.types.types.KnownTypeScalar",
    "hassette.types.HandlerType": "hassette.types.handlers.HandlerType",
    "hassette.types.AsyncHandlerType": "hassette.types.handlers.AsyncHandlerType",
    "hassette.types.ComparisonCondition": "hassette.types.types.ComparisonCondition",
    "hassette.types.Predicate": "hassette.types.types.Predicate",
    "hassette.types.ChangeType": "hassette.types.types.ChangeType",
    "hassette.models.entities.EntityT": "hassette.models.entities.base.EntityT",
    "hassette.models.states.StateT": "hassette.models.states.base.StateT",
    "hassette.models.states.StateValueT": "hassette.models.states.base.StateValueT",
    "EntityT": "hassette.models.entities.base.EntityT",
    "StateT": "hassette.models.states.base.StateT",
    "StateValueT": "hassette.models.states.base.StateValueT",
    "hassette.Api": "hassette.api.api.Api",
    "hassette.api.Api": "hassette.api.api.Api",
    "hassette.scheduler.Scheduler": "hassette.scheduler.scheduler.Scheduler",
    "hassette.app.App": "hassette.app.app.App",
}

CANONICAL_TYPE_MAP = {
    "hassette.types.types.JobCallable": "obj",
    "hassette.types.types.ScheduleStartType": "obj",
    "hassette.models.states.base.StateT": "obj",
    "hassette.models.states.base.StateValueT": "obj",
    "hassette.models.states.StateUnion": "obj",
    "hassette.models.entities.base.EntityT": "obj",
    "hassette.types.handlers.HandlerType": "obj",
    "hassette.types.handlers.AsyncHandlerType": "obj",
    "hassette.types.types.KnownTypeScalar": "obj",
    "hassette.types.types.ComparisonCondition": "obj",
    "hassette.types.types.Predicate": "obj",
    "hassette.types.types.ChangeType": "obj",
}

PYDANTIC_IGNORE_FIELDS = [
    "dict",
    "copy",
    "parse_obj",
    "parse_raw",
    "parse_file",
    "schema",
    "schema_json",
    "model_validate",
    "model_validate_json",
    "model_validate_strings",
    "model_rebuild",
    "model_parametrized_name",
    "model_json_schema",
    "model_construct",
    "from_orm",
    "construct",
    "update_forward_refs",
    "validate",
    "json",
    "model_copy",
    "model_dump",
    "model_dump_json",
    "model_extra",
    "model_computed_fields",
    "model_fields",
    "model_fields_set",
    "model_config",
    "model_rebuild",
    "model_post_init",
]

OTHER_IGNORE_FIELDS = ["create"]


def resolve_aliases(app, doctree):  # noqa
    """Remap documented references to their canonical locations and types."""
    pending_xrefs = doctree.traverse(condition=pending_xref)
    for node in pending_xrefs:
        real_ref = None
        should_update = False

        alias = node.get("reftarget", None)

        # if we've defined this in our remap table, swap it out
        if alias is not None and alias in FOUND_PATH_TO_CANONICAL_MAP:
            real_ref = FOUND_PATH_TO_CANONICAL_MAP[alias]
            node["reftarget"] = real_ref
            should_update = True

        # if real ref is a different reftype, swap that too
        if real_ref in CANONICAL_TYPE_MAP:
            node["reftype"] = CANONICAL_TYPE_MAP[real_ref]
            should_update = True

        if alias in CANONICAL_TYPE_MAP:
            node["reftype"] = CANONICAL_TYPE_MAP[alias]
            should_update = True

            # use short name for type aliases
            alias = alias.split(".")[-1]

        if should_update:
            text_node = next(iter(node.traverse(lambda n: n.tagname == "#text")))
            text_node.parent.replace(text_node, Text(alias))


def skip_members(app, what, name, obj, skip, options):  # noqa
    if not name or not isinstance(name, str):
        return skip

    parts = name.split(".")
    if len(parts) > 1 and parts[-1] in PYDANTIC_IGNORE_FIELDS:
        logger.debug("Skipping Pydantic field %s from docs", name)
        return True

    if len(parts) > 1 and parts[-1] in OTHER_IGNORE_FIELDS:
        logger.debug("Skipping other field %s from docs", name)
        return True

    return skip


def setup(app):
    app.connect("doctree-read", resolve_aliases)
    app.connect("autoapi-skip-member", skip_members)

    return {
        "version": "0.1",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
