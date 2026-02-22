from __future__ import annotations

from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]


# ---------------------------------------------------------------------------
# TR-02 — Streak computation trigger (stub)
#
# Planned behaviour (future implementation):
#
# Trigger:  onWrite  users/{uid}/journalEntries/{entryId}
#
# On each write:
#   1. Read all journalRecent entries for the user (already cached on user doc).
#   2. Walk backwards from today (UTC) counting consecutive days with at least
#      one journal entry — the same algorithm currently in StatsRepo
#      (_compute_weekly_activity / streak_count).
#   3. Persist the result to users/{uid}.currentStreak (int) so clients can
#      read it cheaply without re-computing on every stats fetch.
#
# Why it's deferred:
#   - For MVP, streak is computed on-read by StatsRepo using the
#     journalRecent cache — no extra Firestore write is needed.
#   - A dedicated trigger only becomes worthwhile when the journalRecent
#     window (10 entries) is too small to cover the full streak period, or
#     when we introduce a push notification ("you're on a 7-day streak!").
#
# Dependencies needed before this can be implemented:
#   - A `currentStreak` field on the user doc schema.
#   - Agreement on timezone handling (currently UTC throughout).
#   - The notification service for streak milestone alerts.
# ---------------------------------------------------------------------------


def compute_streak_for_user(
    client: firestore.Client,
    uid: str,
    after: dict[str, Any] | None,
) -> None:
    """
    Stub — recompute and persist streak count for uid after a journal write.

    # TODO: implement when currentStreak field is added to the user doc schema.
    """
    pass
