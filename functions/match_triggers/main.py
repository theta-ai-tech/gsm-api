from __future__ import annotations
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]

from functions.match_triggers.on_match_write import (
    qualify_completion_match_write,
    qualify_upcoming_match_write,
)
from functions.match_triggers.upcoming_cache import (
    migrate_upcoming_to_completed_for_user,
    update_upcoming_cache_for_user,
)
from functions.logging_utils import log_event, summarize_uids
from functions.runtime_flags import triggers_enabled


def _extract_match_id(before: dict[str, Any] | None, after: dict[str, Any] | None) -> str | None:
    for source in (after or {}, before or {}):
        match_id = source.get("matchId") or source.get("match_id") or source.get("id")
        if match_id:
            return str(match_id)
    return None


def handle_match_write_update_upcoming_cache(
    client: firestore.Client,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    now: datetime | None = None,
) -> None:
    trigger_name = "onMatchWrite.D1"
    match_id = _extract_match_id(before, after)
    processed_count = 1
    ignored_count = 0
    writes_count = 0

    if not triggers_enabled():
        log_event(
            trigger=trigger_name,
            action="ignore",
            matchId=match_id,
            reason="triggers_disabled",
            changed=False,
            processed_count=processed_count,
            ignored_count=1,
            writes_count=writes_count,
        )
        return

    if now is None:
        now = datetime.now(timezone.utc)

    result = qualify_upcoming_match_write(before, after, now)
    log_event(
        trigger=trigger_name,
        action="qualify",
        matchId=result.match_id or match_id,
        reason=result.reason,
        qualifies=result.qualifies,
        changed=False,
        **summarize_uids(result.participant_uids),
    )
    if not result.qualifies or after is None or result.scheduled_at is None:
        ignored_count = 1
        log_event(
            trigger=trigger_name,
            action="summary",
            matchId=result.match_id or match_id,
            changed=False,
            processed_count=processed_count,
            ignored_count=ignored_count,
            writes_count=writes_count,
            **summarize_uids(result.participant_uids),
        )
        return

    sport = after.get("sport")
    if not sport:
        ignored_count = 1
        log_event(
            trigger=trigger_name,
            action="ignore",
            matchId=result.match_id or match_id,
            reason="sport_missing",
            changed=False,
            processed_count=processed_count,
            ignored_count=ignored_count,
            writes_count=writes_count,
            **summarize_uids(result.participant_uids),
        )
        return

    league_id = after.get("leagueId")
    court_id = after.get("courtId")

    for uid in result.participant_uids:
        changed = update_upcoming_cache_for_user(
            client=client,
            uid=uid,
            match_id=result.match_id,
            scheduled_at=result.scheduled_at,
            sport=str(sport),
            league_id=league_id,
            court_id=court_id,
        )
        if changed:
            writes_count += 1
        log_event(
            trigger=trigger_name,
            action="upsert_upcoming_cache",
            matchId=result.match_id,
            uid=uid,
            changed=changed,
        )

    log_event(
        trigger=trigger_name,
        action="summary",
        matchId=result.match_id,
        changed=writes_count > 0,
        processed_count=processed_count,
        ignored_count=ignored_count,
        writes_count=writes_count,
        **summarize_uids(result.participant_uids),
    )


def handle_match_write_migrate_on_completion(
    client: firestore.Client,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    now: datetime | None = None,
) -> None:
    trigger_name = "onMatchWrite.D2"
    match_id = _extract_match_id(before, after)
    processed_count = 1
    ignored_count = 0
    writes_count = 0

    if not triggers_enabled():
        log_event(
            trigger=trigger_name,
            action="ignore",
            matchId=match_id,
            reason="triggers_disabled",
            changed=False,
            processed_count=processed_count,
            ignored_count=1,
            writes_count=writes_count,
        )
        return

    if now is None:
        now = datetime.now(timezone.utc)

    result = qualify_completion_match_write(before, after, now)
    log_event(
        trigger=trigger_name,
        action="qualify",
        matchId=result.match_id or match_id,
        reason=result.reason,
        qualifies=result.qualifies,
        changed=False,
        **summarize_uids(result.participant_uids),
    )
    if not result.qualifies or after is None or result.finished_at is None:
        ignored_count = 1
        log_event(
            trigger=trigger_name,
            action="summary",
            matchId=result.match_id or match_id,
            changed=False,
            processed_count=processed_count,
            ignored_count=ignored_count,
            writes_count=writes_count,
            **summarize_uids(result.participant_uids),
        )
        return

    sport = after.get("sport")
    if not sport:
        ignored_count = 1
        log_event(
            trigger=trigger_name,
            action="ignore",
            matchId=result.match_id or match_id,
            reason="sport_missing",
            changed=False,
            processed_count=processed_count,
            ignored_count=ignored_count,
            writes_count=writes_count,
            **summarize_uids(result.participant_uids),
        )
        return

    league_id = after.get("leagueId")
    result_by_user = after.get("resultByUser") or {}
    score = after.get("score") or {}
    score_text = score.get("scoreText")

    for uid in result.participant_uids:
        changed = migrate_upcoming_to_completed_for_user(
            client=client,
            uid=uid,
            match_id=result.match_id,
            finished_at=result.finished_at,
            sport=str(sport),
            league_id=league_id,
            result=result_by_user.get(uid),
            score_text=score_text,
        )
        if changed:
            writes_count += 1
        log_event(
            trigger=trigger_name,
            action="migrate_upcoming_to_recent",
            matchId=result.match_id,
            uid=uid,
            changed=changed,
        )

    log_event(
        trigger=trigger_name,
        action="summary",
        matchId=result.match_id,
        changed=writes_count > 0,
        processed_count=processed_count,
        ignored_count=ignored_count,
        writes_count=writes_count,
        **summarize_uids(result.participant_uids),
    )
