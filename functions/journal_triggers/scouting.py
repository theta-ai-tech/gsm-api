from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]

from functions.logging_utils import log_event

_TRIGGER_UPSERT = "onJournalEntryWrite.D4.3"
_TRIGGER_DELETE = "onJournalEntryWrite.D4.4"
_SCOUTING_COLLECTION = "scouting"
_PROCESSED_SUBCOLLECTION = "processedReports"


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


def hash_dedup_key(match_id: str, reporter_uid: str) -> str:
    """One-way SHA-256 hash of the dedup key. No raw UIDs stored in Firestore."""
    raw = f"{match_id}_{reporter_uid}"
    return hashlib.sha256(raw.encode()).hexdigest()


def hash_reporter(reporter_uid: str) -> str:
    """One-way SHA-256 hash of a reporter UID for anonymous unique counting."""
    return hashlib.sha256(reporter_uid.encode()).hexdigest()


def make_tag_sig(weak_tags: list[str], strong_tags: list[str]) -> str:
    """Deterministic signature for a set of scouting tags (used for idempotency)."""
    return ",".join(sorted(weak_tags)) + "|" + ",".join(sorted(strong_tags))


def parse_tag_sig(sig: str) -> tuple[list[str], list[str]]:
    """Parse a stored signature back to (weak_tags, strong_tags) lists."""
    parts = sig.split("|", 1)
    weak = [t for t in parts[0].split(",") if t]
    strong = [t for t in (parts[1] if len(parts) > 1 else "").split(",") if t]
    return weak, strong


def compute_tag_delta(
    old_weak: list[str],
    old_strong: list[str],
    new_weak: list[str],
    new_strong: list[str],
) -> tuple[dict[str, int], dict[str, int]]:
    """Compute per-tag increments/decrements between old and new tag sets.

    Returns (weak_deltas, strong_deltas) where each is {tag: delta_int}.
    Positive means increment, negative means decrement.
    """
    weak_deltas: dict[str, int] = {}
    for tag in new_weak:
        weak_deltas[tag] = weak_deltas.get(tag, 0) + 1
    for tag in old_weak:
        weak_deltas[tag] = weak_deltas.get(tag, 0) - 1
    # Remove zero-deltas
    weak_deltas = {k: v for k, v in weak_deltas.items() if v != 0}

    strong_deltas: dict[str, int] = {}
    for tag in new_strong:
        strong_deltas[tag] = strong_deltas.get(tag, 0) + 1
    for tag in old_strong:
        strong_deltas[tag] = strong_deltas.get(tag, 0) - 1
    strong_deltas = {k: v for k, v in strong_deltas.items() if v != 0}

    return weak_deltas, strong_deltas


# ---------------------------------------------------------------------------
# Firestore writers — subcollection for dedup, transaction for counters
# ---------------------------------------------------------------------------


def _apply_scouting_delta(
    client: firestore.Client,
    opponent_uid: str,
    sport: str,
    weak_deltas: dict[str, int],
    strong_deltas: dict[str, int],
    reporter_hash: str,
    is_new_reporter: bool,
    reporter_removed: bool,
    total_reports_delta: int,
    now: datetime,
) -> None:
    """Transactionally apply tag count deltas to the main scouting document."""
    doc_ref = client.collection(_SCOUTING_COLLECTION).document(opponent_uid)
    txn = client.transaction()

    @firestore.transactional
    def _apply(t: firestore.Transaction) -> None:
        snap = doc_ref.get(transaction=t)
        data: dict[str, Any] = snap.to_dict() or {} if snap.exists else {}

        sport_data: dict[str, Any] = dict(data.get(sport) or {})

        # Apply weak tag deltas
        weak_map: dict[str, Any] = dict(sport_data.get("weak") or {})
        for tag, delta in weak_deltas.items():
            tag_entry = dict(weak_map.get(tag) or {})
            new_count = max(0, int(tag_entry.get("count", 0)) + delta)
            if new_count == 0:
                weak_map.pop(tag, None)
            else:
                tag_entry["count"] = new_count
                if delta > 0:
                    tag_entry["lastReported"] = now
                weak_map[tag] = tag_entry

        # Apply strong tag deltas
        strong_map: dict[str, Any] = dict(sport_data.get("strong") or {})
        for tag, delta in strong_deltas.items():
            tag_entry = dict(strong_map.get(tag) or {})
            new_count = max(0, int(tag_entry.get("count", 0)) + delta)
            if new_count == 0:
                strong_map.pop(tag, None)
            else:
                tag_entry["count"] = new_count
                if delta > 0:
                    tag_entry["lastReported"] = now
                strong_map[tag] = tag_entry

        # Update totalReports
        sport_data["totalReports"] = max(
            0, int(sport_data.get("totalReports", 0)) + total_reports_delta
        )

        # Update uniqueReporters via anonymous reporter hash counts
        reporter_counts: dict[str, int] = dict(
            sport_data.get("_reporterCounts") or {}
        )
        if is_new_reporter:
            reporter_counts[reporter_hash] = (
                reporter_counts.get(reporter_hash, 0) + 1
            )
        if reporter_removed:
            cur = reporter_counts.get(reporter_hash, 0) - 1
            if cur <= 0:
                reporter_counts.pop(reporter_hash, None)
            else:
                reporter_counts[reporter_hash] = cur
        sport_data["_reporterCounts"] = reporter_counts
        sport_data["uniqueReporters"] = len(reporter_counts)

        sport_data["weak"] = weak_map
        sport_data["strong"] = strong_map
        sport_data["lastUpdated"] = now

        # Overwrite the full document (no merge) so that removed nested keys
        # (e.g. a tag whose count dropped to 0) are actually deleted.
        # Safe because we read the full doc inside this transaction.
        data["uid"] = opponent_uid
        data[sport] = sport_data
        data["lastUpdated"] = now
        t.set(doc_ref, data)

    _apply(txn)


def _upsert_scouting(
    client: firestore.Client,
    opponent_uid: str,
    sport: str,
    weak_tags: list[str],
    strong_tags: list[str],
    dedup_hash: str,
    reporter_hash: str,
    now: datetime,
) -> bool:
    """Create or update a scouting report using before/after diff.

    Stores the report signature in a subcollection for dedup and privacy.
    Computes a delta against any previous report with the same dedup key
    and applies it to the main scouting document.
    """
    subcoll_ref = (
        client.collection(_SCOUTING_COLLECTION)
        .document(opponent_uid)
        .collection(_PROCESSED_SUBCOLLECTION)
    )
    report_ref = subcoll_ref.document(dedup_hash)

    new_sig = make_tag_sig(weak_tags, strong_tags)

    # Read existing report for this dedup key (if any)
    existing_snap = report_ref.get()
    if existing_snap.exists:
        existing_data = existing_snap.to_dict() or {}
        old_sig = existing_data.get("tagSig", "")
        if old_sig == new_sig:
            return False  # idempotent — same tags already stored
        old_weak, old_strong = parse_tag_sig(old_sig)
        is_new_reporter = False
    else:
        old_weak, old_strong = [], []
        is_new_reporter = True

    weak_deltas, strong_deltas = compute_tag_delta(
        old_weak, old_strong, weak_tags, strong_tags
    )

    total_reports_delta = 1 if not existing_snap.exists else 0

    # Write subcollection doc (outside the main-doc transaction)
    report_ref.set({
        "sport": sport,
        "tagSig": new_sig,
        "reporterHash": reporter_hash,
        "updatedAt": now,
    })

    # Apply delta to main scouting doc
    _apply_scouting_delta(
        client=client,
        opponent_uid=opponent_uid,
        sport=sport,
        weak_deltas=weak_deltas,
        strong_deltas=strong_deltas,
        reporter_hash=reporter_hash,
        is_new_reporter=is_new_reporter,
        reporter_removed=False,
        total_reports_delta=total_reports_delta,
        now=now,
    )
    return True


def _remove_scouting(
    client: firestore.Client,
    opponent_uid: str,
    sport: str,
    dedup_hash: str,
    now: datetime,
) -> bool:
    """Reverse a scouting report when a journal entry is deleted.

    Reads the stored tags from the subcollection, decrements counters,
    then deletes the subcollection doc.
    """
    subcoll_ref = (
        client.collection(_SCOUTING_COLLECTION)
        .document(opponent_uid)
        .collection(_PROCESSED_SUBCOLLECTION)
    )
    report_ref = subcoll_ref.document(dedup_hash)

    existing_snap = report_ref.get()
    if not existing_snap.exists:
        return False

    existing_data = existing_snap.to_dict() or {}
    old_sig = existing_data.get("tagSig", "")
    reporter_hash_val: str = existing_data.get("reporterHash", "")
    old_weak, old_strong = parse_tag_sig(old_sig)

    # Compute delta: removing all old tags
    weak_deltas = {tag: -1 for tag in old_weak}
    strong_deltas = {tag: -1 for tag in old_strong}

    # Check if this reporter has other reports in the subcollection
    reporter_removed = True
    for doc in subcoll_ref.where(
        "reporterHash", "==", reporter_hash_val
    ).limit(2).stream():
        if doc.id != dedup_hash:
            reporter_removed = False
            break

    # Delete subcollection doc first
    report_ref.delete()

    # Apply reverse delta to main scouting doc
    _apply_scouting_delta(
        client=client,
        opponent_uid=opponent_uid,
        sport=sport,
        weak_deltas=weak_deltas,
        strong_deltas=strong_deltas,
        reporter_hash=reporter_hash_val,
        is_new_reporter=False,
        reporter_removed=reporter_removed,
        total_reports_delta=-1,
        now=now,
    )
    return True


# ---------------------------------------------------------------------------
# Trigger entry points
# ---------------------------------------------------------------------------


def handle_scouting_upsert(
    client: firestore.Client,
    uid: str,
    entry_id: str,
    after: dict[str, Any],
) -> bool:
    """Update scouting profile when a journal entry with opponent tags is created/updated.

    Reads opponentWeak/opponentStrong from the reflection, looks up the match
    to determine the opponent, then applies a before/after diff to scouting counters.
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
    dedup_h = hash_dedup_key(match_id, uid)
    reporter_h = hash_reporter(uid)

    changed = _upsert_scouting(
        client=client,
        opponent_uid=opponent_uid,
        sport=sport,
        weak_tags=weak_tags,
        strong_tags=strong_tags,
        dedup_hash=dedup_h,
        reporter_hash=reporter_h,
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
    """Reverse scouting profile updates when a journal entry is deleted.

    Reads the stored tags from the processedReports subcollection and
    decrements counters accordingly.
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
    dedup_h = hash_dedup_key(match_id, uid)

    changed = _remove_scouting(
        client=client,
        opponent_uid=opponent_uid,
        sport=sport,
        dedup_hash=dedup_h,
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
