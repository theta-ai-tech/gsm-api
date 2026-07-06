"""Account management router — self-service account deletion (App Store gate)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from app.dependencies.repos import (
    get_auth_admin,
    get_journal_repo,
    get_point_history_repo,
    get_users_repo,
)
from app.deps import get_current_user
from app.repos.journal_repo import JournalRepo
from app.repos.point_history_repo import PointHistoryRepo
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser
from app.services import account_service
from app.services.auth_admin import AuthAdmin

router = APIRouter(prefix="/me/account", tags=["account"])


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    current_user: CurrentUser = Depends(get_current_user),
    users_repo: UsersRepo = Depends(get_users_repo),
    journal_repo: JournalRepo = Depends(get_journal_repo),
    point_history_repo: PointHistoryRepo = Depends(get_point_history_repo),
    auth_admin: AuthAdmin = Depends(get_auth_admin),
) -> None:
    """Delete the authenticated caller's account (anonymize-in-place, 204).

    Hard-deletes the caller's own journal and point-history subcollections and
    tombstones the user doc (preserving ``uid`` + ``rankings`` so opponents'
    histories keep resolving), then deletes the Firebase Auth user last so a
    mid-flow failure leaves the token valid and the request retryable.
    """
    account_service.delete_account(
        current_user.uid,
        users_repo=users_repo,
        journal_repo=journal_repo,
        point_history_repo=point_history_repo,
        auth_admin=auth_admin,
    )
