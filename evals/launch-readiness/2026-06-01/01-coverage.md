# MVP Coverage vs the End Goal — 2026-06-01

Graded against the product vision (`../docs/strategy/prd-idea.md`), the functional spec, and the
frozen contracts (`docs/api/contracts.md`). The end-goal loop the PRD demands:

> find opponents at your level → play → log/verify scores → build a competitive identity (points,
> tier, streaks, rivalries) → leagues turn casual play into competitive structure.

Legend: ✅ complete & closeable · 🟡 built but with a gap · ⛔ loop cannot be closed

| Product promise (PRD) | Backend status | Evidence / gap |
|---|---|---|
| **PLAY — singles core loop** | ✅ | broadcast → offer → accept → match → `verify-score` → scoring/state all wired (`play_service.py`, `match_confirmation_service.py`, `routers/play.py`, `routers/matches.py`). |
| **PLAY — doubles** | ✅ | Full doubles path: 4-participant matches, team-based confirm, per-player scoring (`_verify_score_doubles`, `_complete_with_scoring_doubles`). |
| **PLAY — `/me/state` machine** | ✅ | All 9 modes incl. doubles payloads (`docs/api/contracts.md` §GET /me/state). |
| **Venues (padel-first req.)** | ✅ | `/venues/search`, `/venues`, `/venues/suggest` implemented (`routers/venues.py`). |
| **Scoring standard (the moat)** | 🟡 | Formula matches PRD (base 100 / upset 50 / +5% elo / −50 penalty, floor-clamped) — `scoring_service.py`. Gap: **result integrity hole** lets a player self-confirm (see `02-adversarial.md` F-1). |
| **IMPROVE — journal / north star** | ✅ | `routers/improve.py`, `journal_service.py` (prior sprints). |
| **THE LAB — points / tiers / leaderboard / ticker** | ✅ | `routers/lab.py` (8 read endpoints), ticker events emitted on completion. |
| **CLUBHOUSE — athlete card / streaks / PB / local pulse** | ✅ | `clubhouse_service.py`, streak/PB/tier-crossed tickers wired into completion. |
| **LEAGUES — browse** | ✅ | `GET /leagues` with region/sport/status filters + pagination (`routers/leagues.py`, `league_service.py`). |
| **LEAGUES — join (capacity-safe)** | ✅ | `POST /leagues/{id}/join` — capacity + duplicate checks **inside** a transaction, `Increment(1)` (`league_service.py:39-69`). Correct. |
| **LEAGUES — standings** | 🟡 | `GET /leagues/{id}/standings` computes dense ranking; member wins/losses populated by an idempotent trigger on league-match completion (`functions/scoring_triggers/main.py:115 handle_match_write_update_league_stats`). Infra is correct — but it never fires (see next row). |
| **LEAGUES — play a league match** | ⛔ | **No path creates a match with a `leagueId`.** The only match-creation flow (offer accept) hardcodes `"leagueId": None` (`play_service.py:1067,1095`) and there is no league-match scheduling endpoint. So `GET /leagues/{id}/matches` is always empty and standings never populate. The PRD's core league value ("every league match counts toward your GSM score") is **not deliverable**. |
| **LEAGUES — mobile launch integration** | ⛔ | Leagues appear **nowhere** in the FROZEN mobile contract (`docs/api/contracts.md` endpoint index). Mobile cannot consume them at launch even though the read/join surface exists. |

## Is the MVP scope "good enough"?

**For a padel-first launch: yes, with leagues removed from the launch claim.** The vision's Year-1
horizon is explicitly *"the padel matchmaking utility — prove the core loop: find opponents, play
matches, build your score."* That loop is built and (after the F-1/F-2 fixes) trustworthy. Venues
and doubles — the two things the functional spec calls hard requirements for padel-first — are done.

**The scope is over-claimed on leagues.** Sprint 8 booked 16 league issues (LG-1..16) as the
schema/model/repo/service/router/tests/docs for leagues, and they are individually done. But the
*epic* was decomposed without an issue for "create/schedule a league match," so the stream produced
a browse/join shell whose competitive payload can never arrive. This is a planning gap, not a
coding failure: every issue passed, the feature still doesn't work. It's exactly what grading
against the issue list (instead of the product loop) hides — and the reason this eval exists.

**Recommendation:** treat the MVP as **Play + Venues + supporting tabs** for launch. Either add a
league-match scheduling slice (and put leagues in the mobile contract) or formally reclassify
leagues as the first post-launch epic. Don't ship the current half-loop as "leagues."
