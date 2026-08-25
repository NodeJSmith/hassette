"""Shared `app_config` shape logic, used by both `hassette.core` and `hassette.web`.

Extracted here (rather than left as two independent implementations) so `AppFactory` and
the per-instance HTTP routes can never disagree on how many instances a given `app_config`
value represents.
"""

from copy import deepcopy


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
