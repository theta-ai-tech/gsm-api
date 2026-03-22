from __future__ import annotations

from typing import Optional, cast

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.models.leaderboard import LeaderboardSnapshot
from app.repos.base import RepoBase
from app.repos.mappers import to_leaderboard_snapshot

_COLLECTION = "leaderboards"


class LeaderboardRepo(RepoBase):
    def get_snapshot(self, region: str, sport: str) -> Optional[LeaderboardSnapshot]:
        doc_id = f"{region}_{sport}"
        doc = cast(
            firestore.DocumentSnapshot,
            self.client.collection(_COLLECTION).document(doc_id).get(),
        )
        if not doc.exists:
            return None
        data = doc.to_dict() or {}
        return to_leaderboard_snapshot(data)

    def list_by_region(self, region: str) -> list[LeaderboardSnapshot]:
        query = self.client.collection(_COLLECTION).where("region", "==", region)
        results: list[LeaderboardSnapshot] = []
        for doc in query.stream():
            data = doc.to_dict() or {}
            results.append(to_leaderboard_snapshot(data))
        return results

    def list_by_sport(self, sport: str) -> list[LeaderboardSnapshot]:
        query = self.client.collection(_COLLECTION).where("sport", "==", sport)
        results: list[LeaderboardSnapshot] = []
        for doc in query.stream():
            data = doc.to_dict() or {}
            results.append(to_leaderboard_snapshot(data))
        return results
