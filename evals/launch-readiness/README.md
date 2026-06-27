# Launch-Readiness Evals

A repeatable, CTO-level review that answers one question before we ship a milestone:
**is the backend actually ready, or does it just look ready on the sprint board?**

Each run lives in a dated subfolder and grades the API against the *intended product* (the
`../docs/` vision + `spec/` contracts) rather than against the issue list — because a sprint can be
"all green" while the product loop it was meant to deliver still doesn't close.

## Folder layout

```
evals/
  launch-readiness/
    README.md              ← this file (the procedure)
    YYYY-MM-DD/            ← one folder per eval run
      00-summary.md        ← CTO verdict + go/no-go + top blockers
      01-coverage.md       ← MVP completeness vs the end-goal docs
      02-adversarial.md    ← quality findings ranked by severity, evidence-backed
```

## The procedure

Run these phases in order. Each phase feeds the next.

1. **Establish the end goal.** Read the product vision and strategy (`../docs/product`,
   `../docs/strategy`) and the frozen contracts (`spec/`). Write down, in your own words, the
   core loop the product must support. This is what you grade against — not the sprint tracker.

2. **Map the surface.** Inventory every implemented endpoint (`api/app/routers`, `main.py`) and
   diff it against the documented contracts (`docs/api/contracts.md`, `docs/api/endpoints.md`).
   Flag: placeholder/stub endpoints, missing endpoints, and contract drift. Note anything that is
   "MVP" on the board but absent from the frozen mobile contract.

3. **Deep-dive the launch-critical paths.** Read the actual implementation (services, repos,
   triggers) for the paths that, if wrong, sink the launch: match lifecycle, scoring, auth, and
   any capacity/money/state-machine flow. Hunt for correctness bugs, missing authorization, race
   conditions, Firestore cost traps, and weak tests. **Verify before you claim** — trace a finding
   to the line that proves it (e.g. confirm a trigger does *not* exist before calling a feature
   non-functional). Cite `file:line`.

4. **Trace each headline loop end-to-end.** For every feature the product promises, follow it from
   API entry to data write to read-back. A loop that has all its pieces but can't be *closed*
   (e.g. join a league but never create a league match) is an incomplete feature, not a done one.

5. **Write the verdict.** Produce `00-summary.md` (go/no-go, ship-blockers, what's solid),
   `01-coverage.md` (per-feature completeness vs the end goal), and `02-adversarial.md` (findings
   ranked Critical/High/Medium/Low with evidence and a concrete fix).

## Grading stance

- Grade against the **product**, not the checklist. "All issues merged" is the input, not the
  answer.
- A finding without a `file:line` (or a proven absence) is a hunch — verify it or drop it.
- Severity is about **launch impact**: does it corrupt data, block the core loop, or leak/abuse?
  Cosmetic and deferred-by-design items are Low.
- Separate *completeness* (is the loop wired?) from *quality* (is the wired loop correct?). They
  fail launches differently.

## Inputs checklist

- [ ] `../docs/product/*` and `../docs/strategy/*` (end goal)
- [ ] `docs/api/contracts.md`, `spec/mvp-backend-roadmap-*.md`, `spec/*gap*.md`
- [ ] `.agent/SPRINT.md`, `.agent/ROADMAP.md` (claimed status)
- [ ] `api/app/routers`, `api/app/services`, `api/app/repos`, `functions/` (reality)
- [ ] `docs/api/endpoints.md` and related wiki docs (documented behavior)
