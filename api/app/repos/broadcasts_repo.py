from __future__ import annotations

from typing import Optional

from app.models.enums import BroadcastStatusEnum
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
