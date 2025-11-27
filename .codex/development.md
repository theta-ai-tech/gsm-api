# GSM – Development Guide (Local)

## Prereqs
- Python 3.11
- Node 18+ and `firebase-tools` (for emulators)
- Docker Desktop (optional, for container run)

## Setup
```bash
make venv
make install
```

## Run API (no emulator)

```bash
make api-dev
# http://localhost:8000/health
# http://localhost:8000/docs

# Contributing (Dev Phase)

## Branches & PRs
- Create feature branches: `feat/...`, `fix/...`, `chore/...`, `test/...`
- Open a PR to `main`; CI must pass before merge

## Commits (suggested)
- `feat: add /users/{uid} GET`
- `fix: handle 404 for missing user`
- `chore: ruff format + autofix`
- `test: add /health endpoint test`

## Code style & quality
- Format + lint: `ruff format` and `ruff check --fix`
- Types: `mypy api`
- Tests: unit for logic, integration for emulator

## CI (PRs)
Workflow: `.github/workflows/ci.yml`
- **Ruff** (lint + format check)
- **mypy** (type-check)
- **pytest** (spins up Firestore emulator)
Triggers: `pull_request`, manual `workflow_dispatch`.

## Deploy (main)
Workflow: `.github/workflows/deploy.yml`
- Build Docker → Push to **Artifact Registry** → Deploy to **Cloud Run**
- Auth via **Workload Identity Federation** (no JSON keys)
Triggers: `push` to `main`, manual `workflow_dispatch`.

## Branch protection
- Require PRs into `main`
- Require checks: Ruff, mypy, pytest (from CI workflow)
- Optional: linear history
