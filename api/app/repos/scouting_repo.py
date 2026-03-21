from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, cast

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.models.scouting import ScoutingProfile
from app.repos.base import RepoBase
from app.repos.mappers import to_scouting_profile

_COLLECTION = "scouting"


class ScoutingRepo(RepoBase):
    def get_profile(self, uid: str) -> Optional[ScoutingProfile]:
        doc = cast(
            firestore.DocumentSnapshot,
            self.client.collection(_COLLECTION).document(uid).get(),
        )
        if not doc.exists:
            return None
        data = doc.to_dict() or {}
        data["uid"] = doc.id
        return to_scouting_profile(data)

    def increment_tag(
        self,
        uid: str,
        sport: str,
        category: str,
        tag: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        doc_ref = self.client.collection(_COLLECTION).document(uid)
        doc_ref.set(
            {
                "uid": uid,
                sport: {
                    category: {
                        tag: {
                            "count": firestore.Increment(1),
                            "lastReported": now,
                        },
                    },
                    "totalReports": firestore.Increment(1),
                    "lastUpdated": now,
                },
            },
            merge=True,
        )
