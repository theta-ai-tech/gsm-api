from dataclasses import dataclass
import math

from app.models.enums import TierEnum
from app.models.tier import TierConfig
from app.services.tier_service import get_tier

TIER_ORDER = {
    TierEnum.AMATEUR: 0,
    TierEnum.INTERMEDIATE: 1,
    TierEnum.ADVANCED: 2,
    TierEnum.COMPETITIVE: 3,
}


@dataclass(frozen=True, slots=True)
class ScoreDelta:
    total: int
    base: int = 0
    upset_bonus: int = 0
    elo_bonus: int = 0
    penalty: int = 0


@dataclass(frozen=True, slots=True)
class ScoringResult:
    winner_delta: ScoreDelta
    loser_delta: ScoreDelta
    winner_new_pts: int
    loser_new_pts: int
    winner_new_tier: TierEnum
    loser_new_tier: TierEnum
    winner_tier_crossed: bool
    loser_tier_crossed: bool


def calculate_score_delta(
    winner_pts: int,
    loser_pts: int,
    winner_tier: TierEnum | str,
    loser_tier: TierEnum | str,
) -> ScoreDelta:
    base = 100
    upset_bonus = 0
    elo_bonus = 0

    if _is_higher_tier(loser_tier, winner_tier):
        upset_bonus = 50
        pts_diff = loser_pts - winner_pts
        if pts_diff > 0:
            elo_bonus = math.floor(pts_diff * 0.05)

    return ScoreDelta(
        total=base + upset_bonus + elo_bonus,
        base=base,
        upset_bonus=upset_bonus,
        elo_bonus=elo_bonus,
    )


def calculate_penalty(
    loser_pts: int,
    winner_pts: int,
    loser_tier: TierEnum | str,
    winner_tier: TierEnum | str,
) -> int:
    del loser_pts, winner_pts

    if _is_higher_tier(loser_tier, winner_tier):
        return -50
    return 0


def apply_floor(new_pts: int, registration_tier: TierEnum | str, tier_config: TierConfig) -> int:
    return max(new_pts, tier_config.get_floor(registration_tier))


def compute_match_scoring(
    winner_pts: int,
    loser_pts: int,
    winner_tier: TierEnum | str,
    loser_tier: TierEnum | str,
    winner_reg_tier: TierEnum | str,
    loser_reg_tier: TierEnum | str,
    tier_config: TierConfig,
    *,
    walkover: bool = False,
    retired: bool = False,
) -> ScoringResult:
    winner_current_tier = _normalize_tier(winner_tier)
    loser_current_tier = _normalize_tier(loser_tier)

    if walkover or retired:
        zero_delta = ScoreDelta(total=0)
        return ScoringResult(
            winner_delta=zero_delta,
            loser_delta=zero_delta,
            winner_new_pts=winner_pts,
            loser_new_pts=loser_pts,
            winner_new_tier=winner_current_tier,
            loser_new_tier=loser_current_tier,
            winner_tier_crossed=False,
            loser_tier_crossed=False,
        )

    winner_delta = calculate_score_delta(winner_pts, loser_pts, winner_tier, loser_tier)
    loser_penalty = calculate_penalty(loser_pts, winner_pts, loser_tier, winner_tier)
    loser_delta = ScoreDelta(total=loser_penalty, penalty=loser_penalty)

    winner_new_pts = winner_pts + winner_delta.total
    loser_new_pts = apply_floor(loser_pts + loser_penalty, loser_reg_tier, tier_config)

    winner_new_tier = _normalize_tier(get_tier(winner_new_pts, tier_config.thresholds))
    loser_new_tier = _normalize_tier(get_tier(loser_new_pts, tier_config.thresholds))

    return ScoringResult(
        winner_delta=winner_delta,
        loser_delta=loser_delta,
        winner_new_pts=winner_new_pts,
        loser_new_pts=loser_new_pts,
        winner_new_tier=winner_new_tier,
        loser_new_tier=loser_new_tier,
        winner_tier_crossed=winner_new_tier != winner_current_tier,
        loser_tier_crossed=loser_new_tier != loser_current_tier,
    )


def _is_higher_tier(candidate: TierEnum | str, reference: TierEnum | str) -> bool:
    return TIER_ORDER[_normalize_tier(candidate)] > TIER_ORDER[_normalize_tier(reference)]


def _normalize_tier(tier: TierEnum | str) -> TierEnum:
    return TierEnum(tier)
