from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]
from google.cloud.firestore_v1.field_path import FieldPath  # type: ignore[attr-defined, import-untyped]

from app.models import Match
from app.models.enums import SportEnum
from app.repos.base import RepoBase
from app.repos.mappers import to_match


def _apply_cursor(
    query: firestore.Query, cursor: Optional[dict], field: str, client: firestore.Client
) -> firestore.Query:
    if not cursor:
        return query
    ts = cursor.get(field)
    match_id = cursor.get("matchId")
    if ts and match_id:
        doc_ref = client.collection("matches").document(match_id)
        return query.start_after([ts, doc_ref])
    return query


class MatchesRepo(RepoBase):
    def get_by_id(self, match_id: str) -> Optional[Match]:
        doc = self.client.collection("matches").document(match_id).get()
        data = self._doc_to_dict(doc)
        if data is None:
            return None
        return to_match(data, match_id=match_id)

    def list_upcoming_for_user(
        self, uid: str, limit: int = 20, cursor: Optional[dict] = None
    ) -> List[Match]:
        now = datetime.now(timezone.utc)
        query = (
            self.client.collection("matches")
            .where("participantUids", "array_contains", uid)
            .where("status", "==", "scheduled")
            .where("scheduledAt", ">=", now)
            .order_by("scheduledAt")
            .order_by(FieldPath.document_id())
            .limit(limit)
        )
        query = _apply_cursor(query, cursor, "scheduledAt", self.client)
        docs = query.stream()
        return [to_match(doc.to_dict() or {}, match_id=doc.id) for doc in docs]

    def list_completed_for_user(
        self, uid: str, limit: int = 20, cursor: Optional[dict] = None
    ) -> List[Match]:
        query = (
            self.client.collection("matches")
            .where("participantUids", "array_contains", uid)
            .where("status", "==", "completed")
            .order_by("finishedAt", direction=firestore.Query.DESCENDING)
            .order_by(FieldPath.document_id(), direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        query = _apply_cursor(query, cursor, "finishedAt", self.client)
        docs = query.stream()
        return [to_match(doc.to_dict() or {}, match_id=doc.id) for doc in docs]

    def list_upcoming_for_league(
        self, league_id: str, limit: int = 50, cursor: Optional[dict] = None
    ) -> List[Match]:
        query = (
            self.client.collection("matches")
            .where("leagueId", "==", league_id)
            .where("status", "==", "scheduled")
            .order_by("scheduledAt")
            .order_by(FieldPath.document_id())
            .limit(limit)
        )
        query = _apply_cursor(query, cursor, "scheduledAt", self.client)
        docs = query.stream()
        return [to_match(doc.to_dict() or {}, match_id=doc.id) for doc in docs]

    def list_completed_for_league(
        self, league_id: str, limit: int = 50, cursor: Optional[dict] = None
    ) -> List[Match]:
        query = (
            self.client.collection("matches")
            .where("leagueId", "==", league_id)
            .where("status", "==", "completed")
            .order_by("finishedAt", direction=firestore.Query.DESCENDING)
            .order_by(FieldPath.document_id(), direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        query = _apply_cursor(query, cursor, "finishedAt", self.client)
        docs = query.stream()
        return [to_match(doc.to_dict() or {}, match_id=doc.id) for doc in docs]

    def list_upcoming_for_division(
        self,
        league_id: str,
        division_id: str,
        limit: int = 50,
        cursor: Optional[dict] = None,
    ) -> List[Match]:
        query = (
            self.client.collection("matches")
            .where("leagueId", "==", league_id)
            .where("divisionId", "==", division_id)
            .where("status", "==", "scheduled")
            .order_by("scheduledAt")
            .order_by(FieldPath.document_id())
            .limit(limit)
        )
        query = _apply_cursor(query, cursor, "scheduledAt", self.client)
        docs = query.stream()
        return [to_match(doc.to_dict() or {}, match_id=doc.id) for doc in docs]

    def list_completed_for_division(
        self,
        league_id: str,
        division_id: str,
        limit: int = 50,
        cursor: Optional[dict] = None,
    ) -> List[Match]:
        query = (
            self.client.collection("matches")
            .where("leagueId", "==", league_id)
            .where("divisionId", "==", division_id)
            .where("status", "==", "completed")
            .order_by("finishedAt", direction=firestore.Query.DESCENDING)
            .order_by(FieldPath.document_id(), direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        query = _apply_cursor(query, cursor, "finishedAt", self.client)
        docs = query.stream()
        return [to_match(doc.to_dict() or {}, match_id=doc.id) for doc in docs]

    def list_head_to_head(self, pair: str, sport: SportEnum, limit: int = 10) -> List[Match]:
        """Return completed H2H matches for a pair ordered by finishedAt DESC.

        Queries by participantPair then filters sport/status in Python to avoid
        needing a third composite index field.
        """
        _FETCH_CAP = 100
        query = (
            self.client.collection("matches")
            .where("participantPair", "==", pair)
            .order_by("finishedAt", direction=firestore.Query.DESCENDING)
            .order_by(FieldPath.document_id(), direction=firestore.Query.DESCENDING)
            .limit(_FETCH_CAP)
        )
        results: List[Match] = []
        for doc in query.stream():
            data = doc.to_dict() or {}
            if data.get("sport") != sport.value or data.get("status") != "completed":
                continue
            results.append(to_match(data, match_id=doc.id))
            if len(results) >= limit:
                break
        return results
