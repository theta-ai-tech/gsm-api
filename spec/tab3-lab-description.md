# GSM Strategic PRD: Tab 3 – THE LAB (The Brain)

This document serves as the comprehensive functional and strategic specification for **Tab 3: THE LAB**, the analytics and intelligence engine of the **Grand Slam Matchmaking (GSM)** ecosystem.

> **Status**: Draft — endpoints and workflows to be revisited after code is finalised.
>
> **Related docs**: `arch/scoring_engine.md`, `tab3-implementation-plan.md`, `wiki/DATA_DICTIONARY.md`, `wiki/functions.md`

---

## I. Executive Summary & Vision

*   **One-Line Pitch:** Professional intelligence for the amateur — a data-powered analytics engine that turns match history and training reflections into actionable scouting reports, standardised rankings, and a personal performance "stock price."
*   **The Problem:** Most players don't know *why* they win or lose, and they have no way to scout their next opponent. Training stays reactive. Progress is invisible.
*   **The Payoff:** A data moat that makes GSM the "Nasdaq" of amateur racket sports. If you aren't on GSM, your ranking doesn't exist.
*   **Core Goal:** Synthesise raw data from Tab 1 (PLAY) and Tab 2 (IMPROVE) into proprietary scouting reports, standardised rankings, and performance analytics.

---

## II. The "Titan" Strategic Framework

*   **Mark Cuban (The Data Moat & Scalability):** "Data is the only thing that scales without human labor. If you own the scoring standard, you own the market." → The 1000–4000 Point Standard. This tab must feel like a professional financial terminal for sports. The more data ingested, the higher the barrier to entry for competitors.
*   **Alex Hormozi (High-Ticket Value Stacking):** "You're giving them a scouting report that usually costs thousands in pro coaching. That is a Grand Slam Offer." → The "Rivalry Scout." Before a match, a player can unlock a deep-dive analysis of an opponent's weaknesses — intel that used to require a private coach.
*   **Gary Vaynerchuk (Community Intelligence Arbitrage):** "Use the collective brain of the community to build a master database." → The "Scouting Ticker." Aggregated tags from every user's private journal create a crowd-sourced profile of every player on the platform, driving organic engagement and screenshot-worthy leaderboard moments.

---

## III. Design Principles

1.  **Instant gratification**: The player who confirms a match sees their updated score immediately. No waiting for background jobs.
2.  **Eventual consistency for global state**: Rankings, leaderboards, and opponent score updates propagate asynchronously via triggers. A `lastUpdated` timestamp signals freshness to the mobile client.
3.  **Per-sport isolation**: A user's tennis score is independent of their padel score. Each sport has its own point track.
4.  **Auditability**: Every point change is recorded in a time-series subcollection with a reason code. No silent mutations.
5.  **Rebalanceable tiers**: Tier thresholds are stored as configuration (`config/tiers`), not hardcoded. A rebalance operation can reclassify users without changing their point totals.

---

## IV. Functional Features & Interaction Flow

### Flow 1: The Lab Dashboard (Initial State)

The default view when entering Tab 3 — a high-level view of the user's "Market Value" and "Skill DNA."

*   **Top Section — The Progression Graph:** A high-contrast line graph of the user's GSM Points (1000–4000+ scale). Visual threshold markers at Amateur (1000), Intermediate (2000), Advanced (3000), and Competitive (4000). Cuban's "Stock Price" — the single most important metric on the platform.
*   **Center Section — The Skill DNA Radar Chart:** A 5-axis spider chart: Serve, Power, Net Play, Stamina, Mental. Data sourced from Tab 2's "went well / went wrong" reflection tags, aggregated via the D4 trigger and `config/skillTaxonomy`. Comparison Mode: overlay your DNA with the average DNA of the next tier up (`config/tierAverages`) to see where you're lagging.
*   **Bottom Section — Quick Stats Overview:** Win Rate, Current Streak, Tier Ranking, Global Rank. All compute-on-read from cached user doc fields.

**Interaction — The "Scrub" Feature:** Users can slide their finger across the Progression Graph to see their exact point total on any given day. Each data point shows the match-specific context (e.g., "Oct 12: +120 pts vs. Mans L."). The graph scrub provides haptic "clicks" as you move through time.

**API**: `GET /me/lab/dashboard` (points, tier, rank, stats), `GET /me/lab/progression?sport=tennis` (paginated pointHistory for the graph), `GET /me/lab/skill-dna?sport=tennis` (radar chart data + comparison tier).

---

### Flow 2: The Rivalry Scout (Head-to-Head Search)

Scouting a specific opponent before a match to gain a tactical edge. Deep-linked from Tab 1 when clicking an opponent's name in MATCH_SCHEDULED state.

*   **Interaction:** User taps the "Search Rival" bar at the top of The Lab.
*   **The UI — "Tale of the Tape":** A side-by-side comparison card.
*   **Key Data Points:**
    *   **Win Probability %:** Computed on-read using a sigmoid formula based on point difference. A 500-point advantage ≈ 75% win probability. Formula: `1 / (1 + 10^(-diff / 1000))`.
    *   **Overlay Radar Chart:** Your Skill DNA (blue fill) vs. theirs (white outline).
    *   **Past History:** Scorelines of previous encounters, queried via the `participantPair` field (deterministic lexicographic UID pair, e.g., `user_alice_user_bob`).
    *   **Community Scouting:** Aggregated weak/strong tags from `scouting/{opponentUid}` — anonymous counts only ("7 players noted weak backhand").
    *   **The "Danger Zone" (Phase 4):** AI-identified patterns where you lose points to this specific person. Requires point-by-point match data (not yet captured).

**API**: `GET /me/lab/rivalry/{opponentUid}?sport=tennis` (H2H stats, win probability, match history, scouting summary).

---

### Flow 3: Community Intelligence — Global Ticker & Local Rankings

Community status and social proof — Gary Vaynerchuk's organic growth engine.

*   **The Ticker:** A scrolling horizontal bar showing "Global Upsets" (e.g., "SARAH K. [+150 pts] UPSET A 3500-RATED PLAYER"). Written inline during match confirmation when `winner_tier < loser_tier`. 24-hour TTL.
*   **Local Leaderboard:** Vertical list of top 10 players in the user's region, sorted by pts. Pre-computed hourly by D7.1.
*   **Rising Stars:** Top 5 players by `delta7d` (point change in last 7 days). The screenshot-worthy moment: seeing your name on Rising Stars drives Instagram shares.

**API**: `GET /lab/leaderboard?region=athens&sport=tennis` (top 10 + rising stars), `GET /lab/ticker?region=athens&sport=tennis` (recent upsets/milestones).

---

## V. The Scoring Engine

The mathematical heart of GSM. Translates match outcomes into a unified point rating per sport.

### Scoring Formula

| Outcome | Points Change | Condition |
|---------|--------------|-----------|
| Win (standard) | +100 | Beating an opponent in the same tier |
| Win (upset bonus) | +50 additional | Beating an opponent in a higher tier |
| Win (Elo bonus) | +5% of point difference | Beating someone with significantly higher points (applied on top of base + upset) |
| Loss (downward) | −50 | Losing to an opponent in a lower tier |
| Loss (standard) | 0 | Losing to someone in the same or higher tier |

### Tier Thresholds

Stored in `config/tiers` (Firestore document, not hardcoded):

| Tier | Min Points | Max Points | Color |
|------|-----------|-----------|-------|
| Amateur | 1000 | 1999 | `#8B8B8B` |
| Intermediate | 2000 | 2999 | `#00A3CC` |
| Advanced | 3000 | 3999 | `#BFFF00` |
| Competitive | 4000 | ∞ | `#FF6B35` |

### Floor Enforcement

Each user has a `registrationTier` set at signup (self-selected). Points can never drop below that tier's starting value, preventing score tanking. A Competitive player who loses many matches cannot artificially drop into Amateur ranges.

### Execution Trigger

Scoring executes **inline within the match confirmation transaction** — `POST /matches/{matchId}/verify-score`. This is the same Firestore transaction that sets `match.status = completed`. The confirming player sees their new score instantly in the "Victory Animation" (GSM points rising on screen).

After the transaction commits, async triggers handle global state:
- **D5.1**: Recompute `globalRanking` ordinals for the sport (batch read+sort+write).
- **D5.2**: Update league member stats if `match.leagueId` is set.

### Confirm Endpoint Response (Extended)

The match confirmation response includes a scoring payload for the Victory Animation:

```json
{
  "matchId": "match_789",
  "status": "completed",
  "scoring": {
    "sport": "tennis",
    "yourPtsBefore": 2100,
    "yourPtsAfter": 2300,
    "delta": 200,
    "breakdown": {
      "baseWin": 100,
      "upsetBonus": 50,
      "eloBonus": 50,
      "penalty": 0
    },
    "tierBefore": "intermediate",
    "tierAfter": "intermediate",
    "tierCrossed": false
  }
}
```

### Edge Cases

| Case | Handling |
|------|----------|
| Same-tier match | Winner: +100, Loser: 0 |
| Points cross a tier boundary | Tier recomputed on-read from active threshold config |
| Points would go below floor | Floor enforced — cannot drop below registration tier start |
| Disputed match resolved | Scoring runs at resolution time, not initial submission |
| League vs. casual match | Same formula; league context is metadata only (in pointHistory) |
| Walkover / retirement | No points awarded to either player |

---

## VI. Data Architecture

### Skill DNA

Tab 2's MatchReflection stores free-form tags (`went_well: ["first_serve", "net_approach"]`). These are mapped to 5 radar axes via a configurable taxonomy in `config/skillTaxonomy`:

```json
{
  "axes": ["serve", "power", "net_play", "stamina", "mental"],
  "tagMap": {
    "first_serve": "serve",
    "double_faults": "serve",
    "ace": "serve",
    "forehand_winner": "power",
    "backhand_winner": "power",
    "net_approach": "net_play",
    "volley": "net_play",
    "endurance": "stamina",
    "fitness": "stamina",
    "concentration": "mental",
    "composure": "mental",
    "tiebreak": "mental"
  },
  "version": 1
}
```

**Aggregation**: Denormalised `skillDna` map on user doc, updated by D4 trigger on journal writes. Score per axis: `round(positive / (positive + negative) * 100)`. Minimum 3 data points before displaying.

### Head-to-Head (participantPair)

Firestore's `array-contains` only supports one value per query. To query "matches where both Alice and Bob participated," every match doc gets a `participantPair` field — a deterministic string of two UIDs in lexicographic order:

```
participantPair: "user_alice_user_bob"
```

Composite index: `(participantPair ASC, finishedAt DESC)` for paginated H2H history.

### Scouting Profiles

Path: `scouting/{uid}`. One document per player, aggregating community observations:

```json
{
  "uid": "user_bob",
  "tennis": {
    "weak": {
      "backhand": {"count": 7, "lastReported": "2026-03-01T10:00:00Z"},
      "stamina_set3": {"count": 3, "lastReported": "2026-02-28T15:00:00Z"}
    },
    "strong": {
      "first_serve": {"count": 5, "lastReported": "2026-03-01T09:00:00Z"}
    },
    "totalReports": 12,
    "uniqueReporters": 8,
    "lastUpdated": "2026-03-01T10:00:00Z"
  }
}
```

**Privacy**: Scouting reports are anonymous. Stores counts, not reporter UIDs. Users see "7 players noted weak backhand" — never who said it.

### Leaderboards

Path: `leaderboards/{region}_{sport}`. Pre-computed snapshots, not live queries. Written hourly by D7.1.

```json
{
  "region": "athens",
  "sport": "tennis",
  "entries": [
    {"uid": "user_123", "name": "Alex", "pts": 3450, "tier": "advanced", "rank": 1, "delta7d": 250}
  ],
  "risingStars": [
    {"uid": "user_789", "name": "Dana", "pts": 2100, "delta7d": 400, "rank": 15}
  ],
  "lastUpdated": "2026-03-01T12:00:00Z"
}
```

Region resolution: derived from `users/{uid}.preferences.area` via `config/regions`.

### Upsets Ticker

Path: `ticker/{auto}`. Capped collection of recent notable events:

```json
{
  "type": "upset",
  "sport": "tennis",
  "region": "athens",
  "winnerUid": "user_789",
  "winnerName": "Dana",
  "loserTier": "advanced",
  "delta": 200,
  "createdAt": "2026-03-01T14:30:00Z",
  "expiresAt": "2026-03-02T14:30:00Z"
}
```

Written inline during match confirmation when `winner_tier < loser_tier`. 24-hour TTL with scheduled cleanup (D7.2) or Firestore TTL policy.

### Point History

Path: `users/{uid}/pointHistory/{entryId}`. Time-series subcollection powering the Progression Graph:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `sport` | string (enum) | Yes | Which sport this entry is for |
| `pts` | number | Yes | Point total after this event |
| `delta` | number | Yes | Points gained or lost |
| `reason` | string (enum) | Yes | `match_win`, `match_loss`, `upset_bonus`, `penalty`, `admin_adjustment`, `tier_rebalance` |
| `matchId` | string | Conditional | Reference to the match (null for admin adjustments) |
| `opponentUid` | string | Conditional | Opponent's UID |
| `opponentPtsBefore` | number | Conditional | Opponent's points before match (audit trail) |
| `leagueId` | string | Optional | If this was a league match |
| `createdAt` | timestamp | Yes | When this event occurred |
| `tierBefore` | string | Optional | Tier before this event |
| `tierAfter` | string | Optional | Tier after this event |

**Indexes:**
- Composite: `(sport ASC, createdAt DESC)` — Progression Graph query
- Single: `createdAt DESC` — recent activity across all sports

---

## VII. New Firestore Schema (Complete)

| Collection / Field | Type | Purpose |
|---|---|---|
| `config/tiers` | Document | Tier threshold config (rebalanceable) |
| `config/skillTaxonomy` | Document | Tag → radar axis mapping |
| `config/tierAverages` | Document | Average Skill DNA per tier (comparison mode) |
| `config/regions` | Document | Area → region mapping for leaderboards |
| `users/{uid}.rankings.{sport}.tier` | string | Cached tier derived from pts + thresholds |
| `users/{uid}.rankings.{sport}.registrationTier` | string | User's self-selected tier at signup (point floor) |
| `users/{uid}.rankings.{sport}.lastUpdated` | timestamp | When ranking was last modified |
| `users/{uid}/pointHistory/{entryId}` | Subcollection | Time-series of every point change |
| `users/{uid}.skillDna.{sport}` | Map | Denormalised skill radar scores (5 axes) |
| `matches/{matchId}.participantPair` | String | Lexicographic UID pair for H2H queries |
| `scouting/{uid}` | Document | Aggregated community observations per player |
| `leaderboards/{region}_{sport}` | Document | Pre-computed regional leaderboard snapshots |
| `ticker/{auto}` | Document | Recent notable events (upsets, milestones) |

---

## VIII. API Endpoints Reference

| # | Method | Path | Purpose | Phase |
|---|--------|------|---------|-------|
| 1 | POST | `/matches/{matchId}/verify-score` | **Extend**: add inline scoring to existing match confirmation flow | P1 (Modified) |
| 2 | GET | `/me/lab/dashboard` | Current points, tier, global rank, basic stats | P1 |
| 3 | GET | `/me/lab/progression?sport=tennis` | Paginated point history for the Progression Graph | P1 |
| 4 | GET | `/me/lab/skill-dna?sport=tennis` | User's radar chart data + optional comparison tier | P2 |
| 5 | GET | `/me/lab/rivalry/{opponentUid}?sport=tennis` | H2H stats: win probability, match history, record | P2 |
| 6 | GET | `/me/lab/scouting/{opponentUid}?sport=tennis` | Community scouting report for an opponent | P3 |
| 7 | GET | `/lab/leaderboard?region=athens&sport=tennis` | Regional leaderboard (top 10 + rising stars) | P3 |
| 8 | GET | `/lab/ticker?region=athens&sport=tennis` | Recent upsets and milestones | P3 |

---

## IX. New Triggers

| ID | Collection / Schedule | Event | Purpose |
|---|---|---|---|
| D4.1 | `users/{uid}/journalEntries/{id}` | write | Map reflection tags to radar axes via `config/skillTaxonomy` |
| D4.2 | (continuation of D4.1) | — | Update `users/{uid}.skillDna.{sport}` counters |
| D4.3 | (continuation of D4.1) | — | Update `scouting/{opponentUid}` if opponent tags present |
| D5.1 | `matches/{matchId}` | update → completed | Recompute `globalRanking` ordinals for the sport |
| D5.2 | `matches/{matchId}` | update → completed | Update league member stats if `leagueId` set |
| D7.1 | Scheduled (hourly) | — | Compute leaderboard snapshots + rising stars |
| D7.2 | Scheduled (daily) | — | Clean up expired ticker entries |
| D7.3 | Scheduled (hourly) | — | Compute tier averages for Skill DNA comparison mode |

---

## X. Implementation Phases

Tab 3 is built in four sequential phases, each delivering a shippable vertical slice:

```
Phase 1: Scoring Engine ──────────────────────┐
  (Points, tiers, pointHistory,               │
   inline scoring, progression graph)          │
                                               ▼
Phase 2: Skill DNA & Head-to-Head ────────────┐
  (Tag taxonomy, skill aggregation,            │
   rivalry history, win probability)           │
                                               ▼
Phase 3: Community Intelligence ──────────────┐
  (Scouting profiles, leaderboards,            │
   upsets ticker, regional snapshots)          │
                                               ▼
Phase 4: AI & Premium ────────────────────────
  (Danger Zone, Win Predictor,
   AI Training Plans, Scout of the Month)
```

See `tab3-implementation-plan.md` for the full 44-issue breakdown and sprint allocation.

### Phase 4: AI & Premium (High-Level)

Deliberately left at a high level — detailed architecture after Phases 1–3 are in production:

| Feature | Description | Complexity |
|---------|-------------|------------|
| **Danger Zone** | AI identifies loss patterns vs. specific opponents. Architecture: `arch/danger_zone_data_model.md`. Uses post-match set-level annotations (`matchAnalysis/{matchId}`) instead of point-by-point data. Aggregated patterns in `dangerZone/{uid}`. Owner-only privacy model. Singles only for v1. UI/UX spec needed: #211. | Very High |
| **Win Predictor** | Preparation bonus based on recent training targeting opponent weaknesses. Architecture: `arch/win_predictor_heuristic.md`. `preparation_bonus` (0.0–0.05) returned as a **separate signal** alongside unchanged `win_probability` on the rivalry endpoint. Linear recency decay, 7-day window, 5pp cap. UI/UX spec needed: #211. | High |
| **AI Training Plan** | Personalised drill recommendations from Skill DNA weaknesses + opponent scouting. Architecture: `arch/ai_training_plan.md`. `drills/{drillId}` collection, `GET /me/lab/training-plan` endpoint, opponent-aware mode from rivalry view. Pro subscription required. Creates feedback loop with Win Predictor `preparation_bonus`. UI/UX spec needed: #218. | High |
| **Scout of the Month** | Gamification badge for users whose scouting tags best predict match outcomes. Architecture: `arch/scout_of_the_month.md`. Correlation pipeline (D5.3 trigger) validates weak tags against subsequent match outcomes using winner reflections and score patterns. Endpoints: `GET /me/lab/scout-stats`, `GET /lab/scout-leaderboard`, `PATCH /me/settings/scout-leaderboard`. Achievement tiers (Bronze→Elite) display on Athlete Card (Tab 4). Monthly title awarded per region+sport. Opt-in, not premium-gated. Singles only for v1. UI/UX spec needed: #225. | Medium |
| **Interactive Haptics** | Haptic "clicks" when scrubbing the progression graph. Mobile-only, no backend. | Low |

---

## XI. Cross-Tab Data Flows

### Tab 1 → Tab 3: Match Confirmation Feeds Scoring
When `POST /matches/{matchId}/verify-score` completes, the inline scoring engine writes updated points and `pointHistory` entries. These feed the Progression Graph and tier placement. Async triggers (D5) update global rankings.

### Tab 2 → Tab 3: Reflections Feed Skill DNA & Scouting
Journal reflections trigger D4, mapping skill tags to radar axes (Skill DNA) and incrementing opponent counters (scouting profiles).

### Tab 3 → Tab 1: Scouting Report in MATCH_SCHEDULED
When a user is in MATCH_SCHEDULED state, the scouting section pulls `scouting/{opponentUid}` data and the rivalry endpoint for H2H stats and win probability.

---

## XII. Figma & Technical Specifications

### Visual Aesthetics

*   **Style:** Analytical, "Data-Stream," High-Tech — differentiated from Tab 1's action-oriented UI.
*   **Primary Background:** `#0A0E12` (Deep Pitch).
*   **Primary Accent:** `#00D1FF` (Electric Blue) — used for all charts and data visualisations. Differentiates the "Lab" from the "Action" of the Play tab.
*   **Secondary Accent:** `#BFFF00` (Volt Green) — used sparingly for "Win" indicators and positive growth.
*   **Typography:** Condensed Bold for titles; Monospace (e.g., JetBrains Mono) for point values and data streams to give it a "Terminal" feel.
*   **Shadows:** Blue outer-glow on Radar Chart points (`0px 0px 8px rgba(0, 209, 255, 0.6)`).
*   **Charts:** Clean, minimalist vectors with zero clutter. Glow effects on radar chart lines.

### The 3-Interaction Rule

*   Dashboard → Progression Graph scrub: 1 tap + drag.
*   Dashboard → Rival Scout: 2 taps (search bar → select opponent).
*   MATCH_SCHEDULED → Rival Scout: 1 tap (deep-link from opponent name).

---

## XIII. Open Questions

1.  **Knockout tournaments**: Should tournament points use the same scale or a parallel track? (Recommendation: same scale, with `reason: tournament_win` in pointHistory.)
2.  **Decay**: Should inactive players lose points over time? (Recommendation: not in v1. Revisit with 6+ months of activity data.)
3.  **Initial placement**: Should first few matches use a "provisional" multiplier (e.g., 2x for first 5 matches) to help find true level faster? (Recommendation: yes — add `provisional` boolean and `matchesPlayed` counter.)
4.  **Double scoring on dispute resolution**: If a disputed match is resolved later, does scoring use current points or points at match time? (Recommendation: current points — avoids complexity of point-in-time lookups.)
