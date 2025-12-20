from hassette.core.type_registry import register_type_converter_fn


@register_type_converter_fn(error_message="String must be a boolean-like value, got {from_type}")
def str_to_bool(value: str) -> bool:
    """Convert HA boolean strings like 'on'/'off' to Python bool.

    The decorator infers from_type and to_type from the function signature.
    """
    value_lower = value.lower()
    if value_lower in ("on", "true", "yes", "1"):
        return True
    elif value_lower in ("off", "false", "no", "0"):
        return False
    raise ValueError(f"Invalid boolean value: {value}")
