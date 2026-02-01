from hassette import TYPE_REGISTRY

# Get all registered conversions
conversions = TYPE_REGISTRY.list_conversions()

for from_type, to_type, _entry in conversions:
    print(f"{from_type.__name__} → {to_type.__name__}")
