from __future__ import annotations

from typing import List, Optional

from app.models import Division
from app.repos.base import RepoBase
from app.repos.mappers import to_division


def _division_to_firestore_doc(division: Division) -> dict:
    return {
        "name": division.name,
        "ordinal": division.ordinal,
        "ratingRange": {
            "min": division.rating_range.min,
            "max": division.rating_range.max,
        },
        "currentPlayers": division.current_players,
        "status": division.status.value,
    }


class DivisionsRepo(RepoBase):
    def _collection(self, league_id: str):
        return self.client.collection("leagues").document(league_id).collection("divisions")

    def get_by_id(self, league_id: str, division_id: str) -> Optional[Division]:
        doc = self._collection(league_id).document(division_id).get()
        data = self._doc_to_dict(doc)
        if data is None:
            return None
        return to_division(data, division_id=division_id)

    def list_for_league(self, league_id: str, limit: int = 100) -> List[Division]:
        query = self._collection(league_id).order_by("ordinal").limit(limit)
        return [to_division(doc.to_dict() or {}, division_id=doc.id) for doc in query.stream()]

    def create_division(self, league_id: str, division: Division) -> None:
        self._collection(league_id).document(division.division_id).set(
            _division_to_firestore_doc(division)
        )

    def set_division_current_players(
        self, league_id: str, division_id: str, current_players: int
    ) -> None:
        self._collection(league_id).document(division_id).update(
            {"currentPlayers": current_players}
        )
