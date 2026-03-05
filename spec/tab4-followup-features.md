# Tab 4: THE CLUBHOUSE — Follow-Up Features

**Status**: Parked (post-MVP)  
**Last Updated**: 2026-03-04  
**Related**: `spec/tab4-clubhouse-spec.md` (main spec)

---

## Overview

These features were identified during the Tab 4 gap analysis and explicitly deferred from the MVP scope. Each should be revisited once Tab 4 Phases 1–2 are shipped and validated.

---

## F1. Activity Feed v2 — Dedicated Collection

**Origin**: §4.2 Option B from the gap analysis.

**Context**: The MVP reuses the existing `ticker/{auto}` collection from Tab 3, adding new event types (personal_best, win_streak, tier_crossed). This works for read-only activity cards but has limitations: no social interactions (likes/comments), no per-user personalisation, and a 24-hour TTL that isn't ideal for a social feed.

**What v2 Would Add**:
- New `activityFeed/{region}_{sport}/{eventId}` collection with longer retention (30 days?)
- Per-user feed personalisation (prioritise players you've matched against)
- Social interactions: reactions / likes on feed events
- Follow/friend system to curate whose activity you see
- Push notifications for friends' milestones

**Prerequisites**: Tab 4 MVP shipped, user engagement data to validate that Local Pulse drives retention.

**Estimated Scope**: Full spec + 2–3 sprints of backend + iOS work.

---

## F2. League Win Events in Feed

**Origin**: §2.2 item 5 from the gap analysis.

**Context**: The MVP feed includes events generated from match confirmations (personal bests, streaks, tier crossings, upsets). League completion events ("Sarah K. won the South London City Slam League!") require a different trigger — they fire when a league's status transitions to `completed` and a winner is determined.

**What This Would Add**:
- New trigger (or D3 extension) on `leagues/{leagueId}` status change to `completed`
- Write a `league_win` event to the ticker collection
- Determine winner from league member stats (highest wins, or custom league rules)
- Feed card with league name, sport, winner name

**Prerequisites**: League completion flow fully implemented and tested. Tab 4 Phase 2 (feed) live.

**Estimated Scope**: S–M (1–2 days) once league completion is stable.

---

## F3. Charity / Ball Donation Flow ("Give Back")

**Origin**: §4.3 from the gap analysis. Deferred until a charity partner and payment model are confirmed.

**Context**: The draft describes a gamified slider for donating cans of balls to youth programmes. This requires real-money transactions, a charity partner, and legal/compliance considerations.

**Open Questions (to resolve before speccing)**:
- Who is the charity partner? Local youth programmes per region, or a single global partner?
- Payment model: real currency via Stripe/IAP, or "GSM Credits" earned through play?
- Tax receipts / donation confirmations required?
- Is there a minimum donation? Maximum?
- Does the app take a fee, or is 100% passed through?
- Regulatory requirements per country (charity solicitation laws vary)?

**What This Would Add**:
- `donations/{donationId}` collection (user, amount, charity, timestamp)
- `users/{uid}.donationStats` denormalised totals (lifetime balls donated, current month)
- `POST /me/clubhouse/donate` endpoint
- Payment gateway integration (Stripe / Apple IAP)
- Donation milestone events in the activity feed
- Donation slider + impact tracker SwiftUI component
- Donation leaderboard (optional gamification)

**Prerequisites**: Charity partner confirmed, payment model decided, legal review.

**Estimated Scope**: 2+ sprints (heavily depends on payment integration).

---

## F4. Social Groups / "The 3000 Club"

**Origin**: §4.4 from the gap analysis. Tier-gated social groups mentioned in the Hormozi strategy.

**Context**: The draft references "The 3000 Club" — exclusive groups for Advanced-tier players. This is essentially a social networking layer (groups, membership, content/chat) that would be a major product vertical on its own.

**What This Would Add**:
- Group/club data model (`clubs/{clubId}`, members subcollection)
- Tier-based access control (auto-qualify based on `rankings.{sport}.tier`)
- Group activity feed or chat
- Club badges on the Athlete Card
- Club leaderboards

**Prerequisites**: Tab 4 MVP shipped, clear product vision for what "group activity" means (chat? shared feed? events?).

**Estimated Scope**: Full PRD + 3–4 sprints minimum. Should be treated as its own product initiative.

---

## F5. Activity Feed v2 — Broader Scope Enhancements

**Origin**: Collected from various gap analysis observations.

**Potential additions once the MVP feed is validated**:
- Training streak events from Tab 2 (e.g., "7-day training streak!")
- Community milestone events (e.g., "Athens region reached 500 matches this month!")
- Re-match suggestions in the feed ("You and Alex played 3 close matches — challenge again?")
- Seasonal highlights / year-in-review cards

---

## Tracking

| ID | Feature | Blocked By | Priority |
|----|---------|------------|----------|
| F1 | Activity Feed v2 (dedicated collection) | Tab 4 Phase 2 shipped | Medium |
| F2 | League win events in feed | League completion flow stable | Low |
| F3 | Charity / Give Back | Charity partner + payment model | Low |
| F4 | Social Groups / The 3000 Club | Own PRD needed | Low |
| F5 | Broader feed enhancements | Tab 4 Phase 2 shipped | Low |
