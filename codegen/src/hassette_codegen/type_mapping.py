"""Map YAML selector types to Python type annotations."""

import sys

SELECTOR_TYPE_MAP: dict[str, str] = {
    "boolean": "bool",
    "text": "str",
    "color_rgb": "tuple[int, int, int]",
    "color_temp": "int",
    "object": "Any",
    "state": "str",
    "entity": "str",
    "area": "str",
    "media": "dict[str, Any]",
    "constant": "Any",
    "target": "dict[str, Any]",
    "device": "str",
    "action": "dict[str, Any]",
    "duration": "dict[str, int]",
    "date": "str",
    "time": "str",
    "datetime": "str",
    "addon": "str",
    "backup_location": "str",
    "conversation_agent": "str",
    "config_entry": "str",
    "floor": "str",
    "label": "str",
    "language": "str",
    "location": "dict[str, float]",
    "theme": "str",
    "icon": "str",
    "template": "str",
    "trigger": "dict[str, Any]",
    "condition": "dict[str, Any]",
    "assist_pipeline": "str",
    "file": "str",
    "country": "str",
    "qr_code": "str",
    "ui_color": "str",
}


def map_selector_to_type(selector_type: str, selector_data: dict, domain: str = "") -> str:
    """Map a YAML selector type to a Python type string."""
    if selector_type == "number":
        step = selector_data.get("step")
        if step is not None and isinstance(step, (int, float)) and step < 1:
            return "float"
        return "int"

    if selector_type == "select":
        options = selector_data.get("options", [])
        if options and all(isinstance(o, str) for o in options):
            quoted = ", ".join(f'"{o}"' for o in options)
            return f"Literal[{quoted}]"
        return "str"

    if selector_type in SELECTOR_TYPE_MAP:
        return SELECTOR_TYPE_MAP[selector_type]

    context = f" in {domain}" if domain else ""
    print(f"WARNING: Unknown selector type '{selector_type}'{context} — defaulting to Any", file=sys.stderr)
    return "Any"
