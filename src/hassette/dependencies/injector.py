"""Parameter injection for event handlers with dependency injection support."""

import inspect
import logging
import typing
from typing import Any

from hassette.exceptions import DependencyError, DependencyInjectionError, DependencyResolutionError
from hassette.utils.type_utils import get_optional_type_arg, is_optional_type

from .extraction import AnnotationDetails, extract_from_signature, validate_di_signature

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
                    event, param_name, param_type, annotation_details
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
        self, event: "Event[Any]", param_name: str, param_type: type, annotation_details: AnnotationDetails
    ) -> Any:
        """Extract and convert a single parameter value.

        Args:
            event: The event to extract from.
            param_name: Name of the parameter.
            param_type: Expected type of the parameter.
            annotation_details: AnnotationDetails containing extractor and converter.

        Returns:
            The extracted and converted parameter value.

        Raises:
            DependencyResolutionError: If extraction or conversion fails.
        """
        extractor = annotation_details.extractor
        converter = annotation_details.converter

        # Extract the value
        try:
            extracted_value = extractor(event)
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

        # Convert if converter exists
        if converter:
            try:
                extracted_value = converter(extracted_value, target_type)
            except Exception as e:
                raise DependencyResolutionError(
                    f"Handler '{self.handler_name}' - failed to convert parameter '{param_name}' "
                    f"to type '{target_type}': {e}"
                ) from e

        return extracted_value
