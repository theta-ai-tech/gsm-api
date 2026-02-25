from __future__ import annotations

from typing import List, Optional

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]
from google.cloud.firestore_v1.field_path import FieldPath  # type: ignore[attr-defined, import-untyped]

from app.models import JournalEntry
from app.repos.base import RepoBase
from app.repos.mappers import to_journal_entry


def _apply_cursor(
    query: firestore.Query, cursor: Optional[dict], client: firestore.Client, uid: str
) -> firestore.Query:
    if not cursor:
        return query
    created_at = cursor.get("createdAt")
    entry_id = cursor.get("entryId")
    if created_at and entry_id:
        doc_ref = (
            client.collection("users").document(uid).collection("journalEntries").document(entry_id)
        )
        return query.start_after([created_at, doc_ref])
    return query


class JournalRepo(RepoBase):
    def _collection(self, uid: str):
        return self.client.collection("users").document(uid).collection("journalEntries")

    def list_entries(
        self, uid: str, limit: int = 20, cursor: Optional[dict] = None
    ) -> List[JournalEntry]:
        query = (
            self._collection(uid)
            .order_by("createdAt", direction=firestore.Query.DESCENDING)
            .order_by(FieldPath.document_id(), direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        query = _apply_cursor(query, cursor, self.client, uid)
        docs = query.stream()
        return [to_journal_entry(doc.to_dict() or {}, entry_id=doc.id, uid=uid) for doc in docs]

    def get_entry(self, uid: str, entry_id: str) -> Optional[JournalEntry]:
        """Read a single journal entry. Returns None if the document does not exist."""
        doc = self._collection(uid).document(entry_id).get()
        data = self._doc_to_dict(doc)
        if data is None:
            return None
        return to_journal_entry(data, entry_id=entry_id, uid=uid)

    def create_entry(self, uid: str, entry_data: dict) -> str:
        """
        Create a new journal entry document.

        Args:
            uid: Owner's user ID.
            entry_data: Firestore-formatted dict (camelCase fields).

        Returns:
            The auto-generated entry ID.
        """
        doc_ref = self._collection(uid).document()
        doc_ref.set(entry_data)
        return doc_ref.id

    def update_entry(self, uid: str, entry_id: str, updates: dict) -> None:
        """
        Partially update a journal entry.

        Args:
            uid: Owner's user ID.
            entry_id: ID of the entry to update.
            updates: Dict of camelCase fields to update (merged, not replaced).

        Raises:
            google.api_core.exceptions.NotFound: If the document does not exist.
        """
        self._collection(uid).document(entry_id).update(updates)
