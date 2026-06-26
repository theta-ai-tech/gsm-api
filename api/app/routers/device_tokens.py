from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import get_current_user
from app.dependencies.repos import get_users_repo
from app.models.device_token import DeleteDeviceTokenRequest, RegisterDeviceTokenRequest
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser

router = APIRouter(prefix="/me/device-tokens", tags=["device-tokens"])


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
def register_device_token(
    request: RegisterDeviceTokenRequest,
    current_user: CurrentUser = Depends(get_current_user),
    users_repo: UsersRepo = Depends(get_users_repo),
) -> None:
    """Idempotently register the caller's push token; refreshes lastSeenAt if already present."""
    try:
        users_repo.upsert_device_token(current_user.uid, request.token, request.platform)
    except ValueError as exc:
        if str(exc).startswith("user_not_found:"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_device_token(
    request: DeleteDeviceTokenRequest,
    current_user: CurrentUser = Depends(get_current_user),
    users_repo: UsersRepo = Depends(get_users_repo),
) -> None:
    """Remove the caller's push token (logout/rotation). No-op if not present."""
    users_repo.remove_device_token(current_user.uid, request.token)
