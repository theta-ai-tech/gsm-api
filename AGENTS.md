# Repository Guidelines

The project implements the backend for GSM - a web/mobile app that builds a social match making application with  features like leagues/matches and journal for self development.

## Working Rules
- Do not run tests unless explicitly instructed; the user will run them manually.
- After any code edits, run `make fmt format type` inside the active venv and ensure they pass.

## Context
We need a managed, autoscaling runtime for a containerized Python API, plus native event triggers for Firestore/Storage/PubSub.

## Project Structure & Module Organization
- API code: `api/app` with FastAPI entrypoint in `api/app/main.py`; domain folders (`models`, `services`, `routers`, `rules`, `utils`) are stubs awaiting features.
- Infrastructure: `Dockerfile`, `infra/`, and `ops/Makefile` for local tooling; Cloud Functions placeholders live in `functions/`.
- Tests: unit scaffolding in `tests/unit`, emulator-driven integration helpers in `tests/integration`.

## Setup, Build, and Local Runs
- Create env + install dev deps: `make venv && make install`.
- Run API (no emulator): `make api-dev` (serves on port 8000).
- Run against Firestore emulator: `make emu-firestore` (new shell) then `make api-dev-emu` (exports `FIRESTORE_EMULATOR_HOST`, `GOOGLE_CLOUD_PROJECT`).
- Seed emulator sample data: `make seed`.
- Docker images: `make docker-build` or `make docker-build-amd64`; run with `make docker-run` (exposes port 8080).

## Coding Style & Naming Conventions
- Python 3.11+, line length 100 (ruff config in `pyproject.toml`); prefer type hints (mypy target).
- Ruff for lint/formatting: `make fmt` (fixes) and `make format` (formatter pass).
- Function/variable names use `snake_case`; classes `PascalCase`; routes keep FastAPI path operations in `routers` when added.
- **Unit** mirrors `api/app/...`; no external services (mock SDKs)
- **Integration** hits emulators (Firestore now; Auth later if needed)
- Use fixtures in `tests/*/conftest.py`

## Testing Guidelines
- Frameworks: pytest + pytest-asyncio; FastAPI `TestClient` for units; Firestore emulator for integration.
- Run all tests: `make test`; unit-only: `make test-unit`; integration (requires emulator env vars): `make test-int`.
- Integration tests auto-clean `users` collection (see `tests/integration/conftest.py`); ensure `FIRESTORE_EMULATOR_HOST` and `GOOGLE_CLOUD_PROJECT` are set or use `make api-dev-emu`/`make seed` helpers.

### Integration (needs emulator)
export FIRESTORE_EMULATOR_HOST=127.0.0.1:8082
export GOOGLE_CLOUD_PROJECT=gsm-dev-f70d0
pytest -q tests/integration

## Commit & Pull Request Guidelines
- Use short, imperative commit titles with optional scope/ticket, e.g., `feat: add league router` or `fix: auth guard (#42)`.
- Ensure commits are linted (`make fmt`) and typed (`make type`) when touching Python code.
- PRs: describe intent and testing performed; link issues/tickets; add emulator notes or screenshots for API responses when relevant.

## Security & Configuration Tips
- Never point integration tests at production Firestore; rely on the emulator (`FIRESTORE_EMULATOR_HOST=127.0.0.1:8082`).
- Keep secrets out of code and `firebase.json`; use env vars for local creds, and prefer `make` targets that export safe defaults.

## Components
- **API:** FastAPI container on **Cloud Run** (region: `europe-west8`)  
- **Triggers:** **Cloud Functions Gen 2** for Firestore/PubSub events (same region)  
- **Data Store:** **Firestore** (Native mode)  
- **Container Registry:** **Artifact Registry** (Docker)  
- **Auth:** **Firebase Auth** (clients sign in → send **ID token** to API)  
- **CI/CD:** GitHub Actions → build/push image → deploy to Cloud Run via **Workload Identity Federation (WIF)**

## Runtime Flow (request path)
1. Client signs in with Firebase → obtains **ID token**.  
2. Client calls API with `Authorization: Bearer <ID_TOKEN>`.  
3. FastAPI dependency verifies token via `firebase_admin.auth.verify_id_token`.  
4. Handler uses `request.state.uid` to authorize and query Firestore.  
5. Response returned.  
