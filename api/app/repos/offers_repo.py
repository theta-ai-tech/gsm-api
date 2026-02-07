from __future__ import annotations

from typing import Optional

from app.models.enums import OfferStatusEnum
from app.models.play import Offer
from app.repos.base import RepoBase
from app.repos.mappers import to_offer


class OffersRepo(RepoBase):
    """Repository for offers collection (Tab 1 challenge offers)."""

    def get_by_id(self, offer_id: str) -> Optional[Offer]:
        """Get a single offer by ID."""
        doc = self.client.collection("offers").document(offer_id).get()
        data = self._doc_to_dict(doc)
        if data is None:
            return None
        return to_offer(data, offer_id=offer_id)

    def get_by_ids(self, offer_ids: list[str]) -> list[Offer]:
        """
        Batch get multiple offers by IDs.

        Args:
            offer_ids: List of offer document IDs

        Returns:
            List of Offer objects (skips non-existent docs)
        """
        if not offer_ids:
            return []

        # Firestore batch get
        doc_refs = [self.client.collection("offers").document(oid) for oid in offer_ids]
        docs = self.client.get_all(doc_refs)

        offers = []
        for doc in docs:
            if doc.exists:
                offers.append(to_offer(doc.to_dict() or {}, offer_id=doc.id))
        return offers

    def get_active_outgoing(self, from_uid: str) -> Optional[Offer]:
        """Get the active outgoing offer for a user (if any)."""
        docs = (
            self.client.collection("offers")
            .where("fromUid", "==", from_uid)
            .where("status", "==", "pending")
            .limit(1)
            .stream()
        )
        for doc in docs:
            return to_offer(doc.to_dict() or {}, offer_id=doc.id)
        return None

    def get_pending_for_user(self, to_uid: str) -> list[Offer]:
        """Get all pending incoming offers for a user."""
        docs = (
            self.client.collection("offers")
            .where("toUid", "==", to_uid)
            .where("status", "==", "pending")
            .stream()
        )
        return [to_offer(doc.to_dict() or {}, offer_id=doc.id) for doc in docs]

    def create(self, offer_data: dict) -> str:
        """
        Create a new offer document.

        Args:
            offer_data: Firestore-formatted dict (camelCase fields)

        Returns:
            The created offer ID
        """
        doc_ref = self.client.collection("offers").document()
        doc_ref.set(offer_data)
        return doc_ref.id

    def update_status(
        self, offer_id: str, status: OfferStatusEnum, match_id: str | None = None
    ) -> None:
        """
        Update the status of an offer (e.g., pending → accepted/declined/expired/cancelled).

        Args:
            offer_id: Offer document ID
            status: New status
            match_id: Optional match ID (set when status=accepted)
        """
        update_data = {"status": status.value}
        if match_id:
            update_data["matchId"] = match_id
        self.client.collection("offers").document(offer_id).update(update_data)

    def batch_update_status(self, offer_ids: list[str], status: OfferStatusEnum) -> None:
        """
        Batch update status for multiple offers (e.g., decline all pending offers).

        Args:
            offer_ids: List of offer document IDs
            status: New status to set for all
        """
        if not offer_ids:
            return

        batch = self.client.batch()
        for offer_id in offer_ids:
            doc_ref = self.client.collection("offers").document(offer_id)
            batch.update(doc_ref, {"status": status.value})
        batch.commit()

    def delete(self, offer_id: str) -> None:
        """Delete an offer document (if needed for cleanup)."""
        self.client.collection("offers").document(offer_id).delete()
