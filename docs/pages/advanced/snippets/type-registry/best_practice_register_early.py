# my_converters.py
from hassette import register_type_converter_fn


class MyType:
    """Placeholder for a custom type."""


@register_type_converter_fn  # Registered when module is imported
def str_to_mytype(value: str) -> MyType: ...
