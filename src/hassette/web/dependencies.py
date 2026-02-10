"""FastAPI dependency injection helpers for the Hassette Web API."""

import typing

from fastapi import Request

if typing.TYPE_CHECKING:
    from hassette import Hassette
    from hassette.api import Api
    from hassette.core.data_sync_service import DataSyncService


def get_hassette(request: Request) -> "Hassette":
    return request.app.state.hassette


def get_data_sync(request: Request) -> "DataSyncService":
    return request.app.state.hassette._data_sync_service


def get_api(request: Request) -> "Api":
    return request.app.state.hassette.api
