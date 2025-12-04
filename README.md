[![CI (lint, type, tests)](https://github.com/theta-gsm/gsm-api/actions/workflows/ci.yml/badge.svg)](https://github.com/theta-gsm/gsm-api/actions/workflows/ci.yml)

# gsm-api
FastAPI service for GameSetMatch (GSM). Containerized, deployed via Cloud Run, CI on PRs.

---

## Quickstart (local, no Docker)
```bash
make venv
make install
make api-dev
# open http://localhost:8000/health
# docs: http://localhost:8000/docs
```

### Authenticated request (Firebase ID token)
- Required env: `FIREBASE_PROJECT_ID=<your-project-id>`
- Optional: `CORS_ORIGINS=http://localhost:3000,https://app.example.com`
- Optional (local emulator): `FIREBASE_AUTH_EMULATOR_HOST=localhost:9099`
- For real tokens locally, set ADC: `GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json`

Example call (replace with a real Firebase ID token):
```bash
curl -H "Authorization: Bearer $ID_TOKEN" http://localhost:8000/users/<uid>
```

### AuthZ helpers (FastAPI)
- Restrict to the same user: `require_self(current_user, uid)`
- Require league admin (global role claim or league membership role): `dependencies=[Depends(require_league_member("admin"))]`
- Example routes (see `app/main.py`):
  - `POST /leagues/{league_id}/members` -> 201 for admins, 403 otherwise
  - `DELETE /leagues/{league_id}/members/{uid}` -> 204 for admins, 403 otherwise

## Run against Firestore emulator (recommended for dev)

Terminal A : 
```bash
make emu-firestore
# or: make emu-all (adds Auth emulator if/when needed)
```

Terminal B:
```bash
make api-dev-emu
# Health: http://localhost:8000/health
```

---

## Testing (pytest)

| Always active the venv locally `source .venv/bin/activate`

```bash
pytest -q tests/unit
# or: make test-unit
```
More detail: see `.codex/testing.md` for auth and manual test steps.

---

## Linting

```bash
make format && make fmt
mypy api
# or: make fmt && make type
```

---

## Run in Docker

Build:
```bash
  make docker-build   # or: make docker-build-amd64 (Apple Silicon)
```

Run:
```bash
  make docker-run     # serves on http://127.0.0.1:8080
```

Health & Docs:
  http://127.0.0.1:8080/health
  http://127.0.0.1:8080/docs

Notes:
- If http://localhost doesn’t load, use http://127.0.0.1 (IPv6 vs IPv4).
- The container doesn’t use your local venv; it has its own Python & deps.

---

## CORS & environments
- Configure via env only:
  - Dev: `CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000`
  - Prod: `CORS_ORIGINS=https://app.gamesetmatch.io`
  - Credentials: `CORS_ALLOW_CREDENTIALS=0` (default; set to `1` only if using cookies)
- Native mobile apps and server-to-server calls are not affected by CORS.
