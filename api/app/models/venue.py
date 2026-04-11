from __future__ import annotations

from app.models.base import GsmBaseModel
from app.models.common import GeoCoordinates
from app.models.enums import SportEnum


class VenueSummary(GsmBaseModel):
    """Curated venue document from the ``venues/{venueId}`` collection.

    Represents the thin seed list of manually curated venues (15–20 Athens
    sports clubs for MVP) that power the league venue picker and ``GET
    /venues?sport=&area=`` endpoint. Non-curated venues resolved via Google
    Places are represented by :class:`app.models.common.VenueRef` instead.
    """

    venue_id: str
    name: str
    coordinates: GeoCoordinates
    area: str
    sports: list[SportEnum]
    court_count: int | None = None
    indoor: bool | None = None
    place_id: str | None = None
