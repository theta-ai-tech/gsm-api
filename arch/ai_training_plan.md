# AI Training Plan — Drill Database & Recommendation Logic

Architecture document for the AI Training Plan feature (Phase 4, Tab 3 - THE LAB). This feature generates personalised training recommendations by matching a player's Skill DNA weaknesses and optional opponent scouting data to a curated drill database.

> **Scope**: This document covers the drill data model, recommendation algorithm, content pipeline, API integration, and phased rollout. It does not cover AI-generated drill content (deferred to a future phase with justification below).
>
> **Dependencies**: Phase 2 (Skill DNA), Phase 3 (scouting profiles), Win Predictor heuristic (uses the same `TRAINING_TO_WEAKNESS_MAP` vocabulary bridge).

---

## I. Open Questions Analysis

### Q1: How should drills be structured and stored?

**Answer: Firestore collection (`drills/{drillId}`) with a static seed, not hardcoded config.**

Three storage strategies were considered:

| Strategy | Pros | Cons | Verdict |
|----------|------|------|---------|
| **Hardcoded in Python** | Zero Firestore reads; simple deployment | Cannot add/edit without redeployment; no admin tooling path; bloats code | Rejected |
| **Firestore config document** (`config/drills`) | Single read; cacheable | 1MB doc limit constrains growth; no per-drill querying; awkward to paginate | Rejected |
| **Firestore collection** (`drills/{drillId}`) | Per-drill queries; indexable by axis/sport/difficulty; admin CRUD path; no size ceiling | Extra reads (mitigated by small result sets and caching) | **Chosen** |

The collection approach is consistent with how GSM stores other domain entities (matches, leagues, scouting profiles). Drills are read infrequently (only when a user requests training recommendations) and the total corpus is small (50-200 drills in v1), so read costs are negligible.

A local in-memory cache (TTL 1 hour) on the API server eliminates repeated Firestore reads for the same drill set within a deployment window. Drills change rarely — the cache hit rate will be near 100%.

### Q2: How does the recommendation engine select drills?

**Answer: Weakness-first matching with optional opponent-aware prioritisation.**

The engine operates in two modes:

1. **General mode** (no opponent specified): Recommends drills that target the user's weakest Skill DNA axes. This is the default when a user opens the training plan from the Lab dashboard.

2. **Opponent-aware mode** (opponent UID provided): Prioritises drills that target the intersection of the user's weaknesses AND the opponent's known weaknesses from scouting. This is the pre-match preparation mode, deep-linked from the Rivalry Scout.

The opponent-aware mode reuses the `TRAINING_TO_WEAKNESS_MAP` from the Win Predictor heuristic, ensuring consistency: drills recommended in opponent-aware mode directly feed the `preparation_bonus` calculation.

### Q3: How should drill content be managed?

**Answer: Developer-seeded initial corpus, with admin API expansion path.**

The initial drill database is seeded via the existing `tools/seed_data.py` + `tools/seed_mapping.py` pipeline, the same mechanism used for scouting profiles and leaderboard data. This keeps the content pipeline simple for v1.

Future expansion paths (in priority order):
1. **Admin API**: A protected `POST /admin/drills` endpoint for content managers to add drills without redeployment.
2. **Community contributions**: Users submit drill suggestions that are moderated before inclusion. Requires a review queue (significant UX work, deferred).
3. **AI-generated drills**: LLM produces drill descriptions from weakness patterns. Requires quality control and content review (deferred to Phase 5+).

### Q4: What is the minimum viable drill database size?

**Answer: 30 drills (6 per Skill DNA axis, across 2 difficulty levels).**

The recommendation engine needs enough variety to avoid showing the same drill repeatedly. With 5 radar axes and 2 difficulty tiers (beginner-intermediate, advanced-competitive), 30 drills provide:
- 3 drills per axis per difficulty tier
- Sufficient rotation for weekly recommendations (users train 2-3 times/week)
- Coverage across all three sports (some drills are sport-specific, others are universal)

The v1 seed targets 40-50 drills to provide comfortable headroom. Below 20 drills, the feature feels thin — users see repeats within a week. Above 100 drills, curation quality becomes the bottleneck.

### Q5: Should this be a rule-based engine or ML model?

**Answer: Rule-based for v1, with the same ML upgrade path as the Win Predictor.**

The reasoning mirrors the Win Predictor decision (see `arch/win_predictor_heuristic.md` section I, Q3):

1. **Insufficient interaction data.** ML recommendation requires implicit feedback (drill completed, drill skipped, match outcome after training). GSM has zero data points linking drill recommendations to outcomes. The rule-based engine generates this data as a byproduct.

2. **Cold start.** New users have sparse Skill DNA (minimum 3 data points per axis before display). A rule-based engine handles sparse data gracefully by falling back to general-purpose drills.

3. **Explainability.** "We recommend this drill because your net play score is 35/100 and your next opponent has weak volleys" is more trustworthy than a black-box ranking.

---

## II. Proposed Data Model

### A. New collection: `drills/{drillId}`

Static content collection containing the drill catalogue. Drills are sport-tagged and mapped to Skill DNA axes.

**Path**: `drills/{drillId}`

```json
{
  "drillId": "drill_serve_accuracy_01",
  "title": "Target Serve Placement",
  "description": "Place 4 targets in the service box corners. Hit 10 serves to each target, tracking accuracy. Focus on ball toss consistency and follow-through direction.",
  "sport": "tennis",
  "axis": "serve",
  "tags": ["first_serve", "ace", "serve"],
  "difficulty": "intermediate",
  "durationMinutes": 20,
  "equipment": ["balls", "targets"],
  "playerCount": 1,
  "trainingFocusMapping": ["serve"],
  "createdAt": "2026-03-28T10:00:00Z",
  "isActive": true
}
```

### B. Field definitions: `drills/{drillId}`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `drillId` | string | Yes | Stable identifier, used as document ID |
| `title` | string | Yes | Short drill name (max 80 chars) |
| `description` | string | Yes | Drill instructions (max 500 chars) |
| `sport` | string (enum) | Yes | One of `SportEnum` (`tennis`, `padel`, `pickleball`) or `universal`. **Note:** `universal` is a drill-only value not present in `SportEnum`. The filtering logic treats it as matching any sport — see Step 1 in section III. A `DrillSportEnum` extending `SportEnum` with `universal` should be defined in `models/`. |
| `axis` | string (enum) | Yes | Primary Skill DNA axis: `serve`, `power`, `net_play`, `stamina`, `mental` |
| `tags` | array[string] | Yes | Scouting/taxonomy tags this drill addresses (from `config/skillTaxonomy.tagMap`) |
| `difficulty` | string (enum) | Yes | `DrillDifficultyEnum`: `beginner`, `intermediate`, `advanced`, `competitive`. **Note:** This is a new drill-specific enum, *not* `TierEnum` (`amateur`, `intermediate`, `advanced`, `competitive`). The one-tier-adjacent filtering maps user tiers to drill difficulties: `amateur` → sees `beginner` + `intermediate`; `intermediate` → sees `beginner` + `intermediate` + `advanced`; `advanced` → sees `intermediate` + `advanced` + `competitive`; `competitive` → sees `advanced` + `competitive`. |
| `durationMinutes` | int | Yes | Estimated duration (10-60 range) |
| `equipment` | array[string] | No | Required equipment beyond standard (e.g., `["targets", "cones"]`) |
| `playerCount` | int | Yes | Minimum players needed (1 = solo drill, 2 = partner required) |
| `trainingFocusMapping` | array[string] | Yes | Maps to `TrainingFocusEnum` values — when a user logs this drill as a training session, these are the suggested `trainingFocus` pills |
| `createdAt` | timestamp | Yes | When drill was added to the database |
| `isActive` | boolean | Yes | Soft-delete flag; inactive drills are excluded from recommendations |

### C. Recommendation response schema

The recommendation endpoint returns a ranked list of drills with relevance scoring. This is the API response model, not a Firestore document.

```json
{
  "recommendations": [
    {
      "drill_id": "drill_serve_accuracy_01",
      "title": "Target Serve Placement",
      "description": "Place 4 targets in the service box corners...",
      "sport": "tennis",
      "axis": "serve",
      "difficulty": "intermediate",
      "duration_minutes": 20,
      "equipment": ["balls", "targets"],
      "player_count": 1,
      "relevance_score": 0.85,
      "relevance_reason": "Your serve score is 35/100 — this drill targets your weakest axis",
      "opponent_relevant": true,
      "opponent_reason": "3 players noted your opponent has a weak return of serve"
    }
  ],
  "weakness_summary": {
    "weakest_axis": "serve",
    "weakest_score": 35,
    "axes_below_threshold": ["serve", "stamina"]
  },
  "opponent_context": {
    "opponent_uid": "user_bob",
    "matched_weaknesses": ["first_serve", "stamina_set3"],
    "scouting_confidence": 12
  }
}
```

### D. Relationship to existing collections

```
users/{uid}
    |
    +-- skillDna.{sport}  ---------> weakness axes for recommendation input
    |     serve: {positive, negative, score}
    |     power: {positive, negative, score}
    |     net_play: {positive, negative, score}
    |     stamina: {positive, negative, score}
    |     mental: {positive, negative, score}
    |
    +-- journalEntries/
    |     +-- {entryId}
    |         entryType: "training"
    |         trainingFocus: [...]  -------> training history (avoid repeat drills)
    |         createdAt: ...

scouting/{opponentUid}
    +-- {sport}.weak: {tag: count} ---------> opponent weakness input

drills/{drillId}  (new)
    +-- axis, tags, difficulty, sport  -----> drill catalogue for matching

config/skillTaxonomy
    +-- tagMap: {tag: axis}  -------> vocabulary bridge (existing)
```

### E. No new user-level collections

The recommendation is compute-on-read. There is no `trainingPlans/{uid}` collection. Recommendations are generated fresh on each request based on the current Skill DNA and scouting state. This avoids staleness and eliminates a write/sync burden.

Training history awareness (avoiding repeat recommendations) uses the existing `journalEntries` subcollection — the engine queries recent training sessions and filters drills whose `trainingFocusMapping` overlaps with recently logged focuses.

---

## III. Recommendation Algorithm

### Overview

The recommendation engine is a pure function that takes three inputs and produces a ranked drill list:

```
recommend_drills(
    skill_dna: SportSkillDna,
    drills: list[Drill],
    opponent_weaknesses: dict[str, int] | None,
    recent_training_focuses: list[str],
    user_tier: str,
) -> list[RankedDrill]
```

### Step 1: Filter eligible drills

From the full drill catalogue, filter to:
- `sport` matches the requested sport OR `sport == "universal"`
- `isActive == true`
- `difficulty` is within one tier of the user's tier, using the tier-to-difficulty mapping: `amateur` → `beginner` + `intermediate`; `intermediate` → `beginner` + `intermediate` + `advanced`; `advanced` → `intermediate` + `advanced` + `competitive`; `competitive` → `advanced` + `competitive`

The tier-to-difficulty mapping bridges `TierEnum` (user tiers) to `DrillDifficultyEnum` (drill difficulties). This prevents beginners from seeing drills they cannot execute and competitive players from seeing drills too basic to be useful.

### Step 2: Compute weakness scores

Extract the user's Skill DNA and identify weak axes. Axes may be `None` (insufficient data — fewer than 3 reflections for that axis). Missing axes are assigned a neutral need score of 0.50 so that drills targeting them appear mid-rank rather than being hidden or over-prioritised.

```python
WEAKNESS_THRESHOLD = 50  # axes scoring below this are "weak"
DEFAULT_AXIS_NEED = 0.50 # neutral need for axes with insufficient data

ALL_AXES = ["serve", "power", "net_play", "stamina", "mental"]

axis_scores = {}
for axis_name in ALL_AXES:
    axis_obj = getattr(skill_dna, axis_name, None)  # SportSkillDna axes are nullable
    if axis_obj is not None and axis_obj.score is not None:
        axis_scores[axis_name] = axis_obj.score
    else:
        axis_scores[axis_name] = None  # insufficient data

# Invert scores: lower skill = higher need = higher weight
# Missing axes get DEFAULT_AXIS_NEED (0.50) — mid-rank, neither prioritised nor hidden
axis_need = {
    axis: DEFAULT_AXIS_NEED if score is None else max(0, 100 - score) / 100.0
    for axis, score in axis_scores.items()
}
```

An axis with score 20 gets need 0.80; an axis with score 80 gets need 0.20; an axis with `None` (insufficient data) gets need 0.50. This creates a continuous gradient rather than a binary weak/strong split, and degrades gracefully for users with partial Skill DNA profiles.

> **Note**: The endpoint still returns 404 if the user has *no* Skill DNA at all for the sport (zero axes populated). Partial profiles (1-4 axes populated) are handled by the neutral fallback above.

### Step 3: Score each drill — base relevance

For each eligible drill, compute a base relevance score from the user's axis need:

```
base_relevance = axis_need[drill.axis]
```

A drill targeting the user's weakest axis gets the highest base relevance.

### Step 4: Score each drill — opponent bonus

If opponent scouting data is provided, compute an opponent relevance bonus:

```python
OPPONENT_BONUS_WEIGHT = 0.3  # opponent context adds up to 30% to the score

# Reuse TRAINING_TO_WEAKNESS_MAP from win_predictor_heuristic
drill_addresses_weakness = any(
    tag in opponent_weak_tags
    for tag in drill.tags
)

opponent_bonus = OPPONENT_BONUS_WEIGHT if drill_addresses_weakness else 0.0
```

This reuses the same tag vocabulary and matching logic as the Win Predictor's `TRAINING_TO_WEAKNESS_MAP`, ensuring that drills recommended in opponent-aware mode will contribute to the `preparation_bonus` when logged as training sessions.

### Step 5: Score each drill — recency penalty

Penalise drills whose `trainingFocusMapping` overlaps with the user's recent training focuses (last 7 days):

```python
RECENCY_PENALTY = 0.2  # reduce score by 20% for recently trained focuses

recently_trained = set(recent_training_focuses)
drill_focuses = set(drill.training_focus_mapping)

if drill_focuses & recently_trained:
    recency_modifier = -RECENCY_PENALTY
else:
    recency_modifier = 0.0
```

This prevents the engine from recommending serve drills to a user who just logged three serve training sessions this week. The penalty is mild (20%) — if serve is genuinely the user's weakest axis, serve drills still rank high despite the penalty.

### Step 6: Compute final score and rank

```
final_score = base_relevance + opponent_bonus + recency_modifier
```

Clamp to [0.0, 1.0]. Sort descending by `final_score`. Return the top N drills (default N=5, configurable via constant).

### Step 7: Generate relevance reasons

For each recommended drill, generate a human-readable explanation:

- If `base_relevance > 0.5`: "Your {axis} score is {score}/100 — this drill targets your weakest area"
- If `opponent_bonus > 0`: "{count} players noted your opponent has weak {tag}"
- If `recency_modifier < 0`: "You've been training {focus} recently — try mixing it up"

These strings are returned in the response for the mobile client to display as coaching context.

### Complete formula summary

```
eligible     = filter(sport, isActive, difficulty_adjacent)
base         = (100 - axis_score) / 100           # 0.0–1.0, weakness-proportional
opp_bonus    = 0.3 if drill tags match opponent weaknesses, else 0.0
recency_pen  = -0.2 if drill focus recently trained, else 0.0
final_score  = clamp(base + opp_bonus + recency_pen, 0.0, 1.0)
```

### Worked Example

**Setup:**
- User: intermediate tier, tennis
- Skill DNA: serve=35, power=72, net_play=45, stamina=60, mental=80
- Opponent scouting (tennis): `{"first_serve": 4, "stamina_set3": 2}`
- Recent training (last 7 days): `["serve", "footwork"]`

**Drill candidates after filtering:**

| Drill | Axis | Tags | Focus Mapping |
|-------|------|------|---------------|
| Target Serve Placement | serve | first_serve, serve | serve |
| Net Rush Drill | net_play | volley, net_approach | volley |
| 3rd Set Stamina Builder | stamina | stamina_set3, endurance | cardio |
| Backhand Cross-Court | power | backhand_winner | backhand |

**Scoring (applying Steps 3-6):**

| Drill | Base (axis need) | Opp Bonus (Step 4: drill.tags ∩ opponent weak tags) | Recency Pen (Step 5: focusMapping ∩ recent training) | Final |
|-------|-----------------|-----------|-------------|-------|
| Target Serve Placement | 0.65 (serve=35) | +0.3 (`first_serve` ∈ opponent tags ✓) | -0.2 (`serve` ∈ recent training ✓) | **0.75** |
| Net Rush Drill | 0.55 (net_play=45) | 0.0 (no tag match) | 0.0 (`volley` ∉ recent training) | **0.55** |
| 3rd Set Stamina Builder | 0.40 (stamina=60) | +0.3 (`stamina_set3` ∈ opponent tags ✓) | 0.0 (`cardio` ∉ recent training) | **0.70** |
| Backhand Cross-Court | 0.28 (power=72) | 0.0 (no tag match) | 0.0 (`backhand` ∉ recent training) | **0.28** |

**Result:** Serve drill ranks first (0.75) — despite the recency penalty, the axis need (0.65) plus opponent bonus (0.3) overwhelm it. Stamina Builder is second (0.70) — moderate weakness but a direct opponent tag match via `stamina_set3`. Net rush is third (0.55) — decent weakness, no bonuses or penalties. The engine correctly prioritises the user's weak areas that also exploit the opponent's known weaknesses.

---

## IV. Content Pipeline

### Initial seed strategy

The v1 drill database is seeded as static data in `tools/seed_data.py`, following the established pattern for scouting profiles and leaderboard snapshots.

Each drill is defined as a Python dataclass and converted to a Firestore document via `tools/seed_mapping.py`. The seed script runs as part of `make seed-emu` for emulator testing.

### Drill catalogue structure (v1 target: 40-50 drills)

| Axis | Tennis | Padel | Pickleball | Universal | Total |
|------|--------|-------|------------|-----------|-------|
| serve | 3 | 2 | 2 | 1 | 8 |
| power | 3 | 2 | 2 | 1 | 8 |
| net_play | 3 | 2 | 2 | 1 | 8 |
| stamina | 2 | 1 | 1 | 4 | 8 |
| mental | 2 | 1 | 1 | 4 | 8 |
| **Total** | **13** | **8** | **8** | **11** | **40** |

Universal drills (footwork, cardio, visualisation, match simulation) apply across all three sports. Sport-specific drills reference sport-specific techniques (e.g., padel bandeja, pickleball dink).

### Difficulty distribution

| Difficulty | Count | Target audience |
|------------|-------|-----------------|
| beginner | 10 | Amateur tier (1000-1999 pts) |
| intermediate | 15 | Intermediate tier (2000-2999 pts) |
| advanced | 10 | Advanced tier (3000-3999 pts) |
| competitive | 5 | Competitive tier (4000+ pts) |

Higher tiers have fewer drills because competitive players have more specific needs — the v1 catalogue serves the bulk of users (amateur + intermediate = 62% of drills).

### Metadata standards

- **Title**: Imperative verb + focus (e.g., "Improve First Serve Consistency", "Build Net Confidence"). Max 80 chars.
- **Description**: 2-3 sentences covering setup, execution, and success criteria. Max 500 chars. No jargon — written for amateur players.
- **Equipment**: Only non-standard items listed. Racquet and balls are assumed. Common extras: `targets`, `cones`, `wall`, `ball_machine`, `partner`.
- **Duration**: In 5-minute increments. Range: 10-60 minutes. Most drills target 15-20 minutes (fits a pre-match warmup or standalone session).

### Future expansion

The drill collection schema supports growth without migration:

1. **New axes**: If the Skill DNA radar adds a 6th axis, new drills with that axis value are simply added to the collection. No existing drills are affected.
2. **Video content**: A future `videoUrl` field (string, optional) can be added to drill documents without breaking existing clients (they ignore unknown fields).
3. **Community ratings**: A future `avgRating` and `ratingCount` field pair enables user feedback on drill quality, allowing content curation based on community signal.

---

## V. API Integration

### Endpoint: `GET /me/lab/training-plan`

| Attribute | Value |
|-----------|-------|
| Method | GET |
| Path | `/me/lab/training-plan` |
| Auth | Bearer (self) — Premium (Pro subscription required) |
| Query params | `sport` (required, enum), `opponent_uid` (optional, string), `limit` (optional, int, default 5, max 10) |

### Request flow

```
GET /me/lab/training-plan?sport=tennis&opponent_uid=user_bob
    |
    v
1. Auth + Premium gate (verify Pro subscription)
    |
    v
2. Fetch user's skillDna.{sport} (users_repo)
    |
    v
3. Fetch all active drills (drills_repo, cached in-memory)
    |
    v
4. [If opponent_uid] Fetch scouting/{opponent_uid}.{sport}.weak (scouting_repo)
    |
    v
5. Fetch recent training sessions, last 7 days (journal_repo)
    |
    v
6. Run recommend_drills() pure function (training_plan_service)
    |
    v
7. Return TrainingPlanResponse
```

Steps 2-5 are independent Firestore reads that can be parallelised. Step 6 is CPU-only (pure function, no I/O).

### Request model

No request body — all inputs via query parameters.

```python
# Query parameters (in router)
sport: SportEnum           # required
opponent_uid: str | None   # optional
limit: int = 5             # optional, 1-10
```

### Response model

```python
class DrillRecommendation(GsmBaseModel):
    drill_id: str
    title: str
    description: str
    sport: str
    axis: str
    difficulty: str
    duration_minutes: int
    equipment: list[str]
    player_count: int
    relevance_score: float          # 0.0-1.0
    relevance_reason: str           # human-readable explanation
    opponent_relevant: bool         # true if drill targets opponent weakness
    opponent_reason: str | None     # explanation of opponent relevance

class WeaknessSummary(GsmBaseModel):
    weakest_axis: str
    weakest_score: int
    axes_below_threshold: list[str]  # axes with score < 50

class OpponentContext(GsmBaseModel):
    opponent_uid: str
    matched_weaknesses: list[str]    # scouting tags matched to drills
    scouting_confidence: int         # total scouting reports for this opponent

class TrainingPlanResponse(GsmBaseModel):
    recommendations: list[DrillRecommendation]
    weakness_summary: WeaknessSummary
    opponent_context: OpponentContext | None  # null if no opponent specified
```

### Premium gate

The AI Training Plan is a Pro feature. The endpoint checks the user's subscription status before processing. Non-Pro users receive a `403 Forbidden` with a message directing them to upgrade.

```python
# Premium check in router (before processing)
if not current_user.is_pro:
    raise HTTPException(
        status_code=403,
        detail="AI Training Plan requires a Pro subscription"
    )
```

The `is_pro` field is read from the user's profile or auth claims. The exact mechanism depends on the subscription infrastructure (deferred to the subscription system design). For v1, a simple boolean field on the user document (`users/{uid}.isPro`) is sufficient.

### Error responses

| Status | Condition | Detail |
|--------|-----------|--------|
| 401 | No/invalid auth token | "Not authenticated" |
| 403 | User is not Pro subscriber | "AI Training Plan requires a Pro subscription" |
| 404 | Opponent not found (if `opponent_uid` provided) | "User not found" |
| 404 | User has no Skill DNA for this sport | "No Skill DNA data for tennis. Play and reflect on more matches to build your profile." |
| 422 | Invalid sport or limit | Pydantic validation error |

### Constants

New constants for `api/app/constants.py`:

```python
TRAINING_PLAN_DEFAULT_LIMIT = 5           # default number of drill recommendations
TRAINING_PLAN_MAX_LIMIT = 10              # maximum recommendations per request
TRAINING_PLAN_WEAKNESS_THRESHOLD = 50     # axis score below which it's "weak"
TRAINING_PLAN_OPPONENT_BONUS = 0.3        # opponent weakness match bonus weight
TRAINING_PLAN_RECENCY_PENALTY = 0.2       # penalty for recently trained focuses
TRAINING_PLAN_RECENCY_WINDOW_DAYS = 7     # lookback for recent training
TRAINING_PLAN_DRILL_CACHE_TTL_SECS = 3600 # 1 hour in-memory cache for drill catalogue
```

---

## VI. Implementation Phases

### Phase 4a: Drill database + data layer

1. Add `Drill` Pydantic model to `api/app/models/`.
2. Add `DrillsRepo` with `list_active_drills(sport)` to `api/app/repos/`.
3. Add drill mapper to `repos/mappers.py` (camelCase <-> snake_case).
4. Add `get_drills_repo` dependency to `api/app/dependencies/repos.py`.
5. Add drill seed data to `tools/seed_data.py` and `tools/seed_mapping.py`.
6. Seed 40-50 drills covering all axes, sports, and difficulty levels.

### Phase 4b: Recommendation engine + endpoint

1. Add `recommend_drills()` pure function to `api/app/services/training_plan_service.py`.
2. Add constants to `api/app/constants.py`.
3. Add `GET /me/lab/training-plan` endpoint to `api/app/routers/lab.py`.
4. Add response models (`TrainingPlanResponse`, `DrillRecommendation`, etc.) to the router.
5. Wire up the endpoint: auth -> premium gate -> data fetch -> recommend -> respond.
6. Add `list_recent_training()` repo method if not already added by Win Predictor (LAB-26).

### Phase 4c: Tests + premium gate

1. Unit tests for `recommend_drills()` — all edge cases from section VII.
2. Unit tests for the endpoint — mock repos, verify response shape and premium gate.
3. Integration tests — seed drills + user data in emulator, verify end-to-end.
4. Implement premium gate (depends on subscription infrastructure).

### Phase 4d: Training history feedback loop (deferred)

1. When a user logs a training session, suggest matching drills from their recent recommendations.
2. Track which recommended drills were actually practiced (via `trainingFocus` overlap in journal entries).
3. Use completion data to improve recommendations (boost drills the user hasn't tried, demote drills they skip).

### Phase 4e: AI-enhanced content (deferred, 6+ months)

1. LLM-generated drill descriptions tailored to user context.
2. Dynamic drill creation based on specific weakness combinations.
3. Coaching narrative: "Focus on X this week because your last 3 matches show Y pattern."
4. Requires content quality review pipeline.

---

## VII. Edge Cases

| Case | Handling |
|------|----------|
| **No Skill DNA data at all** | Return 404 with message: "No Skill DNA data for {sport}. Play and reflect on more matches to build your profile." Zero axes populated for this sport. |
| **Partial Skill DNA (some axes missing)** | Axes with insufficient data (`None`) get a neutral need of 0.50 — mid-rank. Drills targeting these axes still appear but don't dominate. The `weakness_summary` only includes populated axes; `insufficient_axes` is listed separately so the client can prompt the user to reflect more. |
| **All axes above threshold (no weaknesses)** | The algorithm still works — axes with score 80 get need 0.20. Recommendations are less urgent but still valid. The `weakness_summary.axes_below_threshold` is empty. Response includes a note: "Your skills are well-balanced. These drills maintain your edge." |
| **No scouting data for opponent** | `opponent_context` is null. `opponent_bonus` is 0 for all drills. Base relevance drives ranking entirely. |
| **Opponent UID not found** | Return 404: "User not found." |
| **No active drills for the sport** | Return empty `recommendations` list. This should not happen with a properly seeded database but is handled gracefully. |
| **New user (no training history)** | `recency_modifier` is 0 for all drills (no penalty). Recommendations are purely weakness-driven. |
| **User trained every focus area recently** | All drills receive a -0.2 penalty. The ranking still works — the highest-need axis drills are still on top, just with lower absolute scores. |
| **Non-Pro user** | 403 before any data is fetched. Zero Firestore reads wasted. |
| **Universal drills vs sport-specific** | Universal drills (`sport == "universal"`) are included for every sport query. They rank alongside sport-specific drills using the same scoring formula. |
| **Difficulty mismatch** | An `amateur` user sees `beginner` + `intermediate` drills only. An `intermediate` user sees `beginner` + `intermediate` + `advanced`. Mapping from `TierEnum` → `DrillDifficultyEnum` is explicit (see Step 1 in section III). |

---

## VIII. Relationship to Existing Architecture

```
users/{uid}
    |
    +-- skillDna.{sport}  ---------> weakness input (existing, Phase 2)
    |     {axis: {positive, negative, score}}
    |
    +-- rankings.{sport}.tier  ----> difficulty filtering (existing, Phase 1)
    |
    +-- journalEntries/
    |     +-- entryType: "training"
    |         trainingFocus: [...]  -> recency penalty (existing, Tab 2)
    |
    +-- isPro  --------------------> premium gate (new field, simple boolean)

scouting/{opponentUid}
    +-- {sport}.weak: {tag: count} -> opponent bonus (existing, Phase 3)

drills/{drillId}  (new collection)
    +-- axis, tags, difficulty
    +-- sport, title, description
    +-- trainingFocusMapping  -----> links to TrainingFocusEnum (existing)

config/skillTaxonomy  (existing)
    +-- tagMap: {tag: axis}  ------> vocabulary reference

                    |
                    v
          recommend_drills() [new pure function]
                    |
                    v
          GET /me/lab/training-plan [new endpoint]
                    |
                    v
          TrainingPlanResponse
            +-- recommendations[]  (ranked drills)
            +-- weakness_summary   (Skill DNA context)
            +-- opponent_context   (scouting context, optional)
```

The feature introduces one new Firestore collection (`drills/{drillId}`) and one new endpoint. All other data dependencies are existing collections. The recommendation engine is a pure function with no side effects — it reads data and computes a ranking without writing anything to Firestore.

The connection to the Win Predictor is deliberate: drills recommended in opponent-aware mode map to `TrainingFocusEnum` values via `trainingFocusMapping`. When a user logs one of these drills as a training session, the Win Predictor's `compute_preparation_bonus()` will detect the relevance to opponent weaknesses and increase the `preparation_bonus`. This creates a virtuous loop:

```
AI Training Plan recommends drill → User trains → Logs training session
  → Win Predictor detects relevant training → preparation_bonus increases
    → User sees "Your preparation gives you an edge" in Rivalry Scout
```

---

## IX. Observability and Tuning

### Logging

The `recommend_drills()` function logs at `DEBUG` level:
- Number of eligible drills after filtering
- User's weakest axis and score
- Number of drills with opponent bonus (if opponent mode)
- Number of drills with recency penalty
- Top 3 drill IDs and their final scores

### Tuning knobs

All parameters are constants (not hardcoded in the formula):

| Constant | Default | What it controls |
|----------|---------|-----------------|
| `TRAINING_PLAN_DEFAULT_LIMIT` | 5 | Default recommendations returned |
| `TRAINING_PLAN_MAX_LIMIT` | 10 | Maximum recommendations per request |
| `TRAINING_PLAN_WEAKNESS_THRESHOLD` | 50 | Score below which an axis is labelled "weak" |
| `TRAINING_PLAN_OPPONENT_BONUS` | 0.3 | Weight for opponent weakness match |
| `TRAINING_PLAN_RECENCY_PENALTY` | 0.2 | Penalty for recently trained focus areas |
| `TRAINING_PLAN_RECENCY_WINDOW_DAYS` | 7 | Lookback window for training history |
| `TRAINING_PLAN_DRILL_CACHE_TTL_SECS` | 3600 | In-memory cache TTL for drill catalogue |

These can be promoted to a `config/trainingPlan` Firestore document for dynamic tuning if needed.

### Success metrics

The feature is successful if:
1. **Engagement**: >30% of Pro users who view the training plan log at least one training session within 48 hours.
2. **Relevance**: <10% of users dismiss all recommendations without logging any (indicates poor targeting).
3. **Win Predictor synergy**: Users who follow training plan recommendations before a match have a higher `preparation_bonus` than those who train ad hoc.
4. **Retention signal**: Pro subscribers who use the training plan have lower churn than those who don't (measured after 3+ months of data).
