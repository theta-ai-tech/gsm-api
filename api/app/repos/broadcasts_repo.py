from __future__ import annotations

from typing import Optional

from app.models.enums import BroadcastStatusEnum, MatchTypeEnum
from app.models.play import Broadcast
from app.repos.base import RepoBase
from app.repos.mappers import to_broadcast


class BroadcastsRepo(RepoBase):
    """Repository for broadcasts collection (Tab 1 availability announcements)."""

    def get_by_id(self, broadcast_id: str) -> Optional[Broadcast]:
        """Get a single broadcast by ID."""
        doc = self.client.collection("broadcasts").document(broadcast_id).get()
        data = self._doc_to_dict(doc)
        if data is None:
            return None
        return to_broadcast(data, broadcast_id=broadcast_id)

    def get_active_by_owner(self, owner_uid: str) -> Optional[Broadcast]:
        """Get the active broadcast for a user (if any)."""
        docs = (
            self.client.collection("broadcasts")
            .where("ownerUid", "==", owner_uid)
            .where("status", "==", "active")
            .limit(1)
            .stream()
        )
        for doc in docs:
            return to_broadcast(doc.to_dict() or {}, broadcast_id=doc.id)
        return None

    def list_active(
        self,
        sport: str | None = None,
        match_type: MatchTypeEnum | None = None,
        limit: int = 25,
    ) -> list[Broadcast]:
        """List active broadcasts ordered by createdAt desc.

        Applies an optional matchType filter. When match_type is provided a
        composite Firestore index on (status, matchType, createdAt) is required.
        """
        query = (
            self.client.collection("broadcasts")
            .where("status", "==", "active")
            .order_by("createdAt", direction="DESCENDING")
        )
        if match_type is not None:
            query = query.where("matchType", "==", match_type.value)
        if sport is not None:
            query = query.where("sport", "==", sport)
        query = query.limit(limit)
        results: list[Broadcast] = []
        for doc in query.stream():
            results.append(to_broadcast(doc.to_dict() or {}, broadcast_id=doc.id))
        return results

    def create(self, broadcast_data: dict) -> str:
        """
        Create a new broadcast document.

        Args:
            broadcast_data: Firestore-formatted dict (camelCase fields)

        Returns:
            The created broadcast ID
        """
        doc_ref = self.client.collection("broadcasts").document()
        doc_ref.set(broadcast_data)
        return doc_ref.id

    def update_status(self, broadcast_id: str, status: BroadcastStatusEnum) -> None:
        """Update the status of a broadcast (e.g., active → cancelled/expired/matched)."""
        self.client.collection("broadcasts").document(broadcast_id).update({"status": status.value})

    def delete(self, broadcast_id: str) -> None:
        """Delete a broadcast document (if needed for cleanup)."""
        self.client.collection("broadcasts").document(broadcast_id).delete()
