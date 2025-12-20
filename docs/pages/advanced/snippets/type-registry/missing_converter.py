from hassette import TYPE_REGISTRY


class CustomType:
    pass


try:
    result = TYPE_REGISTRY.convert("value", CustomType)
except TypeError as e:
    print(e)  # "No converter registered for str -> CustomType"
