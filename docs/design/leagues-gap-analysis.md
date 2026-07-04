# League Endpoint Gap Analysis

> ⚠️ **Design / decision record — non-canonical.** This document captures intent and history and is *not* kept in lockstep with the code. For current behavior, defer to the canonical docs under [`../README.md`](../README.md).

**Date**: 2026-04-09
**Author**: gsm-tpm
**Status**: Draft — pending product decisions
**Target**: Sprint 7+ (after current Sprint 6 / Venue epic)

---

## 1. What Already Exists

The league infrastructure is partially built. The data model, triggers, and read-side plumbing are in place. The write-side API layer and the two PRD screens (PL-L1, PL-L2) are not.

### 1.1 Data Model (Complete)

| Artifact | Path | Status |
|----------|------|--------|
| `leagues/{leagueId}` collection | `docs/data/data-dictionary.md` lines 397-410, 466-479 | Fully defined: name, sport, season, status, ownerUid, meta |
| `leagues/{leagueId}/members/{uid}` subcollection | `docs/data/data-dictionary.md` lines 412-525 | Fully defined: role, status, joinedAt, stats |
| League enums | `api/app/models/enums.py` lines 25-41 | `LeagueStatusEnum` (active/completed/upcoming), `LeagueRoleEnum` (player/admin/captain), `LeagueMemberStatusEnum` (active/left/banned) |
| `League` Pydantic model | `api/app/models/league.py` | Fields: league_id, name, sport, season, status, owner_uid, meta |
| `LeagueMember` Pydantic model | `api/app/models/league.py` | Fields: uid, role, status, joined_at, stats |
| `LeagueSummary` model | `api/app/models/common.py` lines 66-71 | Cache model: league_id, name, sport, status, role |
| User league caches | `docs/data/data-dictionary.md` lines 100-101 | `leaguesActive[]` and `leaguesCompleted[]` on user docs (cap 20) |
| Composite indexes | `docs/data/data-dictionary.md` lines 437-438 | League match indexes declared: `leagueId + status + scheduledAt/finishedAt` |

### 1.2 Repository Layer (Partial)

| Artifact | Path | Status |
|----------|------|--------|
| `LeaguesRepo.get_by_id()` | `api/app/repos/leagues_repo.py` | Reads single league doc |
| `LeaguesRepo.list_members()` | `api/app/repos/leagues_repo.py` | Lists members ordered by joinedAt (cap 200) |
| `MatchesRepo.list_upcoming_for_league()` | `api/app/repos/matches_repo.py` lines 68-82 | League match query (upcoming, paginated) |
| `MatchesRepo.list_completed_for_league()` | `api/app/repos/matches_repo.py` lines 83-95 | League match query (completed, paginated) |
| `UsersRepo.get_leagues_by_status()` | `api/app/repos/users_repo.py` lines 28-32 | Reads active/completed league summaries from user doc |
| Mappers | `api/app/repos/mappers.py` | `to_league()`, `to_league_member()`, `_parse_league_summary()` all implemented |

### 1.3 Triggers (Complete)

| Trigger | Path | Status |
|---------|------|--------|
| D3.1 — league member upsert | `functions/league_triggers/on_league_member_write.py` | Upserts league summary into user doc on member write |
| D3.2 — league member removal | `functions/league_triggers/on_league_member_write.py` | Removes league summary from user doc on leave/ban/delete |
| D5.2 — league member stats | `functions/scoring_triggers/league_member_stats.py` | Increments wins/losses on league member doc after match completion |

### 1.4 Auth & Security (Complete)

| Artifact | Path | Status |
|----------|------|--------|
| `RoleService` | `api/app/services/role_service.py` | `is_league_member()`, `get_league_member_role()`, `get_league_owner_uid()` |
| `require_league_member()` dependency | `api/app/security.py` lines 84-96 | Factory for route-level league auth |
| `require_membership()` helper | `api/app/security.py` lines 56-81 | Resolution: global role -> owner -> member doc -> 403 |

### 1.5 Existing Endpoints (Placeholder Only)

| Endpoint | Path | Status |
|----------|------|--------|
| `POST /leagues/{league_id}/members` | `api/app/main.py` lines 174-184 | Placeholder — returns stub JSON, does NOT write to Firestore |
| `DELETE /leagues/{league_id}/members/{uid}` | `api/app/main.py` lines 187-199 | Placeholder — returns stub JSON, does NOT delete from Firestore |

### 1.6 Seed Data (Complete)

Three sample leagues exist in `tools/seed_data.py`: `padel-local-2025` (active), `tennis-local-2025` (upcoming), `tennis-completed-2024` (completed). League members and league-tagged matches are seeded and used in integration tests.

### 1.7 No Existing Router

There is no `api/app/routers/leagues.py`. The two placeholder endpoints live directly in `main.py`. There is no league service layer (`api/app/services/league_service.py` does not exist).

---

## 2. What Is Missing

Mapped against the two PRD screens (PL-L1 League Browser, PL-L2 My League View).

### 2.1 Schema Gaps

| Gap | Detail | Impact |
|-----|--------|--------|
| **No `region` field on leagues collection** | PRD specifies `GET /leagues?region=athens&sport=padel&status=open`. The `leagues/{leagueId}` schema has no `region` field. | Cannot filter leagues by region without adding this field + a composite index. |
| **No `maxPlayers` / `currentPlayers` fields** | PRD shows "8 / 12 spots filled" progress bar. No capacity tracking exists on league docs. | Need `maxPlayers` (int) and either `currentPlayers` (denormalized counter) or compute from member count at read time. |
| **No `startDate` / `endDate` fields** | PRD shows "8 weeks - Starts May 1". No scheduling fields exist on league docs. | Need `startDate` and `duration` or `endDate` for display. |
| **No `tier` / `skillLevel` field** | PRD shows "Intermediate - Padel" on league cards. No skill-level field exists. | Need a tier or skill-level field for display and optional filtering. |
| **No `open` status in `LeagueStatusEnum`** | PRD filters by `status=open`. Current enum has: `active`, `completed`, `upcoming`. "Open for registration" is not represented. | **Product decision required**: is "open" a separate status, or does "upcoming" mean "open for registration"? |

### 2.2 Endpoint Gaps

| # | Endpoint | PRD Screen | Status |
|---|----------|------------|--------|
| 1 | `GET /leagues` (browse/filter) | PL-L1 | **Does not exist.** No league listing endpoint at all. |
| 2 | `POST /leagues/{leagueId}/join` | PL-L1 | **Does not exist.** Self-serve join flow has no endpoint. The existing `POST /leagues/{league_id}/members` is admin-only and a stub. |
| 3 | `GET /leagues/{leagueId}` (detail) | PL-L2 | **Does not exist.** `LeaguesRepo.get_by_id()` exists in the repo but is not exposed via any route. |
| 4 | `GET /leagues/{leagueId}/standings` | PL-L2 | **Does not exist.** No standings computation logic exists. Must derive from `members/{uid}.stats` (wins/losses). |
| 5 | `GET /leagues/{leagueId}/matches` | PL-L2 (schedule) | **Does not exist as a route.** `MatchesRepo.list_upcoming_for_league()` exists in the repo but is not exposed. |

### 2.3 Service Layer Gaps

| Gap | Detail |
|-----|--------|
| No `LeagueService` | No business logic layer for league operations (join, leave, browse, standings computation). |
| No standings computation | Standings must be derived from member stats (wins, losses, points). No sorting/ranking logic exists. |
| No join flow validation | Self-serve join needs: capacity check, duplicate check, status check (league must be open/upcoming), optional skill-level gating. |

### 2.4 Router Gap

No `api/app/routers/leagues.py` exists. All league endpoints currently live as stubs in `main.py`.

### 2.5 Index Gaps

| Index | Detail |
|-------|--------|
| `leagues` collection: `region + sport + status` | Required for the browse query `GET /leagues?region=athens&sport=padel&status=open`. Does not exist. |

### 2.6 Test Gaps

No unit or integration tests exist for league endpoints (only for the auth/security layer, triggers, and league summary cache operations).

---

## 3. Items Requiring Product Decisions

Before implementation can begin, these decisions must be resolved.

### PD-1: What does "open" mean for league status?

The PRD filters by `status=open` but the existing enum has `active`, `completed`, `upcoming`.

- **Option A**: Add a new `OPEN` status to `LeagueStatusEnum`. Leagues transition: `upcoming` -> `open` (registration opens) -> `active` (play begins) -> `completed`. **Tradeoff**: adds a state transition to manage; cleaner semantic separation.
- **Option B**: Treat `upcoming` as equivalent to "open for registration." Filter by `status=upcoming` on the API. **Tradeoff**: simpler, no enum change; but conflates "announced but not yet open" with "accepting registrations."
- **Recommendation**: Option A for clarity. The founding league playbook (`docs/strategy/padel-launch-playbook-v1.md`) distinguishes between "announced" and "registration open" phases, which maps to `upcoming` vs `open`.

### PD-2: Region source for leagues

The PRD queries `region=athens`. The league schema has no `region` field.

- **Option A**: Add a `region` string field to `leagues/{leagueId}` matching the region system used by leaderboards (`config/regions`). **Tradeoff**: requires backfill of existing seed data; clean and consistent with existing region infrastructure.
- **Option B**: Derive region from the league owner's `preferences.area` via the `config/regions` mapping. **Tradeoff**: no schema change; but couples league region to owner location, which may not match the league's actual region.
- **Recommendation**: Option A. Leagues should have an explicit region. Consistent with how `ticker` events already store `region` directly.

### PD-3: League creation flow

The PRD defines browse and join but not creation. Who creates leagues?

- **Option A**: Admin-only (via Firebase console or seed scripts). Leagues are created operationally for the founding league and future seasons. **Tradeoff**: no `POST /leagues` endpoint needed for MVP; limits self-serve.
- **Option B**: Self-serve `POST /leagues` endpoint where any user can create a league. **Tradeoff**: significant additional scope (validation, moderation, capacity management).
- **Recommendation**: Option A for MVP. The founding league (`docs/strategy/padel-launch-playbook-v1.md` section 3) is operationally managed. Defer self-serve creation to follow-up.

### PD-4: Capacity tracking — denormalized or computed?

The PRD shows "8 / 12 spots filled."

- **Option A**: Add `maxPlayers` (int) and `currentPlayers` (int, denormalized counter) to the league doc. Increment/decrement `currentPlayers` on join/leave via transaction. **Tradeoff**: fast reads, one extra field to maintain.
- **Option B**: Store only `maxPlayers`. Compute current count by counting member docs at read time. **Tradeoff**: no denormalized counter to maintain; adds a subcollection count query on every browse card render.
- **Recommendation**: Option A. The browse endpoint renders multiple league cards; computing member counts per card at read time is O(N) subcollection reads. A denormalized counter is consistent with the project's caching philosophy.

### PD-5: Standings sort order

The PRD shows "rank, name, W/L/pts, tier ring."

- **Option A**: Sort by wins descending, then losses ascending (simple W/L record). **Tradeoff**: simple; doesn't account for games not yet played.
- **Option B**: Sort by a computed points value (e.g., 3 pts per win, 1 pt per loss, 0 unplayed). **Tradeoff**: requires a points formula; more flexible.
- **Recommendation**: Option A for MVP. The member `stats` map already tracks wins and losses (written by D5.2). Sort by wins DESC, losses ASC. Defer a points formula to follow-up.

### PD-6: Join eligibility — skill gating

The PRD shows "Intermediate - Padel" on league cards, implying skill-level filtering.

- **Option A**: Add an optional `tier` field to leagues (e.g., "beginner", "intermediate", "advanced"). Enforce at join time: user's tier in that sport must match. **Tradeoff**: requires tier lookup on join; adds a tier field.
- **Option B**: Display-only. Show the tier label but do not enforce at join time. **Tradeoff**: simpler; risk of mismatched skill levels in a league.
- **Recommendation**: Option B for MVP. Enforcement is complex (tier can change between join and play). Display the intended tier; rely on social norms for the founding league.

---

## 4. Implementation Plan

Assumes product decisions PD-1 through PD-6 are resolved. Phased by data dependency.

### Dependency Map

```
Phase 1 (Schema) ─────────► Phase 2 (Service + Repo) ─────────► Phase 3 (Endpoints)
                                                                        │
                                                                        ▼
                                                                  Phase 4 (Tests + Seed)
```

### Phase 1: Schema + Models

| Issue | Title | Scope | Est. | Dependencies |
|-------|-------|-------|------|--------------|
| LG-1 | Add league browse fields to schema: region, maxPlayers, currentPlayers, startDate, endDate, tier | Schema | S (1 SP) | PD-1, PD-2 resolved |
| LG-2 | Update League Pydantic model + enums (add OPEN status if PD-1=A, add new fields) | Model | S (1 SP) | LG-1 |
| LG-3 | Declare composite index: leagues collection region + sport + status | Infra | S (1 SP) | LG-1 |

### Phase 2: Service + Repo

| Issue | Title | Scope | Est. | Dependencies |
|-------|-------|-------|------|--------------|
| LG-4 | Extend LeaguesRepo: list_by_filter(region, sport, status, limit, cursor), get_member_count() | Repo | M (2 SP) | LG-2, LG-3 |
| LG-5 | Create LeagueService: join flow (capacity check, duplicate check, status check, write member doc, increment currentPlayers) | Service | M (2 SP) | LG-4 |
| LG-6 | Add standings computation to LeagueService: read members, sort by wins DESC / losses ASC, return ranked list | Service | S (1 SP) | LG-4 |

### Phase 3: Endpoints (Router)

| Issue | Title | Scope | Est. | Dependencies |
|-------|-------|-------|------|--------------|
| LG-7 | Create leagues router: GET /leagues (browse with region, sport, status filters + pagination) | API | M (2 SP) | LG-4 |
| LG-8 | Add GET /leagues/{leagueId} (detail view) | API | S (1 SP) | LG-4 |
| LG-9 | Add GET /leagues/{leagueId}/standings | API | S (1 SP) | LG-6 |
| LG-10 | Add POST /leagues/{leagueId}/join (self-serve join, auth required) | API | M (2 SP) | LG-5 |
| LG-11 | Add GET /leagues/{leagueId}/matches (upcoming + completed, paginated) | API | S (1 SP) | LG-4 |
| LG-12 | Migrate existing placeholder endpoints from main.py to leagues router | API | S (1 SP) | LG-7 |

### Phase 4: Tests + Seed + Docs

| Issue | Title | Scope | Est. | Dependencies |
|-------|-------|-------|------|--------------|
| LG-13 | Update seed data: add region, maxPlayers, currentPlayers, startDate, endDate, tier to sample leagues | Seed | S (1 SP) | LG-2 |
| LG-14 | Unit tests: LeagueService join flow, standings computation, browse filtering | Test | M (2 SP) | LG-5, LG-6 |
| LG-15 | Integration tests: league browse, join, standings, matches queries against emulator | Test | M (2 SP) | LG-7 through LG-11 |
| LG-16 | Update wiki: endpoints.md, DATA_DICTIONARY.md, dbschema.md, models.md with league endpoints and new fields | Docs | S (1 SP) | LG-7 through LG-11 |

### Totals

| Phase | Issues | Story Points |
|-------|--------|-------------|
| Phase 1: Schema + Models | LG-1, LG-2, LG-3 | 3 SP |
| Phase 2: Service + Repo | LG-4, LG-5, LG-6 | 5 SP |
| Phase 3: Endpoints | LG-7 through LG-12 | 8 SP |
| Phase 4: Tests + Seed + Docs | LG-13 through LG-16 | 6 SP |
| **Total** | **16 issues** | **22 SP** |

### Suggested Sprint Allocation

- **Sprint 7** (Phase 1 + Phase 2): LG-1 through LG-6 (8 SP). Schema, models, repo, service.
- **Sprint 8** (Phase 3 + Phase 4): LG-7 through LG-16 (14 SP). Likely needs splitting across two sprints given 5-6 SP target. Recommend LG-7, LG-8, LG-9, LG-10 (6 SP) in Sprint 8, remainder in Sprint 9.

---

## 5. Sprint Readiness

### Current Sprint (Sprint 6)

Sprint 6 is focused on Tab 4 Clubhouse Phase 2 wrap-up (CH-18 done, CH-19 in progress) and Venue epic Phase 1 (VEN-1 through VEN-6, 6 issues planned).

### Conflicts

| Concern | Detail | Severity |
|---------|--------|----------|
| Sprint 6 is full | 11 SP already allocated (above 5-6 SP target). League work cannot start until Sprint 7 at earliest. | Low — expected sequencing. |
| No cross-feature dependency | League endpoints do not depend on VEN-* (venues) or CH-* (clubhouse). Can run in parallel or after. | None. |
| `main.py` placeholder migration | LG-12 moves existing stubs from `main.py` to a new `leagues.py` router. If any other sprint work touches `main.py`, coordinate merge order. | Low. |
| Seed data changes | LG-13 extends `tools/seed_data.py` with new league fields. If VEN seed work (VEN-3) also modifies seed data, merge carefully. | Low. |

### Blockers

None. League work can begin in Sprint 7 once product decisions PD-1 through PD-6 are resolved.

---

## 6. Open Questions

| # | Question | Blocking | Notes |
|---|----------|----------|-------|
| PD-1 | Is "open" a new league status or does "upcoming" mean "open for registration"? | LG-1, LG-2 | See section 3. |
| PD-2 | Should leagues have an explicit `region` field? | LG-1, LG-3 | See section 3. |
| PD-3 | Is league creation admin-only for MVP? | Scope | See section 3. |
| PD-4 | Denormalized `currentPlayers` counter or computed at read time? | LG-1, LG-5 | See section 3. |
| PD-5 | Standings sort: simple W/L or points formula? | LG-6 | See section 3. |
| PD-6 | Tier enforcement on join or display-only? | LG-5 | See section 3. |
| PD-7 | Does "Challenge [Name]" on PL-L2 reuse the existing match creation flow or is it a new endpoint? | Scope | PRD says "pre-fills a challenge with league context." Assumed: reuses existing `POST /me/play/broadcast` or offer flow with `leagueId` parameter. Needs confirmation. |
| PD-8 | Leave/quit flow for MVP? | Scope | The existing `DELETE /leagues/{league_id}/members/{uid}` stub is admin-only. Should players be able to self-leave? Assumed: deferred to follow-up. |

---

## 7. Explicitly Out of Scope (MVP)

Tracked for follow-up:

| Item | Reason | Tracked In |
|------|--------|------------|
| `POST /leagues` (self-serve creation) | Founding league is operationally managed (PD-3) | Follow-up |
| League win events in feed (F2) | Depends on league completion flow being stable | `docs/product/tab4-clubhouse-followup.md` F2 |
| Knockout/tournament bracket mode | PRD v2 scope is round-robin only | Follow-up |
| League entry fees / payments | Monetization phase (Month 4-5 per strategic review) | Follow-up |
| Player self-leave endpoint | Admin-managed for founding league | Follow-up |
| League notification/reminder system | Not in MVP PRD screens | Follow-up |
