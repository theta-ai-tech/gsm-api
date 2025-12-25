from __future__ import annotations

from typing import List, Optional


from app.models import League, LeagueMember
from app.repos.base import RepoBase
from app.repos.mappers import to_league, to_league_member


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
