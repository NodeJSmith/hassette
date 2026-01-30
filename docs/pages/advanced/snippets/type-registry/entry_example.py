from hassette import TypeConverterEntry

entry = TypeConverterEntry(
    func=int,
    from_type=str,
    to_type=int,
    error_message="Cannot convert '{value}' to integer",
)
