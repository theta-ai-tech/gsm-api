"""
Tab 2 IMPROVE router - Journal and stats endpoints.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from google.cloud import firestore  # type: ignore[attr-defined, import-untyped]

from app.dependencies.repos import (
    get_firestore_client,
    get_journal_repo,
    get_matches_repo,
    get_users_repo,
)
from app.deps import get_current_user
from pydantic import Field
from app.models.base import GsmBaseModel
from app.models.journal import (
    CreateJournalEntryRequest,
    CreateJournalEntryResponse,
    JournalEntry,
    UpdateJournalEntryRequest,
)
from app.models.stats import NorthStarGoal, UserStats
from app.repos.journal_repo import JournalRepo
from app.repos.matches_repo import MatchesRepo
from app.repos.users_repo import UsersRepo
from app.security import CurrentUser
from app.services.journal_service import JournalService

router = APIRouter(prefix="/me", tags=["improve"])

# ===== Common response descriptions =====

_401 = {"description": "Missing or invalid Firebase ID token"}
_403 = {"description": "Entry belongs to a different user"}
_404_entry = {"description": "Journal entry not found"}
_404_user = {"description": "User not found"}
_422 = {"description": "Validation error — see `details` array in response body"}


# ===== Dependency =====


def get_journal_service(
    users_repo: UsersRepo = Depends(get_users_repo),
    journal_repo: JournalRepo = Depends(get_journal_repo),
    matches_repo: MatchesRepo = Depends(get_matches_repo),
    firestore_client: firestore.Client = Depends(get_firestore_client),
) -> JournalService:
    return JournalService(users_repo, journal_repo, matches_repo, firestore_client)


# ===== Cursor helpers =====


def _decode_cursor(cursor_str: str | None) -> dict | None:
    if not cursor_str:
        return None
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor_str.encode()))
        created_at_raw = data.get("createdAt")
        if created_at_raw:
            data["createdAt"] = datetime.fromisoformat(created_at_raw)
        return data
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cursor")


def _encode_cursor(entry: JournalEntry) -> str:
    data = {"createdAt": entry.created_at.isoformat(), "entryId": entry.entry_id}
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()


# ===== Response models =====


class JournalListResponse(GsmBaseModel):
    entries: list[JournalEntry]
    next_cursor: str | None = None


class JournalUpdateResponse(GsmBaseModel):
    entry_id: str
    updated: bool = True


class SetNorthStarRequest(GsmBaseModel):
    goal_text: str = Field(max_length=500)
    target_date: datetime | None = None


# ===== GET /me/journal =====


@router.get(
    "/journal",
    response_model=JournalListResponse,
    summary="List journal entries",
    responses={
        400: {"description": "Invalid cursor token"},
        401: _401,
    },
)
def list_journal_entries(
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None),
    current_user: CurrentUser = Depends(get_current_user),
    journal_service: JournalService = Depends(get_journal_service),
):
    """
    List the authenticated user's journal entries, sorted by createdAt DESC.

    Pagination is cursor-based. Pass the `next_cursor` value from a previous
    response as the `cursor` query param to fetch the next page.
    Returns an empty list for users with no entries.
    """
    parsed_cursor = _decode_cursor(cursor)
    entries = journal_service.list_entries(current_user.uid, limit=limit, cursor=parsed_cursor)
    next_cursor = _encode_cursor(entries[-1]) if len(entries) == limit else None
    return JournalListResponse(entries=entries, next_cursor=next_cursor)


# ===== POST /me/journal =====


@router.post(
    "/journal",
    response_model=CreateJournalEntryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a journal entry",
    responses={
        401: _401,
        404: _404_user,
        409: {"description": "Business rule conflict (e.g. duplicate match entry)"},
        422: _422,
    },
)
def create_journal_entry(
    request: CreateJournalEntryRequest,
    current_user: CurrentUser = Depends(get_current_user),
    journal_service: JournalService = Depends(get_journal_service),
):
    """
    Create a journal entry (match or training).

    Atomically writes the entry document and prepends a summary to
    the journalRecent cache on the user document.
    Returns 422 for validation errors (e.g. missing duration on training entries).
    """
    try:
        return journal_service.create_entry(current_user.uid, request)
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_msg)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_msg)


# ===== PATCH /me/journal/{entry_id} =====


@router.patch(
    "/journal/{entry_id}",
    response_model=JournalUpdateResponse,
    summary="Update a journal entry",
    responses={
        401: _401,
        403: _403,
        404: _404_entry,
        409: {"description": "Update rejected due to a business rule conflict"},
    },
)
def update_journal_entry(
    entry_id: str,
    request: UpdateJournalEntryRequest,
    current_user: CurrentUser = Depends(get_current_user),
    journal_service: JournalService = Depends(get_journal_service),
):
    """
    Enrich an existing journal entry with reflection data (tags, body, skill tags).

    Only fields set in the request body are written; unset fields are left
    unchanged. Returns 404 if the entry does not exist, 403 if it belongs
    to a different user.
    """
    try:
        journal_service.update_entry(current_user.uid, entry_id, request)
        return JournalUpdateResponse(entry_id=entry_id)
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_msg)
        if "does not belong" in error_msg:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=error_msg)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error_msg)


# ===== GET /me/stats =====


@router.get(
    "/stats",
    response_model=UserStats,
    summary="Get dashboard statistics",
    responses={
        401: _401,
        404: _404_user,
    },
)
def get_dashboard_stats(
    current_user: CurrentUser = Depends(get_current_user),
    journal_service: JournalService = Depends(get_journal_service),
):
    """
    Return dashboard statistics for the authenticated user.

    Computes weekly activity, streak count, and aggregate match/training
    totals from cached data on the user doc — no expensive Firestore queries.
    Returns sensible defaults (all zeros, empty activity map) for new users.
    """
    try:
        return journal_service.get_dashboard_stats(current_user.uid)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


# ===== GET /me/journal/{entry_id} =====


@router.get(
    "/journal/{entry_id}",
    response_model=JournalEntry,
    summary="Get a journal entry",
    responses={
        401: _401,
        404: _404_entry,
    },
)
def get_journal_entry(
    entry_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    journal_service: JournalService = Depends(get_journal_service),
):
    """
    Fetch a single journal entry for the authenticated user.

    Returns 404 if the entry does not exist or belongs to a different user.
    Ownership is implicitly enforced by the Firestore subcollection path
    (users/{uid}/journalEntries/{entry_id}), so no explicit 403 is needed —
    another user's entry is simply not found under the caller's path.
    """
    entry = journal_service.get_entry(current_user.uid, entry_id)
    if entry is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Journal entry {entry_id!r} not found",
        )
    return entry


# ===== PUT /me/north-star =====


@router.put(
    "/north-star",
    response_model=NorthStarGoal,
    summary="Set North Star goal",
    responses={
        401: _401,
        404: _404_user,
    },
)
def set_north_star(
    request: SetNorthStarRequest,
    current_user: CurrentUser = Depends(get_current_user),
    journal_service: JournalService = Depends(get_journal_service),
):
    """
    Upsert the authenticated user's North Star goal.

    Always overwrites any previous goal, resets progress to 0%, and stamps
    a new createdAt. target_date is optional.
    """
    try:
        return journal_service.set_north_star(
            current_user.uid,
            goal_text=request.goal_text,
            target_date=request.target_date,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
