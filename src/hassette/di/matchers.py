"""Built-in `ParameterMatcher` implementations.

`TypeMatcher` matches bare type annotations (including subclasses). `AnnotatedMatcher`
matches `Annotated[T, metadata]` annotations, absorbing the extraction logic that used to
live in `bus/extraction.py:extract_from_annotated`.
"""

import inspect
import types
import typing
from dataclasses import dataclass
from typing import get_args, get_origin
from warnings import warn

from hassette.utils.type_utils import get_type_and_details, is_annotated_type, normalize_annotation

from .types import AnnotationDetails, InjectionParam, identity


@dataclass(frozen=True, slots=True)
class TypeMatcher:
    """Matches parameters whose (unwrapped) annotation is `match_type` or a subclass of it.

    Parameterized generics (e.g. `Event[Any]`) are unwrapped to their origin before the
    subclass check, matching the behavior of `hassette.events.type_checks.is_event_type`.
    """

    match_type: type

    def match(self, param: inspect.Parameter) -> InjectionParam | None:
        annotation = param.annotation
        if annotation is inspect.Parameter.empty:
            return None

        origin = get_origin(annotation)
        base_type = origin or annotation

        matched = inspect.isclass(base_type) and issubclass(base_type, self.match_type)
        if not matched and (origin is types.UnionType or origin is typing.Union):
            args = get_args(annotation)
            matched = any(inspect.isclass(arg) and issubclass(arg, self.match_type) for arg in args)

        if not matched:
            return None

        return InjectionParam(
            name=param.name,
            source_type=self.match_type,
            target_type=annotation,
            extractor=identity,
        )


@dataclass(frozen=True, slots=True)
class AnnotatedMatcher:
    """Matches `Annotated[T, metadata]` parameters.

    `metadata` may be an `AnnotationDetails` instance or a bare callable extractor - bare
    callables are auto-wrapped into `AnnotationDetails(extractor=metadata)`. Any other
    metadata shape emits a warning and is treated as a non-match.
    """

    source_type: type

    def match(self, param: inspect.Parameter) -> InjectionParam | None:
        annotation = param.annotation
        if annotation is inspect.Parameter.empty:
            return None

        if not is_annotated_type(annotation):
            return None

        type_details = get_type_and_details(annotation)
        if type_details is None:
            return None

        inner_type, metadata = type_details

        if isinstance(metadata, AnnotationDetails):
            details = metadata
        elif callable(metadata):
            details = AnnotationDetails(extractor=metadata)
        else:
            warn(
                f"Invalid Annotated metadata: {metadata} is not AnnotationDetails or callable extractor",
                stacklevel=2,
            )
            return None

        target_type = normalize_annotation(inner_type)

        return InjectionParam(
            name=param.name,
            source_type=details.source_type or self.source_type,
            target_type=target_type,
            extractor=details.extractor,
            converter=details.converter,
        )


__all__ = ["AnnotatedMatcher", "TypeMatcher"]
