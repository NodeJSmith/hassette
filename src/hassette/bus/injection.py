"""Parameter injection for event handlers with dependency injection support."""

import inspect
from collections.abc import Callable
from logging import getLogger
from typing import Any

from hassette.conversion import ANNOTATION_CONVERTER, TYPE_MATCHER
from hassette.di import AnnotatedMatcher, CallableInvoker, TypeMatcher, build_injection_plan
from hassette.events import Event
from hassette.exceptions import DependencyError, DependencyInjectionError, DependencyResolutionError
from hassette.utils.func_utils import callable_short_name
from hassette.utils.type_utils import get_pretty_actual_type_from_value, is_optional, normalize_annotation

LOGGER = getLogger(__name__)


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

        try:
            plan = build_injection_plan(signature, [AnnotatedMatcher(source_type=Event), TypeMatcher(Event)])
        except Exception as e:
            raise DependencyInjectionError(
                f"Handler '{handler_name}' has invalid signature for dependency injection: {e}"
            ) from e

        self.invoker = CallableInvoker(plan)
        self.conversion_map = {param.name: (param.target_type, param.converter) for param in plan}

    def inject_parameters(self, event: Event[Any], **kwargs: Any) -> dict[str, Any]:
        """Extract and inject parameters from event into kwargs.

        Args:
            event: The event to extract parameters from.
            **kwargs: Existing keyword arguments (will be updated, not replaced).

        Returns:
            Updated kwargs dictionary with injected parameters.

        Raises:
            DependencyResolutionError: If parameter extraction or conversion fails.
        """
        available: dict[type, Any] = {Event: event}

        for param in self.invoker.params:
            if param.name in kwargs:
                LOGGER.warning(
                    "Handler '%s' - parameter '%s' provided in kwargs will be overridden by DI",
                    self.handler_name,
                    param.name,
                )

            try:
                raw_value = param.extractor(available[param.source_type])
                target_type, converter = self.conversion_map[param.name]
                kwargs[param.name] = self.extract_and_convert_parameter(
                    param.name,
                    raw_value,
                    target_type,
                    converter,
                )
            except DependencyError:
                raise
            except Exception as e:
                LOGGER.error(
                    "Handler '%s' - unexpected error extracting parameter '%s': %s",
                    self.handler_name,
                    param.name,
                    e,
                )
                raise DependencyResolutionError(
                    f"Handler '{self.handler_name}' - failed to extract parameter '{param.name}': {e}"
                ) from e

        return kwargs

    def extract_and_convert_parameter(
        self,
        param_name: str,
        raw_value: Any,
        param_type: Any,
        converter: Callable[[Any, Any], Any] | None = None,
    ) -> Any:
        actual_type = get_pretty_actual_type_from_value(raw_value)

        normalized = normalize_annotation(param_type, constructible=True)
        if raw_value is None and is_optional(normalized):
            return None

        effective_converter = converter or ANNOTATION_CONVERTER.convert
        converter_name = callable_short_name(effective_converter, 2)

        if TYPE_MATCHER.matches(raw_value, normalized):
            LOGGER.debug(
                "Handler '%s' - skipping conversion for parameter '%s' (already matches '%s')",
                self.handler_name,
                param_name,
                normalized,
            )
            return raw_value

        try:
            return effective_converter(raw_value, param_type)
        except Exception as e:
            raise DependencyResolutionError(
                f"Handler '{self.handler_name}' - failed to convert parameter '{param_name}' "
                f"of type '{actual_type}' to '{param_type}' "
                f"using converter {converter_name}: {type(e).__name__}: {e}"
            ) from e
