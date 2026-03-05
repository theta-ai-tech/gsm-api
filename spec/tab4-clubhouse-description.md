# Tab 4: THE CLUBHOUSE — Product Spec (Pre-Functional)

**Version**: 0.1 (Draft)  
**Status**: Decisions captured, open questions pending — functional spec to follow  
**Last Updated**: 2026-03-04  
**Related**: `spec/tab4-clubhouse-followup.md` ([follow-up features](./tab4-clubhouse-followup.md))  
**Source PRD**: Tab 4 Clubhouse DRAFT (project knowledge)

---

## 1. Purpose

Tab 4 is the social and community layer of the GSM ecosystem. While Tabs 1–3 cover Execution, Improvement, and Analytics, Tab 4 is the reward — the digital lounge where players flex their wins, check the local scene, and engage with the community. The strategic goal is social proof, community retention, and gamified engagement.

This document captures the product decisions made during the gap analysis against the Functional Tab Spec v1.2 and existing codebase. It serves as the bridge between the original PRD and the full functional spec (state machine, endpoints, data models, sequence diagrams) that will be written next.

---

## 2. Resolved Decisions

### 2.1 Terminology & Display

| Decision | Resolution | Impact |
|----------|-----------|--------|
| **Levels vs. Tiers** | Use the existing **4-tier system** (Amateur, Intermediate, Advanced, Competitive). No granular levels. The Athlete Card displays tier name + point total. | No new data model. Reads existing `rankings.{sport}.tier` and `rankings.{sport}.pts`. |
| **"GSM Point Stock" label** | Drop the "Stock" terminology. UI will display points naturally (e.g., "3,600 pts"). Fix at design time, no backend impact. | UI-only. |
| **"The 3000 Club" / tier-gated groups** | **Deferred** — tracked as a separate future feature. Not in Tab 4 MVP scope. | See [F4 in follow-up features](./tab4-clubhouse-followup.md#f4-social-groups--the-3000-club). |

### 2.2 Data & Backend

| Decision | Resolution | Impact |
|----------|-----------|--------|
| **Win streaks** | Introduce streak tracking on the user doc: `currentStreak` and `bestStreak` per sport under `rankings.{sport}`. Updated during match confirmation transaction. | New fields on user doc. Extends the scoring engine transaction (SE-5). |
| **Personal bests** | Add a `personalBest` field to `rankings.{sport}` (highest pts ever reached). Updated inline during match confirmation when new pts > existing personal best. | New field on user doc. Minor addition to scoring transaction. |
| **League win events** | **Follow-up** — not MVP. Will be added once the league completion flow is stable. | See [F2 in follow-up features](./tab4-clubhouse-followup.md#f2-league-win-events-in-feed). |

### 2.3 Architecture

| Decision | Resolution | Impact |
|----------|-----------|--------|
| **Local Pulse feed** | **MVP: Extend the existing `ticker` collection** (from Tab 3) with new event types: `personal_best`, `win_streak`, `tier_crossed`. Tab 3 reads upset events; Tab 4 reads all event types with sport + region filters. | No new collection. New event types written during match confirmation. |
| **Activity Feed v2** | **Tracked as follow-up** — dedicated `activityFeed` collection with social interactions, longer retention, and personalisation. Only if MVP feed validates the retention hypothesis. | See [F1 in follow-up features](./tab4-clubhouse-followup.md#f1-activity-feed-v2--dedicated-collection). |
| **Charity / Give Back** | **Deferred** entirely. No backend work until a charity partner and payment model are confirmed. | See [F3 in follow-up features](./tab4-clubhouse-followup.md#f3-charity--ball-donation-flow-give-back). |

---

## 3. MVP Scope

Tab 4 MVP consists of two phases, both dependent on Tab 3 Phase 1 (scoring engine) being live.

### Phase 1: Athlete Card & Profile

The user's digital identity card, assembled from existing cached data.

**Components**:
- Avatar with tier-coloured ring (Volt Green for active)
- Tier badge (e.g., "ADVANCED") + point total (e.g., "3,600 pts")
- Sport selector (tennis / padel / pickleball) if the user has rankings in multiple sports
- Tap → Athlete Resume overlay: aggregated view of achievements (personal bests, best streak, completed matches count, leagues completed)

**Data sources** (all existing, no new backend):
- `users/{uid}.rankings.{sport}` — tier, pts, globalRanking
- `users/{uid}.rankings.{sport}.personalBest` — **new field** (added as part of this work)
- `users/{uid}.rankings.{sport}.bestStreak` — **new field**
- `users/{uid}.completedMatches` — existing cache
- `users/{uid}.leaguesCompleted` — existing cache

**Sharing**: Athlete Card can be shared via native iOS share sheet (UIActivityViewController) with a styled card image rendered client-side.

### Phase 2: Local Pulse Activity Feed

A regional activity feed showing milestones from nearby players.

**Event types** (written to `ticker/{auto}`):

| Event Type | Trigger | Written By |
|------------|---------|------------|
| `upset` | Winner tier < loser tier | Match confirmation transaction (already exists from Tab 3) |
| `personal_best` | New pts > existing personalBest | Match confirmation transaction (new) |
| `win_streak` | currentStreak reaches 3, 5, 10, etc. | Match confirmation transaction (new) |
| `tier_crossed` | tierAfter ≠ tierBefore | Match confirmation transaction (new) |

**Read endpoint**: `GET /lab/ticker?region={region}&sport={sport}&types=all` (extend existing ticker endpoint with optional `types` filter, or add a new `/clubhouse/feed` endpoint — to be decided in functional spec).

**Regional scoping**: Same region resolution as leaderboards — derived from `users/{uid}.preferences.area` via `config/regions`.

---

## 4. Open Questions for Product

These must be resolved before the functional spec is written.

### OQ-1: Sharing Infrastructure

The draft mentions "Share to Instagram Story" multiple times (Athlete Card, feed events, Athlete Resume). Questions:

- **Is native iOS sharing (UIActivityViewController) sufficient for MVP?** This would let users share to any app (Instagram, WhatsApp, etc.) via the system share sheet, with a styled image.
- **Or do we need a dedicated "Instagram Story" integration?** Instagram has a specific API for story sharing with custom stickers. This is more work but more polished.
- **Is the share image rendered client-side (SwiftUI → image) or does the backend generate it?** The existing `ShareCardData` model in `api/app/models/share.py` is documented as client-only. Do we keep it that way?

**Recommendation**: Native iOS share sheet for MVP. Instagram-specific integration as a follow-up if sharing metrics warrant it.

### OQ-2: Athlete Resume — Scope & Data

The draft says tapping the tier badge opens an "Athlete Resume" — a shareable list of all achievements. Questions:

- **What exactly appears on the resume?** Proposed list: personal best per sport, best win streak, total matches played, total wins, leagues completed, biggest upset (beat someone X pts above). Is this sufficient, or do we want specific "badges" (e.g., "First Win", "10-Match Streak", "Tier-Up")?
- **Is this computed on-the-fly from existing cached data, or do we need an `achievements` collection?** On-the-fly is simpler but limits us to stats. A collection enables unlock-style badges with timestamps.
- **Is the resume shareable as a single image, or is it an interactive overlay only?**

**Recommendation**: On-the-fly computation from cached data for MVP. Define a fixed list of "stat rows" (not dynamic badges). Shareable as an image via the same sharing mechanism as OQ-1.

### OQ-3: Feed Privacy & Visibility

- **Can users see activity from players they've never matched against?** The draft implies a geographic feed (all local activity), not a social-graph feed (only people you know).
- **Can a user opt out of appearing in the Local Pulse?** Some users might not want their losses or streaks broadcast.
- **Are player names shown in full, or abbreviated?** The draft shows "Mans L." and "Sarah K." (first name + last initial) — is this the standard?

**Recommendation**: Geographic feed scoped by region (same as leaderboards). Opt-out toggle in user preferences. First name + last initial for privacy.

### OQ-4: Streak Milestones

- **Which streak milestones trigger a feed event?** Every win? Or only at thresholds (3, 5, 10, 15, 20...)?
- **Does a loss reset the streak entirely, or do we track "best streak in last 30 days"?**
- **Are streaks per-sport or across all sports?**

**Recommendation**: Feed events at thresholds (3, 5, 10, 20). Loss resets `currentStreak` to 0; `bestStreak` is all-time per sport.

### OQ-5: Empty States

- **Brand-new user with zero matches**: What does the Clubhouse show? A prompt to play their first match? A static illustration?
- **Region with no recent activity**: What does Local Pulse show? "No activity yet — be the first!" or activity from a wider region?

---

## 5. Dependency Chain

```
Tab 3 Phase 1: Scoring Engine (SE-1 → SE-15)
  │  Must be live — provides pts, tiers, pointHistory
  │
  ├─► Tab 4 Phase 1: Athlete Card
  │     Adds: personalBest, currentStreak, bestStreak fields
  │     Reads: rankings, completedMatches, leaguesCompleted
  │
  └─► Tab 4 Phase 2: Local Pulse Feed
        Extends: ticker collection with new event types
        Extends: match confirmation transaction with feed event writes
        Depends on: Phase 1 fields (personalBest, streaks)
```

---

## 6. Next Steps

1. **Product owner resolves OQ-1 through OQ-5** (this document).
2. **Write the Tab 4 functional spec** following the same structure as Tabs 1–3 in the Functional Tab Spec v1.2:
   - State machine (empty state, loading, populated, etc.)
   - API endpoints table
   - Data models table (new fields + extended collections)
   - Trigger modifications (match confirmation extensions)
   - Sequence diagrams (Mermaid)
   - Cross-tab integration updates
3. **Create GitHub issues** from the phased plan, following the SE-/LAB- naming convention (proposed: `CH-1` through `CH-N`).
4. **Update Functional Tab Spec v1.2** to v1.3 with Tab 4 as a new section.
