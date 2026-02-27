from __future__ import annotations

import argparse
import os
import socket
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]
from google.cloud.firestore_v1.field_path import FieldPath  # type: ignore[import-untyped]


@dataclass
class IntegrityReport:
    scanned_users: int = 0
    failures: list[str] = field(default_factory=list)

    def fail(self, uid: str, message: str) -> None:
        self.failures.append(f"[{uid}] {message}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only cache integrity checker.")
    parser.add_argument("--env", choices=["emu", "dev"], required=True)
    parser.add_argument("--uid", help="Check only one user uid.")
    parser.add_argument("--limit", type=int, default=50, help="Max users to scan when --uid is not set.")
    parser.add_argument("--project", help="Project id (required for dev if env var not set).")
    return parser.parse_args()


def _project_id(args: argparse.Namespace) -> str:
    project = args.project or os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("FIREBASE_PROJECT_ID")
    if not project:
        raise RuntimeError("Missing project id. Use --project or set GOOGLE_CLOUD_PROJECT.")
    return project


def _validate_env(args: argparse.Namespace) -> None:
    if args.env != "emu":
        return
    host = os.getenv("FIRESTORE_EMULATOR_HOST")
    if not host:
        raise RuntimeError("FIRESTORE_EMULATOR_HOST must be set for --env emu.")
    if not (host.startswith("localhost") or host.startswith("127.0.0.1")):
        raise RuntimeError("Refusing --env emu: FIRESTORE_EMULATOR_HOST must point to localhost.")
    host_name, sep, port_raw = host.partition(":")
    if not sep or not port_raw.isdigit():
        raise RuntimeError("FIRESTORE_EMULATOR_HOST must be in host:port format.")
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


def _find_duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def _validate_id_list(
    report: IntegrityReport, uid: str, values: Any, field_name: str, cap: int
) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        report.fail(uid, f"{field_name} must be a list")
        return []
    if len(values) > cap:
        report.fail(uid, f"{field_name} exceeds cap {cap} (actual={len(values)})")
    non_strings = [v for v in values if not isinstance(v, str)]
    if non_strings:
        report.fail(uid, f"{field_name} has non-string ids")
    ids = [v for v in values if isinstance(v, str)]
    duplicates = _find_duplicates(ids)
    if duplicates:
        report.fail(uid, f"{field_name} has duplicate ids: {duplicates}")
    return ids


def _summary_match_ids(
    report: IntegrityReport, uid: str, items: Any, field_name: str, cap: int
) -> list[str]:
    if items is None:
        return []
    if not isinstance(items, list):
        report.fail(uid, f"{field_name} must be a list")
        return []
    if len(items) > cap:
        report.fail(uid, f"{field_name} exceeds cap {cap} (actual={len(items)})")
    ids: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            report.fail(uid, f"{field_name}[{index}] must be an object")
            continue
        match_id = item.get("matchId")
        if not isinstance(match_id, str) or not match_id:
            report.fail(uid, f"{field_name}[{index}] missing valid matchId")
            continue
        ids.append(match_id)
    duplicates = _find_duplicates(ids)
    if duplicates:
        report.fail(uid, f"{field_name} has duplicate matchId values: {duplicates}")
    return ids


def _summary_entry_ids(
    report: IntegrityReport, uid: str, items: Any, field_name: str, cap: int
) -> list[str]:
    if items is None:
        return []
    if not isinstance(items, list):
        report.fail(uid, f"{field_name} must be a list")
        return []
    if len(items) > cap:
        report.fail(uid, f"{field_name} exceeds cap {cap} (actual={len(items)})")

    entry_ids: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            report.fail(uid, f"{field_name}[{index}] must be an object")
            continue
        entry_id = item.get("entryId")
        if not isinstance(entry_id, str) or not entry_id:
            report.fail(uid, f"{field_name}[{index}] missing valid entryId")
            continue
        entry_ids.append(entry_id)

    duplicates = _find_duplicates(entry_ids)
    if duplicates:
        report.fail(uid, f"{field_name} has duplicate entryId values: {duplicates}")
    return entry_ids


def _fetch_match(client: firestore.Client, cache: dict[str, dict[str, Any] | None], match_id: str):
    if match_id not in cache:
        snap = client.collection("matches").document(match_id).get(timeout=15)
        cache[match_id] = snap.to_dict() if snap.exists else None
    return cache[match_id]


def _validate_upcoming(
    client: firestore.Client,
    report: IntegrityReport,
    uid: str,
    user_doc: dict[str, Any],
    now: datetime,
    match_cache: dict[str, dict[str, Any] | None],
) -> None:
    summary_ids = _summary_match_ids(report, uid, user_doc.get("upcomingMatches"), "upcomingMatches", 10)
    id_list = _validate_id_list(report, uid, user_doc.get("upcomingMatchIds"), "upcomingMatchIds", 10)
    ids = summary_ids or id_list

    for match_id in ids:
        match = _fetch_match(client, match_cache, match_id)
        if match is None:
            report.fail(uid, f"upcoming reference missing canonical match: {match_id}")
            continue
        if match.get("status") != "scheduled":
            report.fail(uid, f"upcoming match {match_id} status must be scheduled")
        scheduled_at = match.get("scheduledAt")
        if not isinstance(scheduled_at, datetime):
            report.fail(uid, f"upcoming match {match_id} missing scheduledAt")
        elif scheduled_at <= now:
            report.fail(uid, f"upcoming match {match_id} scheduledAt is not in the future")


def _validate_completed(
    client: firestore.Client,
    report: IntegrityReport,
    uid: str,
    user_doc: dict[str, Any],
    match_cache: dict[str, dict[str, Any] | None],
) -> None:
    summary_ids = _summary_match_ids(
        report, uid, user_doc.get("completedMatches"), "completedMatches", 10
    )
    id_list = _validate_id_list(
        report, uid, user_doc.get("recentCompletedMatchIds"), "recentCompletedMatchIds", 10
    )
    ids = summary_ids or id_list

    for match_id in ids:
        match = _fetch_match(client, match_cache, match_id)
        if match is None:
            report.fail(uid, f"recent completed reference missing canonical match: {match_id}")
            continue
        if match.get("status") != "completed":
            report.fail(uid, f"completed match {match_id} status must be completed")
        finished_at = match.get("finishedAt")
        if not isinstance(finished_at, datetime):
            report.fail(uid, f"completed match {match_id} missing finishedAt")


def _validate_journal_recent(
    client: firestore.Client,
    report: IntegrityReport,
    uid: str,
    user_doc: dict[str, Any],
) -> None:
    entry_ids = _summary_entry_ids(report, uid, user_doc.get("journalRecent"), "journalRecent", 10)
    for entry_id in entry_ids:
        snap = (
            client.collection("users")
            .document(uid)
            .collection("journalEntries")
            .document(entry_id)
            .get(timeout=15)
        )
        if not snap.exists:
            report.fail(uid, f"journalRecent reference missing canonical journal entry: {entry_id}")
            continue
        data = snap.to_dict() or {}
        if bool(data.get("isDeleted", False)):
            report.fail(uid, f"journalRecent references soft-deleted journal entry: {entry_id}")


def _league_summary_list(user_doc: dict[str, Any]) -> tuple[str, list[Any]]:
    if isinstance(user_doc.get("leagueSummaries"), list):
        return "leagueSummaries", user_doc.get("leagueSummaries", [])
    combined: list[Any] = []
    if isinstance(user_doc.get("leaguesActive"), list):
        combined.extend(user_doc.get("leaguesActive", []))
    if isinstance(user_doc.get("leaguesCompleted"), list):
        combined.extend(user_doc.get("leaguesCompleted", []))
    return "leaguesActive+leaguesCompleted", combined


def _validate_league_summaries(
    client: firestore.Client,
    report: IntegrityReport,
    uid: str,
    user_doc: dict[str, Any],
    league_cache: dict[str, bool],
) -> None:
    field_name, summaries = _league_summary_list(user_doc)
    if not summaries:
        return
    if not isinstance(summaries, list):
        report.fail(uid, f"{field_name} must be a list")
        return
    if len(summaries) > 20:
        report.fail(uid, f"{field_name} exceeds cap 20 (actual={len(summaries)})")

    league_ids: list[str] = []
    for index, item in enumerate(summaries):
        if not isinstance(item, dict):
            report.fail(uid, f"{field_name}[{index}] must be an object")
            continue
        league_id = item.get("leagueId")
        if not isinstance(league_id, str) or not league_id:
            report.fail(uid, f"{field_name}[{index}] missing valid leagueId")
            continue
        league_ids.append(league_id)

    duplicates = _find_duplicates(league_ids)
    if duplicates:
        report.fail(uid, f"{field_name} has duplicate leagueId values: {duplicates}")

    for league_id in league_ids:
        if league_id not in league_cache:
            exists = client.collection("leagues").document(league_id).get(timeout=15).exists
            league_cache[league_id] = bool(exists)
        if not league_cache[league_id]:
            report.fail(uid, f"league summary references missing league: {league_id}")


def _user_ids(client: firestore.Client, args: argparse.Namespace) -> list[str]:
    if args.uid:
        return [args.uid]
    docs = (
        client.collection("users")
        .order_by(FieldPath.document_id())
        .limit(max(args.limit, 0))
        .stream(timeout=20)
    )
    return [doc.id for doc in docs]


def run_check(client: firestore.Client, args: argparse.Namespace) -> IntegrityReport:
    report = IntegrityReport()
    now = datetime.now(timezone.utc)
    match_cache: dict[str, dict[str, Any] | None] = {}
    league_cache: dict[str, bool] = {}

    for uid in _user_ids(client, args):
        report.scanned_users += 1
        snapshot = client.collection("users").document(uid).get(timeout=15)
        if not snapshot.exists:
            report.fail(uid, "user document not found")
            continue
        user_doc = snapshot.to_dict() or {}

        _validate_upcoming(client, report, uid, user_doc, now, match_cache)
        _validate_completed(client, report, uid, user_doc, match_cache)
        _validate_journal_recent(client, report, uid, user_doc)
        _validate_league_summaries(client, report, uid, user_doc, league_cache)

    return report


def _print_report(report: IntegrityReport) -> None:
    print(f"Scanned users: {report.scanned_users}")
    if not report.failures:
        print("OK: cache integrity checks passed.")
        return
    print(f"Failures: {len(report.failures)}")
    for failure in report.failures:
        print(f"- {failure}")


def main() -> int:
    args = _parse_args()
    try:
        _validate_env(args)
        project = _project_id(args)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    client = firestore.Client(project=project)
    report = run_check(client, args)
    _print_report(report)
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
