from hassette import TYPE_REGISTRY

try:
    result = TYPE_REGISTRY.convert("not_a_number", int)
except ValueError as e:
    # Error message uses the error_message from the converter
    print(e)  # Error details about the conversion failure
