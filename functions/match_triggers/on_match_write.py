from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class UpcomingQualificationResult:
    qualifies: bool
    reason: str
    match_id: str
    participant_uids: list[str]
    scheduled_at: datetime | None


def _is_aware(value: datetime) -> bool:
    return value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None


def _list_from(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def _get_match_id(before: dict[str, Any] | None, after: dict[str, Any] | None) -> str:
    for source in (after or {}, before or {}):
        for key in ("matchId", "match_id", "id"):
            match_id = source.get(key)
            if match_id:
                return str(match_id)
    return ""


def _has_relevant_change(before: dict[str, Any], after: dict[str, Any]) -> bool:
    for key in ("status", "scheduledAt", "participantUids"):
        if before.get(key) != after.get(key):
            return True
    return False


def qualify_upcoming_match_write(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    now: datetime,
) -> UpcomingQualificationResult:
    match_id = _get_match_id(before, after)
    participant_uids = _list_from((after or {}).get("participantUids"))
    scheduled_at = (after or {}).get("scheduledAt")

    if after is None:
        return UpcomingQualificationResult(
            qualifies=False,
            reason="deleted",
            match_id=match_id,
            participant_uids=_list_from((before or {}).get("participantUids")),
            scheduled_at=(before or {}).get("scheduledAt"),
        )

    status = after.get("status")
    if status != "scheduled":
        return UpcomingQualificationResult(
            qualifies=False,
            reason="status_not_scheduled",
            match_id=match_id,
            participant_uids=participant_uids,
            scheduled_at=scheduled_at if isinstance(scheduled_at, datetime) else None,
        )

    if scheduled_at is None or not isinstance(scheduled_at, datetime):
        return UpcomingQualificationResult(
            qualifies=False,
            reason="scheduled_at_missing",
            match_id=match_id,
            participant_uids=participant_uids,
            scheduled_at=None,
        )

    if not _is_aware(scheduled_at):
        return UpcomingQualificationResult(
            qualifies=False,
            reason="scheduled_at_naive",
            match_id=match_id,
            participant_uids=participant_uids,
            scheduled_at=scheduled_at,
        )

    if scheduled_at <= now:
        return UpcomingQualificationResult(
            qualifies=False,
            reason="scheduled_at_past",
            match_id=match_id,
            participant_uids=participant_uids,
            scheduled_at=scheduled_at,
        )

    if before is not None and not _has_relevant_change(before, after):
        return UpcomingQualificationResult(
            qualifies=False,
            reason="no_op",
            match_id=match_id,
            participant_uids=participant_uids,
            scheduled_at=scheduled_at,
        )

    return UpcomingQualificationResult(
        qualifies=True,
        reason="qualifies",
        match_id=match_id,
        participant_uids=participant_uids,
        scheduled_at=scheduled_at,
    )
