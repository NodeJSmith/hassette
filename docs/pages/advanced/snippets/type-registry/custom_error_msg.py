from hassette.core.type_registry import register_type_converter_fn


class MyType:
    pass


@register_type_converter_fn(error_message="Cannot convert '{value}' to MyType. Expected format: X,Y,Z")
def str_to_mytype(value: str) -> MyType:
    """Convert string to MyType with clear error handling.

    Types inferred from signature: str → MyType
    """
    # ... conversion logic with helpful ValueError messages
    return MyType()
