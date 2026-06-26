from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone

from google.cloud import firestore  # type: ignore[import-untyped]

from functions.match_triggers.main import (
    handle_match_write_migrate_on_completion,
    handle_match_write_update_upcoming_cache,
)

# Notification-delivery smoke tuning. The deployed onNotificationIntentCreated trigger
# stamps a no-tokens intent within a couple of seconds; poll briefly rather than forever.
_NOTIFICATION_POLL_TIMEOUT_SECONDS = 30.0
_NOTIFICATION_POLL_INTERVAL_SECONDS = 1.0


def _require(value: bool, message: str) -> None:
    if not value:
        raise RuntimeError(message)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _create_user_doc(client: firestore.Client, uid: str) -> None:
    client.collection("users").document(uid).set(
        {
            "uid": uid,
            "name": "Smoke Trigger User",
            "email": f"{uid}@example.com",
            "rankings": {},
            "preferences": {"area": 0, "levels": {}, "sports": []},
            "upcomingMatches": [],
            "completedMatches": [],
            "upcomingMatchIds": [],
            "recentCompletedMatchIds": [],
        }
    )


def _match_payload(uid: str, match_id: str, scheduled_at: datetime) -> dict:
    return {
        "matchId": match_id,
        "sport": "tennis",
        "status": "scheduled",
        "scheduledAt": scheduled_at,
        "participantUids": [uid],
        "participants": [{"uid": uid, "role": "player"}],
        "leagueId": None,
        "courtId": None,
    }


def _complete_match_payload(base: dict, finished_at: datetime) -> dict:
    updated = dict(base)
    updated["status"] = "completed"
    updated["finishedAt"] = finished_at
    updated["resultByUser"] = {updated["participantUids"][0]: "W"}
    return updated


def _assert_upcoming(user_doc: dict, match_id: str) -> None:
    upcoming_ids = user_doc.get("upcomingMatchIds") or []
    upcoming = user_doc.get("upcomingMatches") or []
    _require(match_id in upcoming_ids, "upcomingMatchIds missing match id")
    _require(
        any(item.get("matchId") == match_id for item in upcoming),
        "upcomingMatches missing match id",
    )


def _assert_completed(user_doc: dict, match_id: str) -> None:
    upcoming_ids = user_doc.get("upcomingMatchIds") or []
    completed_ids = user_doc.get("recentCompletedMatchIds") or []
    completed = user_doc.get("completedMatches") or []
    _require(match_id not in upcoming_ids, "upcomingMatchIds still contains match id")
    _require(match_id in completed_ids, "recentCompletedMatchIds missing match id")
    _require(
        any(item.get("matchId") == match_id for item in completed),
        "completedMatches missing match id",
    )


def smoke(env: str, project: str | None) -> None:
    client = firestore.Client(project=project)
    suffix = _now_utc().strftime("%Y%m%d%H%M%S")
    uid = f"smoke_triggers_user_{suffix}"
    match_id = f"smoke_triggers_match_{suffix}"

    user_ref = client.collection("users").document(uid)
    match_ref = client.collection("matches").document(match_id)

    try:
        _create_user_doc(client, uid)

        scheduled_at = _now_utc() + timedelta(hours=1)
        match_payload = _match_payload(uid, match_id, scheduled_at)
        match_ref.set(match_payload)

        handle_match_write_update_upcoming_cache(
            client=client, before=None, after=match_payload, now=_now_utc()
        )

        user_doc = user_ref.get().to_dict() or {}
        _assert_upcoming(user_doc, match_id)

        finished_at = _now_utc()
        completed_payload = _complete_match_payload(match_payload, finished_at)
        match_ref.set(completed_payload)

        handle_match_write_migrate_on_completion(
            client=client, before=match_payload, after=completed_payload, now=_now_utc()
        )

        user_doc = user_ref.get().to_dict() or {}
        _assert_completed(user_doc, match_id)

        print(f"Smoke OK ({env}) for match {match_id}")
    finally:
        match_ref.delete()
        user_ref.delete()


def smoke_notification_delivery(env: str, project: str | None) -> None:
    """Prove the deployed onNotificationIntentCreated trigger fires — without FCM creds.

    Writes a ``notificationIntents`` doc for a user that has NO device tokens, then polls
    the intent doc. When the deployed trigger runs it takes the no-tokens path and stamps
    ``deliveryStatus == "no_tokens"`` plus ``deliveredAt`` — neither of which needs FCM
    credentials. This is the honest, credential-free proof that the trigger is live.

    Triggers only run when a Functions runtime is attached (deployed ``dev`` or a running
    Functions emulator). Under ``--env emu`` we only have the Firestore emulator, so no
    trigger fires; this step SKIPS gracefully instead of hanging on a doc that never stamps.
    """
    if env != "dev":
        print(
            "Notification-delivery smoke SKIPPED (env="
            f"{env}): the onNotificationIntentCreated trigger only runs under a Functions "
            "runtime (deployed dev). The Firestore-only emulator does not execute triggers, "
            "so there is nothing to poll here."
        )
        return

    client = firestore.Client(project=project)
    suffix = _now_utc().strftime("%Y%m%d%H%M%S")
    uid = f"smoke_notify_user_{suffix}"
    intent_id = f"smoke_notify_intent_{suffix}"

    user_ref = client.collection("users").document(uid)
    intent_ref = user_ref.collection("notificationIntents").document(intent_id)

    try:
        # User intentionally has NO deviceTokens so the trigger takes the no_tokens path.
        _create_user_doc(client, uid)

        intent_ref.set(
            {
                "type": "match_scheduled",
                "targetUid": uid,
                "title": "Smoke notification",
                "body": "Notification-delivery smoke (no tokens expected)",
                "matchId": f"smoke_notify_match_{suffix}",
                "dedupeKey": f"match_scheduled:smoke_notify_match_{suffix}:{uid}",
                "createdAt": _now_utc(),
                "deliveryStatus": "pending",
            }
        )

        deadline = time.monotonic() + _NOTIFICATION_POLL_TIMEOUT_SECONDS
        intent_doc: dict = {}
        while time.monotonic() < deadline:
            intent_doc = intent_ref.get().to_dict() or {}
            if intent_doc.get("deliveredAt") is not None:
                break
            time.sleep(_NOTIFICATION_POLL_INTERVAL_SECONDS)

        _require(
            intent_doc.get("deliveredAt") is not None,
            "notification intent was not stamped with deliveredAt within "
            f"{_NOTIFICATION_POLL_TIMEOUT_SECONDS:.0f}s — is the trigger deployed?",
        )
        _require(
            intent_doc.get("deliveryStatus") == "no_tokens",
            f"expected deliveryStatus 'no_tokens', got {intent_doc.get('deliveryStatus')!r}",
        )

        print(
            f"Notification smoke OK ({env}) for intent {intent_id} (deliveryStatus=no_tokens)"
        )
    finally:
        intent_ref.delete()
        user_ref.delete()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Smoke test match trigger cache behavior."
    )
    parser.add_argument("--env", choices=["emu", "dev"], required=True)
    parser.add_argument("--project", default=None)
    args = parser.parse_args()

    if args.env == "dev" and not args.project:
        print("--project is required for dev smoke.", file=sys.stderr)
        return 1

    smoke(args.env, args.project)
    smoke_notification_delivery(args.env, args.project)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
