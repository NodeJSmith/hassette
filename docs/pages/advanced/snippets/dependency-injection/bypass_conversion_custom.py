from typing import Annotated, Any

from hassette import accessors as A
from hassette.event_handling.dependencies import AnnotationDetails


def my_converter(value: Any, _: type) -> int | None:
    if value is None:
        return None
    return int(value) * 100


BrightnessPercent = Annotated[
    int,
    AnnotationDetails(
        extractor=A.get_attr_new("brightness"),
        converter=my_converter,
    ),
]
