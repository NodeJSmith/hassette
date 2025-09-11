import typing
from dataclasses import dataclass

if typing.TYPE_CHECKING:
    from hassette.core.events import StateChangeEvent


@dataclass(frozen=True)
class DomainIs:
    domain: str

    def __call__(self, event: "StateChangeEvent") -> bool:
        data = event.payload

        return data.domain == self.domain

    def __repr__(self) -> str:
        return f"DomainIs(domain={self.domain!r})"


@dataclass(frozen=True)
class EntityIs:
    entity_id_wanted: str

    def __call__(self, event: "StateChangeEvent") -> bool:
        data = event.payload.data

        return data.entity_id == self.entity_id_wanted

    def __repr__(self) -> str:
        return f"EntityIs(entity_id_wanted={self.entity_id_wanted!r})"
