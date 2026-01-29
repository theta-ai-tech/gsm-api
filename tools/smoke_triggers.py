from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

from google.cloud import firestore  # type: ignore[import-untyped]

from functions.match_triggers.main import (
    handle_match_write_migrate_on_completion,
    handle_match_write_update_upcoming_cache,
)


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test match trigger cache behavior.")
    parser.add_argument("--env", choices=["emu", "dev"], required=True)
    parser.add_argument("--project", default=None)
    args = parser.parse_args()

    if args.env == "dev" and not args.project:
        print("--project is required for dev smoke.", file=sys.stderr)
        return 1

    smoke(args.env, args.project)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
