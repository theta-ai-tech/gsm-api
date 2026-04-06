# CLAUDE.md

## Workflow Operations

### 1. Plan Node Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately - don't keep pushing.
- One plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent strategy
- Use subagents liberally to keep main context window clean. If user has prompted for a specific subagent delegate the appropriate task.
- Offload research, exploration and parallel analysis to subagents
- For complex problems, throw more compute via subagents
- One task per subagent for focused execution

### 3. Self-Improvement loop
- After ANY correction from the user : update `.claude/rules/lessons_learned.md` with the pattern.
- Write rules for yourself that prevent the same mistake
- Iterate on these lessons until error rate drops
- Review lessons at session start for relevant project! DO THIS ALWAYS!

## Team Operations

- **Skills:** `/next-issue`, `/post-merge`, `/plan-sprint`, `/standup`, `/review-pr`, `/lookup-docs`
- **Agents:** `gsm-backend-developer` (implementation), `gsm-tpm` (specs & planning)
- **Sprint tracking:** `.agent/SPRINT.md`, `.agent/ARCHIVE_SPRINT.md`

## Project Overview

GSM (GameSetMatch) API — backend for a social sports matchmaking app (tennis, padel, pickleball). FastAPI on Cloud Run, Firestore as the database, Cloud Functions Gen 2 for event triggers, Firebase Auth for identity.

## Tech Stack

- **Language:** Python 3.11+
- **Framework:** FastAPI + Pydantic v2 + Uvicorn
- **Database:** Firestore (Native mode) with denormalized caches
- **Auth:** Firebase Auth (Bearer ID tokens verified via `firebase_admin.auth.verify_id_token`)
- **Infra:** Cloud Run (europe-west8), Cloud Functions Gen 2, Artifact Registry
- **CI/CD:** GitHub Actions with Workload Identity Federation (WIF)

## Project Structure

```
api/app/           # FastAPI application
  main.py          # App entrypoint
  routers/         # HTTP endpoints (play.py, improve.py)
  services/        # Business logic
  repos/           # Data access layer (Firestore)
  models/          # Pydantic models
  dependencies/    # FastAPI dependency injection
  security.py      # Auth & authorization helpers
functions/         # Cloud Functions for Firebase (triggers)
tests/
  unit/            # Unit tests (mocked Firestore, no emulator)
  integration/     # Integration tests (requires Firestore emulator)
  tools/           # Tool utility tests
tools/             # Operational scripts (seed, cache rebuild, query checks)
scripts/           # Deployment and smoke test shell scripts
ops/Makefile       # All make targets (included by root Makefile)
deploy/            # Deployment config (last_good_revision_dev.txt etc.)
infra/             # Infrastructure config (Cloud Run, Artifact Registry)

# Documentation
wiki/              # Internal reference docs: DATA_DICTIONARY.md, endpoints.md,
                   #   dbschema.md, models.md, repositories.md, functions.md,
                   #   me-state.md, auth.md, queries.md, observability.md, etc.
arch/              # Architecture docs: match_lifecycle.md, me_state_machine.md,
                   #   league_member_triggers.md
spec/              # Product specs: functional-tab-spec-v1.4.md, PRD, tab descriptions
                   #   (tab1-play, tab2-improve, tab3-lab, tab4-clubhouse), playbooks
plans/             # Implementation plans per feature area (e.g. plan-tab1.md)
```

## Setup

```bash
make venv && make install      # Create venv + install deps
```

## Common Commands

```bash
# Lint & type check (run after every code change)
make fmt format type

# Tests
make test-unit                 # Unit tests (no emulator needed)
make test-int                  # Integration tests (requires emulator)
make test                      # All tests (unit + tools + integration)

# Local dev
make emu-firestore             # Start Firestore emulator (separate shell)
make api-dev-emu               # Run API against emulator (port 8000)

# Docker
make docker-build              # Build image
make docker-run                # Run locally (port 8080)
```

## Coding Conventions

- Line length: 100 (ruff config in `api/pyproject.toml`)
- `snake_case` for functions/variables, `PascalCase` for classes
- Type hints everywhere (mypy enforced)
- Ruff for linting and formatting

## Testing

- **pytest** + **pytest-asyncio**; FastAPI `TestClient` for unit tests
- Unit tests mirror `api/app/` structure in `tests/unit/`
- Integration tests require emulator env vars:
  - `FIRESTORE_EMULATOR_HOST=127.0.0.1:8082`
  - `GOOGLE_CLOUD_PROJECT=gsm-dev-f70d0`
- Markers: `@pytest.mark.integration`, `@pytest.mark.seeded`
- Fixtures live in `tests/*/conftest.py`

## Working Rules

- Do not run tests in ad-hoc sessions unless explicitly instructed. Exception: `/next-issue` and `/autopilot` workflows run `make test` automatically before committing — but first check the Firestore emulator is up at `127.0.0.1:8082`. If it's not running, stop and tell the user to run `make emu-all` and `make api-dev-emu-auth` in separate terminals before continuing.
- After any code edits, run `make fmt format type` inside the active venv and ensure they pass.
- Never point tests at production Firestore; always use the emulator.
- Keep secrets out of code; use env vars for credentials.
- For `/review-pr`, run required `gh` commands directly and do not ask in chat first. This workflow rule does not override platform sandbox or approval policies; if a `gh` command still triggers an approval UI, invoke it directly and let the platform handle it. Prefer approved `gh` prefix rules to reduce repeated prompts.

## Commit Style

Short imperative titles with optional scope: `feat: add league router`, `fix: auth guard (#42)`.
Ensure `make fmt` and `make type` pass before committing.

## Agent Delegation

When a matching agent is available, delegate work to it instead of doing it inline.
Pass the full issue/task context and project conventions so the agent can work autonomously.
Only handle simple/quick tasks directly (file reads, one-liner edits, answering questions).

| Agent | Delegate when | Do NOT delegate |
|-------|--------------|-----------------|
| `gsm-backend-developer` | New features, bug fixes, issue implementation, PRs, tests | Quick file reads, one-liner edits, answering questions |
| `gsm-tpm` | New feature specs, gap analysis, issue decomposition, product decisions | Implementation work, code changes |
