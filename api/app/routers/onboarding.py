from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import get_current_user
from app.dependencies.repos import get_tier_config_repo, get_users_repo
from app.models.onboarding import RegisterMeRequest
from app.models.user import PrivateUserProfile
from app.repos.tier_config_repo import TierConfigRepo
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser
from app.services.onboarding_service import OnboardingService

router = APIRouter(prefix="/me", tags=["onboarding"])


def get_onboarding_service(
    users_repo: UsersRepo = Depends(get_users_repo),
    tier_config_repo: TierConfigRepo = Depends(get_tier_config_repo),
) -> OnboardingService:
    return OnboardingService(users_repo, tier_config_repo)


@router.post("", response_model=PrivateUserProfile, status_code=status.HTTP_201_CREATED)
def register_me(
    request: RegisterMeRequest,
    current_user: CurrentUser = Depends(get_current_user),
    service: OnboardingService = Depends(get_onboarding_service),
) -> PrivateUserProfile:
    """
    Create user profile on first onboarding. Re-POST returns 409.
    registrationTier is derived server-side from the supplied level and is immutable.
    """
    try:
        return service.register_me(
            uid=current_user.uid,
            token_email=current_user.email,
            token_picture=current_user.picture,
            request=request,
        )
    except ValueError as exc:
        msg = str(exc)
        if msg == "already_registered":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User profile already exists",
            )
        if msg == "email_required":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="email is required: not present in token and not provided in request body",
            )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)
