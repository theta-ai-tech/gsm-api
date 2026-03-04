"""
D5.1 — Global ranking recomputation on match completion.

Triggered by Firestore document updates on matches/{matchId}.
Qualifies when status transitions to 'completed' (any prior status).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]

from functions.logging_utils import log_event
from functions.match_triggers.on_match_write import qualify_ranking_recomputation
from functions.runtime_flags import triggers_enabled
from functions.scoring_triggers.global_ranking import recompute_global_ranking

_TRIGGER = "onMatchWrite.D5.1"


def _extract_match_id(before: dict[str, Any] | None, after: dict[str, Any] | None) -> str | None:
    for source in (after or {}, before or {}):
        match_id = source.get("matchId") or source.get("match_id") or source.get("id")
        if match_id:
            return str(match_id)
    return None


def handle_match_write_recompute_global_ranking(
    client: firestore.Client,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    now: datetime | None = None,
) -> None:
    """
    On match completion, recompute globalRanking ordinals for all users in that sport.

    Points update inline (SE-5); rank positions update here asynchronously.
    """
    match_id = _extract_match_id(before, after)

    if not triggers_enabled():
        log_event(
            trigger=_TRIGGER,
            action="ignore",
            matchId=match_id,
            reason="triggers_disabled",
            changed=False,
            processed_count=1,
            ignored_count=1,
            writes_count=0,
        )
        return

    if now is None:
        now = datetime.now(timezone.utc)

    result = qualify_ranking_recomputation(before, after, now)
    log_event(
        trigger=_TRIGGER,
        action="qualify",
        matchId=result.match_id or match_id,
        reason=result.reason,
        qualifies=result.qualifies,
        changed=False,
    )

    if not result.qualifies or after is None:
        log_event(
            trigger=_TRIGGER,
            action="summary",
            matchId=result.match_id or match_id,
            changed=False,
            processed_count=1,
            ignored_count=1,
            writes_count=0,
        )
        return

    sport = after.get("sport")
    if not sport:
        log_event(
            trigger=_TRIGGER,
            action="ignore",
            matchId=result.match_id or match_id,
            reason="sport_missing",
            changed=False,
            processed_count=1,
            ignored_count=1,
            writes_count=0,
        )
        return

    users_updated = recompute_global_ranking(client, str(sport), now)

    log_event(
        trigger=_TRIGGER,
        action="summary",
        matchId=result.match_id,
        sport=str(sport),
        changed=users_updated > 0,
        processed_count=1,
        ignored_count=0,
        writes_count=users_updated,
        users_updated=users_updated,
    )
