from __future__ import annotations

from pydantic import Field

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


class CreateVenueSuggestionResponse(GsmBaseModel):
    """Response body for ``POST /venues/suggest``."""

    suggestion_id: str = Field(alias="suggestionId")
