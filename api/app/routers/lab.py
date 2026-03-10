"""
Tab 3 LAB router — progression graph and scoring insights.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.constants import LAB_PROGRESSION_DEFAULT_LIMIT, LAB_PROGRESSION_MAX_LIMIT
from app.dependencies.repos import get_point_history_repo
from app.deps import get_current_user
from app.models.base import GsmBaseModel
from app.models.enums import SportEnum
from app.models.point_history import PointHistoryEntry
from app.repos.point_history_repo import PointHistoryRepo
from app.security import CurrentUser

router = APIRouter(prefix="/me/lab", tags=["lab"])

_401 = {"description": "Missing or invalid Firebase ID token"}


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


def _encode_cursor(entry: PointHistoryEntry) -> str:
    data = {"createdAt": entry.created_at.isoformat(), "entryId": entry.entry_id}
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode()


# ===== Response model =====


class ProgressionResponse(GsmBaseModel):
    sport: SportEnum
    entries: list[PointHistoryEntry]
    cursor: str | None = None
    has_more: bool = False


# ===== GET /me/lab/progression =====


@router.get(
    "/progression",
    response_model=ProgressionResponse,
    summary="Get point history for the progression graph",
    responses={
        400: {"description": "Invalid sport or cursor"},
        401: _401,
    },
)
def get_progression(
    sport: SportEnum = Query(..., description="Sport to filter by"),
    limit: int = Query(
        default=LAB_PROGRESSION_DEFAULT_LIMIT,
        ge=1,
        le=LAB_PROGRESSION_MAX_LIMIT,
        description="Maximum number of entries to return",
    ),
    cursor: str | None = Query(
        default=None, description="Pagination cursor from previous response"
    ),
    current_user: CurrentUser = Depends(get_current_user),
    point_history_repo: PointHistoryRepo = Depends(get_point_history_repo),
) -> ProgressionResponse:
    """
    Return paginated point history for the authenticated user and given sport,
    ordered by createdAt DESC (most recent first).

    Pass the `cursor` value from a previous response to fetch the next page.
    `has_more` indicates whether additional entries exist beyond the current page.
    """
    parsed_cursor = _decode_cursor(cursor)

    # Fetch one extra to detect whether more pages exist.
    entries = point_history_repo.list_entries(
        uid=current_user.uid,
        sport=sport,
        limit=limit + 1,
        cursor=parsed_cursor,
    )

    has_more = len(entries) > limit
    page = entries[:limit]
    next_cursor = _encode_cursor(page[-1]) if has_more else None

    return ProgressionResponse(
        sport=sport,
        entries=page,
        cursor=next_cursor,
        has_more=has_more,
    )
