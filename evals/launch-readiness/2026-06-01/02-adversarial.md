# Adversarial Quality Review — 2026-06-01

Hybrid depth: contract sweep across the surface + deep code dive on the launch-critical paths
(match lifecycle, scoring, auth, league join). Findings ranked by **launch impact**. Each carries
evidence (`file:line`) and a concrete fix. Loop-completeness findings live in `01-coverage.md`.

---

## F-1 — Singles result can be self-confirmed (no two-party agreement) · **CRITICAL**

**Where:** `api/app/services/match_confirmation_service.py:150` (`verify_score`) →
`:895` (`_second_submission`).

**What:** The only guards in `verify_score` are (a) caller is a participant and (b) match status is
`scheduled` or `pending_confirmation`. On the second call the code branches purely on
`stored_winner_uid == request.winner_uid`; it never checks that the confirming `uid` differs from
the player who submitted the first result. So the submitter can call `verify-score` twice with the
same `winner_uid` and drive the match to `completed`, awarding points with **no opponent
agreement**.

The doubles path *does* guard this — `_second_submission_doubles:355` rejects confirmation from the
submitter's own team ("Confirmation must come from a player on the opposing team"). The singles
path has no equivalent.

**Why it matters:** The PRD names verified match results "the moat … every point change is
auditable." Self-confirmation lets any user inflate their own rating unilaterally. At launch this is
a rating-integrity and abuse hole, not a cosmetic one.

**Fix:** In `_second_submission`, reject when `uid` is already in `match.result_submitted_by` (i.e.
the confirmer is the original submitter) → raise `ValueError` (router maps to 409). Mirror the
doubles opposing-party rule. Add a unit test: same uid submits twice → second call rejected.

---

## F-2 — Completion transaction reads match status outside the txn → double-scoring race · **HIGH**

**Where:** `match_confirmation_service.py:164` (status read via `matches_repo.get_by_id`, **outside**
any transaction) and `:996 _scoring_txn` / `:490` (doubles) — the completion transactions read the
*user* docs but **never read the match doc inside the txn** to re-assert `pending_confirmation`.

**What:** Two concurrent (or one auto-retried) second-submissions both pass the out-of-txn status
check, both enter `_complete_with_scoring`, and each adds deltas to the user docs. The user-doc
reads inside the txn give partial protection (Firestore optimistic concurrency aborts one), **but**
on a transactional retry the closure re-executes against freshly-committed pts and adds the delta a
second time — there is no in-txn guard that the match is still `pending_confirmation`, so scoring
is applied again. Result: a match can be scored twice (double points, duplicate `pointHistory`).

**Why it matters:** Silent rating corruption under contention or normal Firestore retries. Hard to
detect after the fact.

**Fix:** Inside `_scoring_txn`, `get` the match ref first and assert
`status == pending_confirmation` (and not already `completed`); abort the txn otherwise. This makes
the transition idempotent and retry-safe. Same fix for the doubles completion txn.

---

## F-3 — Doubles scoring uses an undocumented heuristic · **MEDIUM**

**Where:** `match_confirmation_service.py:434 _complete_with_scoring_doubles` (avg opposing pts via
integer floor division; "highest-tier opponent" used for the upset comparison).

**What:** Doubles points are computed per-player by averaging the opposing pair's pts and comparing
against the highest-tier opponent. This is a reasonable design, but it appears in **no spec** — the
PRD scoring table and `api-launch-contracts.md` only show a doubles *response example*, not the
rule. The averaging and tier-pick choices are load-bearing for every doubles rating and have no
product sign-off or documented rationale.

**Fix:** Document the doubles scoring rule in `spec/` (or `wiki/`) and get product to confirm it
matches intent. Low code risk; the risk is silent divergence from what the product owner expects.

---

## F-4 — Upset/penalty are tier-only, ignoring within-tier point gaps · **MEDIUM (product question)**

**Where:** `scoring_service.py:47,69` (`_is_higher_tier` drives both upset bonus and −50 penalty).

**What:** The PRD says "losing to a **lower-ranked** opponent costs 50 points." The code interprets
"ranked" strictly as **tier**, so a 1,950-pt Intermediate losing to a 1,050-pt Intermediate (a big
within-tier upset) incurs **no** penalty and the winner gets **no** upset bonus. Whether that
matches product intent is unclear — "ranked" could mean points, not tier.

**Fix:** Confirm with product whether ranking comparisons should be points-based or tier-based. If
tier-based is intended, note it in the scoring spec so it isn't mistaken for a bug later.

---

## F-5 — Disputed matches have no resolution path · **MEDIUM (operational)**

**Where:** `_dispute` / `_dispute_doubles` set status `disputed`; no endpoint transitions out of it.
Documented as a known limitation (`api-launch-contracts.md` §Known Limitations #1): "require admin
intervention via the Firebase console."

**What:** Acceptable as an MVP scope cut, but at launch a disputed match strands all participants in
`MATCH_DISPUTED` play-tab state until someone hand-edits Firestore. There is no tested runbook in
the eval inputs confirming ops can actually do this safely.

**Fix:** Verify OPS-2 (operator playbook) contains a concrete, tested dispute-resolution procedure
(which fields to set to release the participants). If not, add one before launch.

---

## F-6 — No visible rate-limiting / abuse controls on score submission · **LOW (launch-risk to watch)**

**What:** `verify-score`, `broadcast`, and `offers` have no application-level throttling. Combined
with F-1 this widens the rating-manipulation surface. Likely fine for a small Athens beta; revisit
before broad launch.

**Fix:** None required for a controlled beta. Track for scale; consider per-uid write limits.

---

## Lower-severity / by-design (no launch action)

- **Offer expiry hardcoded to 5 min** (`api-launch-contracts.md` #4) — documented, intentional.
- **Vestigial `court_id/court_name/court_geo` in MATCH_SCHEDULED** (#6) — superseded by `venue_ref`,
  kept for back-compat; clients told to ignore.
- **Standings `display_name` falls back to `uid`** (`league_service.py:91`) — names not yet on member
  docs; cosmetic, and moot until the league-match loop exists (`01-coverage.md`).
- **`venue_ref` / `source_broadcast_id` not echoed** in offer-create response (#2) — documented.

---

## Things checked that are CORRECT (verified, not assumed)

- **League join capacity** is race-safe — capacity + duplicate checks are *inside* the transaction
  with `Increment(1)` (`league_service.py:39-69`). No TOCTOU.
- **League member stats trigger** exists and is idempotent per `match_id`
  (`functions/scoring_triggers/main.py:115`, `increment_member_stats`) — standings *would* populate
  correctly if league matches could be created.
- **Auth** is enforced on every router; the inline `/users/{uid}` uses `require_self`
  (`main.py:176`) — no profile-enumeration leak.
- **Scoring formula** matches the PRD tier/bonus/penalty table with floor clamping
  (`scoring_service.py`).
- **Doubles confirm** correctly requires opposing-party agreement and routes genuine disagreement to
  `disputed` (`_second_submission_doubles:355,362`).
