"""
Global ranking recomputation for D5.1 trigger.

Pure logic is isolated in assign_global_rankings() for testability.
recompute_global_ranking() performs the Firestore read-sort-write cycle.
"""

from __future__ import annotations

from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]

_BATCH_SIZE = 500


def assign_global_rankings(user_pts: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """
    Given a list of (uid, pts) pairs, return (uid, global_ranking) pairs.

    Rankings are 1-indexed, highest pts = rank 1. Sequential (no tie-sharing).
    Input order is preserved for users with equal pts (stable sort).
    """
    sorted_pairs = sorted(user_pts, key=lambda x: x[1], reverse=True)
    return [(uid, rank + 1) for rank, (uid, _) in enumerate(sorted_pairs)]


def recompute_global_ranking(client: firestore.Client, sport: str) -> int:
    """
    Query all users ranked in sport, assign 1-indexed globalRanking by pts DESC,
    and batch-write updated globalRanking + lastUpdated back to user docs.

    lastUpdated is set to firestore.SERVER_TIMESTAMP so it reflects the actual
    Firestore write time, even when the globalRanking ordinal did not change.

    Returns the number of user docs updated.

    TODO (scalability): At >10K users per sport, replace with an incremental approach
    that only updates ranks near the changed position.

    TODO (debounce): If multiple matches complete in quick succession, avoid redundant
    full recalculations by using Cloud Tasks with a deduplication key per sport.
    """
    field_pts = f"rankings.{sport}.pts"

    docs = (
        client.collection("users")
        .order_by(field_pts, direction=firestore.Query.DESCENDING)
        .stream()
    )

    user_pts: list[tuple[str, int]] = []
    for doc in docs:
        data: dict[str, Any] = doc.to_dict() or {}
        pts = ((data.get("rankings") or {}).get(sport) or {}).get("pts")
        if pts is not None:
            user_pts.append((doc.id, int(pts)))

    rankings = assign_global_rankings(user_pts)

    batch = client.batch()
    batch_count = 0
    updated = 0

    for uid, rank in rankings:
        user_ref = client.collection("users").document(uid)
        batch.update(
            user_ref,
            {
                f"rankings.{sport}.globalRanking": rank,
                f"rankings.{sport}.lastUpdated": firestore.SERVER_TIMESTAMP,
            },
        )
        batch_count += 1
        updated += 1
        if batch_count == _BATCH_SIZE:
            batch.commit()
            batch = client.batch()
            batch_count = 0

    if batch_count > 0:
        batch.commit()

    return updated
