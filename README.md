# gsm-api
API calls for the GSM

## Quickstart
```bash
make venv
make install
make api-dev
# open http://localhost:8000/health

## Run in Docker

Build:
  make docker-build   # or: make docker-build-amd64 (Apple Silicon)

Run:
  make docker-run     # serves on http://127.0.0.1:8080

Health & Docs:
  http://127.0.0.1:8080/health
  http://127.0.0.1:8080/docs

Notes:
- If http://localhost doesn’t load, use http://127.0.0.1 (IPv6 vs IPv4).
- The container doesn’t use your local venv; it has its own Python & deps.


