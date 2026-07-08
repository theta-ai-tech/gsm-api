from __future__ import annotations

from typing import List, Optional, cast

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]
from google.cloud.firestore_v1.field_path import FieldPath  # type: ignore[attr-defined, import-untyped]

from app.models import League, LeagueMember, LeagueTeam
from app.models.enums import LeagueStatusEnum, LeagueTeamStatusEnum, SportEnum
from app.repos.base import RepoBase
from app.repos.mappers import to_league, to_league_member, to_league_team


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

    def get_member(self, league_id: str, uid: str) -> Optional[LeagueMember]:
        doc = (
            self.client.collection("leagues")
            .document(league_id)
            .collection("members")
            .document(uid)
            .get()
        )
        data = self._doc_to_dict(doc)
        if data is None:
            return None
        return to_league_member(data, uid=uid)

    def list_members(self, league_id: str, limit: Optional[int] = 200) -> List[LeagueMember]:
        query = (
            self.client.collection("leagues")
            .document(league_id)
            .collection("members")
            .order_by("joinedAt")
        )
        if limit is not None:
            query = query.limit(limit)
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

    def get_team(self, league_id: str, team_id: str) -> Optional[LeagueTeam]:
        doc = (
            self.client.collection("leagues")
            .document(league_id)
            .collection("teams")
            .document(team_id)
            .get()
        )
        data = self._doc_to_dict(doc)
        if data is None:
            return None
        return to_league_team(data, team_id=team_id)

    def list_teams(
        self, league_id: str, status: Optional[LeagueTeamStatusEnum] = None
    ) -> List[LeagueTeam]:
        query: firestore.Query = cast(
            firestore.Query,
            self.client.collection("leagues").document(league_id).collection("teams"),
        )
        if status is not None:
            query = query.where("status", "==", status.value)
        return [to_league_team(doc.to_dict() or {}, team_id=doc.id) for doc in query.stream()]

    def create_team(self, league_id: str, team_id: str, doc: dict) -> None:
        self.client.collection("leagues").document(league_id).collection("teams").document(
            team_id
        ).set(doc)

    def list_partner_invites_by_email(self, email_normalized: str) -> List[dict]:
        """Return raw ``partnerInvites`` lookup docs matching a normalized email.

        Top-level ``partnerInvites`` collection keyed by
        ``{placeholderUid}__{leagueId}``. Used at registration to backfill every
        outstanding invite across leagues. Each returned dict carries an injected
        ``id`` (the lookup doc id).
        """
        docs = (
            self.client.collection("partnerInvites")
            .where("emailNormalized", "==", email_normalized)
            .stream()
        )
        results: List[dict] = []
        for doc in docs:
            data = doc.to_dict() or {}
            data["id"] = doc.id
            results.append(data)
        return results

    def find_teams_for_user(
        self, league_id: str, uid: str, statuses: list[LeagueTeamStatusEnum]
    ) -> List[LeagueTeam]:
        query = (
            self.client.collection("leagues")
            .document(league_id)
            .collection("teams")
            .where("memberUids", "array_contains", uid)
        )
        status_values = {s.value for s in statuses}
        teams = [to_league_team(doc.to_dict() or {}, team_id=doc.id) for doc in query.stream()]
        return [team for team in teams if team.status.value in status_values]
