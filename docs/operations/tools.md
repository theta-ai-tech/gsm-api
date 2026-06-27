# Tools & Operations Runbook

This page explains when each operational tool should be used, how it is triggered, and where to run it from.

Run location for CLI commands in this document: repo root (`gsm-api`).

---

## Quick matrix

| Tool / Workflow | Purpose | Trigger type | Where it runs |
| --- | --- | --- | --- |
| `make seed-emu` / `python -m tools.seed_firestore --env emu` | Seed Firestore emulator data | Manual | Local terminal |
| `make check-queries-emu` / `python -m tools.check_queries` | Verify repo query contracts on emulator | Manual (and can be CI-added later) | Local terminal |
| `python -m tools.rebuild_caches ...` | Rebuild user cache fields from canonical data | Manual (repair/backfill) | Local terminal |
| `python -m tools.check_cache_integrity ...` | Read-only cache invariant checker | Manual (verification/guardrail) | Local terminal |
| `python -m tools.migrate_journal_fields ...` | Backfill missing journal fields in `journalEntries` docs | Manual (one-off migration) | Local terminal |
| `./scripts/deploy_functions.sh ...` / `make deploy-functions` | Deploy Firebase Functions + run smoke | Manual | Local terminal |
| `./scripts/rollback_functions.sh ...` | Roll back Functions to known-good revision | Manual | Local terminal |
| `./scripts/smoke_triggers.sh --env emu|dev ...` | Smoke test trigger cache behavior | Manual (also auto after deploy script) | Local terminal |
| `make smoke-functions` | HTTP ping check for `gsm_ping` | Manual | Local terminal |
| `.github/workflows/ci.yml` | Lint/type/tests with emulator | Automatic on PR, manual dispatch | GitHub Actions |
| `.github/workflows/deploy.yml` | Build & deploy API container to Cloud Run | Automatic on `main`, manual dispatch | GitHub Actions |
| `.github/workflows/functions-deploy.yml` | Deploy Firebase Functions | Manual dispatch | GitHub Actions |
| `.github/workflows/functions-rollback.yml` | Roll back Firebase Functions | Manual dispatch | GitHub Actions |

---

## Detailed guidance

### 1) Seed emulator data
- **Command:** `make seed-emu`
- **When:** local integration testing, query checks, smoke checks need baseline data.
- **Prereq:** Firestore emulator running (`make emu-firestore`).
- **Trigger:** manual local.

### 2) Query contract checks
- **Command:** `make check-queries-emu`
- **When:** after repo/query/index changes to validate expected sorting/filter behavior.
- **Prereq:** emulator running and seeded.
- **Trigger:** manual local.

### 3) Cache rebuilder (D6.1)
- **Command (single user dry-run):**
  - `python -m tools.rebuild_caches --env emu --uid <uid> --dry-run`
- **Command (all users apply):**
  - `make rebuild-caches-emu`
- **When:** cache drift after missed triggers, schema migrations, bad deployments, bulk imports.
- **Trigger:** manual local.
- **Safety:** use `--dry-run` first.

### 3b) Cache integrity checker (D6.4)
- **Command (sample):**
  - `python -m tools.check_cache_integrity --env emu --limit 50`
- **Command (single user):**
  - `python -m tools.check_cache_integrity --env emu --uid <uid>`
- **When:** before/after deploys, after cache rebuilds, or during incident triage.
- **Trigger:** manual local.
- **Behavior:** read-only; exits non-zero on violations.
- **Coverage:** upcoming/completed match caches, league summary references, and `journalRecent` invariants (cap/duplicates/existence/not-deleted).

### 3c) Journal field migration tool (EX06)
- **Command (dry-run):**
  - `python -m tools.migrate_journal_fields --env emu --dry-run`
- **Command (single user apply):**
  - `python -m tools.migrate_journal_fields --env emu --uid <uid>`
- **When:** legacy journal documents are missing newer fields (`entryType`, `trainingFocus`, soft-delete flags, etc.).
- **Trigger:** manual local.
- **Safety:** run `--dry-run` first; writes are batched and deterministic (stable user/doc ordering).

### 4) Functions deploy
- **Command:** `make deploy-functions` or `./scripts/deploy_functions.sh --project <id>`
- **When:** deploying trigger/function changes.
- **Trigger:** manual local or manual GitHub Actions workflow (`functions-deploy.yml`).
- **Notes:** deploy script logs revision and runs trigger smoke checks.

### 5) Functions rollback
- **Command:** `./scripts/rollback_functions.sh --project <id> [--revision <sha>]`
- **When:** bad function deployment or smoke failure requiring quick revert.
- **Trigger:** manual local or manual GitHub Actions workflow (`functions-rollback.yml`).
- **Notes:** uses git worktree and logs rollback event.

### 6) Trigger smoke checks
- **Command (emulator):** `./scripts/smoke_triggers.sh --env emu`
- **Command (dev):** `./scripts/smoke_triggers.sh --env dev --project <id>`
- **When:** immediately after deploy, and during local trigger logic changes.
- **Trigger:** auto via `deploy_functions.sh`; also runnable manually.

### 7) HTTP ping smoke
- **Command:** `GSM_PING_URL=<url> make smoke-functions`
- **When:** quick connectivity sanity check for deployed function endpoint.
- **Trigger:** manual local.
- **Note:** this does not validate cache logic; use trigger smoke for behavior checks.

### 8) CI/API deploy workflows
- **`ci.yml`:** automatic on pull requests (lint, mypy, tests with emulator).
- **`deploy.yml`:** automatic on `main` pushes (Cloud Run API deploy).
- **Functions are not auto-deployed on `main` yet** (manual workflows currently).
