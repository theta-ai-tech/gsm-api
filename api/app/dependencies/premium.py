from fastapi import Depends

from app import errors
from app.dependencies.repos import get_users_repo
from app.deps import get_current_user
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser


def require_pro(
    current_user: CurrentUser = Depends(get_current_user),
    users_repo: UsersRepo = Depends(get_users_repo),
) -> CurrentUser:
    """Hard gate: raises 402 if the authenticated user is not a Pro subscriber."""
    profile = users_repo.get_public_profile(current_user.uid)
    if profile is None or not profile.is_pro:
        raise errors.payment_required("This feature requires a Pro subscription")
    return current_user


def get_subscription_status(
    current_user: CurrentUser = Depends(get_current_user),
    users_repo: UsersRepo = Depends(get_users_repo),
) -> bool:
    """Soft gate: returns True if user is Pro, False otherwise."""
    profile = users_repo.get_public_profile(current_user.uid)
    if profile is None:
        return False
    return profile.is_pro
