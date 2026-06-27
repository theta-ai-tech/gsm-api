# Local Setup & Auth Testing

> Get the API running locally against the Firestore + Auth emulators, and exercise auth.
> All targets live in `ops/Makefile` (included by the root `Makefile`).

## First-time setup

```bash
make venv && make install      # create venv + install editable api[dev]
```

## Run the API

```bash
# Plain (no emulator) — liveness only
make api-dev                   # http://localhost:8000 ; docs at /docs ; GET /health

# Against the Firestore emulator (port 8000)
make emu-firestore             # start Firestore emulator in a separate shell
make api-dev-emu

# Against Firestore + Auth emulators (auth-enabled local dev)
make emu-all                   # Firestore + Auth emulators (deny-all rules)
make api-dev-emu-auth
```

Emulator env vars used by integration work:
- `FIRESTORE_EMULATOR_HOST=127.0.0.1:8082`
- `GOOGLE_CLOUD_PROJECT=gsm-dev-f70d0`

Seed sample data into the emulator with `make seed-emu` (see `tools/README.md`).

## Run in Docker

The container ships its own Python and dependencies — it does not use your local venv.

```bash
make docker-build           # or: make docker-build-amd64 (Apple Silicon → amd64)
make docker-run             # serves on http://127.0.0.1:8080
make docker-stop            # stop the local container
```

Health and interactive docs: `http://127.0.0.1:8080/health` and `/docs`. If `localhost` doesn't
load, use `127.0.0.1` (IPv6 vs IPv4). On macOS, `make docker-up` / `make docker-down` start/stop
Docker Desktop.

## Auth testing

| Scenario | How | Expect |
|---|---|---|
| Unit (no network) | `make test-unit` | Mocks Firebase verification; validates header parsing, issuer/audience, owner-guard |
| Public endpoint | `curl http://localhost:8000/health` | `{"ok": true}` |
| Protected, missing token | `curl -i http://localhost:8000/users/someone` | `401` + `WWW-Authenticate: Bearer` |
| Protected, valid owner token | start `make api-dev-emu-auth`, then the `bearer.sh` flow below | owner `200`, non-owner `403` |
| Protected, invalid token | `curl -i -H "Authorization: Bearer badtoken" http://localhost:8000/users/whatever` | `401` |

Sign in against the Auth emulator and call the API:

```bash
./tests/bash/bearer.sh \
  --api-key "<FIREBASE_WEB_API_KEY or emulator key>" \
  --email "test@example.com" \
  --password "StrongPass123!" \
  --api-base "http://localhost:8000"
```

### Real tokens (non-emulator)

```bash
export FIREBASE_PROJECT_ID=<your_project_id>
export GOOGLE_CLOUD_PROJECT=<your_project_id>
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
uvicorn app.main:app --reload --port 8000 --app-dir api
```

Run `bearer.sh` with a real web API key + user creds; expect `200/403` as above.

See [`../architecture/security.md`](../architecture/security.md) for the full auth model.
