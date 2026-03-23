"""
D7 — Scheduled leaderboard computation entry point.

Cloud Scheduler -> Pub/Sub -> this Cloud Function (hourly).
"""

from __future__ import annotations

from google.cloud import firestore  # type: ignore[import-untyped]

from functions.logging_utils import log_event
from functions.runtime_flags import triggers_enabled
from functions.scheduled.leaderboard_computation import compute_leaderboards

_TRIGGER = "D7.leaderboard.scheduled"


def handle_leaderboard_computation() -> None:
    """
    Entry point for the scheduled leaderboard computation.
    Called by the Cloud Scheduler via Pub/Sub.
    """
    if not triggers_enabled():
        log_event(
            trigger=_TRIGGER,
            action="ignore",
            reason="triggers_disabled",
            changed=False,
        )
        return

    client = firestore.Client()
    summary = compute_leaderboards(client)

    log_event(
        trigger=_TRIGGER,
        action="completed",
        changed=summary.get("snapshots_written", 0) > 0,
        **summary,
    )
