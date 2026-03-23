"""
D7 — Scheduled leaderboard computation.

Recomputes regional leaderboard snapshots for every region + sport combination.
Pure logic is isolated in build_leaderboard_entries / build_rising_stars for testability.
compute_leaderboards() performs the full Firestore read-write cycle.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from google.cloud import firestore  # type: ignore[import-untyped]

from functions.logging_utils import log_event
from functions.scoring_triggers.tier_averages import compute_and_write_tier_averages

_TRIGGER = "D7.leaderboard"
_SPORTS = ("tennis", "padel", "pickleball")
_LEADERBOARD_TOP_N = 10
_RISING_STARS_TOP_N = 5
_BATCH_SIZE = 500


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def build_area_to_region(mapping: dict[str, str]) -> dict[int, str]:
    """Convert the string-keyed config/regions mapping to int-keyed lookup."""
    result: dict[int, str] = {}
    for area_str, region in mapping.items():
        try:
            result[int(area_str)] = region
        except (ValueError, TypeError):
            continue
    return result


def extract_users_by_region_sport(
    users: list[dict[str, Any]],
    area_to_region: dict[int, str],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    """
    Group users by (region, sport) based on their preferences.area and rankings.

    A user appears in a (region, sport) bucket if:
    - preferences.area maps to a known region
    - rankings.{sport} exists and has pts
    """
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for user in users:
        prefs = user.get("preferences") or {}
        area = prefs.get("area")
        if area is None:
            continue

        try:
            area_int = int(area)
        except (ValueError, TypeError):
            continue

        region = area_to_region.get(area_int)
        if not region:
            continue

        rankings = user.get("rankings") or {}
        for sport in _SPORTS:
            sport_ranking = rankings.get(sport)
            if not sport_ranking:
                continue
            pts = sport_ranking.get("pts")
            if pts is None:
                continue
            buckets.setdefault((region, sport), []).append(user)

    return buckets


def build_leaderboard_entries(
    users: list[dict[str, Any]],
    sport: str,
    delta7d_map: dict[str, int],
    top_n: int = _LEADERBOARD_TOP_N,
) -> list[dict[str, Any]]:
    """
    Sort users by pts DESC for a given sport, take top N, and return
    leaderboard entry dicts ready for Firestore.
    """
    scored: list[tuple[str, str, int, str | None, int]] = []
    for user in users:
        uid = user.get("uid") or user.get("id") or ""
        name = user.get("name", "")
        rankings = user.get("rankings") or {}
        sport_ranking = rankings.get(sport) or {}
        pts = sport_ranking.get("pts")
        tier = sport_ranking.get("tier")
        if pts is None:
            continue
        delta = delta7d_map.get(uid, 0)
        scored.append((uid, name, int(pts), tier, delta))

    scored.sort(key=lambda x: x[2], reverse=True)
    entries: list[dict[str, Any]] = []
    for rank, (uid, name, pts, tier, delta) in enumerate(scored[:top_n], start=1):
        entry: dict[str, Any] = {
            "uid": uid,
            "name": name,
            "pts": pts,
            "rank": rank,
            "delta7d": delta,
        }
        if tier:
            entry["tier"] = tier
        entries.append(entry)

    return entries


def build_rising_stars(
    users: list[dict[str, Any]],
    sport: str,
    delta7d_map: dict[str, int],
    uid_to_rank: dict[str, int],
    top_n: int = _RISING_STARS_TOP_N,
) -> list[dict[str, Any]]:
    """
    Select users with positive delta7d, sort by delta7d DESC, take top N.
    Returns rising star entry dicts ready for Firestore.

    ``uid_to_rank`` maps each UID to its 1-based position in the overall
    leaderboard (sorted by pts DESC). This is used as the ``rank`` field
    per the data dictionary (overall leaderboard position, not position
    within the rising-stars list).
    """
    candidates: list[tuple[str, str, int, int]] = []
    for user in users:
        uid = user.get("uid") or user.get("id") or ""
        name = user.get("name", "")
        rankings = user.get("rankings") or {}
        sport_ranking = rankings.get(sport) or {}
        pts = sport_ranking.get("pts")
        if pts is None:
            continue
        delta = delta7d_map.get(uid, 0)
        if delta > 0:
            candidates.append((uid, name, int(pts), delta))

    candidates.sort(key=lambda x: x[3], reverse=True)
    stars: list[dict[str, Any]] = []
    for uid, name, pts, delta in candidates[:top_n]:
        stars.append({
            "uid": uid,
            "name": name,
            "pts": pts,
            "delta7d": delta,
            "rank": uid_to_rank.get(uid, 0),
        })

    return stars


def build_uid_to_rank(
    users: list[dict[str, Any]],
    sport: str,
) -> dict[str, int]:
    """
    Sort all users by pts DESC for a sport and return a mapping from
    UID to 1-based overall rank.  Used to populate risingStars[].rank
    with the player's overall leaderboard position.
    """
    scored: list[tuple[str, int]] = []
    for user in users:
        uid = user.get("uid") or user.get("id") or ""
        rankings = user.get("rankings") or {}
        sport_ranking = rankings.get(sport) or {}
        pts = sport_ranking.get("pts")
        if pts is None:
            continue
        scored.append((uid, int(pts)))

    scored.sort(key=lambda x: x[1], reverse=True)
    return {uid: rank for rank, (uid, _) in enumerate(scored, start=1)}


def compute_delta7d_from_history(
    history_entries: list[dict[str, Any]],
    now: datetime,
) -> int:
    """
    Sum the delta values from point history entries created within the last 7 days.
    Entries are expected in Firestore shape with 'delta' and 'createdAt' fields.
    """
    cutoff = now - timedelta(days=7)
    total = 0
    for entry in history_entries:
        created_at = entry.get("createdAt")
        if created_at is None:
            continue
        if isinstance(created_at, datetime) and created_at >= cutoff:
            delta = entry.get("delta", 0)
            total += int(delta)
    return total


# ---------------------------------------------------------------------------
# Firestore I/O
# ---------------------------------------------------------------------------


def _read_region_mapping(client: firestore.Client) -> dict[str, str]:
    """Read config/regions and return the area->region mapping dict."""
    doc = client.collection("config").document("regions").get()
    if not doc.exists:
        raise ValueError("Region config not found in Firestore (config/regions)")
    data = doc.to_dict() or {}
    return data.get("mapping", {})


def _read_all_users(client: firestore.Client) -> list[dict[str, Any]]:
    """Stream all user documents."""
    docs = client.collection("users").stream()
    users: list[dict[str, Any]] = []
    for doc in docs:
        data = doc.to_dict() or {}
        data["uid"] = doc.id
        users.append(data)
    return users


def _read_point_history_since(
    client: firestore.Client,
    uid: str,
    sport: str,
    cutoff: datetime,
) -> list[dict[str, Any]]:
    """Read pointHistory entries for a user+sport since cutoff."""
    entries: list[dict[str, Any]] = []
    query = (
        client.collection("users")
        .document(uid)
        .collection("pointHistory")
        .where("sport", "==", sport)
        .where("createdAt", ">=", cutoff)
    )
    for doc in query.stream():
        entries.append(doc.to_dict() or {})
    return entries


def _compute_delta7d_for_users(
    client: firestore.Client,
    user_uids: list[str],
    sport: str,
    now: datetime,
) -> dict[str, int]:
    """Compute delta7d for a list of user UIDs by reading their pointHistory."""
    cutoff = now - timedelta(days=7)
    delta_map: dict[str, int] = {}
    for uid in user_uids:
        entries = _read_point_history_since(client, uid, sport, cutoff)
        delta = compute_delta7d_from_history(entries, now)
        delta_map[uid] = delta
    return delta_map


def _write_leaderboard_snapshot(
    client: firestore.Client,
    region: str,
    sport: str,
    entries: list[dict[str, Any]],
    rising_stars: list[dict[str, Any]],
    now: datetime,
) -> None:
    """Write a leaderboard snapshot to leaderboards/{region}_{sport}."""
    doc_id = f"{region}_{sport}"
    doc_data: dict[str, Any] = {
        "region": region,
        "sport": sport,
        "entries": entries,
        "risingStars": rising_stars,
        "lastUpdated": now,
    }
    client.collection("leaderboards").document(doc_id).set(doc_data)


def compute_leaderboards(
    client: firestore.Client,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Main entry point: recompute all regional leaderboard snapshots.

    1. Read config/regions for area -> region mapping
    2. Read all users
    3. For each region + sport:
       a. Query pointHistory for delta7d
       b. Build top-10 entries
       c. Build top-5 rising stars
       d. Write snapshot
    4. Update config/tierAverages

    Returns a summary dict for logging.
    """
    if now is None:
        now = datetime.now(tz=timezone.utc)

    # 1. Read region config
    raw_mapping = _read_region_mapping(client)
    area_to_region = build_area_to_region(raw_mapping)

    log_event(
        trigger=_TRIGGER,
        action="read_config",
        regions=sorted(set(area_to_region.values())),
        area_count=len(area_to_region),
    )

    # 2. Read all users
    users = _read_all_users(client)
    log_event(trigger=_TRIGGER, action="read_users", users_count=len(users))

    # 3. Group by region + sport
    buckets = extract_users_by_region_sport(users, area_to_region)

    regions_processed: list[str] = []
    snapshots_written = 0

    for (region, sport), bucket_users in sorted(buckets.items()):
        user_uids = [
            u.get("uid") or u.get("id") or "" for u in bucket_users
        ]

        # 3a. delta7d
        delta7d_map = _compute_delta7d_for_users(client, user_uids, sport, now)

        # 3b. overall rank map (pts-sorted position across all bucket users)
        uid_to_rank = build_uid_to_rank(bucket_users, sport)

        # 3c. entries
        entries = build_leaderboard_entries(bucket_users, sport, delta7d_map)

        # 3d. rising stars
        rising_stars = build_rising_stars(bucket_users, sport, delta7d_map, uid_to_rank)

        # 3e. write
        _write_leaderboard_snapshot(client, region, sport, entries, rising_stars, now)
        snapshots_written += 1

        region_key = f"{region}_{sport}"
        if region_key not in regions_processed:
            regions_processed.append(region_key)

        log_event(
            trigger=_TRIGGER,
            action="write_snapshot",
            region=region,
            sport=sport,
            entries_count=len(entries),
            rising_stars_count=len(rising_stars),
            users_in_bucket=len(bucket_users),
        )

    # 4. Update tier averages
    compute_and_write_tier_averages(client)

    summary: dict[str, Any] = {
        "regions_processed": regions_processed,
        "snapshots_written": snapshots_written,
        "users_count": len(users),
    }

    log_event(
        trigger=_TRIGGER,
        action="summary",
        changed=snapshots_written > 0,
        **summary,
    )

    return summary
