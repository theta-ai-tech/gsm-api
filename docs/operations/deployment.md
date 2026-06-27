# Functions Deployment (D5)

This doc covers the D5 operational workflow for Firebase Functions: versioned deploys,
rollback, and post-deploy smoke checks. The goal is safe iteration with a quick rollback path.

---

## Scope
- Functions deploys are managed via scripts in `scripts/`.
- Deploys are versioned using the current git SHA (or an explicit tag).
- Rollback uses a git worktree and redeploys a known-good revision.
- Smoke checks run after each deploy and validate cache behavior.

---

## Prerequisites
- Firebase CLI installed (`firebase --version`).
- Google Cloud auth via WIF (CI) or local ADC.
- Python 3.11+ for Functions runtime.
- One-time: create the Functions venv:
  ```bash
  make functions-venv
  ```

---

## Versioned deploy (D5.1)

Script:
```bash
./scripts/deploy_functions.sh --project <project-id> [--revision <rev>]
```

Behavior:
- Uses git short SHA if `--revision` is not provided.
- Sets Firebase runtime config: `gsm.revision=<REV>`.
- Deploys functions only: `firebase deploy --only functions`.
- Lists deployed functions.
- Appends a log line to `deploy/last_good_revision_dev.txt`:
  ```
  <sha> DEPLOYED <utc-timestamp>
  ```
- Runs smoke checks automatically after deploy.

Make target:
```bash
make deploy-functions
```

---

## Rollback (D5.2)

Rollback script:
```bash
./scripts/rollback_functions.sh --project <project-id> [--revision <rev>]
```

Behavior:
- If `--revision` is omitted, uses the last `DEPLOYED` entry in
  `deploy/last_good_revision_dev.txt`.
- Uses a temporary git worktree (does not alter your working tree).
- Redeploys via `deploy_functions.sh` at that revision.
- Appends a log line:
  ```
  <sha> ROLLED BACK <utc-timestamp>
  ```

---

## Post-deploy smoke checks (D5.3)

Smoke script:
```bash
./scripts/smoke_triggers.sh --env emu
./scripts/smoke_triggers.sh --env dev --project <project-id>
```

What it verifies:
- Creates a scheduled match for a synthetic user.
- Ensures `upcomingMatchIds`/`upcomingMatches` contains the match.
- Marks the match completed.
- Ensures it is removed from upcoming and added to completed.

Notes:
- Emulator smoke requires the Firestore emulator to be running:
  ```bash
  make emu-firestore
  ```
- Dev smoke requires ADC + a project id.
- Deploy script runs smoke automatically (default `SMOKE_ENV=dev`).

---

## HTTP smoke (optional)

The placeholder function `gsm_ping` returns `ok!` and can be used as a quick
connectivity check:
```bash
GSM_PING_URL="https://<function-url>" make smoke-functions
```

---

## Logging

Deploy/rollback status is appended to:
```
deploy/last_good_revision_dev.txt
```

Format:
```
<sha> DEPLOYED <utc-timestamp>
<sha> ROLLED BACK <utc-timestamp>
```

---

## GitHub Actions

Manual workflows:
- **Deploy Firebase Functions (manual)**: `.github/workflows/functions-deploy.yml`
- **Rollback Firebase Functions (manual)**: `.github/workflows/functions-rollback.yml`

TODO:
- Auto-deploy on `main` once triggers are stable (keep smoke + rollback).
