from __future__ import annotations

from firebase_admin import auth as firebase_auth  # type: ignore[import-untyped]

from app.repos.journal_repo import JournalRepo
from app.repos.point_history_repo import PointHistoryRepo
from app.repos.users_repo import UsersRepo
from app.services.auth_admin import AuthAdmin


def delete_account(
    uid: str,
    *,
    users_repo: UsersRepo,
    journal_repo: JournalRepo,
    point_history_repo: PointHistoryRepo,
    auth_admin: AuthAdmin,
) -> None:
    """Delete the caller's account with anonymize-in-place (LOCKED design).

    Sequence:
      1. Identity — revoke refresh tokens then delete the Firebase Auth user. A
         missing Auth user (already deleted) is tolerated for idempotency.
      2. Own private data — hard-delete ``journalEntries`` and ``pointHistory``.
      3. Tombstone — overwrite ``users/{uid}`` keeping only ``uid`` + ``rankings``
         (drops deviceTokens and all PII), setting ``isDeleted``/``deletedAt``.

    Deliberately does NOT cascade: match docs, opponents' point_history, scouting,
    ticker and leaderboard rows referencing this uid are left intact and render as
    "Deleted Player" via the tombstone.
    """
    try:
        auth_admin.revoke_refresh_tokens(uid)
        auth_admin.delete_user(uid)
    except firebase_auth.UserNotFoundError:
        # Already gone in Firebase Auth; continue with data cleanup (idempotent).
        pass

    journal_repo.delete_all_for_user(uid)
    point_history_repo.delete_all_for_user(uid)
    users_repo.anonymize(uid)
