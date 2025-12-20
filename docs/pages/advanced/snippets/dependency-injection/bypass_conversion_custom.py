from typing import Annotated, Any

from hassette import accessors as A
from hassette.dependencies.annotations import AnnotationDetails


def my_converter(value: Any, to_type: type) -> int:
    # Your custom conversion logic
    return int(value) * 100


BrightnessPercent = Annotated[
    int,
    AnnotationDetails(
        extractor=A.get_attr_new("brightness"),
        converter=my_converter,
    ),
]
