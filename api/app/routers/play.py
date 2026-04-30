"""
Tab 1 PLAY router - Matchmaking endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.dependencies.repos import (
    get_broadcasts_repo,
    get_firestore_client,
    get_matches_repo,
    get_offers_repo,
    get_users_repo,
)
from app.models.play import (
    CreateBroadcastRequest,
    CreateBroadcastResponse,
    MeStateResponse,
    OfferActionResponse,
    SendOfferRequest,
    SendOfferResponse,
)
from app.deps import get_current_user
from app.repos.broadcasts_repo import BroadcastsRepo
from app.repos.matches_repo import MatchesRepo
from app.repos.offers_repo import OffersRepo
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser
from app.services.play_service import PlayService

router = APIRouter(prefix="/me", tags=["play"])


def get_play_service(
    users_repo: UsersRepo = Depends(get_users_repo),
    broadcasts_repo: BroadcastsRepo = Depends(get_broadcasts_repo),
    matches_repo: MatchesRepo = Depends(get_matches_repo),
    offers_repo: OffersRepo = Depends(get_offers_repo),
    firestore_client: firestore.Client = Depends(get_firestore_client),
) -> PlayService:
    """Dependency to get PlayService instance."""
    return PlayService(users_repo, broadcasts_repo, matches_repo, offers_repo, firestore_client)


# ===== GET /me/state =====


@router.get("/state", response_model=MeStateResponse)
def get_me_state(
    current_user: CurrentUser = Depends(get_current_user),
    play_service: PlayService = Depends(get_play_service),
):
    """
    Get current Tab 1 state for the authenticated user.

    Returns mode-specific payload with freshness reconciliation.
    """
    return play_service.get_me_state(current_user.uid)


# ===== POST /me/broadcast =====


@router.post(
    "/broadcast", response_model=CreateBroadcastResponse, status_code=status.HTTP_201_CREATED
)
def create_broadcast(
    request: CreateBroadcastRequest,
    current_user: CurrentUser = Depends(get_current_user),
    play_service: PlayService = Depends(get_play_service),
):
    """
    Start an availability broadcast ("I'm Ready to Play").

    Preconditions:
    - User must be in DISCOVERY state
    """
    try:
        return play_service.create_broadcast(current_user.uid, request)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


# ===== DELETE /me/broadcast =====


@router.delete("/broadcast", status_code=status.HTTP_204_NO_CONTENT)
def cancel_broadcast(
    current_user: CurrentUser = Depends(get_current_user),
    play_service: PlayService = Depends(get_play_service),
):
    """
    Cancel the user's active broadcast.

    Preconditions:
    - User must be in BROADCAST_ACTIVE state
    """
    try:
        play_service.cancel_broadcast(current_user.uid)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


# ===== POST /me/offers =====


@router.post("/offers", response_model=SendOfferResponse, status_code=status.HTTP_201_CREATED)
def send_offer(
    request: SendOfferRequest,
    current_user: CurrentUser = Depends(get_current_user),
    play_service: PlayService = Depends(get_play_service),
):
    """
    Send a challenge offer to another user.

    Preconditions:
    - Sender must be in DISCOVERY or BROADCAST_ACTIVE
    - Sender must not already have an active outgoing offer
    - Recipient must exist
    """
    try:
        return play_service.send_offer(current_user.uid, request)
    except ValueError as e:
        error_msg = str(e)
        # 400 — domain validation errors (bad request inputs / mismatches)
        bad_request_markers = (
            "does not match",
            "requires partner_uid",
            "require a source broadcast",
            "must all be distinct",
            "find_fourth broadcasts are not yet supported",
            "Partner user not found",
            "Broadcast partner user not found",
        )
        if any(marker in error_msg for marker in bad_request_markers):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)
        # 404 — entity lookups (sender/recipient missing)
        if "not found" in error_msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_msg)
        # 409 — state conflicts (already have offer, wrong state, etc.)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_msg)


# ===== POST /me/offers/{offer_id}/accept =====


@router.post("/offers/{offer_id}/accept", response_model=OfferActionResponse)
def accept_offer(
    offer_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    play_service: PlayService = Depends(get_play_service),
):
    """
    Accept an incoming offer. Creates a scheduled match.

    Preconditions:
    - Offer must exist, be pending, and not expired
    - User must be the recipient
    """
    try:
        return play_service.accept_offer(current_user.uid, offer_id)
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_msg)
        if "not the recipient" in error_msg:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=error_msg)
        if "expired" in error_msg:
            raise HTTPException(status_code=status.HTTP_410_GONE, detail=error_msg)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_msg)


# ===== POST /me/offers/{offer_id}/decline =====


@router.post("/offers/{offer_id}/decline", response_model=OfferActionResponse)
def decline_offer(
    offer_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    play_service: PlayService = Depends(get_play_service),
):
    """
    Decline an incoming offer.

    Preconditions:
    - Offer must exist and be pending
    - User must be the recipient
    """
    try:
        return play_service.decline_offer(current_user.uid, offer_id)
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_msg)
        if "not the recipient" in error_msg:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=error_msg)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_msg)


# ===== POST /me/offers/{offer_id}/cancel =====


@router.post("/offers/{offer_id}/cancel", response_model=OfferActionResponse)
def cancel_offer(
    offer_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    play_service: PlayService = Depends(get_play_service),
):
    """
    Cancel an outgoing offer (sender withdraws).

    Preconditions:
    - Offer must exist and be pending
    - User must be the sender
    """
    try:
        return play_service.cancel_offer(current_user.uid, offer_id)
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_msg)
        if "not the sender" in error_msg:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=error_msg)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_msg)
