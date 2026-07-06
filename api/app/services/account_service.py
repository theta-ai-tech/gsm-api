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

    Sequence — **data erasure first, identity destruction last**:
      1. Own private data — hard-delete ``journalEntries`` and ``pointHistory``.
      2. Tombstone — overwrite ``users/{uid}`` keeping only ``uid`` + ``rankings``
         (drops deviceTokens and all PII), setting ``isDeleted``/``deletedAt``.
      3. Identity — delete the Firebase Auth user (the single destructive Auth op;
         it invalidates tokens and locks the caller out immediately). A missing Auth
         user (already deleted) is tolerated for idempotency.

    Ordering rationale (recoverability): every Firestore step runs while the caller's
    ID token is still valid. If any of them fails the Auth user is left intact, so the
    request surfaces a 5xx and the client can safely retry the endpoint — the deletes
    and the tombstone ``set()`` are all idempotent. Identity destruction is a single
    ``delete_user`` call performed last; we do NOT revoke refresh tokens separately,
    because a revoke that succeeds before a failed delete would sign the caller out
    while leaving the Auth user (and its PII) present with no way to retry.

    Deliberately does NOT cascade: match docs, opponents' point_history, scouting,
    ticker and leaderboard rows referencing this uid are left intact and render as
    "Deleted Player" via the tombstone.
    """
    journal_repo.delete_all_for_user(uid)
    point_history_repo.delete_all_for_user(uid)
    users_repo.anonymize(uid)

    try:
        auth_admin.delete_user(uid)
    except firebase_auth.UserNotFoundError:
        # Auth user already gone (e.g. a retry after an earlier partial run);
        # erasure above has completed, so treat this as success (idempotent).
        pass
