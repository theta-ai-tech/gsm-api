from app.models.tier import TierThreshold


def get_tier(pts: int, thresholds: list[TierThreshold]) -> str:
    """Derive the tier name for a given point total.

    Returns the ``tier`` value of the first threshold whose range contains *pts*.
    If *pts* falls below every range, the lowest tier (by ``min_pts``) is returned
    as a fallback.
    """
    for t in thresholds:
        if pts >= t.min_pts and (t.max_pts is None or pts <= t.max_pts):
            return t.tier

    # Fallback: return the tier with the lowest min_pts.
    lowest = min(thresholds, key=lambda t: t.min_pts)
    return lowest.tier
