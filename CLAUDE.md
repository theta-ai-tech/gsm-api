# CLAUDE.md

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
wiki/              # Internal documentation
arch/              # Architecture docs (state machines, lifecycles)
ops/Makefile       # All make targets (included by root Makefile)
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

- Do not run tests unless explicitly instructed; the user will run them manually.
- After any code edits, run `make fmt format type` inside the active venv and ensure they pass.
- Never point tests at production Firestore; always use the emulator.
- Keep secrets out of code; use env vars for credentials.

## Commit Style

Short imperative titles with optional scope: `feat: add league router`, `fix: auth guard (#42)`.
Ensure `make fmt` and `make type` pass before committing.
