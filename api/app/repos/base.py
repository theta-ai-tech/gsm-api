from __future__ import annotations

from typing import Any, Optional, cast

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]


class RepoBase:
    def __init__(self, client: firestore.Client):
        self.client = client

    @staticmethod
    def _doc_to_dict(doc: Any) -> Optional[dict[str, Any]]:
        snap: firestore.DocumentSnapshot = cast(firestore.DocumentSnapshot, doc)
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        data["id"] = snap.id
        return data

    @staticmethod
    def _require(doc: Any) -> dict[str, Any]:
        data = RepoBase._doc_to_dict(doc)
        if data is None:
            raise KeyError("Document not found")
        return data
