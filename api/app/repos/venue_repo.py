from __future__ import annotations

from typing import List, Optional

from app.models import VenueSummary
from app.repos.base import RepoBase
from app.repos.mappers import to_venue_summary


class VenueRepo(RepoBase):
    """Repository for the curated ``venues/{venueId}`` collection.

    Backs the ``GET /venues?sport=&area=`` endpoint and any league-side
    venue picker. The collection is a thin, manually seeded list (15–20
    Athens venues for MVP); any non-curated venue is resolved via Google
    Places and represented as a :class:`app.models.common.VenueRef`.
    """

    COLLECTION = "venues"

    def get_by_id(self, venue_id: str) -> Optional[VenueSummary]:
        """Fetch a single curated venue by its Firestore document ID."""
        doc = self.client.collection(self.COLLECTION).document(venue_id).get()
        data = self._doc_to_dict(doc)
        if data is None:
            return None
        return to_venue_summary(data, venue_id=venue_id)

    def list_by_sport_and_area(self, sport: str, area: str | None = None) -> List[VenueSummary]:
        """List curated venues that support ``sport``, optionally filtered by ``area``.

        ``sport`` is matched via ``array_contains`` against the venue's
        ``sports`` array. ``area`` (when provided) is matched as an exact
        string on the ``area`` field. Results are ordered by ``name`` for
        stable pagination.
        """
        query = self.client.collection(self.COLLECTION).where("sports", "array_contains", sport)
        if area is not None:
            query = query.where("area", "==", area)
        query = query.order_by("name")
        return [to_venue_summary(doc.to_dict() or {}, venue_id=doc.id) for doc in query.stream()]
