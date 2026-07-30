"""Internal event metadata helpers for framework coordination."""


def stamp_websocket_generation(event: object, generation: int | None) -> None:
    object.__setattr__(event, "websocket_generation", generation)


def get_websocket_generation(event: object) -> int | None:
    generation = getattr(event, "websocket_generation", None)
    return generation if isinstance(generation, int) else None
