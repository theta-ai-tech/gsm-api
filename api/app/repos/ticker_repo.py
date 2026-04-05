from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.models.enums import TickerEventTypeEnum
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
            "createdAt": event.created_at,
            "expiresAt": event.expires_at,
        }
        # upset fields
        if event.winner_uid is not None:
            doc_data["winnerUid"] = event.winner_uid
        if event.winner_name is not None:
            doc_data["winnerName"] = event.winner_name
        if event.loser_tier is not None:
            doc_data["loserTier"] = event.loser_tier.value
        if event.delta:
            doc_data["delta"] = event.delta
        # shared subject fields
        if event.user_uid is not None:
            doc_data["userUid"] = event.user_uid
        if event.user_name is not None:
            doc_data["userName"] = event.user_name
        # personal_best fields
        if event.new_pts is not None:
            doc_data["newPts"] = event.new_pts
        if event.previous_best is not None:
            doc_data["previousBest"] = event.previous_best
        # win_streak fields
        if event.streak is not None:
            doc_data["streak"] = event.streak
        # tier_crossed fields
        if event.tier_before is not None:
            doc_data["tierBefore"] = event.tier_before.value
        if event.tier_after is not None:
            doc_data["tierAfter"] = event.tier_after.value
        if event.direction is not None:
            doc_data["direction"] = event.direction
        _, doc_ref = self.client.collection(_COLLECTION).add(doc_data)
        return doc_ref.id

    def list_by_region_sport(
        self,
        region: str,
        sport: str,
        limit: int = 20,
        types: list[TickerEventTypeEnum] | None = None,
    ) -> list[TickerEvent]:
        now = datetime.now(tz=timezone.utc)
        # Fetch ordered by createdAt DESC (the feed's true sort order).
        # Expired events are filtered in memory, so we paginate through
        # batches until we have collected `limit` live events or the
        # query is exhausted.
        batch_size = limit * 3
        base_query = (
            self.client.collection(_COLLECTION)
            .where("region", "==", region)
            .where("sport", "==", sport)
        )
        if types:
            base_query = base_query.where("type", "in", [t.value for t in types])
        base_query = base_query.order_by("createdAt", direction=firestore.Query.DESCENDING)

        results: list[TickerEvent] = []
        cursor: Any | None = None

        while len(results) < limit:
            page_query = base_query.limit(batch_size)
            if cursor is not None:
                page_query = page_query.start_after(cursor)

            docs = list(page_query.stream())
            if not docs:
                break

            for doc in docs:
                data = doc.to_dict() or {}
                event = to_ticker_event(data, event_id=doc.id)
                if event.expires_at > now:
                    results.append(event)
                    if len(results) >= limit:
                        break

            cursor = docs[-1]

        return results
