from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from app.models.base import GsmBaseModel
from app.models.common import GeoCoordinates
from app.models.enums import SportEnum


class CreateVenueSuggestionRequest(GsmBaseModel):
    """Request body for ``POST /venues/suggest``.

    Captures a user-submitted venue that is queued for moderation in the
    ``venueSuggestions/{autoId}`` collection. Suggestions are NOT written to
    the live ``venues`` collection.
    """

    name: str = Field(min_length=1, max_length=200)
    coordinates: GeoCoordinates
    sport: SportEnum
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("name", mode="before")
    @classmethod
    def _strip_and_validate_name(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        stripped = value.strip()
        if not stripped:
            msg = "name must not be blank"
            raise ValueError(msg)
        return stripped


class CreateVenueSuggestionResponse(GsmBaseModel):
    """Response body for ``POST /venues/suggest``."""

    suggestion_id: str = Field(alias="suggestionId")
