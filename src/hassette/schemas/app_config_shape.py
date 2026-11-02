"""Shared `app_config` shape logic, used by both `hassette.core` and `hassette.web`.

Extracted here (rather than left as two independent implementations) so `AppFactory` and
the per-instance HTTP routes can never disagree on which instances a given `app_config`
value represents.
"""

from copy import deepcopy

INSTANCE_NAME_KEY = "instance_name"
"""Config key read literally to name each instance, whatever alias the config class gives the field."""


def normalize_app_config(app_config: dict | list[dict] | None) -> list[dict]:
    """Normalize `app_config` to a list of per-instance config dicts.

    A single dict is one instance; a list is one instance per entry; `None` (an app with no
    configured instances) is an empty list.

    Returns deep copies so a caller mutating the result can never mutate the original
    `app_config` (e.g. `AppManifest.app_config`).
    """
    if app_config is None:
        return []
    if isinstance(app_config, dict):
        return [deepcopy(app_config)]
    return deepcopy(list(app_config))


def configured_instance_names(app_config: dict | list[dict] | None) -> list[str]:
    """The instance names `app_config` configures, in config order.

    Reads each name as `AppManifest` validation resolved it, so `app_config` must come from a validated manifest.
    """
    return [instance[INSTANCE_NAME_KEY] for instance in normalize_app_config(app_config)]


def configs_by_name(app_config: dict | list[dict] | None) -> dict[str, dict]:
    """Each instance's config dict in `app_config`, keyed by its name, which manifest validation keeps unique."""
    return {instance[INSTANCE_NAME_KEY]: instance for instance in normalize_app_config(app_config)}
