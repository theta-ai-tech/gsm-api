# GSM MVP Backend Review and Sprint Roadmap

**Date:** 2026-04-24  
**Author:** Codex  
**Scope reviewed:** `spec/`, `../docs/product/`, `.agent/SPRINT.md`, `.agent/ROADMAP.md`, current open GitHub issues

---

## 1. Executive Summary

The backend is no longer in broad discovery mode. The core singles match loop is already in place, Tab 2 and Tab 3 are substantially built, Tab 4 MVP backend work appears effectively in place, and the recent Venue epic closed most of the location foundation needed for launch.

What remains is concentrated and launch-critical:

1. Finish the venues surface cleanly.
2. Ship doubles end-to-end.
3. Ship leagues browse/join/detail end-to-end.
4. Add release-hardening work that is currently underrepresented in the backlog.

The strongest planning conclusion is this:

- If the product requirement is truly **padel-first launch**, then **Doubles must move ahead of Leagues** on the critical path.
- The amended roadmap now reflects that ordering, while still keeping Leagues in MVP.

### Delivery estimate

- **Aggressive backend MVP finish:** **7 weekly sprints**, ending **2026-06-14**
- **Stakeholder-safe backend MVP finish:** **8 weekly sprints**, ending **2026-06-21**

The 7-sprint path assumes:

- 5-6 issues per sprint
- no major rework from product decisions
- no additional MVP features added beyond the current issue set
- mobile starts integrating before backend completion

The 8-sprint path is the safer one for launch review because it leaves space for issue cleanup, late hardening, and stakeholder sign-off fixes.

---

## 2. Inputs Reviewed

### Planning and sprint sources

- `.agent/SPRINT.md`
- `.agent/ROADMAP.md`
- current open GitHub issues

### Repo specs

Note: the repo uses `spec/`, not `specs/`.

- `spec/leagues-gap-analysis.md`
- `spec/tab1-play-payloads.md`

### Product docs

- `../docs/product/functional-tab-spec-v1.4.md`
- `../docs/product/tab1-play-description.md`
- `../docs/product/tab2-improve-description.md`
- `../docs/product/tab3-lab-description.md`
- `../docs/product/tab4-clubhouse-description.md`
- `../docs/product/tab4-clubhouse-followup.md`

### GitHub issue inventory

Open MVP-labelled issues currently total **38**.

That number is slightly misleading:

- `#159 VEN-2` still shows as open in GitHub even though Sprint 6 marks it done and merged.
- the issue set now also includes the launch-support backlog created during this planning pass: `#271` through `#280`.

Practical planning count:

- **37 practical MVP work items**
- `#159` remains a GitHub hygiene cleanup item rather than real remaining scope

---

## 3. Where We Are Now

## 3.1 What is already in good shape

### Tab 1 PLAY

- Core singles matchmaking flow is already present: broadcast, offers, `/me/state`, match scheduling, score submission, confirmation, and scoring flow.
- Venue foundation is mostly done through Sprint 6:
  - `VEN-1` through `VEN-6` were delivered in Sprint 6
  - `venueRef` now exists across the core play flow

### Tab 2 IMPROVE

- Journal, post-match reflection, north-star concept, and dashboard/stats are already defined and appear substantially built enough for MVP support.
- No remaining MVP-labelled backend issues are currently concentrated here.

### Tab 3 THE LAB

- Scoring engine, progression, leaderboard, and ticker infrastructure are already the backbone for later features.
- Tab 3 is now mainly a dependency provider for Tab 4 and doubles scoring rather than the critical path itself.

### Tab 4 THE CLUBHOUSE

- The MVP direction is already narrowed and the major backend pieces appear in place.
- Follow-up features are explicitly deferred:
  - Activity Feed v2
  - league win feed events
  - charity flow
  - social groups / "3000 Club"

This is good news for planning: Tab 4 is not where the next sprint pressure sits.

---

## 3.2 What is not done

### Venues

Remaining tracked venue work:

- `#164 VEN-7` `POST /venues/suggest`

Additional venue work now ticketed:

- `#271 VEN-8` `GET /venues?sport={sport}&area={area}`

### Doubles

Open doubles MVP issues:

- `#165 DBL-1`
- `#166 DBL-2`
- `#167 DBL-3`
- `#168 DBL-4`
- `#169 DBL-5`
- `#170 DBL-6`
- `#171 DBL-7`
- `#172 DBL-8`
- `#173 DBL-9`
- `#175 DBL-10`

### Leagues

Open league MVP issues:

- `#248` through `#263` inclusive

Leagues are the largest remaining body of work, but not the only critical stream.

---

## 4. What the MVP Should Entail

Based on the issue labels plus the functional/product specs, the backend MVP should be considered complete only when all of the following are true.

### 4.1 Core launch loop

- A player can discover or create a match opportunity.
- A player can play **tennis and padel**.
- A player can attach or inherit a venue where relevant.
- A player can complete a match, score it, confirm it, and see the resulting ranking/state updates.

### 4.2 Padel-first launch requirements

The product spec is explicit here:

- venue support is required for padel-first launch
- doubles support is required for padel-first launch

That means the launch-critical path is not just "finish leagues."  
It is:

1. venues complete
2. doubles complete
3. leagues complete, if the GitHub `mvp` label remains authoritative

### 4.3 Supporting tabs for launch

The MVP backend should also support:

- Tab 2 post-match journaling
- Tab 3 scoring, progression, leaderboard, ticker
- Tab 4 athlete card + local pulse feed on top of the existing ticker model

These appear far closer to done than the remaining Tab 1 gaps.

### 4.4 What is explicitly not MVP

The following should stay out of the launch path:

- Activity Feed v2 dedicated collection
- league win events in the feed
- charity / donation flow
- social groups / gated clubs
- Phase 4 AI / premium Lab features

---

## 5. Remaining MVP Work by Stream

| Stream | Status | Remaining work | Notes |
|---|---|---:|---|
| Venues | Mostly complete | 2 issues | `POST /venues/suggest` and curated venues read endpoint are both now ticketed |
| Doubles | Not started | 10 issues | Critical for padel-first launch |
| Leagues | Partially scaffolded | 16 issues | Biggest single stream; browse/join/detail still absent |
| Launch readiness | Now ticketed | 9 issues | Telemetry, notification contract, smoke, seed/demo data, operator playbook, contract freeze |

### Remaining MVP work items

- Venues: **2**
- Doubles: **10**
- Leagues: **16**
- Launch readiness: **9**
- Practical total: **37**

---

## 6. Critical Planning Conclusions

## 6.1 Doubles should move ahead of leagues

Current planning artifacts are not fully aligned with the product requirement.

Why:

- `functional-tab-spec-v1.4.md` says doubles is required for padel-first launch.
- Leagues remain MVP, but the implementation order still needs Doubles first.

Recommendation:

- **Reorder the next sprint sequence to complete Doubles before Leagues.**

Without doubles, the mobile app cannot honestly launch a padel-first experience even if league browse exists.

## 6.2 Leagues are the biggest scope block

Leagues have the highest issue count and the heaviest API + testing + documentation tail:

- schema
- models
- repo
- service
- router
- five endpoints
- tests
- docs

This is the stream most likely to create spillover if it is left too late.

## 6.3 The backlog now includes the missing venue and launch-support work

During this planning pass, the missing curated venues issue and the launch-support issues were created:

- `#271 VEN-8`
- `#272 DOC-1`
- `#273 OPS-2`
- `#274 OPS-1`
- `#275 SMK-2`
- `#276 SMK-1`
- `#277 NTF-1`
- `#278 OBS-3`
- `#279 OBS-2`
- `#280 OBS-1`

## 6.4 The planning artifacts need cleanup

- `.agent/ROADMAP.md` is stale and still shows venue items as planned even though Sprint 6 marks them done.
- `.agent/ROADMAP.md` duplicates the Doubles section.
- GitHub issue `#159` appears open although Sprint 6 shows it merged.

This is not just cosmetic. It weakens sprint planning confidence for stakeholders.

---

## 7. Proposed Sprint Plan

Assumption: weekly sprints, Monday to Sunday, starting with **Sprint 8 on 2026-04-27**.

### Issue Summary by Sprint

- Sprint 8: `#164, #271, #165, #166, #167, #280`
- Sprint 9: `#168, #169, #170, #171, #172, #173`
- Sprint 10: `#175, #248, #249, #250, #277`
- Sprint 11: `#251, #252, #253, #254, #279`
- Sprint 12: `#255, #256, #257, #258, #260`
- Sprint 13: `#259, #261, #262, #263, #278`
- Sprint 14: `#272, #274, #275, #276, #273`

## 7.1 Sprint 8: Finish venues and establish doubles foundations

**Dates:** 2026-04-27 to 2026-05-03  
**Target load:** 6 items  
**Sprint 8:** `#164, #271, #165, #166, #167, #280`

1. `#164 VEN-7` `POST /venues/suggest`
2. `#271 VEN-8` `GET /venues?sport={sport}&area={area}`
3. `#165 DBL-1` enums + `ParticipantEntry`
4. `#166 DBL-2` match document model
5. `#167 DBL-3` broadcast model
6. `#280 OBS-1` telemetry schema

**Outcome:** Venue API surface is complete, doubles data contracts exist, and launch telemetry has a defined schema.

## 7.2 Sprint 9: Ship the doubles match lifecycle

**Dates:** 2026-05-04 to 2026-05-10  
**Target load:** 6 items  
**Sprint 9:** `#168, #169, #170, #171, #172, #173`

1. `#168 DBL-4` offer + acceptance flow
2. `#169 DBL-5` score logging
3. `#170 DBL-6` scoring engine extension
4. `#171 DBL-7` `/me/state` doubles payloads
5. `#172 DBL-8` discovery feed doubles badges/filter
6. `#173 DBL-9` D-series trigger updates

**Outcome:** The padel-first doubles flow exists end-to-end in backend logic.

## 7.3 Sprint 10: Lock doubles and start league foundations

**Dates:** 2026-05-11 to 2026-05-17  
**Target load:** 5 items  
**Sprint 10:** `#175, #248, #249, #250, #277`

1. `#175 DBL-10` doubles integration tests
2. `#248 LG-1` league schema fields
3. `#249 LG-2` league models + enums
4. `#250 LG-3` Firestore indexes
5. `#277 NTF-1` notification intent contract

**Outcome:** Doubles is hardened and leagues become a real implementation stream while notifications get a launch contract.

## 7.4 Sprint 11: League service layer and browse API

**Dates:** 2026-05-18 to 2026-05-24  
**Target load:** 5 items  
**Sprint 11:** `#251, #252, #253, #254, #279`

1. `#251 LG-4` repo filtering + member count
2. `#252 LG-5` league join service
3. `#253 LG-6` standings computation
4. `#254 LG-7` `GET /leagues`
5. `#279 OBS-2` telemetry for broadcast + offer lifecycle

**Outcome:** League browsing has its repo/service base and the early funnel starts emitting telemetry.

## 7.5 Sprint 12: League detail and join endpoints

**Dates:** 2026-05-25 to 2026-05-31  
**Target load:** 5 items  
**Sprint 12:** `#255, #256, #257, #258, #260`

1. `#255 LG-8` `GET /leagues/{leagueId}`
2. `#256 LG-9` `GET /leagues/{leagueId}/standings`
3. `#257 LG-10` `POST /leagues/{leagueId}/join`
4. `#258 LG-11` `GET /leagues/{leagueId}/matches`
5. `#260 LG-13` seed data update

**Outcome:** Mobile can consume the full core league read/join surface.

## 7.6 Sprint 13: League hardening and completion telemetry

**Dates:** 2026-06-01 to 2026-06-07  
**Target load:** 5 items  
**Sprint 13:** `#259, #261, #262, #263, #278`

1. `#259 LG-12` move placeholder routes out of `main.py`
2. `#261 LG-14` unit tests
3. `#262 LG-15` integration tests
4. `#263 LG-16` docs update
5. `#278 OBS-3` telemetry for match completion + confirmation lifecycle

**Outcome:** League MVP backend is complete and the post-match lifecycle becomes measurable.

## 7.7 Sprint 14: Launch support wrap-up

**Dates:** 2026-06-08 to 2026-06-14  
**Target load:** 5 items  
**Sprint 14:** `#272, #274, #275, #276, #273`

1. `#272 DOC-1` mobile contract freeze
2. `#274 OPS-1` launch-ready Athens demo data
3. `#275 SMK-2` venue + confirmation smoke
4. `#276 SMK-1` doubles lifecycle smoke
5. `#273 OPS-2` operator playbook

**Outcome:** The backend is launch-ready for mobile integration, demos, and operational use.

---

## 8. MVP Finish Date

### Aggressive target

- **Backend MVP complete by 2026-06-14**

This is realistic only if:

- the current sprint allocation largely holds
- doubles is prioritised ahead of leagues
- sprint spillover stays low
- no new MVP scope is introduced

### Safer stakeholder target

- **Backend MVP review-ready by 2026-06-21**

Use this if you want one extra sprint for:

- tracker and issue cleanup
- stakeholder sign-off fixes

Recommendation:

- Use **2026-06-14** as the internal build target.
- Use **2026-06-21** as the external stakeholder-safe target.

---

## 9. Mobile App and Marketing Timing

## 9.1 Mobile app

The mobile app does **not** need to wait for every backend issue to finish before work starts.

Recommended mobile timing:

- **Start mobile shell and current completed tabs immediately**
  - auth
  - Tab 2 surfaces
  - Tab 3 dashboard/ticker
  - Tab 4 athlete card / local pulse
- **Begin Tab 1 padel integration after Sprint 9**
  - by then doubles contracts, `/me/state` payloads, and venue flows should be sufficiently real
- **Begin leagues mobile integration after Sprint 11**
  - browse/join/detail should exist by then

Practical interpretation:

- **mobile implementation can begin during the backend program**
- **mobile feature-complete launch should wait for backend MVP completion**

## 9.2 Marketing

Marketing also should not wait until the very end to begin.

Recommended marketing timing:

- **Sprint 9 onward:** waitlist, landing page, founder story, Athens padel positioning, content capture
- **Sprint 10 onward:** beta recruitment and partner conversations, because the padel core loop should be demoable
- **After Sprint 13 or Sprint 14:** active launch push, because the MVP backend should then be stable enough to support real users

The most useful sequencing is:

1. finish doubles and venue completion
2. demo the real padel flow
3. start beta marketing
4. complete leagues and release hardening
5. launch

---

## 10. Missing Gaps

These are the most important gaps surfaced by the review.

## 10.1 Product / roadmap alignment gap

**Gap:** current roadmap order does not match padel-first launch requirements.

**Fix:** re-prioritise Doubles ahead of Leagues.

## 10.2 Planning artifact drift

**Gap:** `.agent/ROADMAP.md` was stale and partly inaccurate before this update.

**Fix:** keep the sprint allocation and issue statuses aligned in one place as the backlog moves.

## 10.3 GitHub issue hygiene

**Gap:** `#159` appears open even though Sprint 6 marks it done and merged.

**Fix:** close or reconcile stale issue state before next sprint planning.

## 10.4 Launch-support sequencing gap

**Gap:** the support issues now exist, but they still need to be protected from constant spillover behind feature work.

**Fix:** keep `#272` through `#280` explicitly assigned to Sprint 8, 10, 11, 13, and 14 rather than leaving them as generic cleanup.

---

## 11. Recommended Stakeholder Decision

The cleanest plan is:

1. Accept that the current backend critical path is **Venues -> Doubles -> Leagues**
2. Reorder the roadmap so Doubles comes before Leagues
3. Keep Leagues in MVP and sequence them across Sprint 10 through Sprint 13
4. Treat **2026-06-14** as the build target and **2026-06-21** as the safe launch-readiness target
5. Start mobile implementation during the backend program, not after it
6. Start marketing in staged form once the doubles + venues demo loop is real

---

## 12. Questions for Review

These are the questions I would put in front of humans/stakeholders when reviewing this document:

1. Are we comfortable keeping **Doubles ahead of Leagues** in implementation order while both remain in MVP?
2. Is the first mobile client **iOS only**, or is a second client expected in the same launch window?
3. Do we want a dedicated **Sprint 15** as an extra stakeholder buffer, or is Sprint 14 enough if the allocation holds?
