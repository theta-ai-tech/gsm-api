from __future__ import annotations

from typing import Any, Optional

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]
from google.cloud.firestore_v1.field_path import FieldPath  # type: ignore[attr-defined, import-untyped]

from app.models.enums import SportEnum
from app.models.point_history import PointHistoryEntry
from app.repos.base import RepoBase
from app.repos.mappers import to_point_history_entry


def _entry_to_doc(entry: PointHistoryEntry) -> dict[str, Any]:
    return {
        "sport": entry.sport,
        "pts": entry.pts,
        "delta": entry.delta,
        "reason": entry.reason,
        "matchId": entry.match_id,
        "opponentUid": entry.opponent_uid,
        "opponentPtsBefore": entry.opponent_pts_before,
        "leagueId": entry.league_id,
        "createdAt": entry.created_at,
        "tierBefore": entry.tier_before,
        "tierAfter": entry.tier_after,
    }


def _apply_cursor(
    query: firestore.Query, cursor: Optional[dict], client: firestore.Client, uid: str
) -> firestore.Query:
    if not cursor:
        return query
    created_at = cursor.get("createdAt")
    entry_id = cursor.get("entryId")
    if created_at and entry_id:
        doc_ref = (
            client.collection("users").document(uid).collection("pointHistory").document(entry_id)
        )
        doc_snapshot = doc_ref.get()
        if doc_snapshot.exists:
            return query.start_after(doc_snapshot)
        return query.start_after([created_at, doc_ref])
    return query


class PointHistoryRepo(RepoBase):
    def _collection(self, uid: str):
        return self.client.collection("users").document(uid).collection("pointHistory")

    def add_entry(self, uid: str, entry: PointHistoryEntry) -> str:
        """Write a point history entry to the subcollection.

        Returns:
            The auto-generated entry ID.
        """
        doc_ref = self._collection(uid).document()
        doc_ref.set(_entry_to_doc(entry))
        return doc_ref.id

    def add_entry_in_transaction(
        self,
        transaction: firestore.Transaction,
        uid: str,
        entry: PointHistoryEntry,
    ) -> firestore.DocumentReference:
        """Write a point history entry within an existing transaction.

        Returns:
            The DocumentReference for the new entry (ID is set before the transaction commits).
        """
        doc_ref = self._collection(uid).document()
        transaction.set(doc_ref, _entry_to_doc(entry))
        return doc_ref

    def list_entries(
        self,
        uid: str,
        sport: SportEnum,
        limit: int = 20,
        cursor: Optional[dict] = None,
    ) -> list[PointHistoryEntry]:
        """Return point history entries for a user/sport ordered by createdAt DESC.

        Args:
            uid: User ID.
            sport: Sport filter — must match the composite index field.
            limit: Maximum number of entries to return.
            cursor: Pagination cursor with ``createdAt`` and ``entryId`` keys.
        """
        query = (
            self._collection(uid)
            .where("sport", "==", sport)
            .order_by("createdAt", direction=firestore.Query.DESCENDING)
            .order_by(FieldPath.document_id(), direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        query = _apply_cursor(query, cursor, self.client, uid)
        docs = query.stream()
        return [to_point_history_entry(doc.to_dict() or {}, entry_id=doc.id) for doc in docs]
