import traceback
from textwrap import indent


def get_traceback_string(exception: Exception | BaseException) -> str:
    """Get a formatted traceback string from an exception."""

    return "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))


def get_short_traceback(limit: int = 1, indent_output: bool = True) -> str:
    """Get a short traceback string of the current exception. Must be called within an exception handler.

    Args:
        limit: The number of stack levels to include in the traceback.
        indent_output: Whether to indent the output for better readability.

    Returns:
        A formatted traceback string.

    """
    value = traceback.format_exc(limit=limit)
    if indent_output:
        value = indent(value, "    ")

    lines = value.splitlines()
    if lines and not lines[-1].strip():
        lines = lines[:-1]

    value = "\n".join(lines)
    return value
