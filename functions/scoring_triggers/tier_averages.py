"""
D7 — Compute average Skill DNA per tier and write to config/tierAverages.

Pure logic is isolated in compute_tier_averages_from_users() for testability.
compute_and_write_tier_averages() performs the Firestore read-write cycle.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]

from functions.logging_utils import log_event

_TRIGGER = "D7.tierAverages"
_AXES = ("serve", "power", "net_play", "stamina", "mental")
_SPORTS = ("tennis", "padel", "pickleball")
_TIERS = ("amateur", "intermediate", "advanced", "competitive")


def compute_tier_averages_from_users(
    users: list[dict[str, Any]],
) -> dict[str, dict[str, dict[str, int]]]:
    """
    Pure function. Given a list of user dicts (Firestore shape), compute
    per-tier per-sport average axis scores.

    Returns: {tier: {sport: {axis: avg_score, ...}, ...}, ...}
    Tiers or sports with no users who have skillDna are omitted.
    """
    # Accumulator: tier -> sport -> axis -> list of scores
    acc: dict[str, dict[str, dict[str, list[int]]]] = {}

    for user in users:
        rankings = user.get("rankings") or {}
        skill_dna = user.get("skillDna") or {}

        for sport in _SPORTS:
            sport_ranking = rankings.get(sport)
            sport_dna = skill_dna.get(sport)
            if not sport_ranking or not sport_dna:
                continue

            tier = sport_ranking.get("tier")
            if not tier or tier not in _TIERS:
                continue

            for axis in _AXES:
                axis_data = sport_dna.get(axis)
                if axis_data is None:
                    continue
                score = axis_data.get("score")
                if score is None:
                    continue

                acc.setdefault(tier, {}).setdefault(sport, {}).setdefault(axis, []).append(
                    int(score)
                )

    # Average each list
    result: dict[str, dict[str, dict[str, int]]] = {}
    for tier, sports in acc.items():
        for sport, axes in sports.items():
            for axis, scores in axes.items():
                avg = round(sum(scores) / len(scores))
                result.setdefault(tier, {}).setdefault(sport, {})[axis] = avg

    return result


def compute_and_write_tier_averages(client: firestore.Client) -> dict[str, Any]:
    """
    Read all users, compute per-tier Skill DNA averages, and write to config/tierAverages.

    Returns the written document data (for logging/testing).
    """
    now = datetime.now(tz=timezone.utc)

    docs = client.collection("users").stream()
    users = [doc.to_dict() or {} for doc in docs]

    log_event(trigger=_TRIGGER, action="read_users", users_count=len(users))

    averages = compute_tier_averages_from_users(users)

    tiers_with_data = list(averages.keys())
    sports_covered: set[str] = set()
    for tier_sports in averages.values():
        sports_covered.update(tier_sports.keys())

    doc_data: dict[str, Any] = {
        **averages,
        "updatedAt": now,
    }

    client.collection("config").document("tierAverages").set(doc_data)

    log_event(
        trigger=_TRIGGER,
        action="write",
        tiers_with_data=tiers_with_data,
        sports_covered=sorted(sports_covered),
        changed=True,
        writes_count=1,
    )

    return doc_data
