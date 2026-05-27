from hassette import TYPE_REGISTRY

# Get all registered conversions
for (from_type, to_type), entry in sorted(
    TYPE_REGISTRY.conversion_map.items(),
    key=lambda x: (x[0][0].__name__, x[0][1].__name__),
):
    print(f"{from_type.__name__} → {to_type.__name__}")
