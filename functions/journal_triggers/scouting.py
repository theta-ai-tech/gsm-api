from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]

from functions.logging_utils import log_event

_TRIGGER_UPSERT = "onJournalEntryWrite.D4.3"
_TRIGGER_DELETE = "onJournalEntryWrite.D4.4"
_SCOUTING_COLLECTION = "scouting"


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def resolve_opponent_uid(
    reporter_uid: str,
    participant_uids: list[str],
) -> str | None:
    """Return the other participant UID from a two-player match, or None."""
    if len(participant_uids) != 2:
        return None
    others = [uid for uid in participant_uids if uid != reporter_uid]
    return others[0] if others else None


def make_dedup_key(match_id: str, reporter_uid: str) -> str:
    """Deterministic dedup key for one reporter's contribution to one match."""
    return f"{match_id}_{reporter_uid}"


# ---------------------------------------------------------------------------
# Firestore writer — atomic merge with Increment
# ---------------------------------------------------------------------------


def _write_scouting_tags(
    client: firestore.Client,
    opponent_uid: str,
    sport: str,
    weak_tags: list[str],
    strong_tags: list[str],
    dedup_key: str,
    now: datetime,
) -> bool:
    """
    Atomically increment scouting tag counters for an opponent.

    Uses a dedup sub-map to ensure each (matchId, reporterUid) pair is only
    counted once. Returns True if write occurred, False if already processed.
    """
    doc_ref = client.collection(_SCOUTING_COLLECTION).document(opponent_uid)

    txn = client.transaction()

    @firestore.transactional
    def _apply(t: firestore.Transaction) -> bool:
        snap = doc_ref.get(transaction=t)
        data: dict[str, Any] = snap.to_dict() or {} if snap.exists else {}

        sport_data: dict[str, Any] = dict(data.get(sport) or {})
        processed: dict[str, bool] = dict(sport_data.get("processedReports") or {})

        if dedup_key in processed:
            return False

        # Mark as processed
        processed[dedup_key] = True

        # Rebuild weak/strong maps with increments
        weak_map: dict[str, Any] = dict(sport_data.get("weak") or {})
        for tag in weak_tags:
            tag_entry = dict(weak_map.get(tag) or {})
            tag_entry["count"] = int(tag_entry.get("count", 0)) + 1
            tag_entry["lastReported"] = now
            weak_map[tag] = tag_entry

        strong_map: dict[str, Any] = dict(sport_data.get("strong") or {})
        for tag in strong_tags:
            tag_entry = dict(strong_map.get(tag) or {})
            tag_entry["count"] = int(tag_entry.get("count", 0)) + 1
            tag_entry["lastReported"] = now
            strong_map[tag] = tag_entry

        total_reports = int(sport_data.get("totalReports", 0)) + 1
        unique_reporters = int(sport_data.get("uniqueReporters", 0)) + 1

        sport_data["weak"] = weak_map
        sport_data["strong"] = strong_map
        sport_data["totalReports"] = total_reports
        sport_data["uniqueReporters"] = unique_reporters
        sport_data["processedReports"] = processed
        sport_data["lastUpdated"] = now

        write_data: dict[str, Any] = {
            "uid": opponent_uid,
            sport: sport_data,
            "lastUpdated": now,
        }
        t.set(doc_ref, write_data, merge=True)
        return True

    return _apply(txn)


def _remove_scouting_tags(
    client: firestore.Client,
    opponent_uid: str,
    sport: str,
    weak_tags: list[str],
    strong_tags: list[str],
    dedup_key: str,
    now: datetime,
) -> bool:
    """
    Reverse a previously counted scouting report when a journal entry is deleted.

    Only removes if the dedup_key was previously recorded. Decrements counters
    and removes tags that reach zero.
    """
    doc_ref = client.collection(_SCOUTING_COLLECTION).document(opponent_uid)

    txn = client.transaction()

    @firestore.transactional
    def _apply(t: firestore.Transaction) -> bool:
        snap = doc_ref.get(transaction=t)
        if not snap.exists:
            return False
        data: dict[str, Any] = snap.to_dict() or {}

        sport_data: dict[str, Any] = dict(data.get(sport) or {})
        processed: dict[str, bool] = dict(sport_data.get("processedReports") or {})

        if dedup_key not in processed:
            return False

        del processed[dedup_key]

        weak_map: dict[str, Any] = dict(sport_data.get("weak") or {})
        for tag in weak_tags:
            tag_entry = dict(weak_map.get(tag) or {})
            new_count = max(0, int(tag_entry.get("count", 0)) - 1)
            if new_count == 0:
                weak_map.pop(tag, None)
            else:
                tag_entry["count"] = new_count
                weak_map[tag] = tag_entry

        strong_map: dict[str, Any] = dict(sport_data.get("strong") or {})
        for tag in strong_tags:
            tag_entry = dict(strong_map.get(tag) or {})
            new_count = max(0, int(tag_entry.get("count", 0)) - 1)
            if new_count == 0:
                strong_map.pop(tag, None)
            else:
                tag_entry["count"] = new_count
                strong_map[tag] = tag_entry

        sport_data["weak"] = weak_map
        sport_data["strong"] = strong_map
        sport_data["totalReports"] = max(0, int(sport_data.get("totalReports", 0)) - 1)
        sport_data["uniqueReporters"] = max(0, int(sport_data.get("uniqueReporters", 0)) - 1)
        sport_data["processedReports"] = processed
        sport_data["lastUpdated"] = now

        write_data: dict[str, Any] = {
            sport: sport_data,
            "lastUpdated": now,
        }
        t.set(doc_ref, write_data, merge=True)
        return True

    return _apply(txn)


# ---------------------------------------------------------------------------
# Trigger entry points
# ---------------------------------------------------------------------------


def handle_scouting_upsert(
    client: firestore.Client,
    uid: str,
    entry_id: str,
    after: dict[str, Any],
) -> bool:
    """
    Update scouting profile when a journal entry with opponent tags is created/updated.

    Reads opponentWeak/opponentStrong from the reflection, looks up the match
    to determine the opponent, then atomically increments scouting counters.
    """
    trigger = _TRIGGER_UPSERT

    sport: str | None = after.get("sport")
    if not sport:
        log_event(trigger=trigger, action="ignore", uid=uid, entryId=entry_id, reason="no_sport")
        return False

    match_id: str | None = after.get("matchId")
    if not match_id:
        log_event(
            trigger=trigger, action="ignore", uid=uid, entryId=entry_id, reason="no_match_id"
        )
        return False

    reflection: dict[str, Any] = after.get("reflection") or {}
    weak_tags: list[str] = reflection.get("opponentWeak") or []
    strong_tags: list[str] = reflection.get("opponentStrong") or []

    if not weak_tags and not strong_tags:
        log_event(
            trigger=trigger,
            action="ignore",
            uid=uid,
            entryId=entry_id,
            reason="no_opponent_tags",
        )
        return False

    # Look up match to find opponent
    match_snap = client.collection("matches").document(match_id).get()
    if not match_snap.exists:
        log_event(
            trigger=trigger,
            action="ignore",
            uid=uid,
            entryId=entry_id,
            matchId=match_id,
            reason="match_not_found",
        )
        return False

    match_data = match_snap.to_dict() or {}
    participant_uids: list[str] = match_data.get("participantUids") or []
    opponent_uid = resolve_opponent_uid(uid, participant_uids)

    if not opponent_uid:
        log_event(
            trigger=trigger,
            action="ignore",
            uid=uid,
            entryId=entry_id,
            matchId=match_id,
            reason="cannot_resolve_opponent",
        )
        return False

    now = datetime.now(tz=timezone.utc)
    dedup_key = make_dedup_key(match_id, uid)

    changed = _write_scouting_tags(
        client=client,
        opponent_uid=opponent_uid,
        sport=sport,
        weak_tags=weak_tags,
        strong_tags=strong_tags,
        dedup_key=dedup_key,
        now=now,
    )

    log_event(
        trigger=trigger,
        action="upsert",
        uid=uid,
        entryId=entry_id,
        matchId=match_id,
        opponentUid=opponent_uid,
        sport=sport,
        weakCount=len(weak_tags),
        strongCount=len(strong_tags),
        changed=changed,
        writes_count=1 if changed else 0,
    )
    return changed


def handle_scouting_delete(
    client: firestore.Client,
    uid: str,
    entry_id: str,
    before: dict[str, Any],
) -> bool:
    """
    Reverse scouting profile updates when a journal entry is deleted.

    Reads the previous opponent tags from `before` and decrements counters.
    """
    trigger = _TRIGGER_DELETE

    sport: str | None = before.get("sport")
    if not sport:
        log_event(trigger=trigger, action="ignore", uid=uid, entryId=entry_id, reason="no_sport")
        return False

    match_id: str | None = before.get("matchId")
    if not match_id:
        log_event(
            trigger=trigger, action="ignore", uid=uid, entryId=entry_id, reason="no_match_id"
        )
        return False

    reflection: dict[str, Any] = before.get("reflection") or {}
    weak_tags: list[str] = reflection.get("opponentWeak") or []
    strong_tags: list[str] = reflection.get("opponentStrong") or []

    if not weak_tags and not strong_tags:
        log_event(
            trigger=trigger,
            action="ignore",
            uid=uid,
            entryId=entry_id,
            reason="no_opponent_tags",
        )
        return False

    # Look up match to find opponent
    match_snap = client.collection("matches").document(match_id).get()
    if not match_snap.exists:
        log_event(
            trigger=trigger,
            action="ignore",
            uid=uid,
            entryId=entry_id,
            matchId=match_id,
            reason="match_not_found",
        )
        return False

    match_data = match_snap.to_dict() or {}
    participant_uids: list[str] = match_data.get("participantUids") or []
    opponent_uid = resolve_opponent_uid(uid, participant_uids)

    if not opponent_uid:
        log_event(
            trigger=trigger,
            action="ignore",
            uid=uid,
            entryId=entry_id,
            matchId=match_id,
            reason="cannot_resolve_opponent",
        )
        return False

    now = datetime.now(tz=timezone.utc)
    dedup_key = make_dedup_key(match_id, uid)

    changed = _remove_scouting_tags(
        client=client,
        opponent_uid=opponent_uid,
        sport=sport,
        weak_tags=weak_tags,
        strong_tags=strong_tags,
        dedup_key=dedup_key,
        now=now,
    )

    log_event(
        trigger=trigger,
        action="remove",
        uid=uid,
        entryId=entry_id,
        matchId=match_id,
        opponentUid=opponent_uid,
        sport=sport,
        changed=changed,
        writes_count=1 if changed else 0,
    )
    return changed
