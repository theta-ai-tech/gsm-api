# Win Predictor Heuristic (Training Recency Weighting)

Architecture document for the Win Predictor enhancement (Phase 4, Tab 3 - THE LAB). This feature adjusts the base sigmoid win probability by incorporating recent training activity and its relevance to an opponent's known weaknesses.

> **Scope**: This document covers the heuristic formula, data dependencies, integration with the existing rivalry endpoint, and phased rollout. It does not cover ML-based prediction (deferred to a future phase with justification below).
>
> **Dependencies**: LAB-7 (base win probability), Phase 2 (Skill DNA), Phase 3 (scouting profiles).

---

## I. Open Questions Analysis

### Q1: What is the maximum adjustment (cap)?

**Answer: +/- 5 percentage points.**

The base win probability already accounts for the strongest predictor of match outcome: the point differential between two players. The training recency adjustment is a secondary signal -- it captures preparation quality, not fundamental skill level. A cap that is too high would let a week of practice sessions override hundreds of matches worth of point history. A cap that is too low would make the feature invisible and not worth building.

The 5pp cap was chosen by reasoning about boundary cases:

| Scenario | Base prob | Adjustment | Final prob | Feels right? |
|----------|-----------|------------|------------|-------------|
| Equal players, one trains hard all week | 50% | +5pp | 55% | Yes -- slight edge, not decisive |
| Underdog trains specifically for opponent weakness | 33% | +5pp | 38% | Yes -- still underdog, but prepared |
| Favourite trains hard, already dominant | 75% | +5pp | 80% | Yes -- marginal gain, diminishing returns |
| One training session, 5 days ago | 50% | +1pp | 51% | Yes -- minimal, appropriate |

A 5pp cap also keeps the final probability within the existing [0.01, 0.99] clamp range for any realistic base probability. Larger caps (e.g., 10pp) risk making the feature feel unreliable when predictions don't match outcomes -- amateur match results have high variance already.

### Q2: How to weight recency (today vs 5 days ago)?

**Answer: Linear decay over a 7-day window.**

Three decay functions were considered:

| Function | Formula | Day 0 weight | Day 3 weight | Day 6 weight | Complexity |
|----------|---------|-------------|-------------|-------------|------------|
| **Linear** | `(7 - days_ago) / 7` | 1.00 | 0.57 | 0.14 | Low |
| Exponential | `0.5 ^ (days_ago / 3)` | 1.00 | 0.50 | 0.25 | Medium |
| Step function | 1.0 if < 3 days, 0.5 otherwise | 1.00 | 1.00 | 0.50 | Low |

**Linear decay is recommended for v1.** Reasons:

1. **Simplicity**: Easy to explain to users ("recent training counts more"), easy to debug, easy to tune. No hyperparameters beyond the window size.
2. **Smooth degradation**: A training session from 6 days ago still contributes a small amount, rather than dropping off a cliff.
3. **Good enough**: The difference between linear and exponential decay is dwarfed by the noise in amateur match outcomes. Sophistication is not justified at this data volume.
4. **Tunability**: The window size (7 days) is the only knob. It can be adjusted based on user feedback without changing the formula structure.

Sessions older than 7 days receive zero weight. The 7-day window aligns with the typical amateur match cadence (1-3 matches per week) and ensures the adjustment reflects current preparation, not historical training volume.

### Q3: Should this be a simple heuristic or ML model?

**Answer: Heuristic for v1, with a clear upgrade path to ML.**

An ML model is premature for three reasons:

1. **Insufficient training data.** ML prediction requires labeled outcomes: "player A trained X, faced opponent B, result was Y." GSM currently has zero data points linking training logs to match outcomes. Even with Phase 3 in production, it will take months of user adoption before there are enough (training, scouting, outcome) triples to train a meaningful model.

2. **Cold start problem.** Most users will have sparse training logs and scouting data. An ML model would produce unreliable predictions for the majority of users, while the heuristic degrades gracefully to the base probability when data is missing.

3. **Explainability.** A heuristic can be explained: "Your win probability increased 3% because you logged 2 backhand training sessions this week and your opponent has a known backhand weakness." An ML model is a black box. For a v1 feature that users are seeing for the first time, explainability builds trust.

**ML upgrade path:** Once GSM has 6+ months of data linking training logs to match outcomes, a logistic regression or gradient-boosted model can be trained on features like: training frequency, training-to-weakness overlap, recency, Skill DNA trajectory, and H2H history. The heuristic's feature engineering (recency weighting, weakness matching) directly maps to ML features, so the v1 implementation is groundwork, not throwaway.

---

## II. Heuristic Formula

### Overview

The win predictor adjusts the base sigmoid probability with a bounded additive term derived from training relevance:

```
preparation_bonus = training_adjustment    # 0.0 to MAX_ADJUSTMENT (0.05)
```

Where `training_adjustment` is in the range `[0, MAX_ADJUSTMENT]` with `MAX_ADJUSTMENT = 0.05` (5 percentage points).

### Step 1: Compute base probability (existing)

```python
base_prob = 1.0 / (1.0 + 10 ** (-(my_pts - opp_pts) / 1000))
```

This is the existing `win_probability()` function in `scoring_service.py`. No changes needed.

### Step 2: Collect recent training sessions

Query `users/{my_uid}/journalEntries` for entries matching:
- `entry_type == "training"`
- `created_at` within the last 7 days before the match (or current time for on-demand queries)
- `sport` matches the rivalry sport

This returns a list of training journal entries with their `training_focus` pills (e.g., `["serve", "backhand"]`) and `created_at` timestamps.

### Step 3: Collect opponent weakness tags

Read `scouting/{opponent_uid}` and extract the `weak` tags for the relevant sport. Each tag has a `count` (number of community reports) providing a confidence weight.

Example: `{"backhand": {"count": 7}, "stamina_set3": {"count": 3}}`.

### Step 4: Map training focus to weakness tags

Training focus pills and scouting weakness tags use overlapping but not identical vocabularies. A mapping bridges the two:

```python
TRAINING_TO_WEAKNESS_MAP: dict[str, set[str]] = {
    # TrainingFocusEnum -> set of scouting weakness tags it could address
    "serve":     {"first_serve", "double_faults", "ace", "serve"},
    "volley":    {"volley", "net_approach", "net_play"},
    "footwork":  {"footwork", "stamina", "endurance", "fitness", "stamina_set3"},
    "backhand":  {"backhand", "backhand_winner"},
    "cardio":    {"stamina", "endurance", "fitness", "stamina_set3"},
    "strategy":  {"concentration", "composure", "mental", "tiebreak"},
}
```

A training session "matches" an opponent weakness if any of the session's `training_focus` pills map to any of the opponent's `weak` tags.

### Step 5: Compute weighted relevance score

For each training session in the 7-day window:

```
session_recency = (7 - days_since_session) / 7        # linear decay, range (0, 1]
session_match   = 1 if any training_focus maps to any opponent weakness, else 0
session_score   = session_recency * session_match
```

The raw relevance score is the sum of all session scores:

```
raw_relevance = sum(session_score for each session)
```

### Step 6: Normalize and cap

The raw relevance is normalized to the [0, 1] range using a saturation function, then scaled to the maximum adjustment:

```
normalized_relevance = min(1.0, raw_relevance / SATURATION_THRESHOLD)
training_adjustment  = normalized_relevance * MAX_ADJUSTMENT
```

Where:
- `SATURATION_THRESHOLD = 3.0` -- the raw relevance score at which the adjustment reaches its maximum. This means roughly 3 recent, relevant training sessions saturate the bonus.
- `MAX_ADJUSTMENT = 0.05` -- the 5pp cap.

The saturation threshold prevents users who log 10 training sessions from getting 10x the adjustment of someone who logs 1. Returns diminish after ~3 relevant sessions, which matches real-world training benefit curves.

### Step 7: Apply adjustment

```
preparation_bonus = training_adjustment    # 0.0 to MAX_ADJUSTMENT (0.05)
```

**Important: the training adjustment is NOT applied to `win_probability`.** Because the adjustment is one-sided (computed from the requesting user's training only), both players could see boosted probabilities that sum to more than 100%, which breaks probability semantics. Computing a bilateral adjustment would require reading the opponent's training data, violating the privacy model.

Instead, the adjustment is exposed as a **separate field** on the rivalry response:

```json
{
  "win_probability": 0.33,
  "preparation_bonus": 0.05,
  "preparation_detail": {
    "relevant_sessions": 3,
    "matched_weaknesses": ["backhand"],
    "recency_weighted_score": 2.4
  }
}
```

- `win_probability` remains the pure sigmoid based on point difference (unchanged, always sums to 100% across both players)
- `preparation_bonus` is the one-sided training adjustment (0.0–0.05) — a confidence signal, not a probability correction
- `preparation_detail` gives the user insight into what drove the bonus

The mobile client can display this as "Your preparation gives you an edge" or similar, without corrupting the core probability display.

### Complete formula summary

```
win_probability = 1 / (1 + 10^(-point_diff / 1000))    # unchanged sigmoid

preparation_bonus = min(1.0, sum(recency_i * match_i) / 3.0) * 0.05
                                                         # separate signal, 0.0–0.05
```

Note: `preparation_bonus` is returned as a separate field, NOT added to `win_probability`. See Step 7 above for rationale.

---

## III. Worked Examples

### Example 1: Active preparation against a known weakness

**Setup:**
- My points: 2000, Opponent points: 2500
- Base probability: `1 / (1 + 10^(500/1000))` = 0.24 (24%)
- Opponent scouting weaknesses (tennis): `{"backhand": 7, "stamina_set3": 3}`
- My training this week:
  - 2 days ago: `training_focus: ["backhand"]` -- matches "backhand" weakness
  - 4 days ago: `training_focus: ["backhand", "footwork"]` -- matches "backhand" and "stamina_set3"
  - 6 days ago: `training_focus: ["serve"]` -- no match to opponent weaknesses

**Calculation:**
```
Session 1 (2 days ago):  recency = (7-2)/7 = 0.71,  match = 1  -> score = 0.71
Session 2 (4 days ago):  recency = (7-4)/7 = 0.43,  match = 1  -> score = 0.43
Session 3 (6 days ago):  recency = (7-6)/7 = 0.14,  match = 0  -> score = 0.00

raw_relevance   = 0.71 + 0.43 + 0.00 = 1.14
normalized      = min(1.0, 1.14 / 3.0) = 0.38
adjustment      = 0.38 * 0.05 = 0.019
preparation_bonus = 0.019 (≈ 2pp)
```

**Result:** `win_probability` stays at 24%, `preparation_bonus` = 0.02. The UI can show: "Your recent backhand training gives you a slight edge."

### Example 2: Heavy training, all relevant

**Setup:**
- My points: 1500, Opponent points: 1500
- Base probability: 50%
- Opponent scouting weaknesses: `{"backhand": 5, "net_approach": 4}`
- My training this week:
  - Today: `["backhand"]` -- matches
  - 1 day ago: `["backhand", "volley"]` -- matches both
  - 2 days ago: `["volley"]` -- matches net_approach
  - 3 days ago: `["backhand"]` -- matches

**Calculation:**
```
Session 1 (0 days): recency = 1.00, match = 1 -> 1.00
Session 2 (1 day):  recency = 0.86, match = 1 -> 0.86
Session 3 (2 days): recency = 0.71, match = 1 -> 0.71
Session 4 (3 days): recency = 0.57, match = 1 -> 0.57

raw_relevance   = 1.00 + 0.86 + 0.71 + 0.57 = 3.14
normalized      = min(1.0, 3.14 / 3.0) = 1.0
adjustment      = 1.0 * 0.05 = 0.05
preparation_bonus = 0.05 (5pp — max)
```

**Result:** `win_probability` stays at 50%, `preparation_bonus` = 0.05 (maximum). The UI shows: "Your preparation gives you a strong edge — you've been training exactly against their weaknesses."

### Example 3: Training with no scouting data

**Setup:**
- My points: 2200, Opponent points: 2000
- Base probability: 61%
- Opponent scouting: no data (new player or no community reports)
- My training: 3 sessions this week

**Calculation:**
```
No opponent weakness tags -> all session_match = 0 -> raw_relevance = 0
adjustment = 0
preparation_bonus = 0.0
```

**Result:** `win_probability` = 61%, `preparation_bonus` = 0.0. No bonus. The UI can display: "Train against your opponent's weaknesses to earn a preparation edge. Ask the community to scout them!"

### Example 4: Training but not relevant to opponent

**Setup:**
- My points: 1800, Opponent points: 1800
- Base probability: 50%
- Opponent scouting weaknesses: `{"stamina_set3": 4}` (only stamina)
- My training: 2 sessions of `["serve"]` this week

**Calculation:**
```
"serve" does not map to "stamina_set3" -> all session_match = 0
raw_relevance = 0
adjustment = 0
preparation_bonus = 0.0
```

**Result:** `win_probability` = 50%, `preparation_bonus` = 0.0. Training on serve doesn't help against an opponent whose weakness is stamina. The UI can hint: "Your opponent's known weakness is late-set stamina. Consider cardio or footwork training."

---

## IV. Data Dependencies

### Required data sources

| Data | Collection / Path | Status | Used for |
|------|------------------|--------|----------|
| User points | `users/{uid}.rankings.{sport}.pts` | Exists (Phase 1) | Base probability |
| Training logs | `users/{uid}/journalEntries` where `entryType=training` | Exists (Tab 2) | Training sessions with `trainingFocus` and `createdAt` |
| Opponent weaknesses | `scouting/{opponentUid}.{sport}.weak` | Exists (Phase 3) | Weakness tags with community report counts |
| Skill taxonomy | `config/skillTaxonomy` | Exists (Phase 2) | Tag vocabulary reference (informational) |

All required data already exists in production. No new collections or fields are needed for the v1 heuristic.

### Data quality considerations

1. **Training log sparsity.** Most users log 0-2 training sessions per week. The formula handles this gracefully: zero sessions = zero adjustment. The saturation threshold of 3.0 means even 1-2 relevant sessions produce a visible (though small) adjustment.

2. **Scouting data sparsity.** New opponents or opponents in small communities may have few or no scouting reports. Zero weakness tags = zero adjustment. The formula never penalizes the absence of data.

3. **Training focus granularity.** The current `TrainingFocusEnum` has 6 values: `serve`, `volley`, `footwork`, `backhand`, `cardio`, `strategy`. This is coarse but sufficient for v1. If the taxonomy is expanded (e.g., adding `forehand`, `mental_game`), the `TRAINING_TO_WEAKNESS_MAP` simply gains new entries.

4. **Scouting tag vocabulary.** Scouting weakness tags come from the `config/skillTaxonomy.tagMap` values plus community-contributed tags. The `TRAINING_TO_WEAKNESS_MAP` must cover the full tag vocabulary. Unknown tags are ignored (safe default).

---

## V. Integration with Existing Code

### Where the adjustment lives

The adjustment is implemented as a new pure function in `api/app/services/scoring_service.py` alongside the existing `win_probability()` function:

```python
def adjusted_win_probability(
    my_pts: int,
    opponent_pts: int,
    training_sessions: list[TrainingSession],
    opponent_weaknesses: dict[str, int],  # tag -> count
    now: datetime | None = None,
) -> AdjustedWinProbability:
    ...
```

Where `TrainingSession` is a lightweight dataclass:

```python
@dataclass(frozen=True, slots=True)
class TrainingSession:
    training_focus: list[str]
    created_at: datetime
```

And the return type includes both the base and adjusted values for the UI:

```python
@dataclass(frozen=True, slots=True)
class AdjustedWinProbability:
    base: float           # original sigmoid probability
    adjusted: float       # after training recency weighting
    adjustment: float     # delta (adjusted - base)
    training_sessions_used: int  # how many sessions contributed
```

### Endpoint changes

The `GET /me/lab/rivalry/{opponent_uid}` endpoint currently returns `win_probability: float`. This would be extended to include the adjustment breakdown:

```python
class WinProbabilityDetail(GsmBaseModel):
    base: float
    adjusted: float
    training_boost: float
    training_sessions_used: int

class RivalryResponse(GsmBaseModel):
    # ... existing fields ...
    win_probability: float             # backward compat: returns adjusted value
    win_probability_detail: WinProbabilityDetail | None = None  # new, optional
```

The top-level `win_probability` field continues to return a single float (now the adjusted value) for backward compatibility. The new `win_probability_detail` field provides the breakdown for clients that want to display it.

### Endpoint data flow

```
GET /me/lab/rivalry/{opponent_uid}?sport=tennis
    |
    v
1. Fetch my_profile, opp_profile (existing)
    |
    v
2. Compute base_prob = win_probability(my_pts, opp_pts) (existing)
    |
    v
3. [NEW] Fetch my recent training sessions (journal_repo query)
    |
    v
4. [NEW] Fetch opponent scouting profile (scouting_repo, already fetched nearby)
    |
    v
5. [NEW] Compute preparation_bonus = compute_preparation_bonus(...)
    |
    v
6. Return RivalryResponse with win_probability (unchanged) + preparation_bonus (new field)
```

Steps 3-5 are the only additions. Step 3 requires a new repo method on the journal repo to query recent training entries. Step 4 uses the existing `scouting_repo.get_profile()`. Step 5 is a pure function with no I/O. The `win_probability` field remains the pure sigmoid — `preparation_bonus` is a separate field.

### New repo method needed

```python
# In journal_repo.py (or a new query on the existing repo)
def list_recent_training(
    self, uid: str, sport: str, since: datetime, limit: int = 20
) -> list[JournalEntry]:
    """Return training journal entries for a user/sport since a given date."""
```

This queries `users/{uid}/journalEntries` with:
- `entryType == "training"`
- `sport == sport`
- `createdAt >= since`
- `order by createdAt DESC`
- `limit`

**Soft-delete filtering**: Journal entries support soft deletion (`isDeleted` / `deletedAt` fields). The query must either add `isDeleted == false` as a filter condition (requires composite index update) or the repo method must filter deleted entries after reading. The latter is simpler given the small result set (max 20 entries in a 7-day window) and avoids an additional composite index.

A composite index on `(entryType ASC, sport ASC, createdAt DESC)` is required.

### Constants

New constants for `api/app/constants.py`:

```python
WIN_PREDICTOR_MAX_ADJUSTMENT = 0.05       # 5pp maximum
WIN_PREDICTOR_SATURATION_THRESHOLD = 3.0  # raw relevance score for full adjustment
WIN_PREDICTOR_RECENCY_WINDOW_DAYS = 7     # lookback window
WIN_PREDICTOR_MAX_SESSIONS = 20           # max training sessions to consider
```

---

## VI. Edge Cases

| Case | Handling |
|------|----------|
| **No training data** | `raw_relevance = 0`, adjustment = 0. Base probability returned unchanged. |
| **No scouting data** | All `session_match = 0`, adjustment = 0. Base probability returned unchanged. |
| **Both missing** | Adjustment = 0. Equivalent to current behavior. |
| **New user (no points)** | Default points (1000) used for base probability. Training adjustment applied normally if data exists. |
| **Training session on match day** | `days_since = 0`, recency weight = 1.0 (maximum). Valid -- same-day training is the most relevant. |
| **Training session exactly 7 days ago** | `days_since = 7`, recency weight = 0.0. Excluded from calculation (outside window). |
| **Opponent has only "strong" tags, no "weak"** | No weakness tags to match against. Adjustment = 0. |
| **Multiple training focuses in one session** | Each focus pill is checked against weakness tags. One match is enough for `session_match = 1`. Multiple matches in the same session do not double-count (binary match per session). |
| **Same weakness matched by multiple sessions** | Each session contributes independently. Three sessions targeting the same weakness all count (with recency weighting). This rewards sustained, focused preparation. |
| **Very high base probability (>95%)** | Adjustment is additive but clamped at 0.99. A 97% base + 5pp cap = 0.99 (clamped). The feature does not create false certainty. |
| **Daylight saving / timezone edge** | All timestamps are UTC. `days_since` computed from UTC datetimes. No timezone ambiguity. |

---

## VII. Implementation Phases

### Phase 4a: Core heuristic (this issue)

1. Add `TRAINING_TO_WEAKNESS_MAP` constant and `WIN_PREDICTOR_*` constants to `constants.py`.
2. Add `TrainingSession` and `AdjustedWinProbability` dataclasses to `scoring_service.py`.
3. Implement `compute_training_adjustment()` pure function in `scoring_service.py`.
4. Add `list_recent_training()` repo method to `journal_repo.py`.
5. Add Firestore composite index for the new query.
6. Update `get_rivalry()` endpoint to call the adjustment function.
7. Add `WinProbabilityDetail` to the `RivalryResponse`.
8. Unit tests for the pure function (edge cases, boundary values, examples from this doc).
9. Integration test for the rivalry endpoint with seeded training and scouting data.

### Phase 4b: UI hints (deferred)

- Return suggested training focus based on opponent weaknesses ("Train backhand to improve your odds").
- Requires no backend formula changes, only an additional response field.

### Phase 4c: Bilateral adjustment (deferred)

- Factor in the opponent's training data when computing the adjustment.
- Requires privacy review: should a user's adjustment reveal that their opponent has been training?
- May show both adjustments symmetrically: "You trained +3%, they trained +2%" with net effect.

### Phase 4d: ML upgrade (deferred, 6+ months)

- Train a logistic regression model on (training features, scouting features, match outcome) triples.
- Use the heuristic's feature engineering (recency weighting, weakness matching) as input features.
- A/B test ML predictions against heuristic predictions.
- Requires sufficient data volume: minimum 500 (training, match outcome) pairs.

---

## VIII. Weighting Scheme: Training-to-Weakness Matching

### The mapping table

The `TRAINING_TO_WEAKNESS_MAP` bridges two vocabularies:

| Training Focus (`TrainingFocusEnum`) | Matched Scouting Weakness Tags |
|-------------------------------------|-------------------------------|
| `serve` | `first_serve`, `double_faults`, `ace`, `serve` |
| `volley` | `volley`, `net_approach`, `net_play` |
| `footwork` | `footwork`, `stamina`, `endurance`, `fitness`, `stamina_set3` |
| `backhand` | `backhand`, `backhand_winner` |
| `cardio` | `stamina`, `endurance`, `fitness`, `stamina_set3` |
| `strategy` | `concentration`, `composure`, `mental`, `tiebreak` |

### Design decisions

1. **One-to-many mapping.** A single training focus can address multiple weakness tags. Training "footwork" helps exploit opponents weak in stamina-related areas. This is generous by design -- we want the feature to produce visible adjustments even with coarse training data.

2. **Binary match per session.** A session either matches (1) or does not (0). We do not weight by "how many" weakness tags it matches. This avoids over-rewarding sessions with many focus pills while keeping the formula simple.

3. **No scouting confidence weighting in v1.** The opponent's weakness tag `count` (number of community reports) is not used as a multiplier in v1. A weakness reported by 7 people and one reported by 1 person contribute equally to matching. This is a simplification -- v2 could weight by `min(1.0, count / 5)` to require community consensus before a weakness tag influences predictions.

4. **Extensible map.** When new `TrainingFocusEnum` values are added (e.g., `forehand`), only the map needs updating. The formula itself is unchanged.

---

## IX. Relationship to Existing Architecture

```
users/{uid}
    |
    +-- rankings.{sport}.pts  ---------> win_probability() [existing]
    |                                         |
    +-- journalEntries/                       |
    |     +-- {entryId}                       |
    |         entryType: "training"           |
    |         trainingFocus: [...]   ------+  |
    |         createdAt: ...               |  |
    |                                      v  v
    +-- skillDna.{sport}       compute_training_adjustment() [new]
                                           |
scouting/{opponentUid}                     |
    +-- {sport}.weak: {tag: count} --------+
                                           |
                                           v
                               adjusted_win_probability [new]
                                           |
                                           v
                          GET /me/lab/rivalry/{opponent_uid}
                                  RivalryResponse.win_probability
                                  RivalryResponse.win_probability_detail
```

No new Firestore collections are introduced. No new triggers are needed. The feature is entirely compute-on-read, consistent with the existing rivalry endpoint's architecture.

---

## X. Observability and Tuning

### Logging

The `adjusted_win_probability` function should log at `DEBUG` level:
- Number of training sessions found in the window
- Number of sessions that matched opponent weaknesses
- Raw relevance score
- Final adjustment value

This enables post-hoc analysis of how the feature is performing without impacting production latency.

### Tuning knobs

All tunable parameters are constants (not hardcoded in the formula):

| Constant | Default | What it controls |
|----------|---------|-----------------|
| `WIN_PREDICTOR_MAX_ADJUSTMENT` | 0.05 | Maximum probability boost |
| `WIN_PREDICTOR_SATURATION_THRESHOLD` | 3.0 | Sessions needed for full boost |
| `WIN_PREDICTOR_RECENCY_WINDOW_DAYS` | 7 | Lookback window |
| `WIN_PREDICTOR_MAX_SESSIONS` | 20 | Query limit for training sessions |

These can be promoted to `config/winPredictor` (Firestore config document) in a future phase if dynamic tuning without redeployment is needed.

### Success metrics

The feature is successful if:
1. Users who receive a positive `preparation_bonus` win at a rate higher than those who don't, after controlling for the base `win_probability`.
2. The bonus is non-zero for at least 20% of rivalry queries (indicating sufficient training + scouting data coverage).
3. No user reports the preparation bonus as "feeling wrong" in feedback (qualitative signal).

Metric 1 requires tracking: for each rivalry query where `preparation_bonus > 0`, log the `(preparation_bonus, win_probability, actual_outcome)` triple. After 200+ data points, compute whether the bonus correlates with win rate uplift.
