# Scoring

How the match-scoring engine turns a confirmed result into point and tier changes for every
participant. This is the golden-source reference for the singles and doubles point formulas, the
tier-based upset/penalty rules, and the worked examples behind the `verify-score` `scoring` payload.

Source of truth: `api/app/services/scoring_service.py` (singles math) and
`api/app/services/match_confirmation_service.py` (doubles orchestration).

## Overview

Scoring runs **once per match**, on the **second** `verify-score` call — the call that moves the
match from `pending_confirmation` to `completed` (both participants/teams have agreed on the result).
It never runs on the first submit, and the `scoring` payload is always `null` on a
`pending_confirmation` response. Until a match completes, `winner_delta`, `loser_delta`,
`winner_new_pts`, and `loser_new_pts` are all `0`. On completed doubles responses those top-level
fields remain `0`; per-player doubles scoring is exposed through the caller-specific `scoring`
payload.

Each completed match produces, per player:

- a points delta (broken down into `base`, `upset_bonus`, `elo_bonus`, `penalty`),
- a new pts total and a (possibly unchanged) tier,
- a `tier_crossed` flag when the new pts cross a tier threshold,
- a `pointHistory` audit entry with the final `pts` and effective `delta` (skipped entirely for
  walkover/retirement).

### Field-name conventions

The live API response exposes the caller's breakdown in `ScoringPayload` using snake_case field names:
`base_win`, `upset_bonus`, `elo_bonus`, and `penalty`. Stored `pointHistory` entries do **not** persist
that breakdown; they store the final `pts`, effective `delta`, reason, match/opponent metadata, and
tier before/after.

## Tier configuration

Tiers are point bands sourced from `config/tiers` (see `wiki/DATA_DICTIONARY.md`). A player's tier is
**derived** from their current pts via `get_tier()` (`api/app/services/tier_service.py`): the tier is
the first threshold whose `[min_pts, max_pts]` range contains the player's pts.

| Tier | Pts range | Order |
| --- | --- | --- |
| Amateur | 1000–1999 | 0 (lowest) |
| Intermediate | 2000–2999 | 1 |
| Advanced | 3000–3999 | 2 |
| Competitive | 4000+ | 3 (highest) |

The **registration tier** (`registrationTier`, set at signup and immutable) determines a player's
**point floor**: a loser's pts can never be clamped below their registration tier's `min_pts`.

## Singles scoring

For a singles result the engine computes one delta for the winner and one for the loser
(`compute_match_scoring` in `scoring_service.py`).

**Winner:**

```
winner_delta = base (+100)
             + upset_bonus (+50  if winner is strictly lower-tier than loser, else 0)
             + elo_bonus   (floor((loser_pts - winner_pts) * 0.05),
                            only inside an upset AND only when that diff > 0)
```

**Loser:**

```
penalty   = -50  if loser is strictly higher-tier than winner, else 0
loser_new = max(loser_pts + penalty, floor(loser_registration_tier))
loser_delta = loser_new - loser_pts   # the EFFECTIVE change after the floor clamp
```

| Constant | Value | When it applies |
| --- | --- | --- |
| `base` | `+100` | every non-walkover win |
| `upset_bonus` | `+50` | winner's tier strictly **lower** than loser's tier |
| `elo_bonus` | `floor((loser_pts - winner_pts) * 0.05)` | inside an upset, only when `loser_pts - winner_pts > 0` |
| `penalty` | `-50` | loser's tier strictly **higher** than winner's tier |
| floor clamp | `max(raw, min_pts of registration tier)` | always applied to the loser's new pts |

Tier comparison is **by tier, not by raw points** — see [Tier-based comparison](#tier-based-comparison-f-4).
After computing new pts, each player's tier is re-derived; `tier_crossed` is `true` when the new tier
differs from the tier before the match.

### Example A — same-tier win (no upset, no penalty)

Winner Intermediate **2200**, loser Intermediate **2400**. Same tier, so no upset bonus and no
penalty.

| Player | base | upset | elo | penalty | delta | pts before → after | tier_crossed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Winner | +100 | 0 | 0 | 0 | **+100** | 2200 → 2300 | false |
| Loser | 0 | 0 | 0 | 0 | **0** | 2400 → 2400 | false |

The loser delta is `0`. Losing to a **same-tier** opponent carries **no** point penalty — this is
intended (see F-4 below), not a bug.

### Example B — upset win with floor clamp

Winner Amateur **1800** (registration tier Amateur), loser Intermediate **2020** (registration tier
Intermediate). The Amateur beats a higher-tier Intermediate → upset.

- Winner: `base 100 + upset 50 + elo floor((2020 - 1800) * 0.05) = floor(220 * 0.05) = floor(11) = 11`
  → delta **+161** → 1800 → **1961** (still Amateur, range 1000–1999).
- Loser raw: `2020 + (-50) = 1970`. The Intermediate floor is `2000`, so the new pts are clamped:
  `max(1970, 2000) = 2000`. The **effective** loser delta is `2000 - 2020 = -20` (smaller in
  magnitude than the raw −50 because of the clamp).

| Player | base | upset | elo | penalty (raw) | effective delta | pts before → after | tier_crossed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Winner | +100 | +50 | +11 | — | **+161** | 1800 → 1961 | false |
| Loser | — | — | — | −50 | **−20** (clamped) | 2020 → 2000 | false |

### Example C — tier-crossing win

Winner Intermediate **2960**, loser Intermediate **2500**. Same tier (no upset, no penalty), but the
winner's `+100` pushes them across the Advanced threshold at 3000.

| Player | base | upset | elo | penalty | delta | pts before → after | tier_crossed |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Winner | +100 | 0 | 0 | 0 | **+100** | 2960 → 3060 (Intermediate → **Advanced**) | **true** |
| Loser | 0 | 0 | 0 | 0 | **0** | 2500 → 2500 | false |

A `tier_crossed = true` winner drives a `tier_crossed` ticker event.

## Doubles scoring

Doubles is scored **per player** by treating the opposing pair as a single notional opponent
(`_complete_with_scoring_doubles` in `match_confirmation_service.py`). The 4 players are split into a
winner pair and a loser pair (always 2 vs 2), and `compute_match_scoring` is called **once per
player** — 4 calls total.

Each call uses:

- **Opposing-pair average pts**, via **integer division**:
  `avg_opponent_pts = (opp_a_pts + opp_b_pts) // 2`. This averaged value is the `loser_pts` /
  `winner_pts` argument fed to the singles formula, and drives the ELO bonus.
- **The highest-tier opponent** for the tier check (`_highest_tier`), **not** an averaged tier. The
  upset bonus fires if **either** opposing player outranks the scored player by tier — mirroring the
  singles "did I beat someone ranked above me?" intent.

Everything downstream of those two inputs is identical to singles: base +100, upset +50, elo
`floor(diff × 0.05)`, penalty −50, and the loser floor clamp. Streaks and personal bests are
evaluated **per player**, with the same logic as singles.

Differences from singles:

- `pointHistory` reasons are `MATCH_DOUBLES_WIN` / `MATCH_DOUBLES_LOSS` (singles use
  `MATCH_WIN` / `MATCH_LOSS`).
- In each player's `pointHistory` entry, `opponent_uid` is the **alphabetically-first** uid of the
  opposing pair, and `opponent_pts_before` is the **averaged** opposing-pair pts.
- **No upset ticker is emitted for doubles** — intentionally deferred (DBL-6); the 2-vs-2 upset
  comparison rule is still TBD. Tier-crossed and personal-best tickers still fire per player.

### Example — 2-vs-2 mixed tiers

Winner pair A: **P1** Amateur **1900**, **P2** Intermediate **2100**.
Loser pair B: **P3** Intermediate **2200**, **P4** Intermediate **2400**.

Averages (integer division) and top tiers:

- `avg_loser_pts  = (2200 + 2400) // 2 = 2300`, top loser tier = **Intermediate**.
- `avg_winner_pts = (1900 + 2100) // 2 = 2000`, top winner tier = **Intermediate**.

Each player is then scored against those averaged pts + top opposing tier:

| Player | own pts / tier | scored vs | base | upset | elo | penalty | delta | pts after | tier_crossed |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| P1 (win) | 1900 / Amateur | 2300 / Intermediate | +100 | +50 | +20 | — | **+170** | 2070 (Amateur → **Intermediate**) | **true** |
| P2 (win) | 2100 / Intermediate | 2300 / Intermediate | +100 | 0 | 0 | — | **+100** | 2200 | false |
| P3 (loss) | 2200 / Intermediate | 2000 / Intermediate | — | — | — | 0 | **0** | 2200 | false |
| P4 (loss) | 2400 / Intermediate | 2000 / Intermediate | — | — | — | 0 | **0** | 2400 | false |

P1's elo bonus: `floor((2300 - 1900) * 0.05) = floor(400 * 0.05) = floor(20) = 20`. P1 is the only
upset (Amateur beating an Intermediate top opponent) and is the only player who crosses a tier. P3
and P4 lost to a same-tier (top) opponent, so their penalty is `0`.

## Tier-based comparison (F-4)

Upset bonus and penalty are decided by **tier only**, never by the raw point gap — this is the
**intended MVP behavior**, recorded here so it isn't later mistaken for a bug.

Consequence: a large **within-tier** point gap produces neither an upset bonus nor a penalty. For
example, an Intermediate player on **2,950 pts** beating an Intermediate player on **2,050 pts** (both
inside the Intermediate band, 2000–2999):

- the winner gets **base +100 only** (no upset bonus, because they are not a *lower* tier), and
- the loser takes **no penalty** (their opponent is not a *higher* tier).

Only a strict **tier** difference unlocks the +50 upset bonus (for the winner) or the −50 penalty
(for the loser). The `elo_bonus` does scale with the point gap, but only *inside* an upset (i.e. only
once a tier difference already exists). For the MVP this keeps point movement predictable and tied to
the visible tier ladder rather than to fine-grained rating math.

## Walkover / retirement

When a match is completed as a **walkover** or **retirement**, scoring is skipped entirely:

- both deltas are `0`,
- pts and tiers are **unchanged**,
- no `pointHistory` entry is written,
- streaks and personal bests are left untouched.

The match still transitions to `completed`; the `scoring` payload reflects zero deltas.

## See also

- `wiki/DATA_DICTIONARY.md` — `config/tiers` thresholds and the `pointHistory` field schema.
- `spec/api-launch-contracts.md` — the `verify-score` response shape and `ScoringPayload`.
- `api/app/services/scoring_service.py` — singles point math (`compute_match_scoring`).
- `api/app/services/match_confirmation_service.py` — doubles per-player orchestration
  (`_complete_with_scoring_doubles`).
