"""
League member stats update for D5.2 trigger.

increment_member_stats() atomically increments stats.wins or stats.losses on
leagues/{leagueId}/members/{uid} and tracks processed matchIds to prevent
double-counting on trigger replays.
"""

from __future__ import annotations

from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]


def increment_member_stats(
    client: firestore.Client,
    league_id: str,
    uid: str,
    field: str,
    match_id: str,
) -> bool:
    """
    Atomically increment stats.{field} (wins or losses) on the league member doc.

    Idempotent: if match_id is already in processedMatchIds the write is skipped
    and False is returned. Returns True when the update was applied.
    """
    member_ref = (
        client.collection("leagues")
        .document(league_id)
        .collection("members")
        .document(uid)
    )
    transaction = client.transaction()
    result_holder: dict[str, bool] = {}

    @firestore.transactional
    def _apply(txn: firestore.Transaction) -> None:
        snap = member_ref.get(transaction=txn)
        if not snap.exists:
            # Only increment stats for existing members — never create partial docs
            # that would appear as membership authority without role/status/joinedAt.
            result_holder["applied"] = False
            return
        data: dict[str, Any] = snap.to_dict() or {}
        processed: list[str] = data.get("processedMatchIds") or []
        if match_id in processed:
            result_holder["applied"] = False
            return
        txn.set(
            member_ref,
            {
                "stats": {field: firestore.Increment(1)},
                "processedMatchIds": firestore.ArrayUnion([match_id]),
            },
            merge=True,
        )
        result_holder["applied"] = True

    _apply(transaction)
    return result_holder.get("applied", False)
