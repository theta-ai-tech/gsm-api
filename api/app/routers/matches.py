"""
Matches router — score submission and confirmation.
"""

from fastapi import APIRouter, Depends, HTTPException, Path, status
from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.dependencies.repos import (
    get_firestore_client,
    get_matches_repo,
    get_notification_intent_repo,
    get_point_history_repo,
    get_region_config_repo,
    get_ticker_repo,
    get_tier_config_repo,
    get_users_repo,
)
from app.repos.notification_intent_repo import NotificationIntentRepo
from app.deps import get_current_user
from app.rate_limit import rate_limit
from app.models.match import VerifyScoreRequest, VerifyScoreResponse
from app.repos.matches_repo import MatchesRepo
from app.repos.point_history_repo import PointHistoryRepo
from app.repos.region_config_repo import RegionConfigRepo
from app.repos.ticker_repo import TickerRepo
from app.repos.tier_config_repo import TierConfigRepo
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser
from app.services.match_confirmation_service import MatchConfirmationService

router = APIRouter(prefix="/matches", tags=["matches"])


def get_match_confirmation_service(
    matches_repo: MatchesRepo = Depends(get_matches_repo),
    users_repo: UsersRepo = Depends(get_users_repo),
    point_history_repo: PointHistoryRepo = Depends(get_point_history_repo),
    tier_config_repo: TierConfigRepo = Depends(get_tier_config_repo),
    ticker_repo: TickerRepo = Depends(get_ticker_repo),
    region_config_repo: RegionConfigRepo = Depends(get_region_config_repo),
    notification_intent_repo: NotificationIntentRepo = Depends(get_notification_intent_repo),
    firestore_client: firestore.Client = Depends(get_firestore_client),
) -> MatchConfirmationService:
    return MatchConfirmationService(
        matches_repo,
        users_repo,
        point_history_repo,
        tier_config_repo,
        firestore_client,
        ticker_repo=ticker_repo,
        region_config_repo=region_config_repo,
        notification_intent_repo=notification_intent_repo,
    )


@router.post(
    "/{match_id}/verify-score",
    response_model=VerifyScoreResponse,
    dependencies=[Depends(rate_limit("verify_score"))],
)
def verify_score(
    request: VerifyScoreRequest,
    match_id: str = Path(..., min_length=1),
    current_user: CurrentUser = Depends(get_current_user),
    service: MatchConfirmationService = Depends(get_match_confirmation_service),
):
    """
    Submit or confirm a match result.

    - First call (match is 'scheduled'): stores result → match becomes 'pending_confirmation'.
    - Second call (match is 'pending_confirmation'):
        - If winner agrees: scores atomically → match becomes 'completed'.
        - If winner disagrees: match becomes 'disputed' (no scoring).
    - Walkover / retirement: match completes with zero point deltas and no point history written.
    """
    try:
        return service.verify_score(current_user.uid, match_id, request)
    except PermissionError as e:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(e))
    except ValueError as e:
        msg = str(e)
        # Match-not-found maps to 404; other ValueErrors (validation/state
        # errors) are 409. Misconfigured server state (e.g. missing tier
        # config) bubbles up as 500 so it isn't mistaken for a missing match.
        if msg.startswith(f"Match {match_id} not found"):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)
        if "Tier config not found" in msg:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=msg)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)
