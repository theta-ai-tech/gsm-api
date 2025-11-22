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


