from __future__ import annotations

from typing import Optional

from google.api_core.exceptions import Conflict

from app.repos.base import RepoBase
from app.repos.mappers import to_private_user_profile, to_public_user_profile
from app.models import LeagueSummary, PrivateUserProfile, PublicUserProfile


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
