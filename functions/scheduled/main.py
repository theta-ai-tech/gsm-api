"""
Scheduled Cloud Function entry points.

Cloud Scheduler -> Pub/Sub -> Cloud Function.
"""

from __future__ import annotations

from google.cloud import firestore  # type: ignore[import-untyped]

from functions.logging_utils import log_event
from functions.runtime_flags import triggers_enabled
from functions.scheduled.leaderboard_computation import compute_leaderboards
from functions.scheduled.ticker_cleanup import cleanup_expired_ticker_events

_TRIGGER_LEADERBOARD = "D7.leaderboard.scheduled"
_TRIGGER_TICKER = "ticker_cleanup.scheduled"


def handle_leaderboard_computation() -> None:
    """
    Entry point for the scheduled leaderboard computation.
    Called by the Cloud Scheduler via Pub/Sub.
    """
    if not triggers_enabled():
        log_event(
            trigger=_TRIGGER_LEADERBOARD,
            action="ignore",
            reason="triggers_disabled",
            changed=False,
        )
        return

    client = firestore.Client()
    summary = compute_leaderboards(client)

    log_event(
        trigger=_TRIGGER_LEADERBOARD,
        action="completed",
        changed=summary.get("snapshots_written", 0) > 0,
        **summary,
    )


def handle_ticker_cleanup() -> None:
    """
    Entry point for the scheduled ticker TTL cleanup.
    Called by the Cloud Scheduler via Pub/Sub (daily).
    """
    if not triggers_enabled():
        log_event(
            trigger=_TRIGGER_TICKER,
            action="ignore",
            reason="triggers_disabled",
            changed=False,
        )
        return

    client = firestore.Client()
    summary = cleanup_expired_ticker_events(client)

    log_event(
        trigger=_TRIGGER_TICKER,
        action="completed",
        changed=summary.get("total_deleted", 0) > 0,
        **summary,
    )
