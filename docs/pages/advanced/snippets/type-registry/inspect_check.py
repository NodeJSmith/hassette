from hassette import TYPE_REGISTRY

# Check if a converter exists
key = (str, int)
if key in TYPE_REGISTRY.conversion_map:
    entry = TYPE_REGISTRY.conversion_map[key]
    print(f"Converter found for {str} -> {int}")
else:
    print("No converter registered")
