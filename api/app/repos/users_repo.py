from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from google.api_core.exceptions import Conflict

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

    def search_by_name_prefix(
        self, query: str, limit: int, exclude_uid: str | None = None
    ) -> list[dict]:
        """Return raw user docs whose ``nameLower`` starts with ``query`` (case-insensitive).

        Uses the Firestore ``>=`` / ``<`` range trick on the ``nameLower`` field
        to approximate a prefix search. ``query`` is lowercased before matching.
        The calling user (``exclude_uid``) is filtered out of the results.
        Each returned doc carries an injected ``uid`` key.
        """
        q = query.strip().lower()
        if not q:
            return []
        high = q + ""
        docs = (
            self.client.collection("users")
            .where("nameLower", ">=", q)
            .where("nameLower", "<", high)
            .limit(limit + 1)
            .stream()
        )
        results: list[dict] = []
        for doc in docs:
            if exclude_uid is not None and doc.id == exclude_uid:
                continue
            data = doc.to_dict() or {}
            data["uid"] = doc.id
            results.append(data)
            if len(results) >= limit:
                break
        return results

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

    def list_device_tokens(self, uid: str) -> list[dict]:
        """Return raw token dicts from the user doc (consumed by the Cloud Function trigger)."""
        data = self.get_user_doc(uid)
        if data is None:
            return []
        return data.get("deviceTokens") or []
