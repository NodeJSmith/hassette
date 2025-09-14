import typing
from logging import getLogger

from hassette.exceptions import InvalidInheritanceError

from .app_config import AppConfig

if typing.TYPE_CHECKING:
    from hassette.core.apps import App, AppConfigT


LOGGER = getLogger(__name__)


def _get_app_config_class(cls: type["App"]) -> type[AppConfig]:
    """Get the AppConfig type from a App subclass.

    This function retrieves the AppConfig type from the class's __orig_bases__ attribute.
    If no type is found, it returns the default class type of AppConfig.

    Args:
        cls (type[App]): The subclass of App to inspect.

    Returns:
        type[AppConfig]: The subclass of AppConfig for this app.

    Note:
        This is my best attempt (so far) at making App generic so that it can be strongly typed\
        with a user defined Config class, without having to also set a class variable manually, which\
        would allow for mistakes. If a future user/developer has a better idea, please let me know!
    """
    # avoid circular import
    from hassette.core.apps.app import App

    args = ()
    for base in getattr(cls, "__orig_bases__", ()):
        # get the origin to confirm it's a App subclass
        origin = typing.get_origin(base)
        if not origin or not issubclass(origin, App):
            continue

        # if we have a generic type, get the first argument, as long as it's not a TypeVar
        args = getattr(base, "__args__", ())
        if args and not isinstance(args[0], typing.TypeVar):
            break

    # if we haven't found a user_config_class, we'll just return the default
    pydantic_model_args = [arg for arg in args if isinstance(arg, type) and issubclass(arg, AppConfig)]
    if not pydantic_model_args:
        return AppConfig

    return pydantic_model_args[0]


def validate_app(cls: type["App"]) -> type[AppConfig]:
    """Validate the AppConfig class of a App subclass.

    Args:
        cls (type[App]): The subclass of App to validate.

    Returns:
        type[AppConfig]: The AppConfig of the subclass.

    Raises:
        InvalidInheritanceError: If the inheritance order is incorrect.
    """

    LOGGER.debug("Initializing subclass %s", cls.__name__)

    _validate_init_method(cls)

    app_config_cls = _get_app_config_class(cls)

    return app_config_cls


def _validate_init_method(cls: type["App[AppConfigT]"]) -> None:
    """Validate the __init__ method of a App subclass.

    This function checks the method resolution order (MRO) of the class to ensure that
    App is the first class in the MRO that defines an __init__ method. If not, it raises
    an InvalidInheritanceError.

    Args:
        cls (type[App[AppConfigT]]): The subclass of App to validate.

    Raises:
        InvalidInheritanceError: If the inheritance order is incorrect, meaning that a subclass
        of App overrides the __init__ method before App itself.

    Note:
        This was added because if you not define your own __init__ method and you inherit from another class\
        before App, (e.g. Pydantic's BaseModel), it will be the __init__ method that gets called, which\
        `AppHandler` does not expect and will not be able to handle. Unsure if this will see much usage, but it\
        is a good safeguard to have.\
    """
    from hassette.core.apps.app import App  # avoid circular import

    if cls.__module__.startswith("hassette."):
        # skipping internal classes
        return

    LOGGER.debug("Validating __init__ method for %s", cls.__name__)

    mro = cls.mro()
    # get the first index in the MRO where App is found, excepting the first class
    hass_index = [i for i, base in enumerate(mro) if issubclass(base, App) and i != 0][0]
    LOGGER.debug("Found App at index %d in MRO for %s", hass_index, cls.__name__)

    # if the first class in the MRO declares an __init__ method, we can skip the rest
    # assumption: the first class in the MRO is App, so we can check it directly
    if "__init__" in mro[0].__dict__:
        LOGGER.debug("Found __init__ in base class %s", mro[0].__name__)
        return

    for base in mro[1:hass_index]:
        if "__init__" not in base.__dict__:
            continue

        if issubclass(base, App):
            LOGGER.debug("Found first __init__ in subclass of App: %s", base.__name__)
            return

        raise InvalidInheritanceError(
            f"{cls.__name__} inherits from {base.__name__} before App. "
            f"This causes {base.__name__}.__init__ to override App.__init__. "
            f"Put App before {base.__name__} in the base class list."
        )
