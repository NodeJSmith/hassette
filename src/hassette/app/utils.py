import typing

from hassette.app.app_config import AppConfig
from hassette.exceptions import InvalidInheritanceError

if typing.TYPE_CHECKING:
    # breaks a circular import: hassette.app.app -> hassette.config -> hassette.config.config
    # -> hassette.utils.app_utils -> hassette.app.utils
    from hassette.app import App


def get_app_config_class(cls: type["App"]) -> type[AppConfig]:
    """Get the AppConfig type from an App subclass.

    This function retrieves the AppConfig type from the class's __orig_bases__ attribute.
    If no type is found, it returns the default class type of AppConfig.

    Args:
        cls: The subclass of App to inspect.

    Returns:
        The subclass of AppConfig for this app.

    Note:
        The config class is read from `__orig_bases__`, so `App[MyConfig]` needs no separate class variable that
        could disagree with it.
    """
    # house-lint: ignore-next[HSL002] - cycle: app.app -> config -> config.config -> utils.app_utils -> app.utils
    from hassette.app.app import App  # noqa: PLC0415

    for base in getattr(cls, "__orig_bases__", ()):
        origin = typing.get_origin(base)
        if not origin or not issubclass(origin, App):
            continue

        for arg in getattr(base, "__args__", ()):
            if isinstance(arg, type) and issubclass(arg, AppConfig):
                return arg

    # no AppConfig subclass found; fall back to the default
    return AppConfig


def validate_app(cls: type["App"]) -> type[AppConfig]:
    """Check the App subclass's `__init__` inheritance order and return its AppConfig class.

    Args:
        cls: The subclass of App to validate.

    Returns:
        The AppConfig of the subclass.

    Raises:
        InvalidInheritanceError: If the inheritance order is incorrect.
    """
    validate_init_method(cls)

    return get_app_config_class(cls)


def validate_init_method(cls: type["App"]) -> None:
    """Validate the __init__ method of an App subclass.

    This function checks the method resolution order (MRO) of the class to ensure that
    App is the first class in the MRO that defines an __init__ method. If not, it raises
    an InvalidInheritanceError.

    Args:
        cls: The subclass of App to validate.

    Raises:
        InvalidInheritanceError: If the inheritance order is incorrect, meaning that a subclass
        of App overrides the __init__ method before App itself.

    Note:
        A class listed before App (e.g. Pydantic's `BaseModel`) that defines `__init__` would shadow
        `App.__init__`, which `AppHandler` can't handle.
    """
    # house-lint: ignore-next[HSL002] - cycle: app.app -> config -> config.config -> utils.app_utils -> app.utils
    from hassette.app.app import App  # noqa: PLC0415

    if cls.__module__.startswith("hassette."):
        return

    mro = cls.mro()
    app_index = next(i for i, base in enumerate(mro) if i != 0 and issubclass(base, App))

    # the subclass defines its own __init__, so nothing earlier in the MRO can shadow App's
    if "__init__" in mro[0].__dict__:
        return

    for base in mro[1:app_index]:
        if "__init__" not in base.__dict__:
            continue

        if issubclass(base, App):
            return

        raise InvalidInheritanceError(
            f"{cls.__name__} inherits from {base.__name__} before App. "
            f"This causes {base.__name__}.__init__ to override App.__init__. "
            f"Put App before {base.__name__} in the base class list."
        )
