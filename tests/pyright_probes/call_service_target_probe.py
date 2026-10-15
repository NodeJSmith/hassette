"""Pyright probe proving ``call_service`` accepts a ``target`` mixing single IDs and lists (#2831)."""

# ruff: noqa
# pyright: basic

from hassette.api.api import Api
from hassette.testing.recording_api import RecordingApi


async def probe_mixed_target(api: Api, recording: RecordingApi) -> None:
    mixed = {"entity_id": "light.porch", "area_id": ["kitchen", "hall"]}
    single_shape: dict[str, str] = {"entity_id": "light.porch"}
    list_shape: dict[str, list[str]] = {"area_id": ["kitchen", "hall"]}

    for target in (mixed, single_shape, list_shape):
        await api.call_service("light", "turn_on", target=target)
        await recording.call_service("light", "turn_on", target=target)

    await api.call_service("light", "turn_on", target={"entity_id": "light.porch", "area_id": ["kitchen", "hall"]})
    await recording.call_service(
        "light", "turn_on", target={"entity_id": "light.porch", "area_id": ["kitchen", "hall"]}
    )
