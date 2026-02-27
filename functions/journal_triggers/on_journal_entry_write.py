from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]

from functions.logging_utils import log_event


# ---------------------------------------------------------------------------
# Pure cache-mutation helpers (fully testable without Firestore)
# ---------------------------------------------------------------------------


def apply_journal_recent_update(
    current_cache: list[dict[str, Any]] | None,
    entry_id: str,
    summary: dict[str, Any],
    cap: int = 10,
) -> list[dict[str, Any]]:
    """
    Upsert a journal entry summary into the journalRecent cache.

    - Idempotent: if an entry with the same entryId already exists it is
      replaced in place; otherwise the summary is prepended.
    - Sorted newest-first by createdAt.
    - Result is capped at `cap` entries.
    """
    entries: dict[str, dict[str, Any]] = {}
    for item in (current_cache or []):
        item_id = item.get("entryId")
        if item_id:
            entries[str(item_id)] = dict(item)

    entries[entry_id] = dict(summary)
    entries[entry_id]["entryId"] = entry_id  # guarantee the key is present

    def _sort_key(item: dict[str, Any]) -> datetime:
        ts = item.get("createdAt")
        if isinstance(ts, datetime):
            return ts
        return datetime.min.replace(tzinfo=timezone.utc)

    ordered = sorted(entries.values(), key=_sort_key, reverse=True)
    return ordered[:cap]


def apply_journal_recent_removal(
    current_cache: list[dict[str, Any]] | None,
    entry_id: str,
) -> list[dict[str, Any]]:
    """
    Remove a journal entry summary from the journalRecent cache.

    Idempotent: safe to call even if the entry is not in the cache.
    """
    return [
        item for item in (current_cache or []) if item.get("entryId") != entry_id
    ]


# ---------------------------------------------------------------------------
# Transactional Firestore writers
# ---------------------------------------------------------------------------


def _update_journal_recent(
    client: firestore.Client,
    uid: str,
    entry_id: str,
    summary: dict[str, Any],
    cap: int = 10,
) -> bool:
    doc_ref = client.collection("users").document(uid)
    transaction = client.transaction()

    @firestore.transactional
    def _apply(txn: firestore.Transaction) -> bool:
        snapshot = doc_ref.get(transaction=txn)
        if not snapshot.exists:
            return False
        data = snapshot.to_dict() or {}
        current = data.get("journalRecent") or []
        updated = apply_journal_recent_update(current, entry_id, summary, cap=cap)

        if updated == current:
            return False
        txn.update(doc_ref, {"journalRecent": updated})
        return True

    return _apply(transaction)


def _remove_from_journal_recent(
    client: firestore.Client,
    uid: str,
    entry_id: str,
) -> bool:
    doc_ref = client.collection("users").document(uid)
    transaction = client.transaction()

    @firestore.transactional
    def _apply(txn: firestore.Transaction) -> bool:
        snapshot = doc_ref.get(transaction=txn)
        if not snapshot.exists:
            return False
        data = snapshot.to_dict() or {}
        current = data.get("journalRecent") or []
        updated = apply_journal_recent_removal(current, entry_id)

        if updated == current:
            return False
        txn.update(doc_ref, {"journalRecent": updated})
        return True

    return _apply(transaction)


# ---------------------------------------------------------------------------
# Trigger handler entry points
# ---------------------------------------------------------------------------


def handle_journal_entry_create(
    client: firestore.Client,
    uid: str,
    entry_id: str,
    after: dict[str, Any],
) -> bool:
    """
    Upsert a summary for a newly created journal entry into journalRecent.

    Provides a safety net for the API transaction in SV-01: if the
    transaction succeeded the upsert will be a no-op (idempotent).
    """
    trigger_name = "onJournalEntryWrite.TR01.1"
    processed_count = 1
    ignored_count = 0
    writes_count = 0

    summary: dict[str, Any] = {
        "entryId": entry_id,
        "createdAt": after.get("createdAt"),
        "title": after.get("title", ""),
        "matchId": after.get("matchId"),
        "sport": after.get("sport"),
        "entryType": after.get("entryType"),
    }

    if not summary["createdAt"]:
        ignored_count = 1
        log_event(
            trigger=trigger_name,
            action="ignore",
            uid=uid,
            entryId=entry_id,
            reason="createdAt_missing",
            changed=False,
            processed_count=processed_count,
            ignored_count=ignored_count,
            writes_count=writes_count,
        )
        return False

    changed = _update_journal_recent(
        client=client, uid=uid, entry_id=entry_id, summary=summary
    )
    if changed:
        writes_count = 1

    log_event(
        trigger=trigger_name,
        action="upsert",
        uid=uid,
        entryId=entry_id,
        changed=changed,
    )
    log_event(
        trigger=trigger_name,
        action="summary",
        uid=uid,
        entryId=entry_id,
        changed=changed,
        processed_count=processed_count,
        ignored_count=ignored_count,
        writes_count=writes_count,
    )
    return changed


def handle_journal_entry_delete(
    client: firestore.Client,
    uid: str,
    entry_id: str,
) -> bool:
    """
    Remove the summary for a deleted journal entry from journalRecent.
    """
    trigger_name = "onJournalEntryWrite.TR01.2"
    processed_count = 1
    writes_count = 0

    changed = _remove_from_journal_recent(client=client, uid=uid, entry_id=entry_id)
    if changed:
        writes_count = 1

    log_event(
        trigger=trigger_name,
        action="remove",
        uid=uid,
        entryId=entry_id,
        changed=changed,
    )
    log_event(
        trigger=trigger_name,
        action="summary",
        uid=uid,
        entryId=entry_id,
        changed=changed,
        processed_count=processed_count,
        ignored_count=0,
        writes_count=writes_count,
    )
    return changed
