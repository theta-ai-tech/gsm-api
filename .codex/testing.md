# GSM – Testing (pytest)

## Layout

```
tests/
  unit/
    app/
      routers/
        test_health.py
  integration/
    app/
      routers/
        users/
          test_users_router_integration.py  # (placeholder – when implemented)
```


## Conventions
- **Unit** mirrors `api/app/...`; no external services (mock SDKs)
- **Integration** hits emulators (Firestore now; Auth later if needed)
- Use fixtures in `tests/*/conftest.py`

## Commands
```bash
# Unit
pytest -q tests/unit

# Integration (needs emulator)
export FIRESTORE_EMULATOR_HOST=127.0.0.1:8082
export GOOGLE_CLOUD_PROJECT=gsm-dev-f70d0
pytest -q tests/integration