from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]
from functions.logging_utils import log_event


@dataclass(frozen=True)
class LeagueSummaryUpsertResult:
    qualifies: bool
    reason: str
    league_id: str
    uid: str
    role: str | None
    member_status: str | None


@dataclass(frozen=True)
class LeagueSummaryRemovalResult:
    qualifies: bool
    reason: str
    league_id: str
    uid: str
    member_status: str | None


def _get_member_uid(after: dict[str, Any] | None, before: dict[str, Any] | None) -> str:
    for source in (after or {}, before or {}):
        uid = source.get("uid")
        if uid:
            return str(uid)
    return ""


def _has_member_change(before: dict[str, Any], after: dict[str, Any]) -> bool:
    for key in ("role", "status", "divisionId"):
        if before.get(key) != after.get(key):
            return True
    return False


def _is_removed_status(status: str | None) -> bool:
    return status in {"left", "banned"}


def qualify_league_member_upsert(
    league_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> LeagueSummaryUpsertResult:
    # Only active members and role/status changes qualify for summary upserts.
    uid = _get_member_uid(after, before)
    role = (after or {}).get("role")
    member_status = (after or {}).get("status")

    if after is None:
        return LeagueSummaryUpsertResult(
            qualifies=False,
            reason="deleted",
            league_id=league_id,
            uid=uid,
            role=role,
            member_status=member_status,
        )

    if member_status != "active":
        return LeagueSummaryUpsertResult(
            qualifies=False,
            reason="status_not_active",
            league_id=league_id,
            uid=uid,
            role=role,
            member_status=member_status,
        )

    if before is not None and not _has_member_change(before, after):
        return LeagueSummaryUpsertResult(
            qualifies=False,
            reason="no_op",
            league_id=league_id,
            uid=uid,
            role=role,
            member_status=member_status,
        )

    return LeagueSummaryUpsertResult(
        qualifies=True,
        reason="qualifies",
        league_id=league_id,
        uid=uid,
        role=role,
        member_status=member_status,
    )


def qualify_league_member_removal(
    league_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> LeagueSummaryRemovalResult:
    uid = _get_member_uid(after, before)
    after_status = (after or {}).get("status")
    before_status = (before or {}).get("status")

    if after is None:
        return LeagueSummaryRemovalResult(
            qualifies=True,
            reason="deleted",
            league_id=league_id,
            uid=uid,
            member_status=before_status,
        )

    if _is_removed_status(after_status):
        if _is_removed_status(before_status):
            return LeagueSummaryRemovalResult(
                qualifies=False,
                reason="already_removed",
                league_id=league_id,
                uid=uid,
                member_status=after_status,
            )
        return LeagueSummaryRemovalResult(
            qualifies=True,
            reason="status_removed",
            league_id=league_id,
            uid=uid,
            member_status=after_status,
        )

    return LeagueSummaryRemovalResult(
        qualifies=False,
        reason="not_removed",
        league_id=league_id,
        uid=uid,
        member_status=after_status,
    )


def upsert_league_summary(
    existing: list[dict[str, Any]] | None,
    new_summary: dict[str, Any],
    cap: int = 20,
) -> list[dict[str, Any]]:
    # Trim policy: keep active first, then completed; preserve order within each group.
    entries = [dict(item) for item in (existing or [])]
    league_id = new_summary.get("leagueId")
    updated: list[dict[str, Any]] = []
    replaced = False
    for item in entries:
        if item.get("leagueId") == league_id:
            updated.append(dict(new_summary))
            replaced = True
        else:
            updated.append(item)
    if not replaced:
        updated.append(dict(new_summary))

    if len(updated) <= cap:
        return updated

    def _is_active(item: dict[str, Any]) -> bool:
        return item.get("status") == "active"

    active = [item for item in updated if _is_active(item)]
    inactive = [item for item in updated if not _is_active(item)]
    trimmed = active + inactive
    return trimmed[:cap]


def remove_league_summary(
    existing: list[dict[str, Any]] | None,
    league_id: str,
) -> list[dict[str, Any]]:
    return [item for item in (existing or []) if item.get("leagueId") != league_id]


def _upsert_user_league_summary(
    client: firestore.Client,
    uid: str,
    league_id: str,
    summary: dict[str, Any],
    cap: int = 20,
) -> bool:
    # Per-user transaction keeps cache update atomic and idempotent.
    doc_ref = client.collection("users").document(uid)
    transaction = client.transaction()

    @firestore.transactional
    def _apply(transaction: firestore.Transaction) -> bool:
        snapshot = doc_ref.get(transaction=transaction)
        if not snapshot.exists:
            return False
        data = snapshot.to_dict() or {}
        league_status = summary.get("status")
        active_key = "leaguesActive"
        completed_key = "leaguesCompleted"

        active = data.get(active_key) or []
        completed = data.get(completed_key) or []

        if league_status == "active":
            updated_active = upsert_league_summary(active, summary, cap=cap)
            updated_completed = [item for item in completed if item.get("leagueId") != league_id]
        else:
            updated_completed = upsert_league_summary(completed, summary, cap=cap)
            updated_active = [item for item in active if item.get("leagueId") != league_id]

        updates: dict[str, Any] = {}
        if updated_active != active:
            updates[active_key] = updated_active
        if updated_completed != completed:
            updates[completed_key] = updated_completed

        if updates:
            transaction.update(doc_ref, updates)
            return True
        return False

    return _apply(transaction)


def _remove_user_league_summary(
    client: firestore.Client,
    uid: str,
    league_id: str,
) -> bool:
    doc_ref = client.collection("users").document(uid)
    transaction = client.transaction()

    @firestore.transactional
    def _apply(transaction: firestore.Transaction) -> bool:
        snapshot = doc_ref.get(transaction=transaction)
        if not snapshot.exists:
            return False
        data = snapshot.to_dict() or {}
        active_key = "leaguesActive"
        completed_key = "leaguesCompleted"
        active = data.get(active_key) or []
        completed = data.get(completed_key) or []

        updated_active = remove_league_summary(active, league_id)
        updated_completed = remove_league_summary(completed, league_id)

        updates: dict[str, Any] = {}
        if updated_active != active:
            updates[active_key] = updated_active
        if updated_completed != completed:
            updates[completed_key] = updated_completed

        if updates:
            transaction.update(doc_ref, updates)
            return True
        return False

    return _apply(transaction)


def handle_league_member_upsert(
    client: firestore.Client,
    league_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> bool:
    # Trigger entry point: compose summary from league + member doc and upsert into user cache.
    trigger_name = "onLeagueMemberWrite.D3.1"
    processed_count = 1
    ignored_count = 0
    writes_count = 0

    result = qualify_league_member_upsert(league_id, before, after)
    log_event(
        trigger=trigger_name,
        action="qualify",
        leagueId=league_id,
        uid=result.uid,
        reason=result.reason,
        qualifies=result.qualifies,
        changed=False,
    )
    if not result.qualifies or after is None:
        ignored_count = 1
        log_event(
            trigger=trigger_name,
            action="summary",
            leagueId=league_id,
            uid=result.uid,
            changed=False,
            processed_count=processed_count,
            ignored_count=ignored_count,
            writes_count=writes_count,
        )
        return False

    league_doc = client.collection("leagues").document(league_id).get()
    if not league_doc.exists:
        ignored_count = 1
        log_event(
            trigger=trigger_name,
            action="ignore",
            leagueId=league_id,
            uid=result.uid,
            reason="league_not_found",
            changed=False,
            processed_count=processed_count,
            ignored_count=ignored_count,
            writes_count=writes_count,
        )
        return False
    league_data = league_doc.to_dict() or {}

    summary = {
        "leagueId": league_id,
        "name": league_data.get("name", ""),
        "sport": league_data.get("sport"),
        "status": league_data.get("status"),
        "role": after.get("role"),
        "displayName": after.get("displayName"),
        "divisionId": after.get("divisionId"),
    }

    if not summary.get("sport") or not summary.get("status"):
        ignored_count = 1
        log_event(
            trigger=trigger_name,
            action="ignore",
            leagueId=league_id,
            uid=result.uid,
            reason="league_summary_missing_fields",
            changed=False,
            processed_count=processed_count,
            ignored_count=ignored_count,
            writes_count=writes_count,
        )
        return False

    changed = _upsert_user_league_summary(
        client=client,
        uid=result.uid,
        league_id=league_id,
        summary=summary,
    )
    if changed:
        writes_count = 1
    log_event(
        trigger=trigger_name,
        action="upsert",
        leagueId=league_id,
        uid=result.uid,
        changed=changed,
    )
    log_event(
        trigger=trigger_name,
        action="summary",
        leagueId=league_id,
        uid=result.uid,
        changed=changed,
        processed_count=processed_count,
        ignored_count=ignored_count,
        writes_count=writes_count,
    )
    return changed


def handle_league_member_removal(
    client: firestore.Client,
    league_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> bool:
    # Trigger entry point: remove summary on member deletion or removal status.
    trigger_name = "onLeagueMemberWrite.D3.2"
    processed_count = 1
    ignored_count = 0
    writes_count = 0

    result = qualify_league_member_removal(league_id, before, after)
    log_event(
        trigger=trigger_name,
        action="qualify",
        leagueId=league_id,
        uid=result.uid,
        reason=result.reason,
        qualifies=result.qualifies,
        changed=False,
    )
    if not result.qualifies:
        ignored_count = 1
        log_event(
            trigger=trigger_name,
            action="summary",
            leagueId=league_id,
            uid=result.uid,
            changed=False,
            processed_count=processed_count,
            ignored_count=ignored_count,
            writes_count=writes_count,
        )
        return False
    if not result.uid:
        ignored_count = 1
        log_event(
            trigger=trigger_name,
            action="ignore",
            leagueId=league_id,
            reason="uid_missing",
            changed=False,
            processed_count=processed_count,
            ignored_count=ignored_count,
            writes_count=writes_count,
        )
        return False
    changed = _remove_user_league_summary(client=client, uid=result.uid, league_id=league_id)
    if changed:
        writes_count = 1
    log_event(
        trigger=trigger_name,
        action="remove",
        leagueId=league_id,
        uid=result.uid,
        changed=changed,
    )
    log_event(
        trigger=trigger_name,
        action="summary",
        leagueId=league_id,
        uid=result.uid,
        changed=changed,
        processed_count=processed_count,
        ignored_count=ignored_count,
        writes_count=writes_count,
    )
    return changed
