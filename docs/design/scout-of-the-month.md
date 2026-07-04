# Scout of the Month — Outcome Correlation Pipeline

> ⚠️ **Design / decision record — non-canonical.** This document captures intent and history and is *not* kept in lockstep with the code. For current behavior, defer to the canonical docs under [`../README.md`](../README.md).

Architecture document for the "Scout of the Month" gamification feature (Phase 4, Tab 3 - THE LAB). This feature rewards users whose scouting observations most accurately predict match outcomes, creating a feedback loop that incentivises high-quality community intelligence.

> **Scope**: This document covers the correlation pipeline, scoring model, data model, badge/reward system, API integration, and phased rollout. **Singles matches only** — doubles matches (4 participants) require team-level correlation semantics (which player's weakness was exploited?) that are out of scope for v1. See open item below. It does not cover ML-based tag prediction or natural-language scouting (deferred to Phase 5+).
>
> **Known open items**: Doubles correlation extension (how to attribute weakness tags when 2 players share a side).
>
> **Dependencies**: Phase 3 (scouting profiles with reporter tracking via `processedReports` subcollection), match confirmation pipeline (verify-score), journal reflection triggers (D4.3 scouting upsert).

---

## I. Open Questions Analysis

### Q1: How to correlate scouting tags across users reliably?

**Answer: Match-scoped tag intersection with temporal windowing and vocabulary bridging.**

The correlation problem has three layers:

1. **Who tagged what?** The `scouting/{uid}/processedReports/{dedupHash}` subcollection stores per-report data including `sport`, `tagSig` (e.g., `"backhand,stamina_set3|first_serve"`), and `reporterHash`. However, the `reporterHash` is a one-way SHA-256 of the reporter UID — we cannot reverse it to credit a specific user.

   **Solution**: Introduce a new `scoutingCorrelations/{correlationId}` collection that is written at correlation time (post-match). The correlation trigger reads the *journal entry* (which contains the raw `reflection.opponentWeak`/`opponentStrong` tags and the reporter UID) rather than the anonymised scouting profile. This means the pipeline works from journal entries as the source of truth, not from the aggregated `scouting/{uid}` document.

2. **What constitutes a match?** A scouting tag is "confirmed" when an opponent plays a match and the outcome aligns with the tagged weakness. The confirmation signal comes from two sources:
   - **Winner's reflection**: The winner's `went_well` or `opponent_weak` tags overlap with the original scout's tags.
   - **Score pattern**: The match outcome itself (win/loss) combined with the loser having tagged weaknesses.

3. **Timing window**: Only scouting tags that existed *before* the confirming match count. A tag created from a reflection on the same match cannot confirm itself. Tags must have been written before the confirming match's `scheduledAt` timestamp.

| Correlation strategy | Pros | Cons | Verdict |
|---------------------|------|------|---------|
| **Direct tag intersection** (scout's `opponentWeak` tags vs. winner's `went_well`/`opponent_weak` tags) | High precision; both parties independently identified the same weakness | Requires both players to use the same vocabulary; low recall if tag usage is sparse | **Chosen for v1** |
| Axis-level matching (map tags to Skill DNA axes and match at axis level) | Higher recall; tolerant of vocabulary differences | Lower precision; "serve" axis matches too broadly (aces vs. double faults) | Deferred to v2 |
| ML embedding similarity | Handles synonyms and partial matches | Requires training data that does not exist yet | Deferred to Phase 5+ |

### Q2: What is the minimum sample size before "accuracy" is meaningful?

**Answer: 5 confirmed correlations minimum, with a confidence scaling function.**

Statistical reasoning:

- With 1-2 correlations, accuracy is dominated by noise. A scout who tagged one weakness that happened to match once could show 100% accuracy.
- With 5+ correlations, the accuracy begins to stabilise. The binomial confidence interval for 4/5 (80%) at 95% confidence is [36%, 97%] — still wide, but directionally meaningful.
- With 10+ correlations, the interval tightens to useful precision: 8/10 (80%) at 95% confidence is [44%, 97%].

The feature uses a **confidence multiplier** that scales with sample size:

```
confidence = min(1.0, confirmed_correlations / MIN_CORRELATIONS_FOR_RANKING)
display_accuracy = raw_accuracy * confidence
```

Where `MIN_CORRELATIONS_FOR_RANKING = 5`. A scout with 2/2 (100% raw) gets `display_accuracy = 1.0 * 0.4 = 0.40`, while a scout with 8/10 (80% raw) gets `display_accuracy = 0.8 * 1.0 = 0.80`. This prevents low-sample-size scouts from dominating the leaderboard.

Scouts with fewer than `MIN_CORRELATIONS_FOR_DISPLAY = 3` confirmed correlations are not shown on the leaderboard at all — they see a "Keep scouting to earn your rank" message.

### Q3: What badge/reward mechanism fits the GSM gamification model?

**Answer: Monthly title + permanent achievement tiers, integrated with the Athlete Card on Tab 4.**

GSM's gamification philosophy (from the Tab 3 spec) emphasises social proof and screenshot-worthy moments. The badge system should:
1. Create a recurring competition (monthly reset drives engagement).
2. Reward cumulative effort (permanent tiers recognise long-term contribution).
3. Be visible to other users (social proof on the Athlete Card).

**Monthly title**: "Scout of the Month" is awarded to the top-ranked scout in each region+sport combination at month end. The title is displayed on the user's Athlete Card for the following month with a distinctive badge icon. Only one winner per region+sport per month.

**Achievement tiers** (permanent, cumulative):

| Tier | Requirement | Badge |
|------|-------------|-------|
| Bronze Scout | 10 confirmed correlations (lifetime) | Bronze magnifying glass |
| Silver Scout | 30 confirmed correlations + 60% accuracy | Silver magnifying glass |
| Gold Scout | 75 confirmed correlations + 70% accuracy | Gold magnifying glass |
| Elite Scout | 150 confirmed correlations + 75% accuracy | Diamond magnifying glass |

Tiers are one-directional — once earned, they are never revoked (even if accuracy drops). This prevents the frustrating experience of losing a badge.

### Q4: Should correlation run in real-time or batch?

**Answer: Event-triggered (post-match), not real-time and not batch.**

Three processing strategies were considered:

| Strategy | Trigger | Latency | Complexity | Verdict |
|----------|---------|---------|------------|---------|
| **Real-time** (during match confirmation) | Inline in verify-score | Zero | High — adds latency to the critical path | Rejected |
| **Event-triggered** (Cloud Function on match completion) | Firestore trigger on `matches/{matchId}` status change to `completed` | Seconds | Medium — async, does not block match flow | **Chosen** |
| **Batch** (scheduled daily/hourly) | Cloud Scheduler | Hours | Low — simple but stale data | Rejected for primary, used for monthly aggregation |

The correlation pipeline runs as a Cloud Function triggered by match completion (same trigger point as the existing D5.1 ranking recomputation). It processes one match at a time and writes correlation events immediately. A separate scheduled batch job runs monthly to compute the "Scout of the Month" winner and update achievement tiers.

### Q5: Privacy implications — does revealing scouting accuracy expose who tagged whom?

**Answer: Yes, partially. Mitigation: aggregate-only display with opt-in participation.**

The core tension: the current scouting system is anonymous (reporters are hashed, counts are aggregate). The Scout of the Month feature inherently reveals that a user has been scouting, because it publicly ranks scouts by accuracy.

However, it does **not** reveal:
- Who was scouted (the opponents are not displayed).
- What tags were applied (the specific weaknesses are not shown).
- Which matches confirmed the tags (no match-level detail).

The display is: "User A: 85% scouting accuracy (12 confirmed observations)". This reveals that User A scouts opponents, but not who or what — which is already implicit from the journal reflection flow (all users are encouraged to tag opponents).

**Mitigation**: Scout of the Month participation is **opt-in**. Users must enable "Scouting Leaderboard" in their preferences. Users who never opt in will still have their scouting tags processed for community intelligence (as today), but their accuracy stats will not appear on any leaderboard. The `scoutAccuracy/{uid}` document is created for all users (for internal analytics), but the `optedIn` flag controls leaderboard visibility.

Default: opted **in** for new users (to maximise initial participation), with a clear toggle in settings.

---

## II. Proposed Data Model

### A. New collection: `scoutingCorrelations/{correlationId}`

One document per correlation event — created when a scouting tag is validated (or invalidated) by a match outcome.

**Path**: `scoutingCorrelations/{correlationId}`

**Document ID**: deterministic — `{scoutUid}_{matchId}_{tag}` to prevent duplicate correlations for the same scout+match+tag combination.

```json
{
  "correlationId": "user_alice_match_xyz_backhand",
  "scoutUid": "user_alice",
  "scoutedUid": "user_bob",
  "confirmingMatchId": "match_xyz",
  "sport": "tennis",
  "tag": "backhand",
  "tagCategory": "weak",
  "sourceMatchId": "match_abc",
  "sourceEntryId": "journal_entry_123",
  "tagCreatedAt": "2026-03-01T10:00:00Z",
  "confirmedAt": "2026-03-15T14:30:00Z",
  "confirmed": true,
  "confirmationSource": "winner_reflection",
  "confirmationDetail": {
    "winnerTag": "opponent_weak",
    "matchedTag": "backhand"
  },
  "region": "athens",
  "createdAt": "2026-03-15T14:31:00Z"
}
```

### B. Field definitions: `scoutingCorrelations/{correlationId}`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `correlationId` | string | Yes | Deterministic ID: `{scoutUid}_{confirmingMatchId}_{tag}` |
| `scoutUid` | string | Yes | UID of the user who made the scouting observation |
| `scoutedUid` | string | Yes | UID of the user who was scouted (the opponent) |
| `confirmingMatchId` | string | Yes | Match that validated (or failed to validate) the tag |
| `sport` | string (enum) | Yes | `tennis`, `padel`, `pickleball` |
| `tag` | string | Yes | The specific scouting tag being correlated |
| `tagCategory` | string (enum) | Yes | `weak` or `strong` — which scouting bucket the tag came from |
| `sourceMatchId` | string | Yes | Match from which the original scouting tag was generated |
| `sourceEntryId` | string | Yes | Journal entry that produced the scouting tag |
| `tagCreatedAt` | timestamp | Yes | When the scouting tag was originally created |
| `confirmedAt` | timestamp | Yes | When the confirming match completed |
| `confirmed` | boolean | Yes | Whether the tag was validated by the match outcome |
| `confirmationSource` | string (enum) | Yes | How the tag was confirmed: `winner_reflection`, `score_pattern`, `unconfirmed` |
| `confirmationDetail` | map | No | Additional context about the confirmation match |
| `region` | string | Yes | Region of the scout (for regional leaderboards) |
| `createdAt` | timestamp | Yes | When this correlation event was created |

### C. New collection: `scoutAccuracy/{uid}`

Aggregated scouting accuracy stats per user, per sport. Updated incrementally by the correlation pipeline.

**Path**: `scoutAccuracy/{uid}`

```json
{
  "uid": "user_alice",
  "optedIn": true,
  "tennis": {
    "totalTags": 25,
    "confirmedTags": 18,
    "unconfirmedTags": 7,
    "accuracy": 0.72,
    "confidenceScore": 0.72,
    "currentMonthTags": 8,
    "currentMonthConfirmed": 6,
    "currentMonthAccuracy": 0.75,
    "streakConfirmed": 3,
    "lastCorrelationAt": "2026-03-15T14:31:00Z",
    "achievementTier": "silver",
    "achievementTierEarnedAt": "2026-02-28T00:00:00Z"
  },
  "padel": null,
  "pickleball": null,
  "scoutOfTheMonth": [
    {
      "sport": "tennis",
      "region": "athens",
      "month": "2026-02",
      "accuracy": 0.78,
      "confirmedTags": 14
    }
  ],
  "lastUpdated": "2026-03-15T14:31:00Z"
}
```

### D. Field definitions: `scoutAccuracy/{uid}`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `uid` | string | Yes | User this profile belongs to |
| `optedIn` | boolean | Yes | Whether user participates in the scouting leaderboard |
| `{sport}` | map | No | Per-sport accuracy data |
| `{sport}.totalTags` | int | Yes | Total scouting tags that have been **evaluated** (a confirming match exists). Tags with no confirming match are not counted — see edge cases. `totalTags = confirmedTags + unconfirmedTags`. |
| `{sport}.confirmedTags` | int | Yes | Tags validated by subsequent match outcomes (winner reflection or score pattern matched) |
| `{sport}.unconfirmedTags` | int | Yes | Tags that were **evaluated** (a confirming match existed) but not validated — the winner's reflection and score pattern did not confirm the weakness. Tags with no confirming match at all are excluded and do not increment this counter. |
| `{sport}.accuracy` | float | Yes | `confirmedTags / totalTags` (0.0-1.0). Only evaluated tags contribute. |
| `{sport}.confidenceScore` | float | Yes | `accuracy * min(1.0, confirmedTags / MIN_CORRELATIONS_FOR_RANKING)` |
| `{sport}.currentMonthTags` | int | Yes | Tags correlated in the current calendar month |
| `{sport}.currentMonthConfirmed` | int | Yes | Confirmed tags in the current month |
| `{sport}.currentMonthAccuracy` | float | Yes | Monthly accuracy rate |
| `{sport}.streakConfirmed` | int | Yes | Consecutive confirmed correlations (resets on miss) |
| `{sport}.lastCorrelationAt` | timestamp | No | Most recent correlation event |
| `{sport}.achievementTier` | string | No | `bronze`, `silver`, `gold`, `elite` or null |
| `{sport}.achievementTierEarnedAt` | timestamp | No | When the current tier was first achieved |
| `scoutOfTheMonth` | array | No | Historical list of months where user won the title |
| `lastUpdated` | timestamp | Yes | Last profile update |

### E. New collection: `scoutLeaderboard/{region}_{sport}_{month}`

Pre-computed monthly leaderboard snapshot. Written by the monthly batch job.

**Path**: `scoutLeaderboard/{region}_{sport}_{month}`

```json
{
  "region": "athens",
  "sport": "tennis",
  "month": "2026-03",
  "entries": [
    {
      "uid": "user_alice",
      "name": "Alice K.",
      "accuracy": 0.82,
      "confidenceScore": 0.82,
      "confirmedTags": 14,
      "totalTags": 17,
      "achievementTier": "silver",
      "rank": 1
    }
  ],
  "winner": {
    "uid": "user_alice",
    "name": "Alice K.",
    "accuracy": 0.82
  },
  "finalized": false,
  "lastUpdated": "2026-03-15T14:31:00Z"
}
```

### F. Relationship to existing collections

```
users/{uid}
    |
    +-- journalEntries/{entryId}
    |     +-- reflection.opponentWeak: ["backhand", "stamina_set3"]
    |     +-- reflection.opponentStrong: ["first_serve"]
    |     +-- matchId: "match_abc"           <--- source of scouting tags
    |     +-- sport: "tennis"
    |
    +-- preferences.area  -------------------> region resolution

matches/{matchId}
    +-- status: "completed"
    +-- participantUids: ["user_bob", "user_charlie"]
    +-- score: {winnerUid, sets: [...]}      <--- confirming match outcome
    |
    +-- (on completion trigger) ------------>  correlation pipeline

scouting/{uid}                                (existing, unchanged)
    +-- {sport}.weak: {tag: {count, lastReported}}
    +-- {sport}.totalReports
    +-- processedReports/{dedupHash}          <--- NOT used by correlation
                                                  (uses journal entries instead)

scoutingCorrelations/{correlationId}  (new)
    +-- scoutUid, scoutedUid, tag, confirmed
    +-- sourceMatchId, confirmingMatchId

scoutAccuracy/{uid}  (new)
    +-- {sport}.accuracy, confirmedTags, totalTags
    +-- achievementTier, scoutOfTheMonth[]

scoutLeaderboard/{region}_{sport}_{month}  (new)
    +-- entries[], winner, finalized
```

---

## III. Correlation Pipeline

### Overview

The correlation pipeline answers the question: "For a completed match, which prior scouting observations were validated by the outcome?" It runs as a Cloud Function triggered by match completion.

### Trigger point

```
matches/{matchId} status -> "completed"  (existing D5 trigger point)
    |
    v
D5.3: run_scouting_correlation(matchId)  (new trigger)
```

This piggybacks on the same Firestore trigger that drives ranking recomputation (D5.1) and league stats updates (D5.2). The correlation function is a separate handler to keep concerns isolated.

### Pipeline steps

```
Step 1: Read the completed match
    |-- matchId, sport, participantUids, score.winnerUid, finishedAt
    |
    v
Step 2: Read the winner's journal entry for this match (if exists)
    |-- reflection.went_well, reflection.opponent_weak
    |
    v
Step 3: For each participant (the loser), find prior scouting tags
    |-- Query journalEntries where:
    |     - matchId != this match (not self-confirming)
    |     - reflection.opponentWeak or opponentStrong has tags
    |     - the scouted opponent is a participant in this match
    |     - createdAt < this match's scheduledAt (temporal ordering)
    |
    v
Step 4: Correlate — tag intersection
    |-- For each prior scouting tag on the loser:
    |     - Check if the tag appears in the winner's went_well or opponent_weak
    |     - Check if the tag is in the SCOUTING_CORRELATION_MAP (vocabulary bridge)
    |     - Mark as confirmed or unconfirmed
    |
    v
Step 5: Write correlation events
    |-- Write scoutingCorrelations/{scoutUid}_{matchId}_{tag} for each tag
    |
    v
Step 6: Update scout accuracy profiles
    |-- Increment confirmedTags/unconfirmedTags on scoutAccuracy/{scoutUid}
    |-- Recompute accuracy and confidenceScore
    |-- Check achievement tier thresholds
```

### Step 3 detail: Finding prior scouting tags

The pipeline needs to find all journal entries where any user tagged the *loser* of the current match with weakness tags. This requires querying across users, which Firestore does not support natively (journal entries are subcollections under `users/{uid}`).

**Solution: Query the `processedReports` subcollection on the scouting profile.**

The `scouting/{loserUid}/processedReports/{dedupHash}` subcollection contains one document per scouting report. Each document has:
- `sport` (string)
- `tagSig` (e.g., `"backhand,stamina_set3|first_serve"`)
- `reporterHash` (SHA-256 of reporter UID)
- `updatedAt` (timestamp)

The `reporterHash` is one-way, so we cannot recover the reporter UID from it. However, we can work in the opposite direction:

1. From the completed match, identify both participants.
2. For the loser, read `scouting/{loserUid}/processedReports` to get all stored `tagSig` entries.
3. For each `processedReports` entry, we need the reporter UID to credit them. Since the hash is one-way, we need a reverse lookup.

**This reveals a schema gap**: the current `processedReports` subcollection does not store enough information to credit specific reporters. Two solutions:

**Option A: Enrich `processedReports` with an encrypted reporter UID** (chosen for v1).

Add a new field `reporterUidEncrypted` to the `processedReports` document, encrypted with a server-side key. The correlation pipeline can decrypt it to credit the reporter. This maintains the privacy guarantee for reads (the scouting endpoint never decrypts), while allowing the server-side pipeline to attribute credits.

**Option B: Build a separate reporter-to-tag index** (chosen for simplicity in v1).

Add a new top-level collection `scoutingReports/{autoId}` that stores the reporter UID, scouted UID, sport, tags, match ID, and timestamp. This is a denormalised write-ahead log of all scouting observations, written by the D4.3 trigger alongside the existing `processedReports` upsert. The correlation pipeline queries this collection instead of `processedReports`.

| Approach | Pros | Cons | Verdict |
|----------|------|------|---------|
| Enrich `processedReports` | No new collection; minimal schema change | Encryption adds complexity; migration needed for existing docs | Rejected |
| **New `scoutingReports` collection** | Clean separation; no migration; simple queries | Additional write per scouting event; slight storage increase | **Chosen** |

The `scoutingReports` collection is a write-ahead log — it stores what the D4.3 trigger already computes but with the reporter UID in cleartext (server-side only, never exposed via API). The privacy boundary is maintained because no API endpoint reads this collection directly; only the server-side correlation pipeline uses it.

### New collection: `scoutingReports/{autoId}`

```json
{
  "reporterUid": "user_alice",
  "scoutedUid": "user_bob",
  "sport": "tennis",
  "matchId": "match_abc",
  "entryId": "journal_entry_123",
  "weakTags": ["backhand", "stamina_set3"],
  "strongTags": ["first_serve"],
  "createdAt": "2026-03-01T10:00:00Z",
  "isActive": true
}
```

Written by the D4.3 trigger. Soft-deleted (`isActive: false`) when the journal entry is deleted (D4.4 trigger).

### Step 4 detail: Tag matching algorithm

The matching algorithm determines whether a scouting tag was "confirmed" by a match outcome.

**Confirmation signals** (in priority order):

1. **Winner's reflection match** (highest confidence): The winner of the confirming match tagged the same weakness in their own reflection. Example: Scout tagged opponent with "backhand" weakness. Winner's `reflection.went_well` or `reflection.opponent_weak` includes "backhand" or a synonym.

2. **Score pattern match** (medium confidence): The scouted player lost the match, and the tag maps to a pattern visible in the score. Example: "stamina_set3" is confirmed if the scouted player lost in 3 sets after winning the first set. This uses the same score-based pattern detection from the Danger Zone architecture.

3. **Simple outcome match** (lowest confidence): The scouted player lost the match. Any weakness tag gets partial credit because the weakness may have contributed to the loss. This is a weak signal but provides volume for the accuracy calculation.

**Vocabulary bridging**: Scouting tags and reflection tags use the same taxonomy (`config/skillTaxonomy`), but users may use different specific tags for the same concept. A vocabulary bridge maps related tags:

```python
SCOUTING_CORRELATION_MAP: dict[str, set[str]] = {
    # scouting tag -> set of reflection tags that confirm it
    "backhand": {"backhand", "backhand_winner", "backhand_cross"},
    "first_serve": {"first_serve", "ace", "serve"},
    "double_faults": {"double_faults", "serve"},
    "stamina_set3": {"stamina", "endurance", "fitness", "stamina_set3"},
    "net_approach": {"net_approach", "volley", "net_play"},
    "concentration": {"concentration", "composure", "mental", "tiebreak"},
    "forehand_winner": {"forehand_winner", "forehand", "power"},
    "volley": {"volley", "net_approach", "net_play"},
    "footwork": {"footwork", "fitness", "endurance"},
}
```

This reuses the same vocabulary space as `TRAINING_TO_WEAKNESS_MAP` from the Win Predictor, ensuring consistency across features. A tag match is confirmed if the winner's reflection contains any tag in the correlation set for the scouted tag.

### Confirmation weighting

Not all confirmations are equally strong. The correlation event stores the `confirmationSource` for downstream weighting:

| Source | Weight | When used |
|--------|--------|-----------|
| `winner_reflection` | 1.0 | Winner independently identified the same weakness |
| `score_pattern` | 0.7 | Score pattern matches the tagged weakness category |
| `outcome_only` | 0.3 | Scouted player lost, but no specific tag confirmation |

For v1, the accuracy calculation uses binary confirmed/unconfirmed (all weights are 1.0 or 0.0). The weights are stored for future use in a weighted accuracy model (v2).

### Temporal constraints

A scouting tag is only eligible for correlation if:
1. The tag was created (`scoutingReports.createdAt`) **before** the confirming match's `scheduledAt`.
2. The tag was created from a **different** match than the confirming match (`sourceMatchId != confirmingMatchId`).
3. The tag is still active (`isActive: true` — not soft-deleted).

Constraint 2 prevents self-confirmation: if User A plays User B and tags them with "weak backhand", that same match cannot confirm the tag. Only a subsequent match involving User B can confirm it.

### Pipeline pseudocode

```python
def run_scouting_correlation(match_id: str) -> None:
    match = get_match(match_id)
    if match.status != "completed" or not match.score.winner_uid:
        return  # skip walkovers, retirements, draws
    if len(match.participant_uids) != 2:
        return  # singles only — doubles correlation deferred

    sport = match.sport
    winner_uid = match.score.winner_uid
    loser_uid = [uid for uid in match.participant_uids if uid != winner_uid][0]

    # Read winner's reflection for this match (if exists)
    winner_reflection = get_journal_reflection(winner_uid, match_id)
    winner_tags = set()
    if winner_reflection:
        winner_tags = set(
            winner_reflection.went_well
            + winner_reflection.opponent_weak
        )

    # Find all prior scouting reports about the loser
    prior_reports = query_scouting_reports(
        scouted_uid=loser_uid,
        sport=sport,
        before=match.scheduled_at,
        exclude_match_id=match_id,
        is_active=True,
    )

    for report in prior_reports:
        for tag in report.weak_tags:
            correlation_id = f"{report.reporter_uid}_{match_id}_{tag}"
            if correlation_exists(correlation_id):
                continue  # idempotent

            confirmed = False
            source = "unconfirmed"

            # Check winner reflection match
            correlated_tags = SCOUTING_CORRELATION_MAP.get(tag, {tag})
            if winner_tags & correlated_tags:
                confirmed = True
                source = "winner_reflection"

            # Check score pattern (fallback)
            elif matches_score_pattern(tag, match.score):
                confirmed = True
                source = "score_pattern"

            write_correlation(
                correlation_id=correlation_id,
                scout_uid=report.reporter_uid,
                scouted_uid=loser_uid,
                confirming_match_id=match_id,
                tag=tag,
                tag_category="weak",
                source_match_id=report.match_id,
                source_entry_id=report.entry_id,
                confirmed=confirmed,
                confirmation_source=source,
                sport=sport,
                region=get_user_region(report.reporter_uid),
            )

            # Update scout accuracy
            update_scout_accuracy(
                uid=report.reporter_uid,
                sport=sport,
                confirmed=confirmed,
            )
```

---

## IV. Scoring & Ranking

### Accuracy formula

```
raw_accuracy = confirmed_tags / total_correlated_tags       # 0.0-1.0
confidence   = min(1.0, confirmed_tags / MIN_CORRELATIONS)  # 0.0-1.0
score        = raw_accuracy * confidence                    # 0.0-1.0
```

Where `MIN_CORRELATIONS = 5` (minimum confirmed correlations for full confidence weighting).

### Why confidence-weighted accuracy instead of raw accuracy

Raw accuracy favours scouts with few observations. A scout who tagged one weakness correctly has 100% accuracy but provides no meaningful signal. The confidence multiplier penalises low sample sizes:

| Scout | Confirmed | Total | Raw Accuracy | Confidence (min(1, confirmed/5)) | Score |
|-------|-----------|-------|-------------|------------|-------|
| Alice | 2 | 2 | 1.00 | 0.40 | 0.40 |
| Bob | 8 | 10 | 0.80 | 1.00 | 0.80 |
| Carol | 15 | 20 | 0.75 | 1.00 | 0.75 |
| Dave | 4 | 8 | 0.50 | 0.80 | 0.40 |

Bob ranks highest despite lower raw accuracy than Alice, because his score is backed by a meaningful sample.

### Time decay

For the monthly leaderboard, only correlations from the current calendar month contribute to `currentMonthAccuracy`. The all-time accuracy uses all correlations without decay.

A future enhancement (v2) could apply exponential decay to the all-time accuracy so that recent scouting performance matters more than historical accuracy. For v1, the monthly leaderboard provides sufficient recency signal.

### Monthly ranking

The "Scout of the Month" winner is determined at month end by:

1. Filter to scouts who are `optedIn` and have `currentMonthConfirmed >= MIN_CORRELATIONS_FOR_RANKING` (5).
2. Rank by `currentMonthAccuracy` descending, breaking ties by `currentMonthConfirmed` descending (more observations wins the tiebreak).
3. The top scout per region+sport wins the title.

### All-time leaderboard

The all-time leaderboard uses the `confidenceScore` field and requires `confirmedTags >= MIN_CORRELATIONS_FOR_DISPLAY` (3). This leaderboard is available year-round and shows the top 10 scouts per region+sport.

---

## V. Badge/Reward System

### Scout of the Month title

- Awarded to the #1 scout per region+sport at month end.
- Displayed as a badge on the Athlete Card (Tab 4) for the following month.
- Historical wins stored in `scoutAccuracy/{uid}.scoutOfTheMonth[]` array.
- The title rotates monthly — previous winners must re-earn it.

### Achievement tiers

| Tier | Confirmed Tags | Accuracy | Badge Icon | Reward |
|------|---------------|----------|------------|--------|
| Bronze Scout | 10+ | (none) | Bronze magnifying glass | Badge on Athlete Card |
| Silver Scout | 30+ | 60%+ | Silver magnifying glass | Badge + "Trusted Scout" label |
| Gold Scout | 75+ | 70%+ | Gold magnifying glass | Badge + priority in scouting feed |
| Elite Scout | 150+ | 75%+ | Diamond magnifying glass | Badge + "Elite Scout" title + potential Pro feature access |

### Achievement evaluation

Achievement tiers are checked whenever `scoutAccuracy/{uid}` is updated. The check is a pure function:

```python
def evaluate_achievement_tier(
    confirmed_tags: int,
    accuracy: float,
) -> str | None:
    if confirmed_tags >= 150 and accuracy >= 0.75:
        return "elite"
    if confirmed_tags >= 75 and accuracy >= 0.70:
        return "gold"
    if confirmed_tags >= 30 and accuracy >= 0.60:
        return "silver"
    if confirmed_tags >= 10:
        return "bronze"
    return None
```

Tiers are monotonically increasing — once earned, they are never downgraded. The `achievementTierEarnedAt` timestamp records when the tier was first achieved.

### Integration with Tab 4 Clubhouse

The Athlete Card (Tab 4) displays:
- Current achievement tier badge (permanent).
- "Scout of the Month" badge if the user won the title last month (temporary, refreshed monthly).
- Scouting stats summary: "82% accuracy, 45 confirmed observations" (if opted in).

This is read directly from `scoutAccuracy/{uid}` — no additional collection needed.

---

## VI. API Integration

### Endpoint 1: `GET /me/lab/scout-stats?sport=tennis`

Returns the requesting user's own scouting accuracy stats.

| Attribute | Value |
|-----------|-------|
| Method | GET |
| Path | `/me/lab/scout-stats` |
| Auth | Bearer (self) |
| Query params | `sport` (required, enum) |

**Response:**

```json
{
  "total_tags": 25,
  "confirmed_tags": 18,
  "unconfirmed_tags": 7,
  "accuracy": 0.72,
  "confidence_score": 0.72,
  "current_month_accuracy": 0.75,
  "current_month_confirmed": 6,
  "current_month_tags": 8,
  "streak_confirmed": 3,
  "achievement_tier": "silver",
  "achievement_tier_earned_at": "2026-02-28T00:00:00Z",
  "scout_of_the_month_wins": [
    {
      "sport": "tennis",
      "region": "athens",
      "month": "2026-02"
    }
  ],
  "opted_in": true
}
```

**Error responses:**

| Status | Condition | Detail |
|--------|-----------|--------|
| 401 | No/invalid auth token | "Not authenticated" |
| 404 | No scouting accuracy data for this sport | "No scouting data yet. Start tagging opponent strengths and weaknesses in your match reflections." |

### Endpoint 2: `GET /lab/scout-leaderboard?sport=tennis&region=athens`

Returns the scouting leaderboard for a region and sport.

| Attribute | Value |
|-----------|-------|
| Method | GET |
| Path | `/lab/scout-leaderboard` |
| Auth | Bearer (any authenticated user) |
| Query params | `sport` (required, enum), `region` (required, string), `month` (optional, string, format `YYYY-MM`, defaults to current month) |

**Response:**

```json
{
  "region": "athens",
  "sport": "tennis",
  "month": "2026-03",
  "entries": [
    {
      "uid": "user_alice",
      "name": "Alice K.",
      "accuracy": 0.82,
      "confirmed_tags": 14,
      "total_tags": 17,
      "achievement_tier": "silver",
      "rank": 1
    }
  ],
  "current_user_rank": 3,
  "current_user_accuracy": 0.71,
  "scout_of_the_month": {
    "uid": "user_alice",
    "name": "Alice K.",
    "accuracy": 0.82
  },
  "finalized": false
}
```

The `current_user_rank` and `current_user_accuracy` fields are computed on-read from the requesting user's `scoutAccuracy` document and injected into the pre-computed leaderboard response.

**Error responses:**

| Status | Condition | Detail |
|--------|-----------|--------|
| 401 | No/invalid auth token | "Not authenticated" |
| 404 | No leaderboard for this region/sport/month | "No scouting leaderboard data for this region" |

### Endpoint 3: `PATCH /me/settings/scout-leaderboard`

Toggle opt-in/opt-out for the scouting leaderboard.

| Attribute | Value |
|-----------|-------|
| Method | PATCH |
| Path | `/me/settings/scout-leaderboard` |
| Auth | Bearer (self) |

**Request body:**

```json
{
  "opted_in": false
}
```

**Response:** 200 OK with updated `scoutAccuracy` stats.

### Premium gate consideration

For v1, the scouting leaderboard and scout stats are **not** premium-gated. The gamification loop benefits from maximum participation — gating it behind Pro would reduce the pool of scouts and make the leaderboard feel empty.

The "Scout of the Month" title and achievement badges are free. Future premium features could include:
- Detailed correlation breakdown (which specific tags were confirmed).
- Historical accuracy trends graph.
- Scout comparison view (compare your accuracy against another user).

### Constants

New constants for `api/app/constants.py`:

```python
SCOUT_MIN_CORRELATIONS_FOR_DISPLAY = 3     # minimum to appear on leaderboard
SCOUT_MIN_CORRELATIONS_FOR_RANKING = 5     # minimum for full confidence weighting
SCOUT_LEADERBOARD_SIZE = 10                # entries per leaderboard page
SCOUT_BRONZE_THRESHOLD = 10                # confirmed tags for Bronze
SCOUT_SILVER_THRESHOLD = 30                # confirmed tags for Silver
SCOUT_SILVER_ACCURACY = 0.60               # minimum accuracy for Silver
SCOUT_GOLD_THRESHOLD = 75                  # confirmed tags for Gold
SCOUT_GOLD_ACCURACY = 0.70                 # minimum accuracy for Gold
SCOUT_ELITE_THRESHOLD = 150                # confirmed tags for Elite
SCOUT_ELITE_ACCURACY = 0.75               # minimum accuracy for Elite
```

---

## VII. Implementation Phases

### Phase 4a: Data layer + scouting reports write-ahead log

1. Add `scoutingReports/{autoId}` collection schema and Pydantic model.
2. Extend the D4.3 scouting trigger (`functions/journal_triggers/scouting.py`) to write a `scoutingReports` document alongside the existing `processedReports` upsert.
3. Extend the D4.4 scouting delete trigger to soft-delete (`isActive: false`) the corresponding `scoutingReports` document.
4. Add Firestore indexes: `scoutingReports` composite index on `(scoutedUid ASC, sport ASC, createdAt DESC)`.
5. No API changes — this phase is invisible to users.

### Phase 4b: Correlation pipeline

1. Add `scoutingCorrelations/{correlationId}` collection, Pydantic model, repo, and mapper.
2. Add `scoutAccuracy/{uid}` collection, Pydantic model, repo, and mapper.
3. Implement the correlation pipeline as a Cloud Function (D5.3 trigger on match completion).
4. Add `SCOUTING_CORRELATION_MAP` constant.
5. Add `evaluate_achievement_tier()` pure function.
6. Add Firestore indexes for correlation queries.
7. Unit tests for the correlation logic and achievement evaluation.

### Phase 4c: API endpoints + leaderboard

1. Add `GET /me/lab/scout-stats` endpoint.
2. Add `GET /lab/scout-leaderboard` endpoint.
3. Add `PATCH /me/settings/scout-leaderboard` opt-in toggle.
4. Add `scoutLeaderboard/{region}_{sport}_{month}` collection and monthly batch job.
5. Add constants to `api/app/constants.py`.
6. Integration tests with seeded scouting, match, and journal data.

### Phase 4d: Badges + Athlete Card integration

1. Add badge display data to the Athlete Card endpoint (Tab 4).
2. Add "Scout of the Month" monthly winner computation (Cloud Scheduler).
3. Add push notification for monthly winner announcement.
4. Seed badge/achievement data for emulator testing.

### Phase 4e: Weighted accuracy + advanced analytics (deferred)

1. Use `confirmationSource` weights in accuracy calculation (v2 formula).
2. Add accuracy trend graph (historical monthly accuracy).
3. Add tag-level accuracy breakdown ("Your backhand scouting is 90% accurate").
4. Consider ML-based tag prediction: "Based on your past scouting, this player likely has a weak net game."

---

## VIII. Edge Cases

| Case | Handling |
|------|----------|
| **Self-scouting** (user tags their own weakness) | `opponentWeak`/`opponentStrong` tags are about the *opponent*, not the self. The reporter UID is always different from the scouted UID. If a user somehow tags themselves (edge case from data corruption), the correlation pipeline filters out `scoutUid == scoutedUid`. |
| **Tag gaming** (user creates fake scouting tags to inflate accuracy) | Mitigated by requiring a real match with the scouted opponent (`sourceMatchId` must reference a completed match where the reporter participated). Users cannot scout opponents they have never played. The tag must also come from a journal reflection on that match, not fabricated. |
| **Tag gaming via collusion** (two friends agree to tag each other's "weaknesses" and then confirm them) | Partially mitigated by the confidence threshold — collusion requires playing many matches to reach minimum sample sizes. For v1, this is an acceptable risk. v2 could add a "diversity of scouted opponents" requirement (e.g., tags must span 3+ unique scouted UIDs). |
| **No confirming match** | A scouting tag that is never correlated (the scouted player never plays another match) stays uncorrelated. It does not count for or against accuracy. Only tags that have been evaluated (a confirming match exists) contribute to the accuracy calculation. |
| **Scouted player is inactive** | Same as above — no confirming match means no correlation. The tag exists in `scoutingReports` but generates no `scoutingCorrelations` events. |
| **Multiple scouts tag the same weakness** | Each scout is credited independently. If Alice and Bob both tag User C's backhand as weak, and User C loses a match where the winner confirms "backhand", both Alice and Bob receive a confirmed correlation. |
| **Scout tags "strong" instead of "weak"** | **v1 correlates weak tags only.** Strong tags (`opponentStrong`) are stored in `scoutingReports` but not processed by the correlation pipeline. Strong-tag correlation requires inverse logic (confirming a strength when the scouted player *wins*) and different matching semantics. Deferred to a future phase. |
| **Journal entry deleted after correlation** | The `scoutingReports` document is soft-deleted. Future correlation events will skip it. Existing `scoutingCorrelations` entries are **not** retroactively removed — the historical accuracy snapshot is preserved. This prevents accuracy manipulation via selective deletion. |
| **Match disputed or cancelled after correlation** | If a confirming match is later disputed or cancelled, the correlation events from that match should be reversed. The monthly batch job includes a cleanup step that checks correlation events against match statuses and removes invalid correlations. |
| **Region change** | If a user changes their area/region, their `scoutAccuracy` profile is unchanged (it is not region-scoped). The monthly leaderboard uses the user's region at computation time. Historical leaderboard entries are not retroactively updated. |
| **New sport added** | The per-sport map structure (`scoutAccuracy/{uid}.{sport}`) supports new sports without migration. New sports start with zero correlations. |
| **Insufficient data for leaderboard** | If a region+sport has fewer than 3 eligible scouts, the leaderboard displays a "Not enough data yet" message. The Scout of the Month title is not awarded. |
| **Opt-out after winning Scout of the Month** | Historical wins in `scoutOfTheMonth[]` are preserved. The user is removed from future leaderboard displays. The title display on Athlete Card is hidden. |

---

## IX. Observability and Tuning

### Logging

The correlation pipeline logs at `INFO` level:
- Match processed: match ID, sport, winner UID, loser UID
- Reports found: count of prior scouting reports for the loser
- Correlations generated: count of confirmed/unconfirmed events
- Achievement tier changes: when a user earns a new tier

The monthly batch job logs:
- Region+sport processed, number of eligible scouts
- Winner UID and accuracy for each leaderboard

### Tuning knobs

| Constant | Default | What it controls |
|----------|---------|-----------------|
| `SCOUT_MIN_CORRELATIONS_FOR_DISPLAY` | 3 | Minimum confirmed correlations to appear on leaderboard |
| `SCOUT_MIN_CORRELATIONS_FOR_RANKING` | 5 | Confirmed correlations for full confidence weighting |
| `SCOUT_LEADERBOARD_SIZE` | 10 | Entries per leaderboard |
| `SCOUT_BRONZE_THRESHOLD` | 10 | Confirmed tags for Bronze tier |
| `SCOUT_SILVER_THRESHOLD` | 30 | Confirmed tags for Silver tier |
| `SCOUT_SILVER_ACCURACY` | 0.60 | Accuracy for Silver tier |
| `SCOUT_GOLD_THRESHOLD` | 75 | Confirmed tags for Gold tier |
| `SCOUT_GOLD_ACCURACY` | 0.70 | Accuracy for Gold tier |
| `SCOUT_ELITE_THRESHOLD` | 150 | Confirmed tags for Elite tier |
| `SCOUT_ELITE_ACCURACY` | 0.75 | Accuracy for Elite tier |

### Success metrics

The feature is successful if:
1. **Scouting volume increases**: Users who see the leaderboard produce 20%+ more scouting tags per match reflection (measured by comparing `opponentWeak`/`opponentStrong` tag rates before and after feature launch).
2. **Tag quality improves**: The average correlation confirmation rate across all scouts rises from baseline over the first 3 months (indicating users are making more thoughtful observations).
3. **Social engagement**: Scout of the Month announcements generate Athlete Card views and sharing (measured by Athlete Card view count for winners vs. non-winners).
4. **Retention signal**: Users who achieve Bronze+ scouting tiers have higher 30-day retention than those who do not engage with scouting.
