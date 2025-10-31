import typing

from .base import BaseEntity
from .light import LightEntity

EntityT = typing.TypeVar("EntityT")
"""Represents a specific entity type, e.g., LightEntity, SensorEntity, etc."""


__all__ = ["BaseEntity", "EntityT", "LightEntity"]
