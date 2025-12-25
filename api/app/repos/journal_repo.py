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
        return query.start_after(created_at, doc_ref)
    return query


class JournalRepo(RepoBase):
    def list_entries(
        self, uid: str, limit: int = 20, cursor: Optional[dict] = None
    ) -> List[JournalEntry]:
        query = (
            self.client.collection("users")
            .document(uid)
            .collection("journalEntries")
            .order_by("createdAt", direction=firestore.Query.DESCENDING)
            .order_by(FieldPath.document_id(), direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        query = _apply_cursor(query, cursor, self.client, uid)
        docs = query.stream()
        return [to_journal_entry(doc.to_dict() or {}, entry_id=doc.id, uid=uid) for doc in docs]
