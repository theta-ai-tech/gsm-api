from __future__ import annotations

from datetime import datetime, timezone

from app.models import CreateVenueSuggestionRequest
from app.repos.base import RepoBase


class VenueSuggestionsRepo(RepoBase):
    """Repository for the ``venueSuggestions/{autoId}`` moderation queue.

    User-submitted venue suggestions are written here (NOT to the live
    ``venues`` collection). A human moderator reviews each pending entry
    before it is promoted to the curated ``venues`` collection.
    """

    COLLECTION = "venueSuggestions"
    DEFAULT_STATUS = "pending"

    def create(self, uid: str, request: CreateVenueSuggestionRequest) -> str:
        """Create a new venue suggestion document.

        Args:
            uid: Firebase UID of the suggesting user.
            request: Validated request payload.

        Returns:
            The auto-generated Firestore document ID.
        """
        doc_ref = self.client.collection(self.COLLECTION).document()
        doc_ref.set(
            {
                "name": request.name,
                "coordinates": {
                    "lat": request.coordinates.lat,
                    "lng": request.coordinates.lng,
                },
                "sport": request.sport.value,
                "notes": request.notes,
                "suggestedBy": uid,
                "createdAt": datetime.now(timezone.utc),
                "status": self.DEFAULT_STATUS,
            }
        )
        return doc_ref.id
