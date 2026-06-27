# Launch-Readiness Eval — 2026-06-01

**Reviewer stance:** CTO go/no-go on the GSM backend MVP.
**Scope graded:** API against the end-goal docs (`../docs/product`, `../docs/strategy`) and the
frozen launch contracts (`spec/`), not against the sprint board.
**Sprint state at review:** Sprint 8 marks all 33 MVP issues ✅ Done (doubles, leagues, venues,
DOC/OPS/SMK/NTF/OBS).

---

## Verdict: CONDITIONAL GO — singles play loop ships; leagues do not close

The core matchmaking loop the product is built on — discover → broadcast/offer → accept → play →
verify score → ranking/state update — is **implemented end-to-end for both singles and doubles**,
the scoring engine matches the PRD formula, venues are complete, and auth is consistently enforced.
That is a genuine, launchable padel-first core.

But "all issues merged" is masking two problems that matter at launch:

1. **A score-integrity hole in the singles confirm flow** (a player can confirm their own result).
   The PRD calls verified results "the moat." This must be fixed before launch.
2. **The leagues loop does not close.** You can browse, join, and read standings, but **no league
   match can ever be created** — so standings stay empty and the round-robin product the PRD
   describes is not deliverable. Leagues are also absent from the frozen mobile launch contract,
   so mobile cannot integrate them at launch regardless.

So: **ship the play + venues MVP after fixing the confirm hole; do not market leagues as a launch
feature** until the league-match loop is wired.

---

## Ship-blockers (must fix before launch)

| # | Blocker | Severity | Detail |
|---|---------|----------|--------|
| 1 | Singles self-confirmation of match results | **Critical** | No check that the confirmer differs from the submitter. One player can submit *and* confirm, awarding themselves points with no opponent agreement. Breaks verified-results integrity. See `02-adversarial.md` F-1. |
| 2 | Score-completion race / stale status read | **High** | Match status is checked outside the completion transaction; the txn never re-asserts `pending_confirmation`. Concurrent/retried confirms can double-apply scoring. See F-2. |

## Launch-shapers (decide explicitly, don't let them ride)

| # | Item | Why it matters |
|---|------|----------------|
| 3 | Leagues loop incomplete — no league-match creation | The PRD's league product ("every league match counts") can't be delivered. Either wire league-match scheduling, or formally move leagues to post-launch. See `01-coverage.md`. |
| 4 | Leagues not in frozen mobile contract | Even the browse/join surface that exists can't be consumed by mobile at launch. Confirms leagues are effectively post-launch today. |
| 5 | Disputed matches have no resolution API | Disputes require manual Firestore edits. Confirm the operator playbook (OPS-2) has a tested runbook before real users hit this. |

## What's solid (no action needed for launch)

- Singles + doubles play lifecycle, `/me/state` machine, offer/broadcast flow.
- Scoring engine: matches PRD tier/bonus/penalty formula; floor clamping; tier crossing.
- Venues: search (Google + curated), curated list, suggestion queue.
- Auth: Firebase bearer enforced on all routes; `/users/{uid}` gated by `require_self`.
- Telemetry, notification-intent contract, smoke tests, demo seed — the launch-support tail landed.
- Test coverage present: 84 unit + 23 integration suites, including league + doubles paths.

## Recommended path to GO

1. Fix F-1 (reject confirmation from the submitting uid in singles) — small, high-value.
2. Fix F-2 (read match inside the completion txn, assert status) — prevents double-scoring.
3. Make an explicit product call on leagues: wire the match loop, or label post-launch and remove
   from the MVP-complete claim.
4. Confirm OPS-2 covers dispute resolution end-to-end.

See `01-coverage.md` for feature-by-feature completeness and `02-adversarial.md` for the full
findings with evidence and fixes.
