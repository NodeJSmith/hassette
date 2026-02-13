"""Entity state endpoints."""

from fastapi import APIRouter, HTTPException

from hassette.web.dependencies import DataSyncDep
from hassette.web.models import EntityListResponse, EntityStateResponse

router = APIRouter(tags=["entities"])


@router.get("/entities", response_model=EntityListResponse)
async def get_all_entities(data_sync: DataSyncDep) -> EntityListResponse:
    states = data_sync.get_all_entity_states()
    entities = [
        EntityStateResponse(
            entity_id=eid,
            state=s.get("state", ""),
            attributes=s.get("attributes", {}),
            last_changed=s.get("last_changed"),
            last_updated=s.get("last_updated"),
        )
        for eid, s in states.items()
    ]
    return EntityListResponse(count=len(entities), entities=entities)


@router.get("/entities/domain/{domain}", response_model=EntityListResponse)
async def get_domain_entities(domain: str, data_sync: DataSyncDep) -> EntityListResponse:
    states = data_sync.get_domain_states(domain)
    entities = [
        EntityStateResponse(
            entity_id=eid,
            state=s.get("state", ""),
            attributes=s.get("attributes", {}),
            last_changed=s.get("last_changed"),
            last_updated=s.get("last_updated"),
        )
        for eid, s in states.items()
    ]
    return EntityListResponse(count=len(entities), entities=entities)


@router.get("/entities/{entity_id}", response_model=EntityStateResponse)
async def get_entity(entity_id: str, data_sync: DataSyncDep) -> EntityStateResponse:
    state = data_sync.get_entity_state(entity_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Entity {entity_id} not found")
    return EntityStateResponse(
        entity_id=entity_id,
        state=state.get("state", ""),
        attributes=state.get("attributes", {}),
        last_changed=state.get("last_changed"),
        last_updated=state.get("last_updated"),
    )
