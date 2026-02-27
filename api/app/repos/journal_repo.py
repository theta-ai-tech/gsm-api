from __future__ import annotations

from datetime import datetime
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
        doc_snapshot = doc_ref.get()
        if doc_snapshot.exists:
            return query.start_after(doc_snapshot)
        return query.start_after([created_at, doc_ref])
    return query


class JournalRepo(RepoBase):
    def _collection(self, uid: str):
        return self.client.collection("users").document(uid).collection("journalEntries")

    def list_entries(
        self,
        uid: str,
        limit: int = 20,
        cursor: Optional[dict] = None,
        include_deleted: bool = False,
    ) -> List[JournalEntry]:
        query = (
            self._collection(uid)
            .order_by("createdAt", direction=firestore.Query.DESCENDING)
            .order_by(FieldPath.document_id(), direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        query = _apply_cursor(query, cursor, self.client, uid)
        docs = query.stream()
        entries: list[JournalEntry] = []
        for doc in docs:
            entry = to_journal_entry(doc.to_dict() or {}, entry_id=doc.id, uid=uid)
            if include_deleted or not entry.is_deleted:
                entries.append(entry)
        return entries

    def get_entry(
        self, uid: str, entry_id: str, include_deleted: bool = False
    ) -> Optional[JournalEntry]:
        """Read a single journal entry. Returns None if the document does not exist."""
        doc = self._collection(uid).document(entry_id).get()
        data = self._doc_to_dict(doc)
        if data is None:
            return None
        if not include_deleted and bool(data.get("isDeleted", False)):
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

    def get_entry_by_client_request_id(
        self, uid: str, client_request_id: str
    ) -> Optional[JournalEntry]:
        docs = (
            self._collection(uid)
            .where("clientRequestId", "==", client_request_id)
            .limit(1)
            .stream()
        )
        first_doc = next(iter(docs), None)
        if first_doc is None:
            return None
        return to_journal_entry(first_doc.to_dict() or {}, entry_id=first_doc.id, uid=uid)

    def count_entries_since(self, uid: str, since: datetime) -> int:
        docs = self._collection(uid).where("createdAt", ">=", since).limit(1000).stream()
        return sum(1 for _ in docs)
