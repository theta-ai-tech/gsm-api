# GSM-API Documentation Re-Architecture — Design

**Date:** 2026-06-27
**Status:** Approved (tree + scope confirmed); executing migration
**Primary audience:** iOS / client agents (a client developer or iOS code agent that needs to know how to call the API)
**Scope:** Propose, then execute the migration (move/merge files, write new index + diagrams + iOS guide, refresh stale content)
**Layout decision:** Single `docs/` tree replacing the `wiki/`, `arch/`, `spec/`, `plans/` split

---

## 1. Problem

Documentation is spread across four parallel trees (`wiki/` 22 files, `arch/` 7, `spec/` 5, `plans/` 1) with **no index and no map between them**. Concrete issues found during the audit:

- **Data model is described 4 times** at different fidelities: `wiki/dbschema.md`, `wiki/DATA_DICTIONARY.md` (49KB, the real one), `wiki/models.md`, `wiki/tab2-firestore-schema.md`.
- **Queries/repos described 3 times**: `wiki/queries.md`, `wiki/firestore-queries-and-indexes.md`, `wiki/repositories.md` — all framed as "C3, not implemented yet" (long since shipped) and covering only Q1–Q5 while the code has ~18 repos.
- **The Tab-1 state machine lives in two files**: `wiki/me-state.md` + `arch/me_state_machine.md`.
- **Endpoint/payload shapes restated three times**: `wiki/endpoints.md`, `spec/api-launch-contracts.md`, `spec/tab1-play-payloads.md`.
- **Telemetry split** across `wiki/telemetry.md` + `wiki/observability.md`.
- `wiki/overview.md` calls itself the "golden source," last updated **2026-02-07** — it predates leagues, onboarding, clubhouse, lab, venues, device tokens, and the notification delivery pipeline. Current code has 10 routers / 12 services / 18 repos, most unmentioned.
- **No architecture diagram** anywhere.
- **No dedicated client/iOS integration guide.**
- **No docs index / entry point.**
- Epic codenames (`C1`, `C3.5`, `LGM`, `NTF`, `OBS`) leak into doc titles.
- Some references are already broken (e.g. `spec/functional-tab-spec-v1.4.md` referenced but absent).
- Stray temp file at repo root: `pr-289-qa-failure.tmp.md`.

## 2. Target tree

```
docs/
├── README.md                      # THE index — start-here, audience-based routing
├── api/                           # ★ PRIMARY for client/iOS agents
│   ├── README.md                  # How to call GSM: base URLs, auth flow, conventions, error model
│   ├── endpoints.md               # Full endpoint reference
│   ├── contracts.md               # Frozen mobile payload shapes
│   ├── play-tab-state-machine.md  # /me/state contract + diagram
│   ├── notifications.md           # Push/intents from the client POV
│   └── ios-integration.md         # NEW: call patterns, token handling, polling vs push, examples
├── architecture/
│   ├── overview.md                # Refreshed system overview + diagrams
│   ├── diagrams.md                # NEW: system context, request flow, trigger fan-out (Mermaid)
│   ├── match-lifecycle.md
│   ├── triggers.md                # Cloud Functions fan-out
│   └── security.md                # REST-only model, auth, rules, CORS
├── data/
│   ├── data-dictionary.md         # Canonical (49KB)
│   ├── models.md                  # Pydantic models & enums
│   └── queries-and-indexes.md     # Repos + query contracts + indexes (de-"C3"'d)
├── operations/
│   ├── runbook.md
│   ├── deployment.md
│   ├── observability.md           # telemetry + observability merged
│   ├── credentials.md
│   └── tools.md
├── development/
│   ├── local-setup.md             # local dev, emulator, auth-testing
│   └── testing.md
└── design/                        # Historical / deep design docs (non-canonical, clearly marked)
    ├── ai-training-plan.md
    ├── scout-of-the-month.md
    ├── win-predictor-heuristic.md
    ├── danger-zone-data-model.md
    ├── leagues-gap-analysis.md
    ├── mvp-backend-roadmap.md
    ├── plan-tab1.md
    ├── onboarding-level-tier-mapping.md
    └── tab2-firestore-schema.md
```

## 3. Migration map

Clean moves use `git mv` to preserve history. Merges create a new target file and `git rm` the sources.

### Straight moves (`git mv`)
| From | To |
|---|---|
| `wiki/endpoints.md` | `docs/api/endpoints.md` |
| `spec/api-launch-contracts.md` | `docs/api/contracts.md` |
| `wiki/notifications.md` | `docs/api/notifications.md` |
| `wiki/DATA_DICTIONARY.md` | `docs/data/data-dictionary.md` |
| `wiki/models.md` | `docs/data/models.md` |
| `arch/match_lifecycle.md` | `docs/architecture/match-lifecycle.md` |
| `wiki/operator-playbook.md` | `docs/operations/runbook.md` |
| `wiki/functions-deployment.md` | `docs/operations/deployment.md` |
| `wiki/credentials.md` | `docs/operations/credentials.md` |
| `wiki/tools.md` | `docs/operations/tools.md` |
| `arch/ai_training_plan.md` | `docs/design/ai-training-plan.md` |
| `arch/scout_of_the_month.md` | `docs/design/scout-of-the-month.md` |
| `arch/win_predictor_heuristic.md` | `docs/design/win-predictor-heuristic.md` |
| `arch/danger_zone_data_model.md` | `docs/design/danger-zone-data-model.md` |
| `spec/leagues-gap-analysis.md` | `docs/design/leagues-gap-analysis.md` |
| `spec/mvp-backend-roadmap-2026-04-24.md` | `docs/design/mvp-backend-roadmap.md` |
| `spec/onboarding-level-tier-mapping.md` | `docs/design/onboarding-level-tier-mapping.md` |
| `spec/tab1-play-payloads.md` | `docs/design/tab1-play-payloads.md` (payloads folded into api/contracts; kept as history) |
| `plans/plan-tab1.md` | `docs/design/plan-tab1.md` |
| `wiki/tab2-firestore-schema.md` | `docs/design/tab2-firestore-schema.md` |

### Merges
| Target | Sources |
|---|---|
| `docs/api/play-tab-state-machine.md` | `wiki/me-state.md` + `arch/me_state_machine.md` |
| `docs/data/queries-and-indexes.md` | `wiki/queries.md` + `wiki/firestore-queries-and-indexes.md` + `wiki/repositories.md` |
| `docs/architecture/triggers.md` | `wiki/functions.md` + `arch/league_member_triggers.md` |
| `docs/architecture/security.md` | `wiki/security.md` + `wiki/auth.md` + `wiki/cors.md` |
| `docs/operations/observability.md` | `wiki/observability.md` + `wiki/telemetry.md` |
| `docs/development/local-setup.md` | `wiki/auth-testing.md` + emulator/setup notes |
| `docs/development/testing.md` | testing conventions (new, from CLAUDE.md + observability test notes) |

`wiki/dbschema.md` is superseded by `docs/data/data-dictionary.md` — content cross-checked, then `git rm` (dictionary is the canonical, richer version).

### New files authored from current code
- `docs/README.md` — index
- `docs/api/README.md` — client-facing API intro
- `docs/api/ios-integration.md` — the "how do you call us" home for the iOS agent
- `docs/architecture/overview.md` — refreshed (replaces `wiki/overview.md`)
- `docs/architecture/diagrams.md` — Mermaid diagrams

## 4. Reference repoint map

Files that link to moved docs must be updated:
- `README.md` (root) — links to wiki/arch docs → repoint to `docs/...`; add a "Documentation" section pointing at `docs/README.md`.
- `.claude/agents/gsm-tpm.md`, `.claude/agents/gsm-code-reviewer.md` — repoint `wiki/*`, `arch/*`, `spec/*` references. Drop the dead `spec/functional-tab-spec-v1.4.md` reference.
- `.claude/skills/plan-next-issue/SKILL.md` — repoint `wiki/*` references.
- `evals/launch-readiness/*` — repoint `wiki/endpoints.md`, `spec/api-launch-contracts.md`.
- Inter-doc links inside moved files — fix to new relative paths/anchors.
- `tests/smoke/pr-*.sh` — these are historical, archived smoke scripts. Their doc references are comments/echoes; update the path strings but no behavioral change. (Low priority; update opportunistically.)

`CLAUDE.md` project-structure section will be updated to describe the new `docs/` tree.

## 5. Conventions going forward
- One canonical home per topic; everything else links to it (no re-describing).
- No epic codenames in titles or headings; describe the capability, not the sprint that shipped it.
- Diagrams in Mermaid (renders on GitHub, version-controlled).
- `docs/design/` is explicitly non-canonical history; each file gets a banner noting it is a design/decision record, not current reference.
- Every `docs/<section>/` has the index link back to `docs/README.md`.

## 6. Out of scope
- `.agent/` (sprint trackers), `.claude/` skills/agents internals, `brainstorming/`, `evals/` content — these are process/workflow, not product docs, and stay where they are (only their *links* to docs get repointed).
- Rewriting historical `design/` docs — moved as-is with a banner.
