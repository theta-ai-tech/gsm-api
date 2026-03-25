"""
Scheduled ticker TTL cleanup.

Queries the ``ticker`` collection for documents where ``expiresAt <= now``
and deletes them in batches of 500 (Firestore batch-write limit).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]

from functions.logging_utils import log_event

_TRIGGER = "ticker_cleanup"
_COLLECTION = "ticker"
_BATCH_SIZE = 500


def cleanup_expired_ticker_events(
    client: firestore.Client,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Delete all ticker documents whose ``expiresAt`` is in the past or at the boundary.

    Uses ``<=`` to match the read path, which only returns events where
    ``expiresAt > now`` — so exactly-at-boundary docs are already invisible
    to readers and should be cleaned up too.

    Documents are deleted in batches of 500 (Firestore limit).
    Returns a summary dict with the total number of deleted documents.
    """
    if now is None:
        now = datetime.now(tz=timezone.utc)

    query = (
        client.collection(_COLLECTION)
        .where("expiresAt", "<=", now)
    )

    total_deleted = 0

    while True:
        docs = list(query.limit(_BATCH_SIZE).stream())
        if not docs:
            break

        batch = client.batch()
        for doc in docs:
            batch.delete(doc.reference)
        batch.commit()

        deleted_count = len(docs)
        total_deleted += deleted_count

        log_event(
            trigger=_TRIGGER,
            action="batch_delete",
            deleted=deleted_count,
            total_deleted_so_far=total_deleted,
        )

        # If we got fewer than the batch size, there are no more to delete.
        if deleted_count < _BATCH_SIZE:
            break

    summary: dict[str, Any] = {
        "total_deleted": total_deleted,
    }

    log_event(
        trigger=_TRIGGER,
        action="summary",
        changed=total_deleted > 0,
        **summary,
    )

    return summary
