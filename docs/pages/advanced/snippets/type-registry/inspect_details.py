from hassette import TYPE_REGISTRY

# Get details about a specific converter
entry = TYPE_REGISTRY.conversion_map.get((str, bool))
if entry:
    print(f"Error message: {entry.error_message}")
    print(f"Converter: {entry.func}")
