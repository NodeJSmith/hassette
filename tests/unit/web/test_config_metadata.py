"""Unit tests for the ui presentation-metadata mechanism and nested-group field descriptions.

Note: the OpenAPI freshness check does not cover ``ui`` annotation content (it rides in a
``dict[str, Any]`` field), so this test is the sole guard against ``ui``-shape drift.
"""

from typing import Any

from pydantic import BaseModel, Field

from hassette.config.config import HassetteConfig
from hassette.web.config_view import build_config_view

_ALLOWED_UI_KEYS = {"label", "group_label", "order", "widget", "tier"}
_ALLOWED_TIER_VALUES = {"common", "advanced"}


class _AnnotatedModel(BaseModel):
    """Throwaway model: one field with a ui.label override."""

    port: int = Field(default=8126, json_schema_extra={"ui": {"label": "Web API Port"}})


def _walk_ui_blocks(node: Any) -> list[tuple[str, dict[str, Any]]]:
    """Return a list of (path, ui_dict) pairs found anywhere in a schema node."""
    results: list[tuple[str, dict[str, Any]]] = []
    _collect_ui(node, path="", results=results)
    return results


def _collect_ui(node: Any, path: str, results: list[tuple[str, dict[str, Any]]]) -> None:
    if not isinstance(node, dict):
        return
    if "ui" in node and isinstance(node["ui"], dict):
        results.append((path, node["ui"]))
    for key, value in node.items():
        child_path = f"{path}.{key}" if path else key
        if isinstance(value, dict):
            _collect_ui(value, child_path, results)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                _collect_ui(item, f"{child_path}[{i}]", results)


class TestUiRoundTrip:
    """The ui block survives model_json_schema() and build_config_view deref."""

    def test_ui_label_survives_model_json_schema(self) -> None:
        """A field with json_schema_extra ui block appears in model_json_schema output."""
        schema = _AnnotatedModel.model_json_schema()
        ui = schema["properties"]["port"].get("ui")
        assert ui == {"label": "Web API Port"}, f"Expected ui block in schema, got: {ui!r}"

    def test_ui_label_survives_deref(self) -> None:
        """The ui block is intact in config_schema after build_config_view deref."""
        schema = _AnnotatedModel.model_json_schema()
        result = build_config_view(schema, {"port": 8126})
        ui = result["config_schema"]["properties"]["port"].get("ui")
        assert ui == {"label": "Web API Port"}, f"Expected ui block intact after deref, got: {ui!r}"

    def test_hassette_web_api_group_label(self) -> None:
        """HassetteConfig.web_api carries ui.group_label='Web API' in the served schema."""
        schema = HassetteConfig.model_json_schema()
        result = build_config_view(schema, {})
        web_api_node = result["config_schema"]["properties"].get("web_api", {})
        ui = web_api_node.get("ui")
        assert ui is not None, "web_api field must have a ui block"
        assert ui.get("group_label") == "Web API", f"Expected group_label='Web API', got: {ui.get('group_label')!r}"


class TestUiShapeConstraints:
    """Every ui block in the served HassetteConfig schema uses only allowed keys and types."""

    def test_hassette_config_ui_blocks_valid(self) -> None:
        """Walk the full served config schema and assert every ui block is well-formed.

        Checks that every ui block found in the schema:
        - Is a dict
        - Uses only the allowed keys (label, group_label, order, widget, tier)
        - Has correct value types: str for label/group_label/widget, int for order
        - If tier is set, its value is only 'common' or 'advanced'
        """
        schema = HassetteConfig.model_json_schema()
        result = build_config_view(schema, {})
        found = _walk_ui_blocks(result["config_schema"])
        for path, ui in found:
            unknown = set(ui.keys()) - _ALLOWED_UI_KEYS
            assert not unknown, f"ui block at '{path}' has unknown keys: {unknown!r}"
            if "label" in ui:
                assert isinstance(ui["label"], str), f"ui.label at '{path}' must be str, got {type(ui['label'])!r}"
            if "group_label" in ui:
                assert isinstance(ui["group_label"], str), f"ui.group_label at '{path}' must be str"
            if "order" in ui:
                assert isinstance(ui["order"], int), f"ui.order at '{path}' must be int"
            if "widget" in ui:
                assert isinstance(ui["widget"], str), f"ui.widget at '{path}' must be str"
            if "tier" in ui:
                assert ui["tier"] in _ALLOWED_TIER_VALUES, (
                    f"ui.tier at '{path}' must be one of {_ALLOWED_TIER_VALUES!r}, got {ui['tier']!r}"
                )

    def test_no_ui_tier_is_set(self) -> None:
        """No field in HassetteConfig sets ui.tier (tier decisions are deferred)."""
        schema = HassetteConfig.model_json_schema()
        result = build_config_view(schema, {})
        found = _walk_ui_blocks(result["config_schema"])
        for path, ui in found:
            assert "tier" not in ui, f"ui.tier must not be set on any field (found at '{path}')"


class TestNestedGroupDescriptions:
    """Nested-group fields carry schema descriptions from their field docstrings."""

    def test_database_retention_days_has_description(self) -> None:
        """database.retention_days carries a non-empty description in the served schema."""
        schema = HassetteConfig.model_json_schema()
        result = build_config_view(schema, {})
        db_props = result["config_schema"]["properties"]["database"]["properties"]
        description = db_props["retention_days"].get("description", "")
        assert description, "database.retention_days must have a non-empty description from its field docstring"

    def test_groups_with_own_model_config_still_emit_descriptions(self) -> None:
        """WebApiConfig and BlockingIODetectionConfig define their own model_config for ui
        metadata; use_attribute_docstrings must still merge in from the mixin (Pydantic v2
        merges config across the MRO) so their documented fields keep emitting descriptions."""
        schema = HassetteConfig.model_json_schema()
        result = build_config_view(schema, {})
        props = result["config_schema"]["properties"]
        for group in ("web_api", "blocking_io"):
            group_props = props[group]["properties"]
            descriptions = [p.get("description", "") for p in group_props.values()]
            assert any(descriptions), f"{group} must emit field descriptions (mixin config merge intact)"
