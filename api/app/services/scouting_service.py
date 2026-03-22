from __future__ import annotations

from typing import Literal


def compute_confidence(total_reports: int) -> Literal["low", "medium", "high"]:
    if total_reports > 7:
        return "high"
    if total_reports >= 3:
        return "medium"
    return "low"


def sorted_tag_list(
    tag_counts: dict[str, object],
) -> list[tuple[str, int]]:
    """Return (tag, count) pairs sorted by count descending.

    Accepts the ScoutingSportData.weak / .strong dicts whose values are
    ScoutingTagCount instances (with a .count attribute).
    """
    pairs: list[tuple[str, int]] = []
    for tag, tc in tag_counts.items():
        count = getattr(tc, "count", 0)
        pairs.append((tag, count))
    pairs.sort(key=lambda p: p[1], reverse=True)
    return pairs


# Simple tag -> human-readable label map.
# Tags not listed here get a capitalised version of the tag string.
_TAG_LABELS: dict[str, str] = {
    "backhand": "Backhand",
    "forehand": "Forehand",
    "first_serve": "First serve",
    "double_faults": "Double faults",
    "ace": "Ace",
    "volley": "Volley",
    "net_approach": "Net approach",
    "stamina_set3": "Late-set stamina",
    "endurance": "Endurance",
    "fitness": "Fitness",
    "concentration": "Concentration",
    "composure": "Composure",
    "tiebreak": "Tiebreak mentality",
    "serve": "Serve",
    "power": "Power",
    "net_play": "Net play",
    "stamina": "Stamina",
    "mental": "Mental",
    "forehand_winner": "Forehand winner",
    "backhand_winner": "Backhand winner",
}


def tag_label(tag: str) -> str:
    return _TAG_LABELS.get(tag, tag.replace("_", " ").capitalize())
