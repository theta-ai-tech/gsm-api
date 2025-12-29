from __future__ import annotations

from typing import Any, Optional

from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]


class RepoBase:
    def __init__(self, client: firestore.Client):
        self.client = client

    @staticmethod
    def _doc_to_dict(doc: firestore.DocumentSnapshot) -> Optional[dict[str, Any]]:
        if not doc.exists:
            return None
        data = doc.to_dict() or {}
        data["id"] = doc.id
        return data

    @staticmethod
    def _require(doc: firestore.DocumentSnapshot) -> dict[str, Any]:
        data = RepoBase._doc_to_dict(doc)
        if data is None:
            raise KeyError("Document not found")
        return data
