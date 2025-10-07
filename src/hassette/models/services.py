from pydantic import BaseModel, Field

from hassette.models.states.base import Context


class ServiceResponse(BaseModel):
    """Represents the response from a service call."""

    context: Context
    response: dict = Field(default_factory=dict)
