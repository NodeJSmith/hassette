from hassette.core.type_registry import TypeConverterEntry

entry = TypeConverterEntry(
    func=int,
    from_type=str,
    to_type=int,
    error_message="Cannot convert '{value}' to integer",
)
