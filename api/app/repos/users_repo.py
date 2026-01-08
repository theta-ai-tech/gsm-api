from __future__ import annotations

from typing import Optional


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
