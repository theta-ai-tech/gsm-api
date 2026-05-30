from __future__ import annotations

from typing import Any

from app.models.notification import PlayNotificationIntent
from app.repos.base import RepoBase

_SUBCOLLECTION = "notificationIntents"


class NotificationIntentRepo(RepoBase):
    def add_intent(self, intent: PlayNotificationIntent) -> str:
        doc_data: dict[str, Any] = {
            "type": intent.type.value,
            "targetUid": intent.target_uid,
            "title": intent.title,
            "body": intent.body,
            "dedupeKey": intent.dedupe_key,
            "createdAt": intent.created_at,
        }
        if intent.offer_id is not None:
            doc_data["offerId"] = intent.offer_id
        if intent.match_id is not None:
            doc_data["matchId"] = intent.match_id
        if intent.broadcast_id is not None:
            doc_data["broadcastId"] = intent.broadcast_id
        _, doc_ref = (
            self.client.collection("users")
            .document(intent.target_uid)
            .collection(_SUBCOLLECTION)
            .add(doc_data)
        )
        return doc_ref.id
