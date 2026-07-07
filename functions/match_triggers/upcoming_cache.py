from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]


def derive_opponent(
    participants: list[dict[str, Any]] | None,
    participant_uids: list[str] | None,
    uid: str,
) -> tuple[str | None, str | None]:
    """Return (opponent_uid, opponent_name) for ``uid`` from a match's participants.

    Singles / no team info: the first participant whose uid != uid.
    Doubles (teams present): the first participant on the *other* team.
    Fallback when participants are missing/empty: the first other uid in
    participant_uids, with name None.
    """
    participants = participants or []

    my_team: str | None = None
    for item in participants:
        if item.get("uid") == uid:
            my_team = item.get("team")
            break

    for item in participants:
        other_uid = item.get("uid")
        if not other_uid or other_uid == uid:
            continue
        if my_team is not None and item.get("team") == my_team:
            continue
        return str(other_uid), item.get("displayName")

    for other_uid in participant_uids or []:
        if other_uid and other_uid != uid:
            return str(other_uid), None

    return None, None


def apply_upcoming_cache_update(
    current_cache: list[dict[str, Any]] | None,
    match_id: str,
    scheduled_at: datetime,
    cap: int = 10,
    extra_fields: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    # Covered by unit tests: insert into empty, dedupe on retry, sorted ASC, cap at 10.
    entries = list(current_cache or [])

    existing: dict[str, dict[str, Any]] = {}
    for item in entries:
        item_id = item.get("matchId")
        if item_id:
            existing[str(item_id)] = dict(item)

    new_entry: dict[str, Any] = {"matchId": match_id, "scheduledAt": scheduled_at}
    if match_id in existing:
        new_entry = {**existing[match_id], **new_entry}
    if extra_fields:
        new_entry.update(extra_fields)
    existing[match_id] = new_entry

    def _sort_key(item: dict[str, Any]) -> datetime:
        ts = item.get("scheduledAt")
        if isinstance(ts, datetime):
            return ts
        return datetime.min.replace(tzinfo=timezone.utc)

    ordered = sorted(existing.values(), key=_sort_key)
    return ordered[:cap]


def _derive_upcoming_match_ids(entries: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("matchId")) for item in entries if item.get("matchId")]


def apply_completion_cache_migration(
    upcoming_cache: list[dict[str, Any]] | None,
    completed_cache: list[dict[str, Any]] | None,
    match_id: str,
    finished_at: datetime,
    cap: int = 10,
    extra_fields: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    # Covered by unit tests: remove from upcoming, insert/dedupe in completed, sorted DESC, cap at 10.
    upcoming_entries = [dict(item) for item in (upcoming_cache or [])]
    upcoming_entries = [item for item in upcoming_entries if item.get("matchId") != match_id]

    existing: dict[str, dict[str, Any]] = {}
    for item in completed_cache or []:
        item_id = item.get("matchId")
        if item_id:
            existing[str(item_id)] = dict(item)

    new_entry: dict[str, Any] = {"matchId": match_id, "finishedAt": finished_at}
    if match_id in existing:
        new_entry = {**existing[match_id], **new_entry}
    if extra_fields:
        new_entry.update(extra_fields)
    existing[match_id] = new_entry

    def _sort_key(item: dict[str, Any]) -> datetime:
        ts = item.get("finishedAt")
        if isinstance(ts, datetime):
            return ts
        return datetime.min.replace(tzinfo=timezone.utc)

    ordered = sorted(existing.values(), key=_sort_key, reverse=True)
    return upcoming_entries, ordered[:cap]


def _derive_completed_match_ids(entries: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("matchId")) for item in entries if item.get("matchId")]


def migrate_upcoming_to_completed_for_user(
    client: firestore.Client,
    uid: str,
    match_id: str,
    finished_at: datetime,
    sport: str,
    league_id: str | None = None,
    result: str | None = None,
    score_text: str | None = None,
    opponent_uid: str | None = None,
    opponent_name: str | None = None,
    cap: int = 10,
) -> bool:
    doc_ref = client.collection("users").document(uid)
    transaction = client.transaction()

    @firestore.transactional
    def _apply(transaction: firestore.Transaction) -> bool:
        snapshot = doc_ref.get(transaction=transaction)
        if not snapshot.exists:
            return False
        data = snapshot.to_dict() or {}
        upcoming_cache = data.get("upcomingMatches") or []
        completed_cache = data.get("completedMatches") or []
        extra_fields = {
            "sport": sport,
            "leagueId": league_id,
            "result": result,
            "scoreText": score_text,
            "opponentUid": opponent_uid,
            "opponentName": opponent_name,
        }
        updated_upcoming, updated_completed = apply_completion_cache_migration(
            upcoming_cache=upcoming_cache,
            completed_cache=completed_cache,
            match_id=match_id,
            finished_at=finished_at,
            cap=cap,
            extra_fields=extra_fields,
        )
        updated_upcoming_ids = _derive_upcoming_match_ids(updated_upcoming)
        updated_completed_ids = _derive_completed_match_ids(updated_completed)

        updates: dict[str, Any] = {}
        if upcoming_cache != updated_upcoming:
            updates["upcomingMatches"] = updated_upcoming
        if completed_cache != updated_completed:
            updates["completedMatches"] = updated_completed
        if data.get("upcomingMatchIds") != updated_upcoming_ids:
            updates["upcomingMatchIds"] = updated_upcoming_ids
        if data.get("recentCompletedMatchIds") != updated_completed_ids:
            updates["recentCompletedMatchIds"] = updated_completed_ids

        if updates:
            transaction.update(doc_ref, updates)
            return True
        return False

    return _apply(transaction)


def update_upcoming_cache_for_user(
    client: firestore.Client,
    uid: str,
    match_id: str,
    scheduled_at: datetime,
    sport: str,
    league_id: str | None = None,
    court_id: str | None = None,
    cap: int = 10,
) -> bool:
    doc_ref = client.collection("users").document(uid)
    transaction = client.transaction()

    @firestore.transactional
    def _apply(transaction: firestore.Transaction) -> bool:
        snapshot = doc_ref.get(transaction=transaction)
        if not snapshot.exists:
            return False
        data = snapshot.to_dict() or {}
        current_cache = data.get("upcomingMatches") or []
        extra_fields = {
            "sport": sport,
            "leagueId": league_id,
            "courtId": court_id,
            "opponents": [],
        }
        updated_cache = apply_upcoming_cache_update(
            current_cache=current_cache,
            match_id=match_id,
            scheduled_at=scheduled_at,
            cap=cap,
            extra_fields=extra_fields,
        )
        updated_ids = _derive_upcoming_match_ids(updated_cache)

        updates: dict[str, Any] = {}
        if current_cache != updated_cache:
            updates["upcomingMatches"] = updated_cache
        if data.get("upcomingMatchIds") != updated_ids:
            updates["upcomingMatchIds"] = updated_ids

        if updates:
            transaction.update(doc_ref, updates)
            return True
        return False

    return _apply(transaction)
