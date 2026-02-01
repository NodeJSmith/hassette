"""Parameter injection for event handlers with dependency injection support."""

import inspect
import logging
import typing
from collections.abc import Callable
from typing import Any

from hassette.conversion import ANNOTATION_CONVERTER, TYPE_MATCHER
from hassette.exceptions import DependencyError, DependencyInjectionError, DependencyResolutionError
from hassette.utils.func_utils import callable_short_name
from hassette.utils.type_utils import get_pretty_actual_type_from_value, is_optional, normalize_annotation

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
        param_type: Any,
        extractor: Callable[[Any], Any],
        converter: Callable[[Any, Any], Any] | None = None,
    ) -> Any:
        try:
            extracted_value = extractor(event)
        except Exception as e:
            raise DependencyResolutionError(
                f"Handler '{self.handler_name}' - failed to extract parameter '{param_name}' "
                f"of type '{param_type}': {e}"
            ) from e

        actual_type = get_pretty_actual_type_from_value(extracted_value)

        normalized = normalize_annotation(param_type, constructible=True)
        if extracted_value is None and is_optional(normalized):
            return None

        # If caller didn't provide a custom converter, use the annotation-aware one
        conv = converter or ANNOTATION_CONVERTER.convert
        conv_name = callable_short_name(conv, 2)

        # Fast path: if it already matches (deep), skip conversion
        if TYPE_MATCHER.matches(extracted_value, normalized):
            LOGGER.debug(
                "Handler '%s' - skipping conversion for parameter '%s' (already matches '%s')",
                self.handler_name,
                param_name,
                normalized,
            )
            return extracted_value

        # Convert (converter handles union/nested/etc. if using ANNOTATION_CONVERTER)
        try:
            return conv(extracted_value, param_type)
        except Exception as e:
            raise DependencyResolutionError(
                f"Handler '{self.handler_name}' - failed to convert parameter '{param_name}' "
                f"of type '{actual_type}' to '{param_type}' "
                f"using converter {conv_name} "
                f": {type(e).__name__}: {e}"
            ) from e

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
