"""
RoleService centralizes resource-level membership checks (e.g., league membership).

Membership documents live at: leagues/{league_id}/members/{uid} with a `role` field.
The service stays minimal and injectable so handlers can pass a Firestore client or a stub.
"""

from __future__ import annotations

from typing import Optional


class RoleService:
    def __init__(self, db):
        self.db = db

    def _league_doc(self, league_id: str):
        return self.db.collection("leagues").document(league_id)

    def _member_doc(self, league_id: str, uid: str):
        return self._league_doc(league_id).collection("members").document(uid)

    def is_league_member(self, league_id: str, uid: str) -> bool:
        snapshot = self._member_doc(league_id, uid).get()
        return bool(getattr(snapshot, "exists", False))

    def get_league_member_role(self, league_id: str, uid: str) -> Optional[str]:
        snapshot = self._member_doc(league_id, uid).get()
        if not getattr(snapshot, "exists", False):
            return None

        data = snapshot.to_dict() or {}
        role = data.get("role")
        if not role:
            return None
        return str(role)

    def get_league_owner_uid(self, league_id: str) -> Optional[str]:
        snapshot = self._league_doc(league_id).get()
        if not getattr(snapshot, "exists", False):
            return None

        data = snapshot.to_dict() or {}
        owner_uid = data.get("ownerUid") or data.get("owner_uid")
        if not owner_uid:
            return None
        return str(owner_uid)


# Convenience helpers when you don't want to wire the class explicitly.
def is_league_member(firestore_client, league_id: str, uid: str) -> bool:
    return RoleService(db=firestore_client).is_league_member(league_id, uid)


def get_league_member_role(firestore_client, league_id: str, uid: str) -> Optional[str]:
    return RoleService(db=firestore_client).get_league_member_role(league_id, uid)
