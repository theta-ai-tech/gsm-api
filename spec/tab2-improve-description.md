# GSM Strategic PRD: Tab 2 – IMPROVE (The Digital Training Partner)

This document serves as the comprehensive functional and strategic specification for **Tab 2: IMPROVE**, the performance journal and self-improvement engine of the **Grand Slam Matchmaking (GSM)** ecosystem.

> **Related docs**: `wiki/DATA_DICTIONARY.md` (journalEntries schema), `wiki/endpoints.md`, `wiki/functions.md` (D4 trigger)

---

## I. Executive Summary & Vision

*   **One-Line Pitch:** A 30-second post-match journal that turns fleeting court observations into structured data — feeding scouting reports, skill analytics, and personalised training insights across the entire GSM platform.
*   **The Problem:** Amateur players plateau because their training is reactive and their match reflections are lost to memory. Nobody reviews their performance systematically — that's a privilege reserved for players with private coaches.
*   **The Payoff:** Every journal entry strengthens the GSM data moat. Reflections feed Skill DNA (Tab 3), scouting reports (Tab 1), and community intelligence. The more a user journals, the smarter the entire ecosystem becomes.
*   **Core Goal:** Make post-match reflection effortless and habitual — under 30 seconds from court to completed entry.

---

## II. The "Titan" Strategic Framework

*   **Alex Hormozi (The Grand Slam Offer — Speed to Value):** "If it takes more than 30 seconds, you've already lost them." → The pill-based UI. No typing required for the core entry — just tap pills for what went well, what went wrong, and submit. Friction is the enemy of habit formation.
*   **Mark Cuban (Data Compounding):** "Every journal entry is a row in your scouting database. One entry is noise. A thousand entries across the community is a proprietary intelligence network." → The Review Loop. Tags from reflections compound into Skill DNA scores and opponent scouting profiles. Data entered in Tab 2 surfaces as actionable intelligence in Tabs 1 and 3.
*   **Gary Vaynerchuk (The Streak & Social Proof):** "Consistency is the only currency that compounds." → The Streak Counter and Weekly Activity Calendar. Gamify the journaling habit. A 30-day streak badge is shareable. The North Star Goal gives every session purpose.

---

## III. Design Principles

1.  **Under 30-Second Entry**: The pill-based selection UI enables logging while still on the court. No keyboards, no paragraph writing — just taps.
2.  **Two Entry Types**: Match logs (linked to a completed match, auto-populated with opponent/score/result) and Training logs (standalone sessions, no match linkage).
3.  **The Review Loop**: Structured reflections are not just personal notes — they feed the scouting pipeline on Tab 1 and the Skill DNA radar on Tab 3. Every "went wrong: backhand" tag from any user increments the opponent's community scouting profile.
4.  **Compute-on-Read Stats**: Dashboard statistics are derived from cached profile data (`journalRecent`, `completedMatches`) with zero additional Firestore reads. No expensive aggregation queries on every page load.
5.  **Atomic Writes**: Every journal creation is a Firestore transaction that writes the entry doc AND updates the `journalRecent` cache on the user doc in a single atomic operation. No stale caches.

---

## IV. Functional Features & Interaction Flow

### Flow 1: Match Log (Post-Match Reflection)

The primary entry type — logged after a completed match in Tab 1.

*   **Trigger:** User completes a match in Tab 1 (both players confirm score). The app prompts "Log Match" in Tab 2, or the user navigates manually.
*   **Auto-Population:** When creating a match log linked to a `matchId`, the entry auto-populates opponent name, score, and result from the match document. No re-typing.
*   **The Pill-Based Reflection UI:**
    1.  **"What went well?"** — Tap pills: First Serve, Forehand Winner, Net Approach, Volley, Endurance, Composure, Tiebreak, Ace. Multiple selections allowed.
    2.  **"What went wrong?"** — Same pill set, but tags are recorded as negative signals.
    3.  **"Opponent weaknesses?"** — Tags mapped to the opponent's UID. Anonymous. Feeds `scouting/{opponentUid}` via D4.3 trigger.
    4.  **"Opponent strengths?"** — Same as above, positive signals on the opponent's scouting profile.
    5.  **Optional freeform notes** — For players who want to write more (body field, max 2000 chars).
*   **The Hormozi Speed Check:** Steps 1–4 are pill taps only. A focused user completes all four in under 15 seconds. Step 5 is optional. Total time: under 30 seconds.

**API**: `POST /me/journal` with `entry_type: "match"` and `match_id`. Then `PATCH /me/journal/{entry_id}` with the reflection object.

---

### Flow 2: Training Log (Standalone Session)

Logging a practice session with no match linkage.

*   **Trigger:** User taps "Log Training" from the Tab 2 home screen.
*   **Fields:**
    *   **Focus Area Pills:** Serve, Volley, Footwork, Cardio. Multiple selections.
    *   **Duration:** Numeric input in minutes (e.g., 60).
    *   **Optional notes:** Freeform body text.
*   **No Opponent Context:** Training logs don't feed the scouting pipeline. They contribute to streak counts, weekly activity, and (in Phase 4) the AI Training Plan recommender.

**API**: `POST /me/journal` with `entry_type: "training"`, `duration_minutes`, and `training_focus` array.

---

### Flow 3: Structured Reflection (The Review Loop)

The data pipeline that turns personal notes into platform intelligence. This is the feature that differentiates GSM from a simple note-taking app.

*   **Step 1 — Internal Reflection:** "What went well?" and "What went wrong?" map to the user's own Skill DNA. Tags are classified into 5 radar axes via `config/skillTaxonomy`:
    *   **Serve**: first_serve, double_faults, ace
    *   **Power**: forehand_winner, backhand_winner
    *   **Net Play**: net_approach, volley
    *   **Stamina**: endurance, fitness
    *   **Mental**: concentration, composure, tiebreak
*   **Step 2 — Opponent Observation:** "Opponent weaknesses?" and "Opponent strengths?" are mapped to the opponent's UID and stored in `scouting/{opponentUid}`. These are anonymous — no reporter identity is ever revealed.
*   **Step 3 — D4 Trigger Pipeline:** When the journal entry is written to Firestore, the D4 trigger fires:
    *   **D4.2:** Maps "went well/wrong" tags to radar axes, increments positive/negative counters on `users/{uid}.skillDna.{sport}`.
    *   **D4.3:** If opponent tags are present, increments counters on `scouting/{opponentUid}`.

**The Compounding Effect:** After 20+ reflections, a user's Skill DNA radar chart becomes a meaningful performance profile. After 50+ community reflections on an opponent, the scouting report becomes genuinely useful ("12 players noted weak backhand under pressure").

---

### Flow 4: North Star Goal

A single active goal that anchors every session with purpose.

*   **Interaction:** User sets a goal from the dashboard (e.g., "Reduce double faults by 20%", "Win 5 matches this month").
*   **Behaviour:** Setting a new goal always overwrites the previous one and resets progress to 0%. Only one active goal at a time.
*   **Display:** Shown prominently on the Tab 2 dashboard as a progress bar with goal text.
*   **Progress Tracking:** Currently manual (user updates progress). Phase 4 may introduce auto-tracking based on journal data patterns.

**API**: `PUT /me/north-star` (set/overwrite), `GET /me/north-star` (retrieve current).

---

### Flow 5: Dashboard Stats (The Habit Engine)

The Tab 2 home screen — designed to reinforce the journaling habit through visible streaks and activity patterns.

*   **7-Day Activity Calendar:** A row of 7 circles (Mon–Sun) showing which days had journal entries. Filled = active, hollow = inactive. Simple visual pressure to "complete the week."
*   **Streak Counter:** Consecutive days with at least one journal entry. The streak is the primary gamification lever — losing a streak hurts.
*   **Aggregate Stats:** Total matches, total wins, total training sessions, win rate percentage. All computed on-read from cached user doc fields (`completedMatches`, `journalRecent`).

**API**: `GET /me/stats` — returns `UserStats` with `weeklyActivity`, `streak`, and aggregate totals.

---

## V. Data Architecture

### Journal Entry Schema

Path: `users/{uid}/journalEntries/{entryId}`. Owner-only subcollection — ownership is enforced implicitly by the Firestore path.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `title` | string | Yes | Entry title (auto-generated or user-provided) |
| `body` | string | Yes | Freeform notes (can be empty string) |
| `tags` | array\<string\> | No | Freeform tags for searchability |
| `createdAt` | timestamp | Yes | UTC timestamp, indexed for pagination |
| `matchId` | string | No | Reference to match doc (null for training entries) |
| `sport` | string (enum) | No | tennis, padel, pickleball |
| `visibility` | string (enum) | Yes | `private`, `friends`, `public` (enforced at API layer) |
| `entryType` | string (enum) | Yes | `match` or `training` (default: `match` for backward compat) |
| `durationMinutes` | number | No | Training session duration (training entries only) |
| `trainingFocus` | array\<string\> | No | Focus pills: serve, volley, footwork, cardio |
| `reflection` | map | No | Structured reflection (match entries only) |
| `reflection.wentWell` | array\<string\> | No | Positive skill tags |
| `reflection.wentWrong` | array\<string\> | No | Negative skill tags |
| `reflection.opponentWeak` | array\<string\> | No | Opponent weakness tags → feeds scouting |
| `reflection.opponentStrong` | array\<string\> | No | Opponent strength tags → feeds scouting |
| `reflection.aiSummary` | string | No | Phase 4: AI-generated reflection summary |
| `scoreText` | string | No | Denormalized score string (e.g., "6-4 7-5") |
| `result` | string (enum) | No | `win`, `loss`, `draw` |

**Indexes:**
- Composite: `(createdAt DESC)` — cursor-based pagination
- The `journalRecent` cache on the user doc stores the 10 most recent entry summaries for zero-query dashboard rendering.

### journalRecent Cache (User Doc)

Path: `users/{uid}.journalRecent`. Array of maps, capped at 10, ordered newest-first. Updated atomically in the same transaction as the journal entry creation.

```json
[
  {
    "entryId": "e_abc",
    "title": "Match vs. Sam",
    "entryType": "match",
    "sport": "tennis",
    "result": "win",
    "createdAt": "2026-03-01T14:00:00Z"
  }
]
```

### North Star Goal (User Doc)

Path: `users/{uid}.northStarGoal`. Map field on the user document.

```json
{
  "goalText": "Win 5 matches this month",
  "progressPct": 0.0,
  "createdAt": "2026-03-01T10:00:00Z",
  "targetDate": "2026-03-31T23:59:59Z"
}
```

---

## VI. API Endpoints Reference

| # | Method | Path | Purpose | Auth |
|---|--------|------|---------|------|
| 1 | GET | `/me/journal` | List journal entries (paginated, cursor-based, newest first) | Bearer (self) |
| 2 | POST | `/me/journal` | Create a journal entry (match or training) | Bearer (self) |
| 3 | GET | `/me/journal/{entry_id}` | Fetch a single journal entry | Bearer (self) |
| 4 | PATCH | `/me/journal/{entry_id}` | Update entry with reflection, tags, or body | Bearer (self) |
| 5 | GET | `/me/stats` | Dashboard stats (weekly activity, streaks, totals) | Bearer (self) |
| 6 | PUT | `/me/north-star` | Set/overwrite the North Star goal | Bearer (self) |
| 7 | GET | `/me/north-star` | Retrieve current North Star goal | Bearer (self) |

### Request/Response Shapes

**POST /me/journal (Match)**
```json
{
  "entry_type": "match",
  "match_id": "m_789",
  "sport": "tennis",
  "title": "Match vs. Sam",
  "body": "",
  "tags": ["competitive"]
}
```

**POST /me/journal (Training)**
```json
{
  "entry_type": "training",
  "sport": "tennis",
  "title": "Serve practice",
  "body": "Focused on kick serve consistency",
  "duration_minutes": 60,
  "training_focus": ["serve", "footwork"]
}
```

**Response: 201 Created**
```json
{
  "entry_id": "e_abc123",
  "created_at": "2026-03-01T14:00:00Z"
}
```

**PATCH /me/journal/{entry_id} (Add Reflection)**
```json
{
  "reflection": {
    "went_well": ["first_serve", "net_approach"],
    "went_wrong": ["double_faults"],
    "opponent_weak": ["backhand"],
    "opponent_strong": ["serve"]
  }
}
```

**GET /me/journal?limit=20&cursor=\<base64\>**
```json
{
  "entries": [
    {
      "entry_id": "e_abc",
      "uid": "user_123",
      "title": "Match vs. Sam",
      "body": "",
      "entry_type": "match",
      "sport": "tennis",
      "match_id": "m_789",
      "score_text": "6-4 7-5",
      "result": "win",
      "reflection": {
        "went_well": ["first_serve"],
        "went_wrong": ["double_faults"],
        "opponent_weak": ["backhand"],
        "opponent_strong": ["serve"],
        "ai_summary": null
      },
      "tags": ["competitive"],
      "visibility": "private",
      "created_at": "2026-03-01T14:00:00Z"
    }
  ],
  "next_cursor": "eyJjcmVhdGVkQXQiOi4uLn0="
}
```

**GET /me/stats**
```json
{
  "weekly_activity": {
    "2026-02-24": true,
    "2026-02-25": false,
    "2026-02-26": true,
    "2026-02-27": true,
    "2026-02-28": false,
    "2026-03-01": true,
    "2026-03-02": false
  },
  "streak": 4,
  "total_matches": 23,
  "total_wins": 15,
  "total_training": 12,
  "win_rate": 0.65
}
```

### Error Responses

| Status | Condition | Detail |
|--------|-----------|--------|
| 400 | Invalid cursor format | "Invalid cursor" |
| 400 | Invalid entry_type or training_focus values | Pydantic validation error |
| 404 | User not found | "User not found" |
| 404 | Journal entry not found (or wrong owner) | "Journal entry 'e_xxx' not found" |
| 422 | Missing required fields | Pydantic validation error |

---

## VII. Cross-Tab Data Flows

### Tab 1 → Tab 2: Match Completion Triggers Journal Prompt
When a match is finalised in Tab 1 and the D2 trigger migrates it to `completedMatches`, the mobile app prompts "Log Match" in Tab 2. The journal entry auto-populates opponent, score, and result from the match doc.

### Tab 2 → Tab 1: Reflection Feeds Scouting
Every MatchReflection saved in Tab 2 maps opponent weakness/strength tags to the opponent's UID. The D4.3 trigger increments counters on `scouting/{opponentUid}`. When a user enters MATCH_SCHEDULED state in Tab 1, the scouting section aggregates this community data.

### Tab 2 → Tab 3: Reflections Feed Skill DNA
Journal reflections trigger D4.2, which maps internal skill tags ("went well/wrong") to radar axes and updates `users/{uid}.skillDna.{sport}`. This powers the Skill DNA radar chart on Tab 3.

### The Flywheel
```
Match completed (Tab 1)
  → User logs match (Tab 2)
    → Reflection tags recorded
      → D4.2: Skill DNA updated (Tab 3 radar)
      → D4.3: Scouting profile updated (Tab 1 scouting)
        → Next match: opponent sees enriched scouting report
          → User journals that match too...
            → Cycle repeats, data compounds
```

---

## VIII. Figma & Technical Specifications

### Visual Aesthetics

*   **Style:** Warm, introspective — differentiated from Tab 1's competitive energy and Tab 3's analytical density.
*   **Primary Background:** `#0A0E12` (Deep Pitch) — consistent across all tabs.
*   **Primary Accent:** `#BFFF00` (Volt Green) — for positive signals ("went well" pills, streak counter, win indicators).
*   **Secondary Accent:** `#FF6B35` (Warm Orange) — for "went wrong" pills and areas needing improvement.
*   **Pill Design:** Rounded capsules (border-radius: 20px) with `#1C2229` background, Volt Green border when selected (positive) or Warm Orange border (negative). Haptic "tick" on selection.
*   **Typography:** Same as Tab 1 (Inter family), but body text uses a slightly larger size (16pt) for readability in journal entries.

### The 3-Tap Rule

*   **Match Log:** Tap "Log Match" → Tap pills → Tap "Save" = 3 taps + pill selections.
*   **Training Log:** Tap "Log Training" → Select focus + duration → Tap "Save" = 3 taps.
*   **View Entry:** Tap journal list item → Full entry view = 1 tap.

### Key UI Components

*   **The Pill Selector:** Horizontal scrollable row of capsule buttons. Multi-select. Grouped by reflection step (went well / went wrong / opponent weak / opponent strong). Each group has its own colour coding.
*   **The Streak Bar:** Horizontal bar at the top of the dashboard showing flame icon + streak count. Animates on increment. Fades to grey when streak is broken.
*   **The Activity Calendar:** 7-circle row (Mon–Sun). Filled circles pulse briefly when a new entry is added for that day.
*   **The Journal List:** Vertical feed of entry cards, newest first. Match entries show opponent name + score + result badge. Training entries show focus pills + duration. Cursor-based infinite scroll.

---

## IX. Implementation Notes

### Transaction Atomicity

Journal entry creation is a single Firestore transaction that:
1. Creates `users/{uid}/journalEntries/{entryId}` with all fields.
2. Prepends a summary to `users/{uid}.journalRecent` (capped at 10, newest-first).
3. If `match_id` is provided, reads the match doc to denormalise opponent name, score, and result into the entry (lenient — missing match doc logs a warning but doesn't block the write).

### Pagination

Cursor-based using `startAfter(createdAt, entryId)`. Cursors are base64-encoded JSON objects containing `createdAt` (ISO 8601) and `entryId`. The client passes the cursor as a query parameter; the API decodes it and passes it to the Firestore query.

### Backward Compatibility

The `entryType` field was added after initial launch. Old entries without this field default to `match`. The `trainingFocus`, `reflection`, `scoreText`, and `result` fields all have `None`/empty defaults. The mapper layer handles missing fields gracefully.

### Scouting Pipeline (D4 Trigger)

The D4 trigger fires on any write to `users/{uid}/journalEntries/{id}`. It:
1. Checks if the entry has a `reflection` with tags (D4.1 qualification).
2. Maps tags to radar axes via `config/skillTaxonomy` and updates `users/{uid}.skillDna.{sport}` (D4.2).
3. If `opponentWeak`/`opponentStrong` tags are present and a `matchId` links to an opponent UID, increments anonymous counters on `scouting/{opponentUid}` (D4.3).

---

## X. Open Questions

1.  **Visibility enforcement:** The `visibility` field (private/friends/public) is stored but not yet enforced in queries. When friend graphs are implemented, journal entries marked `friends` should be visible in social feeds. For now, all entries are effectively private.
2.  **AI Summary (Phase 4):** The `reflection.aiSummary` field is reserved for an AI-generated summary of the reflection (e.g., "Your serve was strong but you lost composure in tiebreaks"). This requires the AI Training Plan infrastructure from Tab 3 Phase 4.
3.  **Score auto-formatting:** The `scoreText` field is currently denormalised from the match doc as a raw string. A score-formatter utility (e.g., "6-4, 7-5" vs. "6-4 7-5") is deferred to a future task.
4.  **Training focus impact on Skill DNA:** Currently only match reflections feed the Skill DNA. Should training logs with focus areas (e.g., "serve", "footwork") also contribute positive signals to the radar? (Recommendation: yes, with a lower weighting — e.g., 0.5x compared to match reflections.)
