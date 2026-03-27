# Danger Zone Data Model

Architecture document for the "Danger Zone" feature (Phase 4, Tab 3 - THE LAB). This feature identifies specific point-level patterns where a user loses to a particular opponent, enabling insights like "You lose 70% of points when the rally goes over 6 shots."

---

## I. Open Questions Analysis

### Q1: Is point-by-point tracking realistic for amateur self-organized matches?

**Answer: No, not in the traditional sense.**

Professional tennis uses Hawk-Eye, chair umpires, and dedicated statisticians. Amateur self-organized matches have none of this infrastructure. Asking two players to log every single point in real time is:

- **Disruptive**: Pulling out a phone after every point breaks match flow and creates friction.
- **Inaccurate**: Manual real-time entry under competitive stress produces unreliable data.
- **Adoption-killing**: Even motivated users will abandon the feature after 1-2 matches.

However, there is a middle ground: **post-match structured recall**. Players already complete post-match reflections in Tab 2 (journal entries with `went_well`/`went_wrong` tags). We can extend this with a lightweight structured form that captures game-level and momentum-level patterns without requiring point-by-point logging.

### Q2: Could we approximate from set/game patterns + reflection tags instead?

**Answer: Yes, and this is the recommended approach.**

GSM already captures:
- **Structured score**: `match.score.sets[].{p1Games, p2Games, tiebreakScore}` -- game-level granularity.
- **Reflection tags**: `went_well`/`went_wrong` with skill taxonomy mapping to 5 radar axes.
- **Opponent tags**: `opponent_weak`/`opponent_strong` feeding scouting profiles.
- **Skill DNA**: Aggregated axis scores across all reflections.

By combining these with a new **game-level pattern annotation** layer (filled out during the existing post-match reflection flow), we can detect patterns like:
- "You lose more games in 3rd sets against this opponent" (from score data).
- "You consistently note `double_faults` and `stamina` as `went_wrong` after losing to higher-tier players" (from reflection correlation).
- "Your net play success drops in matches lasting 3 sets" (from tag + score cross-reference).

This approximation approach trades point-level granularity for dramatically higher data completeness and user adoption.

### Q3: What is the minimum data granularity needed for useful pattern detection?

**Answer: Game-level patterns + situational context tags.**

The minimum viable granularity has three layers:

| Layer | Granularity | Source | Already exists? |
|-------|-------------|--------|-----------------|
| **Score patterns** | Set/game level | `match.score.sets[]` | Yes |
| **Reflection tags** | Per-match | `journalEntry.reflection.went_well/went_wrong` | Yes |
| **Momentum annotations** | Per-set or key-moment | New: `matchAnalysis` sub-document | No |

The new "momentum annotations" layer is the key addition. Rather than logging every point, users annotate 2-4 key moments or turning points per match. This captures the high-signal data points that drive pattern detection without requiring exhaustive logging.

---

## II. Proposed Data Model

### A. New collection: `matchAnalysis/{matchId}`

One document per completed match, created during the post-match reflection flow. This extends the existing journal entry flow rather than replacing it.

**Path**: `matchAnalysis/{matchId}`

**Ownership**: Created by either participant. Both participants can submit their own analysis, stored in per-UID sub-maps.

```json
{
  "matchId": "match_abc123",
  "sport": "tennis",
  "participantPair": "user_alice_user_bob",
  "analyses": {
    "user_alice": {
      "submittedAt": "2026-03-15T14:30:00Z",
      "setAnnotations": [
        {
          "setNumber": 1,
          "servicePattern": "strong",
          "returnPattern": "neutral",
          "dominantPlayStyle": "baseline",
          "turningPoint": "broke_serve_late",
          "energyLevel": "high",
          "tags": ["first_serve_pct_high", "forehand_winner"]
        },
        {
          "setNumber": 2,
          "servicePattern": "weak",
          "returnPattern": "strong",
          "dominantPlayStyle": "net_approach",
          "turningPoint": "lost_tiebreak",
          "energyLevel": "medium",
          "tags": ["double_faults", "stamina_drop"]
        }
      ],
      "keyMoments": [
        {
          "type": "momentum_shift",
          "setNumber": 2,
          "description": "Lost 4 games in a row after leading 4-2",
          "tags": ["concentration_lapse", "stamina_drop"]
        },
        {
          "type": "pattern_observed",
          "description": "Opponent started coming to net more in set 2",
          "tags": ["opponent_net_play", "passing_shot_weak"]
        }
      ],
      "overallAssessment": {
        "rallyLengthComfort": "short",
        "pacePreference": "fast",
        "weaknessExploited": ["backhand_high", "stamina_set3"],
        "strengthUsed": ["first_serve", "forehand_cross"]
      }
    }
  },
  "createdAt": "2026-03-15T14:30:00Z",
  "lastUpdatedAt": "2026-03-15T15:00:00Z"
}
```

### B. Field definitions: `matchAnalysis/{matchId}`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `matchId` | string | Yes | References `matches/{matchId}` |
| `sport` | string (enum) | Yes | `tennis`, `padel`, `pickleball` |
| `participantPair` | string | Yes | Lexicographic UID pair (same as `matches` collection) for H2H queries |
| `analyses` | map | Yes | Per-UID analysis sub-maps |
| `analyses.{uid}.submittedAt` | timestamp | Yes | When this user submitted their analysis |
| `analyses.{uid}.setAnnotations` | array | Yes | One entry per set played (length matches `match.score.sets`) |
| `analyses.{uid}.keyMoments` | array | No | 0-4 key turning points or observations |
| `analyses.{uid}.overallAssessment` | map | No | High-level match feel and pattern notes |
| `createdAt` | timestamp | Yes | First analysis submission time |
| `lastUpdatedAt` | timestamp | Yes | Most recent analysis submission time |

### C. Field definitions: `setAnnotations[]`

| Field | Type | Required | Values | Description |
|-------|------|----------|--------|-------------|
| `setNumber` | int | Yes | 1-5 | Which set this annotates |
| `servicePattern` | string (enum) | No | `strong`, `neutral`, `weak` | Self-assessment of serve quality this set |
| `returnPattern` | string (enum) | No | `strong`, `neutral`, `weak` | Self-assessment of return quality this set |
| `dominantPlayStyle` | string (enum) | No | `baseline`, `net_approach`, `all_court`, `defensive` | Primary style of play this set |
| `turningPoint` | string (enum) | No | `broke_serve_early`, `broke_serve_late`, `lost_tiebreak`, `won_tiebreak`, `service_run`, `none` | Key turning point of the set |
| `energyLevel` | string (enum) | No | `high`, `medium`, `low` | Perceived energy/fitness level |
| `tags` | array[string] | No | Skill taxonomy tags | Free-form tags using existing taxonomy |

### D. Field definitions: `keyMoments[]`

| Field | Type | Required | Values | Description |
|-------|------|----------|--------|-------------|
| `type` | string (enum) | Yes | `momentum_shift`, `pattern_observed`, `tactical_change`, `mental_reset` | Category of the moment |
| `setNumber` | int | No | 1-5 | Which set (if applicable) |
| `description` | string | No | max 200 chars | Free-text note |
| `tags` | array[string] | No | Skill taxonomy tags | Tags from existing taxonomy |

### E. Field definitions: `overallAssessment`

| Field | Type | Required | Values | Description |
|-------|------|----------|--------|-------------|
| `rallyLengthComfort` | string (enum) | No | `short`, `medium`, `long` | Rally length where user felt most comfortable |
| `pacePreference` | string (enum) | No | `fast`, `moderate`, `slow` | Match pace the user preferred |
| `weaknessExploited` | array[string] | No | Skill taxonomy tags | Which of user's weaknesses the opponent targeted |
| `strengthUsed` | array[string] | No | Skill taxonomy tags | Which strengths the user deployed effectively |

### F. Aggregated analysis: `dangerZone/{uid}`

One document per user, aggregating patterns across all their match analyses. Updated by a trigger or batch job whenever new `matchAnalysis` documents are created.

**Path**: `dangerZone/{uid}`

```json
{
  "uid": "user_alice",
  "tennis": {
    "opponents": {
      "user_bob": {
        "matchesAnalyzed": 5,
        "patterns": [
          {
            "patternId": "late_set_collapse",
            "description": "Loses games in later stages of sets",
            "confidence": 0.72,
            "matchesObserved": 4,
            "evidence": {
              "setAnnotationCorrelation": "energyLevel=low AND turningPoint=broke_serve_late",
              "tagFrequency": {"stamina_drop": 4, "concentration_lapse": 3}
            },
            "lastObserved": "2026-03-15T14:30:00Z"
          },
          {
            "patternId": "weak_backhand_high",
            "description": "Backhand breaks down under high balls",
            "confidence": 0.60,
            "matchesObserved": 3,
            "evidence": {
              "tagFrequency": {"backhand_high": 3, "opponent_lob": 2}
            },
            "lastObserved": "2026-03-10T16:00:00Z"
          }
        ],
        "lastUpdated": "2026-03-15T14:30:00Z"
      }
    },
    "global": {
      "patternsAcrossOpponents": [
        {
          "patternId": "third_set_fatigue",
          "description": "Win rate drops significantly in 3-set matches",
          "confidence": 0.80,
          "matchesObserved": 8,
          "evidence": {
            "setAnnotationCorrelation": "setNumber=3 AND energyLevel=low",
            "winRateInThreeSetters": 0.25
          },
          "lastObserved": "2026-03-15T14:30:00Z"
        }
      ],
      "totalMatchesAnalyzed": 15,
      "lastUpdated": "2026-03-15T14:30:00Z"
    }
  }
}
```

### G. Field definitions: `dangerZone/{uid}`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `uid` | string | Yes | User this profile belongs to |
| `{sport}` | map | No | Per-sport danger zone data |
| `{sport}.opponents.{opponentUid}` | map | No | Per-opponent pattern analysis |
| `{sport}.opponents.{opponentUid}.matchesAnalyzed` | int | Yes | Number of matches with analysis data |
| `{sport}.opponents.{opponentUid}.patterns[]` | array | Yes | Detected patterns (see below) |
| `{sport}.opponents.{opponentUid}.lastUpdated` | timestamp | Yes | Last pattern recalculation |
| `{sport}.global` | map | No | Cross-opponent aggregate patterns |
| `{sport}.global.patternsAcrossOpponents[]` | array | Yes | Patterns that appear regardless of opponent |
| `{sport}.global.totalMatchesAnalyzed` | int | Yes | Total matches with analysis data |

### H. Pattern object definition

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `patternId` | string | Yes | Stable identifier for the pattern type |
| `description` | string | Yes | Human-readable pattern description |
| `confidence` | float | Yes | 0.0-1.0 confidence score based on sample size and consistency |
| `matchesObserved` | int | Yes | Number of matches where this pattern appeared |
| `evidence` | map | Yes | Supporting data for the pattern (correlations, frequencies) |
| `lastObserved` | timestamp | Yes | Most recent match where pattern was detected |

---

## III. Data Collection Method

### Integration with existing post-match flow

The match analysis form integrates into the existing post-match reflection flow. After a match is confirmed (`POST /matches/{matchId}/verify-score`), the user enters the `POST_MATCH_LOG_AVAILABLE` state and can create a journal entry. The match analysis is an optional extension of this flow.

```
Match completed (verify-score)
        |
        v
POST_MATCH_LOG_AVAILABLE
        |
        v
User opens journal entry form (existing flow)
        |
        +-- Basic reflection (existing): went_well/went_wrong tags
        |
        +-- Match Analysis (new, optional): set annotations + key moments
        |
        v
Journal entry saved + matchAnalysis/{matchId} created
```

### UX design principles for data collection

1. **Progressive disclosure**: The basic reflection (tags) is shown first. "Add detailed analysis" expands the set-by-set form. Users who want quick logging skip it; invested users get deeper tools.

2. **Structured choices, not free text**: Every field uses enum pickers (tap-to-select) rather than text input. This keeps data consistent and entry fast.

3. **Per-set cards**: The form shows one card per set played (auto-populated from `match.score.sets`). Each card has 4-5 single-tap fields. A 2-set match analysis takes under 60 seconds.

4. **Key moments are optional**: The `keyMoments` section uses an "Add moment" button. Most users skip it; power users add 1-2 moments.

5. **Smart defaults**: If the user won a set, `servicePattern` defaults to `strong` and `energyLevel` defaults to the previous set's value. Defaults reduce taps.

### API endpoints for data collection

| Method | Path | Purpose | Phase |
|--------|------|---------|-------|
| POST | `/matches/{matchId}/analysis` | Submit match analysis (creates or updates `matchAnalysis/{matchId}`) | P4 |
| GET | `/matches/{matchId}/analysis` | Retrieve match analysis (both participants' views) | P4 |
| GET | `/me/lab/danger-zone/{opponentUid}?sport=tennis` | Danger Zone patterns for a specific opponent | P4 |
| GET | `/me/lab/danger-zone?sport=tennis` | Global Danger Zone patterns (cross-opponent) | P4 |

### Data volume considerations

- **Write frequency**: At most 1 analysis per match per user. With an average of 2-3 matches/week for active users, this is very low write volume.
- **Document size**: A typical `matchAnalysis` document with 2 participants and 3 sets is under 2KB. Well within Firestore's 1MB limit.
- **Aggregation frequency**: `dangerZone/{uid}` is recomputed when new analyses are submitted. With low match frequency, this is not a hot-path concern.

---

## IV. Analysis Approach

### Pattern detection pipeline

Pattern detection runs as a batch process (Cloud Function trigger or scheduled job) when a new `matchAnalysis` document is written. It reads all analyses for the user+opponent pair and applies rule-based pattern detection.

```
matchAnalysis/{matchId} written (trigger)
        |
        v
Read all matchAnalysis docs for participantPair
        |
        v
Correlate with match outcomes (win/loss per set from match.score)
        |
        v
Apply pattern rules (see below)
        |
        v
Write detected patterns to dangerZone/{uid}
```

### Pattern rule categories

#### Category 1: Score-based patterns (from `match.score` alone)

These patterns require zero additional user input -- they work with existing data.

| Pattern | Detection rule | Example insight |
|---------|---------------|-----------------|
| Third-set collapse | Win rate in 3-set matches < 35% (min 4 matches) | "You win only 25% of 3-set matches against Bob" |
| Tiebreak weakness | Tiebreak win rate < 40% (min 3 tiebreaks) | "You've lost 4 of 5 tiebreaks against higher-tier opponents" |
| Slow starter | First-set loss rate > 60% in matches eventually won | "You lose the first set in 70% of your wins -- you're a slow starter" |
| Close-match closer | Win rate in matches with 1+ tiebreak > threshold | "You close out tight matches 80% of the time" |

#### Category 2: Annotation-correlated patterns (from `matchAnalysis`)

These require the new set annotation data.

| Pattern | Detection rule | Example insight |
|---------|---------------|-----------------|
| Service collapse | `servicePattern=weak` correlates with set losses > 70% | "When your serve is off, you lose 80% of those sets" |
| Net-play exploiter | `dominantPlayStyle=net_approach` correlates with set wins > 65% | "You win 75% of sets where you come to net frequently" |
| Fatigue pattern | `energyLevel=low` in later sets correlates with set losses | "When your energy drops in set 3, you lose 90% of the time" |
| Late-break vulnerability | `turningPoint=broke_serve_late` appears in > 50% of lost sets | "You get broken late in sets you lose -- close them out earlier" |

#### Category 3: Cross-source patterns (combining score + annotations + reflections)

The highest-value patterns combine multiple data sources.

| Pattern | Data sources | Example insight |
|---------|-------------|-----------------|
| Opponent-specific weakness | `matchAnalysis.overallAssessment.weaknessExploited` + `scouting/{uid}` | "Bob targets your backhand in 4/5 matches and the community agrees it's your weakness" |
| Reflection-outcome correlation | `journalEntry.reflection.went_wrong` tags + match results | "When you note 'double_faults' as went_wrong, you lose 85% of the time" |
| Stamina-score correlation | `energyLevel` annotations + set score margins | "Your average game margin drops from +2.1 in set 1 to -1.3 in set 3" |

### Confidence scoring

Pattern confidence is computed as:

```
confidence = min(1.0, (matches_observed / min_sample) * consistency_rate)
```

Where:
- `matches_observed`: Number of matches where the pattern conditions were met
- `min_sample`: Minimum matches needed for full confidence (default: 5)
- `consistency_rate`: Fraction of qualifying matches where the pattern held (e.g., 4 out of 5 = 0.80)

Patterns with confidence < 0.50 are not surfaced to the user. Patterns between 0.50-0.70 are shown with a "developing pattern" qualifier. Patterns above 0.70 are shown as established patterns.

### AI enhancement (future)

The rule-based system described above is the initial implementation. A future enhancement can layer ML on top:

1. **Embeddings from reflection text**: Use the free-text `body` field from journal entries + `keyMoments[].description` to build richer feature vectors.
2. **Collaborative filtering**: "Players with similar Skill DNA who face this opponent type tend to lose when..." -- cross-user pattern detection.
3. **Natural language insights**: LLM-generated summaries that synthesize multiple patterns into coaching advice: "Against Bob, focus on shortening rallies and attacking his backhand. Your stamina becomes a liability after set 2."

These enhancements do not change the data model -- they consume the same `matchAnalysis` and `dangerZone` collections.

---

## V. Firestore Schema Summary

### New collections

| Collection | Purpose | Write trigger |
|------------|---------|---------------|
| `matchAnalysis/{matchId}` | Per-match structured annotations from participants | User submits via `POST /matches/{matchId}/analysis` |
| `dangerZone/{uid}` | Aggregated pattern profiles per user | Trigger on `matchAnalysis` writes |

### New indexes

| Collection | Fields | Purpose |
|------------|--------|---------|
| `matchAnalysis` | `participantPair ASC, createdAt DESC` | Query all analyses for a H2H pair |
| `matchAnalysis` | `sport ASC, analyses.{uid}.submittedAt DESC` | Query user's recent analyses |

### New enums

| Enum | Values | Used in |
|------|--------|---------|
| `ServicePattern` | `strong`, `neutral`, `weak` | `setAnnotations[].servicePattern` |
| `ReturnPattern` | `strong`, `neutral`, `weak` | `setAnnotations[].returnPattern` |
| `PlayStyle` | `baseline`, `net_approach`, `all_court`, `defensive` | `setAnnotations[].dominantPlayStyle` |
| `TurningPoint` | `broke_serve_early`, `broke_serve_late`, `lost_tiebreak`, `won_tiebreak`, `service_run`, `none` | `setAnnotations[].turningPoint` |
| `EnergyLevel` | `high`, `medium`, `low` | `setAnnotations[].energyLevel` |
| `KeyMomentType` | `momentum_shift`, `pattern_observed`, `tactical_change`, `mental_reset` | `keyMoments[].type` |
| `RallyLengthComfort` | `short`, `medium`, `long` | `overallAssessment.rallyLengthComfort` |
| `PacePreference` | `fast`, `moderate`, `slow` | `overallAssessment.pacePreference` |

### Relationship to existing collections

```
matches/{matchId}
    |
    +-- score.sets[] (existing game-level data)
    |
    +-- matchAnalysis/{matchId} (new -- keyed by same matchId)
            |
            +-- analyses.{uid}.setAnnotations[] (one per set)
            +-- analyses.{uid}.keyMoments[]
            +-- analyses.{uid}.overallAssessment

users/{uid}
    |
    +-- journalEntries/{entryId} (existing reflections)
    |       +-- reflection.went_well/went_wrong (existing tags)
    |
    +-- pointHistory/{entryId} (existing score timeline)

scouting/{uid} (existing community observations)

dangerZone/{uid} (new -- aggregated patterns)
    |
    +-- {sport}.opponents.{opponentUid}.patterns[]
    +-- {sport}.global.patternsAcrossOpponents[]
```

---

## VI. Trade-offs and Alternatives Considered

### Alternative 1: True point-by-point logging

**Approach**: Log every point with server/returner, shot count, point winner, and how the point ended (winner, error, ace, double fault).

**Pros**: Maximum granularity; could produce insights like "70% of points lost when rally > 6 shots."

**Cons**: Completely unrealistic for amateur self-organized matches. Requires constant phone interaction during play. Data quality would be very low. Adoption would be near zero.

**Verdict**: Rejected. The insight quality does not justify the UX cost for the target audience.

### Alternative 2: Automated tracking via phone sensors

**Approach**: Use phone accelerometer/gyroscope (in pocket or armband) to detect shots and score points automatically.

**Pros**: Zero manual effort during the match.

**Cons**: Extremely complex ML problem. Requires consistent phone placement. Unreliable for amateur use. Not feasible for Phase 4 timeline.

**Verdict**: Rejected for Phase 4. Could be a Phase 5+ R&D initiative.

### Alternative 3: Post-match approximation only (no new data model)

**Approach**: Use only existing data (scores + reflection tags + scouting) to infer patterns.

**Pros**: Zero additional user effort. Works with existing data.

**Cons**: Limited pattern depth. Cannot distinguish "I lose because of stamina in set 3" from "I lose because opponent changes tactics in set 3" without additional context.

**Verdict**: Partially adopted. Score-based patterns (Category 1) use this approach. But the addition of lightweight set annotations unlocks significantly richer pattern detection.

### Alternative 4: Game-by-game logging (chosen middle ground, deferred)

**Approach**: Log the score progression game by game (e.g., who won each game) rather than point by point.

**Pros**: Much less effort than point-by-point. Enables rally-length and break-point analysis.

**Cons**: Still requires in-match logging (after each game), which disrupts flow. More effort than set-level annotations.

**Verdict**: Deferred. If set-level annotations prove insufficient after initial rollout, game-level logging can be added as an opt-in "detailed mode" using the same `matchAnalysis` collection structure (adding a `gameLog` array alongside `setAnnotations`). The schema is forward-compatible.

### Why `matchAnalysis` is a separate collection (not embedded in `matches`)

1. **Separation of concerns**: Match documents are the source of truth for scheduling, status, and canonical results. Analysis is subjective per-participant commentary.
2. **Document size**: Adding analysis data to match documents would bloat them for queries that only need status/score.
3. **Access patterns**: Analysis is read during the Danger Zone flow (rivalry scout), not during match listing or state machine transitions.
4. **Write contention**: Both participants can submit analysis independently without conflicting writes to the match document.

---

## VII. Implementation Phases for Danger Zone

### Phase 4a: Data collection layer

- Add `matchAnalysis` collection, Pydantic models, repo, and mapper.
- Add `POST /matches/{matchId}/analysis` and `GET /matches/{matchId}/analysis` endpoints.
- Integrate analysis form into post-match reflection flow (mobile).
- No pattern detection yet -- just collecting data.

### Phase 4b: Score-based pattern detection

- Implement Category 1 patterns (score-only, works with existing data).
- Add `dangerZone/{uid}` collection, models, repo.
- Add `GET /me/lab/danger-zone` endpoints.
- Trigger pattern recalculation on match completion.

### Phase 4c: Annotation-based pattern detection

- Implement Category 2 patterns (using `matchAnalysis` data).
- Implement Category 3 patterns (cross-source).
- Requires sufficient `matchAnalysis` data from Phase 4a adoption.

### Phase 4d: AI enhancement

- LLM-generated insight summaries.
- Cross-user collaborative pattern detection.
- Natural language coaching recommendations.

---

## VIII. Dependencies

- **Phases 1-3 in production**: Scoring engine, Skill DNA, scouting profiles, and leaderboards must be live with real usage data.
- **Sufficient match volume**: Pattern detection needs a minimum of 3-5 matches per opponent pair to produce meaningful insights. The feature should display a "need more data" state when below threshold.
- **Skill taxonomy v1 stable**: The tag vocabulary used in `setAnnotations[].tags` and `overallAssessment` fields relies on the existing `config/skillTaxonomy`. Changes to the taxonomy require migration logic.
- **Mobile UX for structured input**: The set annotation form is a new mobile UI component. iOS team dependency for the data collection screens.
