from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from google.api_core.exceptions import Conflict

from app.constants import DELETED_PLAYER_NAME
from app.repos.base import RepoBase
from app.repos.mappers import to_private_user_profile, to_public_user_profile
from app.models import LeagueSummary, PrivateUserProfile, PublicUserProfile
from app.models.enums import PlatformEnum


class UsersRepo(RepoBase):
    def get_user_doc(self, uid: str) -> Optional[dict]:
        doc = self.client.collection("users").document(uid).get()
        return self._doc_to_dict(doc)

    def get_public_profile(self, uid: str) -> Optional[PublicUserProfile]:
        data = self.get_user_doc(uid)
        if data is None:
            return None
        return to_public_user_profile(data)

    def get_private_profile(self, uid: str) -> Optional[PrivateUserProfile]:
        data = self.get_user_doc(uid)
        if data is None:
            return None
        return to_private_user_profile(data)

    def get_leagues_by_status(self, uid: str) -> tuple[list[LeagueSummary], list[LeagueSummary]]:
        profile = self.get_private_profile(uid)
        if profile is None:
            return [], []
        return profile.leagues_active, profile.leagues_completed

    def create_profile(self, uid: str, doc: dict) -> None:
        """Write a new user document atomically; raises ValueError if uid already exists."""
        try:
            self.client.collection("users").document(uid).create(doc)
        except Conflict:
            raise ValueError("already_registered")

    def update_play_tab(self, uid: str, updates: dict) -> None:
        """
        Update the playTab map on the user document.

        Args:
            uid: User ID
            updates: Dictionary of playTab fields to update (camelCase keys)
                    Example: {"state": "DISCOVERY", "activeBroadcastId": None}
        """
        # Prefix all keys with "playTab."
        prefixed_updates = {f"playTab.{key}": value for key, value in updates.items()}
        self.client.collection("users").document(uid).update(prefixed_updates)

    def upsert_device_token(self, uid: str, token: str, platform: PlatformEnum) -> None:
        """Idempotent: adds token if new, refreshes lastSeenAt if already present."""
        now = datetime.now(timezone.utc)
        user_ref = self.client.collection("users").document(uid)
        doc = user_ref.get()
        doc_data = self._doc_to_dict(doc)
        if doc_data is None:
            raise ValueError(f"user_not_found:{uid}")
        tokens: list[dict] = doc_data.get("deviceTokens") or []
        for entry in tokens:
            if entry.get("token") == token:
                entry["lastSeenAt"] = now
                user_ref.update({"deviceTokens": tokens})
                return
        tokens.append(
            {"token": token, "platform": str(platform), "createdAt": now, "lastSeenAt": now}
        )
        user_ref.update({"deviceTokens": tokens})

    def remove_device_token(self, uid: str, token: str) -> None:
        """Remove a device token from the user's list. No-op if not found."""
        user_ref = self.client.collection("users").document(uid)
        doc = user_ref.get()
        tokens: list[dict] = (self._doc_to_dict(doc) or {}).get("deviceTokens") or []
        filtered = [t for t in tokens if t.get("token") != token]
        if len(filtered) != len(tokens):
            user_ref.update({"deviceTokens": filtered})

    def anonymize(self, uid: str) -> None:
        """Tombstone the user doc in place (anonymize-in-place, do NOT cascade).

        Overwrites ``users/{uid}`` keeping only ``uid`` and ``rankings`` so opponents'
        head-to-head and point-history lookups keep resolving. All PII (email, phone,
        preferences, deviceTokens, skillDna, leagues, etc.) is stripped by replacing the
        whole document. ``name`` becomes "Deleted Player", ``profileUrl`` is nulled, and
        ``isDeleted``/``deletedAt`` are set. No-op raises are avoided: a missing doc is
        written as a bare tombstone.
        """
        now = datetime.now(timezone.utc)
        user_ref = self.client.collection("users").document(uid)
        existing = self._doc_to_dict(user_ref.get()) or {}
        tombstone = {
            "uid": uid,
            "name": DELETED_PLAYER_NAME,
            "profileUrl": None,
            "rankings": existing.get("rankings") or {},
            "isDeleted": True,
            "deletedAt": now,
        }
        user_ref.set(tombstone)

    def list_device_tokens(self, uid: str) -> list[dict]:
        """Return raw token dicts from the user doc (consumed by the Cloud Function trigger)."""
        data = self.get_user_doc(uid)
        if data is None:
            return []
        return data.get("deviceTokens") or []
