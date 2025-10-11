import traceback


def get_traceback_string(exception: Exception | BaseException) -> str:
    """Get a formatted traceback string from an exception."""

    return "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))
