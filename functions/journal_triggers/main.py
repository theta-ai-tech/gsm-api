from __future__ import annotations

from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]

from functions.journal_triggers.on_journal_entry_write import (
    handle_journal_entry_create,
    handle_journal_entry_delete,
)
from functions.journal_triggers.skill_dna import handle_skill_dna_delete, handle_skill_dna_upsert
from functions.logging_utils import log_event
from functions.runtime_flags import triggers_enabled


def handle_journal_entry_write_upsert(
    client: firestore.Client,
    uid: str,
    entry_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    """
    Entry point for the onWrite trigger — create / update path.

    Fires when a journal entry is created (before=None) or updated.
    Handles: journalRecent cache (TR01.1) + Skill DNA aggregation (D4.1).
    """
    if not triggers_enabled():
        log_event(
            trigger="onJournalEntryWrite.TR01.1",
            action="ignore",
            uid=uid,
            entryId=entry_id,
            reason="triggers_disabled",
            changed=False,
            processed_count=1,
            ignored_count=1,
            writes_count=0,
        )
        return

    if after is None:
        # Deletion — handled by the remove path.
        return

    handle_journal_entry_create(client=client, uid=uid, entry_id=entry_id, after=after)
    handle_skill_dna_upsert(client=client, uid=uid, entry_id=entry_id, after=after)


def handle_journal_entry_write_remove(
    client: firestore.Client,
    uid: str,
    entry_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    """
    Entry point for the onWrite trigger — delete path.

    Fires when `after` is None (document deleted).
    Handles: journalRecent cache (TR01.2) + Skill DNA aggregation (D4.2).
    """
    if not triggers_enabled():
        log_event(
            trigger="onJournalEntryWrite.TR01.2",
            action="ignore",
            uid=uid,
            entryId=entry_id,
            reason="triggers_disabled",
            changed=False,
            processed_count=1,
            ignored_count=1,
            writes_count=0,
        )
        return

    if after is not None:
        # Not a deletion — handled by the upsert path.
        return

    handle_journal_entry_delete(client=client, uid=uid, entry_id=entry_id)
    if before is not None:
        handle_skill_dna_delete(client=client, uid=uid, entry_id=entry_id, before=before)
