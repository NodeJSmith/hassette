import json
from dataclasses import dataclass

from hassette.core.type_registry import register_type_converter_fn


@dataclass
class DeviceInfo:
    name: str
    version: str
    manufacturer: str


@register_type_converter_fn
def str_to_device_info(value: str) -> DeviceInfo:
    """Parse device info JSON.

    Types inferred from signature: str → DeviceInfo
    """
    data = json.loads(value)
    return DeviceInfo(**data)
