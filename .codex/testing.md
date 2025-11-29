# Testing Guide

This doc covers how to exercise GSM API auth locally.

## Auth tests

- **Unit (no network)**  
  `make test-unit`  
  Mocks Firebase token verification; validates header parsing, issuer/audience checks, and owner-only guard.

- **Public endpoint (unauthenticated)**  
  Start API: `make api-dev` (or `make api-dev-emu-auth` if emulators).  
  Then: `curl http://localhost:8000/health` should return `{"ok": true}`.

- **Protected endpoint - missing token**  
  `curl -i http://localhost:8000/users/someone`  
  Expect `401` with `WWW-Authenticate: Bearer`.

- **Protected endpoint - with valid token (owner)**  
  Start API against Auth emulator (recommended):  
  `make api-dev-emu-auth` (fires up API pointing to emulators).  
  Use helper script to sign in and hit the API:
  ```bashs
  ./tests/bash/bearer.sh \
    --api-key "<FIREBASE_WEB_API_KEY or emulator key>" \
    --email "test@example.com" \
    --password "StrongPass123!" \
    --api-base "http://localhost:8000"
  ```
  Expect owner request `200` and non-owner request `403`.

- **Protected endpoint - invalid/foreign token**  
  Swap to a token from another project or mangle the header:  
  `curl -i -H "Authorization: Bearer badtoken" http://localhost:8000/users/whatever`  
  Expect `401`.

- **Real token (non-emulator)**  
  Start API with ADC:  
  ```
  export FIREBASE_PROJECT_ID=<your_project_id>
  export GOOGLE_CLOUD_PROJECT=<your_project_id>
  export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
  uvicorn app.main:app --reload --port 8000 --app-dir api
  ```  
  Run `bearer.sh` with a real web API key + user creds; expect `200/403` as above.
