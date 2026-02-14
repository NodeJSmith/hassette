"""FastAPI dependency injection helpers for the Hassette Web API."""

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, Request

if TYPE_CHECKING:
    from hassette import Hassette
    from hassette.api import Api
    from hassette.core.data_sync_service import DataSyncService


def get_hassette(request: Request) -> "Hassette":
    return request.app.state.hassette


def get_data_sync(request: Request) -> "DataSyncService":
    return request.app.state.hassette.data_sync_service


def get_api(request: Request) -> "Api":
    return request.app.state.hassette.api


# Shared dependency type aliases — import these instead of re-defining locally.
HassetteDep = Annotated["Hassette", Depends(get_hassette)]
DataSyncDep = Annotated["DataSyncService", Depends(get_data_sync)]
ApiDep = Annotated["Api", Depends(get_api)]
