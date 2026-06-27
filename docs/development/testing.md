# Testing

> Test layout, markers, and the commands to run them. Lint/type/format gates too.

## Layout

```
tests/
  unit/          # mocked Firestore, no emulator; mirrors api/app/ structure
  integration/   # requires the Firestore emulator
  tools/         # tool-utility tests
  smoke/         # tests/smoke/pr-{N}.sh — per-PR smoke scripts against the emulator
  bash/          # auth helper scripts (bearer.sh, …)
```

- **pytest** + **pytest-asyncio**; FastAPI `TestClient` for unit tests.
- Markers: `@pytest.mark.integration`, `@pytest.mark.seeded`.
- Fixtures live in `tests/*/conftest.py`.

## Commands

```bash
make test-unit     # unit tests (no emulator)
make test-int      # integration tests (requires emulator)
make test          # everything (unit + tools + integration)
make fmt format type   # ruff format + lint + mypy — run after every code change
```

Integration and `make test` require the emulator up at `127.0.0.1:8082`
(`make emu-all` + `make api-dev-emu-auth` in separate terminals). Never point tests at
production Firestore — always use the emulator.

## Conventions

- Line length 100 (ruff config in `api/pyproject.toml`).
- Type hints everywhere (mypy enforced).
- Unit tests mirror the `api/app/` package layout under `tests/unit/`.
- The editable install (`pip install -e api[dev]`) puts `app` on the import path — do **not**
  add `pythonpath` to `pytest.ini`. If imports fail, re-run `make install`.

## CI

GitHub Actions runs lint, type check, and the unit suite on PRs (badge in the root `README.md`).
Smoke scripts run separately against the emulator; see
[`../architecture/security.md`](../architecture/security.md) for `make emu-smoke` vs `make emu-all`.
