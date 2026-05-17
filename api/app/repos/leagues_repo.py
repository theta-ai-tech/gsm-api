from __future__ import annotations

from typing import List, Optional, cast

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]
from google.cloud.firestore_v1.field_path import FieldPath  # type: ignore[attr-defined, import-untyped]

from app.models import League, LeagueMember
from app.models.enums import LeagueStatusEnum, SportEnum
from app.repos.base import RepoBase
from app.repos.mappers import to_league, to_league_member


def _apply_league_cursor(
    query: firestore.Query, cursor: Optional[dict], client: firestore.Client
) -> firestore.Query:
    if not cursor:
        return query
    start_date = cursor.get("startDate")
    league_id = cursor.get("leagueId")
    if start_date and league_id:
        doc_ref = client.collection("leagues").document(league_id)
        return query.start_after([start_date, doc_ref])
    return query


class LeaguesRepo(RepoBase):
    def get_by_id(self, league_id: str) -> Optional[League]:
        doc = self.client.collection("leagues").document(league_id).get()
        data = self._doc_to_dict(doc)
        if data is None:
            return None
        return to_league(data, league_id=league_id)

    def list_members(self, league_id: str, limit: int = 200) -> List[LeagueMember]:
        query = (
            self.client.collection("leagues")
            .document(league_id)
            .collection("members")
            .order_by("joinedAt")
            .limit(limit)
        )
        docs = query.stream()
        return [to_league_member(doc.to_dict() or {}, uid=doc.id) for doc in docs]

    def list_by_filter(
        self,
        region: Optional[str] = None,
        sport: Optional[SportEnum] = None,
        status: Optional[LeagueStatusEnum] = None,
        limit: int = 20,
        cursor: Optional[dict] = None,
    ) -> List[League]:
        query: firestore.Query = cast(firestore.Query, self.client.collection("leagues"))
        if region is not None:
            query = query.where("region", "==", region)
        if sport is not None:
            query = query.where("sport", "==", sport.value)
        if status is not None:
            query = query.where("status", "==", status.value)
        query = query.order_by("startDate").order_by(FieldPath.document_id()).limit(limit)
        query = _apply_league_cursor(query, cursor, self.client)
        return [to_league(doc.to_dict() or {}, league_id=doc.id) for doc in query.stream()]

    def get_member_count(self, league_id: str) -> int:
        doc = self.client.collection("leagues").document(league_id).get()
        data = self._doc_to_dict(doc)
        if data is None:
            return 0
        current_players = data.get("currentPlayers")
        if current_players is not None:
            return int(current_players)
        members = (
            self.client.collection("leagues").document(league_id).collection("members").stream()
        )
        return sum(1 for _ in members)

    def increment_member_count(self, league_id: str, delta: int = 1) -> None:
        self.client.collection("leagues").document(league_id).update(
            {"currentPlayers": firestore.Increment(delta)}
        )
