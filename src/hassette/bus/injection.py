"""Parameter injection for event handlers with dependency injection support."""

import inspect
import logging
import typing
from collections.abc import Callable
from types import UnionType
from typing import Any, get_args, get_origin

from hassette.core.type_registry import TYPE_REGISTRY
from hassette.exceptions import DependencyError, DependencyInjectionError, DependencyResolutionError
from hassette.utils.type_utils import get_optional_type_arg, is_optional_type, normalize_for_isinstance

from .extraction import extract_from_signature, validate_di_signature

if typing.TYPE_CHECKING:
    from hassette.events import Event

LOGGER = logging.getLogger(__name__)


class ParameterInjector:
    """Handles dependency injection for event handler parameters.

    This class uses parameter annotation details extracted from a handler's signature
    to extract and convert parameters from events, returning a dictionary of injected parameters.
    """

    def __init__(self, handler_name: str, signature: inspect.Signature):
        """Initialize the parameter injector.

        Args:
            handler_name: Name of the handler function for error messages.
            signature: The handler's signature.

        Raises:
            DependencyInjectionError: If the signature is invalid for DI.
        """
        self.handler_name = handler_name
        self.signature = signature

        # Validate signature once during initialization
        try:
            validate_di_signature(signature)
            self.param_details = extract_from_signature(signature)
        except Exception as e:
            raise DependencyInjectionError(
                f"Handler '{handler_name}' has invalid signature for dependency injection: {e}"
            ) from e

    def inject_parameters(self, event: "Event[Any]", **kwargs: Any) -> dict[str, Any]:
        """Extract and inject parameters from event into kwargs.

        Args:
            event: The event to extract parameters from.
            **kwargs: Existing keyword arguments (will be updated, not replaced).

        Returns:
            Updated kwargs dictionary with injected parameters.

        Raises:
            DependencyResolutionError: If parameter extraction or conversion fails.
        """
        for param_name, (param_type, annotation_details) in self.param_details.items():
            if param_name in kwargs:
                LOGGER.warning(
                    "Handler '%s' - parameter '%s' provided in kwargs will be overridden by DI",
                    self.handler_name,
                    param_name,
                )

            try:
                kwargs[param_name] = self._extract_and_convert_parameter(
                    event,
                    param_name,
                    param_type,
                    annotation_details.extractor,
                    annotation_details.converter,
                )
            except DependencyError:
                # Already formatted, just re-raise
                raise
            except Exception as e:
                # Unexpected error - wrap it
                LOGGER.error(
                    "Handler '%s' - unexpected error extracting parameter '%s': %s",
                    self.handler_name,
                    param_name,
                    e,
                )
                raise DependencyResolutionError(
                    f"Handler '{self.handler_name}' - failed to extract parameter '{param_name}': {e}"
                ) from e

        return kwargs

    def _extract_and_convert_parameter(
        self,
        event: "Event[Any]",
        param_name: str,
        param_type: type,
        extractor: Callable[[Any], Any],
        converter: Callable[[Any, type], Any] | None = None,
    ) -> Any:
        """Extract and convert a single parameter value.

        Args:
            event: The event to extract from.
            param_name: Name of the parameter.
            param_type: Expected type of the parameter.
            extractor: Callable to extract the value from the event.
            converter: Optional callable to convert the extracted value to the target type.

        Returns:
            The extracted and converted parameter value.

        Raises:
            DependencyResolutionError: If extraction or conversion fails.
        """
        # Extract the value
        try:
            extracted_value = extractor(event)
            extracted_type = type(extracted_value)
        except Exception as e:
            raise DependencyResolutionError(
                f"Handler '{self.handler_name}' - failed to extract parameter '{param_name}' "
                f"of type '{param_type}': {e}"
            ) from e

        # Handle None for optional parameters
        param_is_optional = is_optional_type(param_type)
        if param_is_optional and extracted_value is None:
            return None

        # Get target type (unwrap Optional if needed)
        target_type = get_optional_type_arg(param_type) if param_is_optional else param_type

        if not converter:
            if not self._needs_conversion(extracted_value, target_type):
                LOGGER.debug(
                    "Handler '%s' - skipping conversion for parameter '%s' of type '%s'",
                    self.handler_name,
                    param_name,
                    target_type,
                )
                return extracted_value

            # use TypeRegistry if no converter provided
            converter = TYPE_REGISTRY.convert

        # Convert if converter exists
        if type(target_type) is UnionType:
            exception_strings = []
            last_idx = len(get_args(target_type)) - 1
            for idx, t in enumerate(get_args(target_type)):
                try:
                    return self._convert_value(converter, extracted_value, param_name, t, extracted_type)
                except Exception as e:
                    exception_strings.append(str(e))
                    if idx == last_idx:
                        formatted_exceptions = "\n" + "; ".join(exception_strings)
                        raise DependencyResolutionError(
                            f"Handler '{self.handler_name}' - failed to convert parameter '{param_name}' "
                            f"of type '{extracted_type}' "
                            f"to any type in Union '{target_type}': {formatted_exceptions}"
                        ) from None

        # not a union type
        return self._convert_value(converter, extracted_value, param_name, target_type, extracted_type)

    def _needs_conversion(self, extracted_value: Any, target_type: type) -> bool:
        """Check if a value needs conversion to the target type."""
        try:
            norm_tt = normalize_for_isinstance(target_type)
            return not isinstance(extracted_value, norm_tt)
        except TypeError:
            origin = get_origin(target_type)
            return isinstance(origin, type) and not isinstance(extracted_value, origin)

    def _convert_value(
        self,
        converter: Callable[[Any, type], Any],
        extracted_value: Any,
        param_name: str,
        target_type: type,
        extracted_type: type,
    ) -> Any:
        """Convert a value to the target type using the converter.

        Args:
            value: The value to convert.
            target_type: The type to convert to.

        Returns:
            The converted value.

        Raises:
            DependencyResolutionError: If conversion fails.
        """
        try:
            return converter(extracted_value, target_type)
        except Exception as e:
            raise DependencyResolutionError(
                f"Handler '{self.handler_name}' - failed to convert parameter '{param_name}' "
                f"of type '{extracted_type.__name__}' "
                f"to type '{target_type.__name__}': {e}"
            ) from e
