from __future__ import annotations

from app.models import VenueSummary
from app.models.enums import VenueStatusEnum
from app.repos.base import RepoBase
from app.repos.mappers import to_venue_summary

CLIENT_VISIBLE_STATUSES: list[str] = [VenueStatusEnum.LIVE.value, VenueStatusEnum.UNVERIFIED.value]


class VenueRepo(RepoBase):
    """Repository for the curated ``venues/{venueId}`` collection.

    Backs the ``GET /venues?sport=&area=`` endpoint and any league-side
    venue picker. The collection is a thin, manually seeded list (15–20
    Athens venues for MVP); any non-curated venue is resolved via Google
    Places and represented as a :class:`app.models.common.VenueRef`.
    """

    COLLECTION = "venues"

    def get_by_id(self, venue_id: str) -> VenueSummary | None:
        """Fetch a single curated venue by its Firestore document ID.

        Intentionally unfiltered by ``status`` — this is a direct/internal
        lookup (e.g. resolving a stored ``venue_id`` reference), not a
        client-facing discovery query, so ``hidden``/``unverified`` venues
        are still resolvable here.
        """
        doc = self.client.collection(self.COLLECTION).document(venue_id).get()
        data = self._doc_to_dict(doc)
        if data is None:
            return None
        return to_venue_summary(data, venue_id=venue_id)

    def list_by_sport_and_area(
        self,
        sport: str,
        area: str | None = None,
        limit: int = 20,
        cursor: dict | None = None,
    ) -> list[VenueSummary]:
        """List curated venues that support ``sport``, optionally filtered by ``area``.

        ``sport`` is matched via ``array_contains`` against the venue's
        ``sports`` array. ``area`` (when provided) is matched as an exact
        string on the ``area`` field. Only ``live``/``unverified`` venues are
        returned — ``hidden`` venues (not-yet-launched regions) are excluded.
        Results are ordered by ``name`` for stable pagination.
        """
        query = self.client.collection(self.COLLECTION).where("sports", "array_contains", sport)
        if area is not None:
            query = query.where("area", "==", area)
        query = query.where("status", "in", CLIENT_VISIBLE_STATUSES)
        query = query.order_by("name").limit(limit)
        if cursor and cursor.get("name"):
            query = query.start_after([cursor["name"]])
        return [to_venue_summary(doc.to_dict() or {}, venue_id=doc.id) for doc in query.stream()]

    def search_by_name_prefix(self, prefix: str, limit: int = 10) -> list[VenueSummary]:
        """Return curated venues whose ``name`` starts with ``prefix`` (case-sensitive).

        Uses the Firestore ``>=`` / ``<`` range trick on the ``name`` field
        to approximate a prefix search. Only ``live``/``unverified`` venues
        are returned. Limited to ``limit`` results.
        """
        upper = prefix[:-1] + chr(ord(prefix[-1]) + 1) if prefix else ""
        query = (
            self.client.collection(self.COLLECTION)
            .where("name", ">=", prefix)
            .where("name", "<", upper)
            .where("status", "in", CLIENT_VISIBLE_STATUSES)
            .order_by("name")
            .limit(limit)
        )
        return [to_venue_summary(doc.to_dict() or {}, venue_id=doc.id) for doc in query.stream()]
