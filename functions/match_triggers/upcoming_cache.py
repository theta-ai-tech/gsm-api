from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]


def apply_upcoming_cache_update(
    current_cache: list[dict[str, Any]] | None,
    match_id: str,
    scheduled_at: datetime,
    cap: int = 10,
    extra_fields: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
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
