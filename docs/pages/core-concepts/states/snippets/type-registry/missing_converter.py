from hassette import TYPE_REGISTRY
from hassette.exceptions import UnableToConvertValueError


class CustomType:
    def __init__(self, value):
        # This constructor raises to simulate a type that cannot be built from str
        raise TypeError("CustomType cannot be constructed from a string")


try:
    result = TYPE_REGISTRY.convert("value", CustomType)
except UnableToConvertValueError as e:
    print(e)  # "Unable to convert 'value' to <class 'CustomType'>"
