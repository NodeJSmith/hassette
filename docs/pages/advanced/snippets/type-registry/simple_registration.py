from hassette.core.type_registry import register_simple_type_converter

# Register a simple converter (uses int() as the converter function)
register_simple_type_converter(
    from_type=str,
    to_type=int,
    fn=int,  # Optional - defaults to to_type constructor if not provided
    error_message="Cannot convert '{value}' to integer",  # Optional
)
