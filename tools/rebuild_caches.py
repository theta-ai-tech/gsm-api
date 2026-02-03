from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]

RPC_TIMEOUT_SECONDS = 15


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild denormalized user caches from canonical Firestore data."
    )
    parser.add_argument("--env", choices=["emu", "dev", "prod"], required=True)
    parser.add_argument("--uid", help="Rebuild a single user uid.")
    parser.add_argument("--all", action="store_true", help="Rebuild all users.")
    parser.add_argument("--dry-run", action="store_true", help="Print changes without writing.")
    parser.add_argument("--project", help="Project id (required for dev/prod if env var not set).")
    return parser.parse_args()


def _project_id(args: argparse.Namespace) -> str:
    project = args.project or os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("FIREBASE_PROJECT_ID")
    if not project:
        raise RuntimeError("Missing project id. Use --project or set GOOGLE_CLOUD_PROJECT.")
    return project


def _validate_env(args: argparse.Namespace) -> None:
    if args.env == "emu":
        host = os.getenv("FIRESTORE_EMULATOR_HOST")
        if not host:
            raise RuntimeError("FIRESTORE_EMULATOR_HOST must be set for --env emu.")
        if not (host.startswith("localhost") or host.startswith("127.0.0.1")):
            raise RuntimeError("Refusing --env emu: FIRESTORE_EMULATOR_HOST must point to localhost.")
        host_name, sep, port_raw = host.partition(":")
        if not sep or not port_raw.isdigit():
            raise RuntimeError(
                "FIRESTORE_EMULATOR_HOST must be in host:port format, e.g. 127.0.0.1:8082."
            )
        # Fail fast if emulator is down to avoid long Firestore retry waits.
        sock = socket.socket()
        sock.settimeout(1.5)
        try:
            sock.connect((host_name, int(port_raw)))
        except OSError as exc:
            raise RuntimeError(
                f"Firestore emulator not reachable at {host}. Start it with: make emu-firestore"
            ) from exc
        finally:
            sock.close()


def compute_upcoming(matches: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    scheduled = [
        m
        for m in matches
        if m.get("status") == "scheduled"
        and isinstance(m.get("scheduledAt"), datetime)
        and m["scheduledAt"] > now
    ]
    ordered = sorted(
        scheduled,
        key=lambda m: (
            m["scheduledAt"],
            str(m.get("matchId", "")),
        ),
    )
    return [
        {
            "matchId": str(m.get("matchId", "")),
            "sport": m.get("sport"),
            "scheduledAt": m.get("scheduledAt"),
            "leagueId": m.get("leagueId"),
            "courtId": m.get("courtId"),
            "opponents": [],
        }
        for m in ordered[:10]
    ]


def compute_recent(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    completed = [
        m
        for m in matches
        if m.get("status") == "completed" and isinstance(m.get("finishedAt"), datetime)
    ]
    ordered = sorted(
        completed,
        key=lambda m: (
            m["finishedAt"],
            str(m.get("matchId", "")),
        ),
        reverse=True,
    )
    return [
        {
            "matchId": str(m.get("matchId", "")),
            "sport": m.get("sport"),
            "finishedAt": m.get("finishedAt"),
            "result": None,
            "scoreText": None,
            "leagueId": m.get("leagueId"),
        }
        for m in ordered[:10]
    ]


def compute_league_summaries(
    user_memberships: list[dict[str, Any]], leagues: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    summaries_by_id: dict[str, dict[str, Any]] = {}
    for membership in user_memberships:
        if membership.get("status") != "active":
            continue
        league_id = str(membership.get("leagueId", ""))
        if not league_id:
            continue
        league = leagues.get(league_id)
        if not league:
            continue
        summaries_by_id[league_id] = {
            "leagueId": league_id,
            "name": league.get("name", ""),
            "sport": league.get("sport"),
            "status": league.get("status"),
            "role": membership.get("role"),
            "_joinedAt": membership.get("joinedAt"),
        }

    ordered = sorted(
        summaries_by_id.values(),
        key=lambda s: (
            s.get("_joinedAt")
            if isinstance(s.get("_joinedAt"), datetime)
            else datetime.min.replace(tzinfo=timezone.utc),
            str(s.get("leagueId", "")),
        ),
        reverse=True,
    )
    out: list[dict[str, Any]] = []
    for item in ordered[:20]:
        cleaned = dict(item)
        cleaned.pop("_joinedAt", None)
        out.append(cleaned)
    return out


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    return value


def _print_change(uid: str, before: dict[str, Any], after: dict[str, Any], dry_run: bool) -> None:
    changed_keys = [k for k in after.keys() if before.get(k) != after.get(k)]
    if not changed_keys:
        print(f"[{uid}] no changes")
        return

    prefix = "DRY-RUN" if dry_run else "UPDATED"
    print(f"[{uid}] {prefix} fields={','.join(sorted(changed_keys))}")
    for key in sorted(changed_keys):
        print(f"  - {key}:")
        print(f"    before={json.dumps(_jsonable(before.get(key)), ensure_ascii=True)}")
        print(f"    after={json.dumps(_jsonable(after.get(key)), ensure_ascii=True)}")


def _fetch_matches_for_uid(client: firestore.Client, uid: str) -> list[dict[str, Any]]:
    docs = (
        client.collection("matches")
        .where("participantUids", "array_contains", uid)
        .stream(timeout=RPC_TIMEOUT_SECONDS)
    )
    out: list[dict[str, Any]] = []
    for doc in docs:
        data = doc.to_dict() or {}
        data["matchId"] = doc.id
        out.append(data)
    return out


def _fetch_league_memberships_for_uid(client: firestore.Client, uid: str) -> list[dict[str, Any]]:
    # Membership docs are expected at leagues/{leagueId}/members/{uid}.
    docs = (
        client.collection_group("members")
        .where("uid", "==", uid)
        .stream(timeout=RPC_TIMEOUT_SECONDS)
    )
    out: list[dict[str, Any]] = []
    for doc in docs:
        data = doc.to_dict() or {}
        parent = doc.reference.parent.parent
        if parent is None:
            continue
        data["leagueId"] = parent.id
        out.append(data)
    return out


def _fetch_leagues_by_ids(client: firestore.Client, league_ids: set[str]) -> dict[str, dict[str, Any]]:
    leagues: dict[str, dict[str, Any]] = {}
    for league_id in sorted(league_ids):
        snapshot = client.collection("leagues").document(league_id).get(timeout=RPC_TIMEOUT_SECONDS)
        if not snapshot.exists:
            continue
        leagues[league_id] = snapshot.to_dict() or {}
    return leagues


def _split_league_summaries(
    league_summaries: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    active = [s for s in league_summaries if s.get("status") == "active"]
    completed = [s for s in league_summaries if s.get("status") != "active"]
    return active, completed


def rebuild_uid(client: firestore.Client, uid: str, dry_run: bool, now: datetime) -> bool:
    user_ref = client.collection("users").document(uid)
    print(f"[{uid}] processing")
    user_snap = user_ref.get(timeout=RPC_TIMEOUT_SECONDS)
    if not user_snap.exists:
        print(f"[{uid}] skipped: user doc not found")
        return False

    user_doc = user_snap.to_dict() or {}

    matches = _fetch_matches_for_uid(client, uid)
    upcoming = compute_upcoming(matches, now=now)
    recent_completed = compute_recent(matches)

    memberships = _fetch_league_memberships_for_uid(client, uid)
    leagues = _fetch_leagues_by_ids(client, {str(m.get("leagueId", "")) for m in memberships})
    league_summaries = compute_league_summaries(memberships, leagues)
    leagues_active, leagues_completed = _split_league_summaries(league_summaries)

    next_values = {
        "upcomingMatches": upcoming,
        "upcomingMatchIds": [m.get("matchId") for m in upcoming if m.get("matchId")],
        "completedMatches": recent_completed,
        "recentCompletedMatchIds": [
            m.get("matchId") for m in recent_completed if m.get("matchId")
        ],
        "leagueSummaries": league_summaries,
        "leaguesActive": leagues_active,
        "leaguesCompleted": leagues_completed,
    }

    before_values = {k: user_doc.get(k) for k in next_values.keys()}
    _print_change(uid=uid, before=before_values, after=next_values, dry_run=dry_run)

    has_changes = any(before_values.get(k) != next_values.get(k) for k in next_values.keys())
    if has_changes and not dry_run:
        user_ref.update(next_values, timeout=RPC_TIMEOUT_SECONDS)
    return has_changes


def _all_user_ids(client: firestore.Client) -> list[str]:
    ids = [doc.id for doc in client.collection("users").stream(timeout=RPC_TIMEOUT_SECONDS)]
    return sorted(ids)


def main() -> int:
    args = _parse_args()
    if not args.uid and not args.all:
        print("Use either --uid <uid> or --all.", file=sys.stderr)
        return 1
    if args.uid and args.all:
        print("Use either --uid or --all, not both.", file=sys.stderr)
        return 1

    try:
        _validate_env(args)
        project = _project_id(args)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    client = firestore.Client(project=project)
    now = datetime.now(timezone.utc)

    uids = [args.uid] if args.uid else _all_user_ids(client)
    changed = 0
    for uid in uids:
        if rebuild_uid(client=client, uid=uid, dry_run=args.dry_run, now=now):
            changed += 1

    action = "would change" if args.dry_run else "updated"
    print(f"Done: processed={len(uids)} users, {action}={changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
