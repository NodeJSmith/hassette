from hassette import TYPE_REGISTRY
from hassette.exceptions import UnableToConvertValueError

try:
    result = TYPE_REGISTRY.convert("not_a_number", int)
except UnableToConvertValueError as e:
    print(e)  # Error details about the conversion failure
