from __future__ import annotations

from typing import Any

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.models.ticker import TickerEvent
from app.repos.base import RepoBase
from app.repos.mappers import to_ticker_event

_COLLECTION = "ticker"


class TickerRepo(RepoBase):
    def add(self, event: TickerEvent) -> str:
        doc_data: dict[str, Any] = {
            "type": event.type.value,
            "sport": event.sport.value,
            "region": event.region,
            "winnerUid": event.winner_uid,
            "winnerName": event.winner_name,
            "loserTier": event.loser_tier.value if event.loser_tier else None,
            "delta": event.delta,
            "createdAt": event.created_at,
            "expiresAt": event.expires_at,
        }
        _, doc_ref = self.client.collection(_COLLECTION).add(doc_data)
        return doc_ref.id

    def list_by_region_sport(
        self,
        region: str,
        sport: str,
        limit: int = 20,
    ) -> list[TickerEvent]:
        query = (
            self.client.collection(_COLLECTION)
            .where("region", "==", region)
            .where("sport", "==", sport)
            .order_by("createdAt", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        results: list[TickerEvent] = []
        for doc in query.stream():
            data = doc.to_dict() or {}
            results.append(to_ticker_event(data, event_id=doc.id))
        return results
