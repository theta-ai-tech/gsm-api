---
name: smoke-test
description: Run or generate smoke tests for a GSM API pull request. Use this whenever someone says "smoke test PR #N", "run manual tests for PR", "verify the manual test steps", "test this PR against the emulator", or when the qa-tester agent needs to validate a PR. The skill checks for an existing test script first (regression mode) — if found, runs it directly. If not, it reads the PR's "How to test manually" section, generates a self-contained bash script at tests/smoke/pr-{N}.sh translating all steps (including Firestore UI edits) into runnable commands. It starts the API from the checkout/worktree under test on API_PORT=8000+PR_NUMBER by default, runs the script, stops only that skill-owned API process, and reports PASS/FAIL per step.
---

You are generating and running smoke tests for a GSM API pull request against local Firestore/Auth emulators and a PR-scoped local API.

Assume the Firestore/Auth emulators are already running (`make emu-all`). Do not assume an existing API on port 8000 is serving the PR code. Start the API yourself from the checkout/worktree under test, using the main repo venv and `API_PORT=8000+PR_NUMBER` by default.

---

## Step 1 — Resolve the PR number

Accept any of: `smoke-test 244`, `smoke-test PR #244`, `smoke-test https://github.com/.../pull/244`. Extract the integer PR number.

---

## Step 2 — Check for an existing script

```bash
ls tests/smoke/pr-{N}.sh 2>/dev/null
```

**If the script exists:** skip PR-body parsing and script generation, then continue at Step 5 so the API is still started from the correct checkout/worktree before the script runs.

**If not:** continue to Step 3.

---

## Step 3 — Fetch the PR and parse manual test steps

```bash
gh pr view {N} --json body,title --jq '{title: .title, body: .body}'
```

Find the section titled "How to test manually" (or similar — "Manual testing", "Testing steps", etc.). Extract every numbered step.

Ignore setup steps that are already handled by the running emulator stack (e.g. "Terminal 1: make emu-all" — skip these, they're already running). Focus on the actual test actions:
- curl calls to the API
- Firestore state changes described as UI interactions
- Expected values to assert

If the PR has no manual test section, report this and stop — there's nothing to generate.

---

## Step 4 — Generate tests/smoke/pr-{N}.sh

Create `tests/smoke/` if it doesn't exist. Write the script using this structure:

```bash
#!/usr/bin/env bash
# Smoke tests for PR #{N}: {title}
# Generated: {date}
# Usage: bash tests/smoke/pr-{N}.sh
#
# Requires: make emu-all running. The smoke-test skill starts the API.

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="${API_BASE_URL:-http://127.0.0.1:8000}"
FIRESTORE="http://127.0.0.1:8082/v1/projects/gsm-dev-f70d0/databases/(default)/documents"

# ── Venv resolution ─────────────────────────────────────────────────────────
# `.venv` only lives in the main checkout, never in git worktrees. When the
# script runs from a worktree, fall back to the main worktree's path via
# `git worktree list`. Then export PYTHONPATH so `import app` resolves to the
# *current* tree's source rather than the editable install's target inside
# the main checkout — otherwise the script would silently exercise main's code.
if [ -f "$REPO_ROOT/.venv/bin/activate" ]; then
  VENV_DIR="$REPO_ROOT/.venv"
else
  MAIN_WT=$(git -C "$REPO_ROOT" worktree list --porcelain 2>/dev/null \
    | awk '/^worktree / {print $2; exit}')
  VENV_DIR="$MAIN_WT/.venv"
fi
if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo "ABORT: no venv found at $VENV_DIR (or $REPO_ROOT/.venv). Run 'make venv && make install' in the main checkout."
  exit 1
fi
export PYTHONPATH="$REPO_ROOT/api${PYTHONPATH:+:$PYTHONPATH}"
# Use this in every shell-out: `. "$VENV_DIR/bin/activate" && python3 -c '...'`

# ── Helpers ────────────────────────────────────────────────────────────────

assert_eq() {
  local name="$1" actual="$2" expected="$3"
  if [ "$actual" = "$expected" ]; then
    echo "  ✓ $name"
    ((PASS++)) || true
  else
    echo "  ✗ $name"
    echo "    expected: $expected"
    echo "    actual:   $actual"
    ((FAIL++)) || true
  fi
}

firestore_patch() {
  # Usage: firestore_patch <collection/docId> <json-body> [field_mask]
  local path="$1" body="$2" mask="${3:-}"
  local url="$FIRESTORE/$path"
  [ -n "$mask" ] && url="$url?updateMask.fieldPaths=$mask"
  curl -s -X PATCH "$url" -H "Content-Type: application/json" -d "$body" > /dev/null
}

firestore_get_field() {
  # Usage: firestore_get_field <collection/docId> <jq-path>
  curl -s "$FIRESTORE/$1" | jq -r "$2 // \"null\""
}

# ── Token acquisition ───────────────────────────────────────────────────────
# Adjust user ID if the PR tests a different seeded user
TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" {USER_ID} -t 2>/dev/null)
if [ -z "$TOKEN" ]; then
  echo "ERROR: Could not get auth token for {USER_ID}. Is the auth emulator running?"
  exit 1
fi

# ── Tests ───────────────────────────────────────────────────────────────────

{TEST_BLOCKS}

# ── Teardown ────────────────────────────────────────────────────────────────
{TEARDOWN_BLOCK}

# ── Summary ─────────────────────────────────────────────────────────────────
echo ""
echo "Smoke tests PR #{N}: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
```

### Translation rules

**curl API checks** — wrap the existing command in `assert_eq`:
```bash
# Step N: {description}
ACTUAL=$(curl -s -H "Authorization: Bearer $TOKEN" $API{path} | jq -r '{jq_filter}')
assert_eq "{description}" "$ACTUAL" "{expected_value}"
```

**Firestore UI edit** — translate "open Firestore UI, set field X to Y" into a `firestore_patch` call:
```bash
# Step N: Set {field} = {value} in Firestore
firestore_patch "{collection}/{docId}" '{"fields":{...}}' "{field.path}"
```

Use the Firestore REST field encoding:
- string: `{"stringValue": "foo"}`
- bool: `{"booleanValue": true}`
- int: `{"integerValue": "42"}`
- null/delete: omit the field and use updateMask

**Nested map fields** (e.g. `preferences.feedOptOut`): encode as nested `mapValue`:
```json
{"fields":{"preferences":{"mapValue":{"fields":{"feedOptOut":{"booleanValue":true}}}}}}
```
Use `updateMask.fieldPaths=preferences.feedOptOut` to avoid overwriting sibling fields.

**Teardown**: if a test mutates Firestore state, add a corresponding reset at the end of the script so repeated runs are idempotent.

### Choosing the user ID

Look in the PR body for the user referenced in `get_emu_token.sh` calls (e.g. `user_ignatios`). If none specified, default to `user_ignatios`.

---

## Step 4.5 — Commit the generated script

After writing the script, commit it to the current branch so it lands in the PR and eventually in `main`:

```bash
git add tests/smoke/pr-{N}.sh
git commit -m "test: add smoke test script for PR #{N}"
git push
```

If the working tree is inside a worktree (`git worktree list` shows a path other than the main repo), run the commit from that worktree path. If there is nothing to commit (file already tracked and unchanged), skip silently.

---

## Step 5 — Start the PR API

Run the API from the checkout/worktree containing `tests/smoke/pr-{N}.sh`. This is required because `.venv` usually lives in the main checkout, while the PR code lives in a git worktree.

Set:

```bash
SCRIPT_ROOT="$(pwd)"
MAIN_REPO_ROOT="$(git -C "$SCRIPT_ROOT" worktree list --porcelain | awk '/^worktree / {print $2; exit}')"
VENV="$MAIN_REPO_ROOT/.venv"
FIRESTORE_EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-127.0.0.1:8082}"
FIREBASE_AUTH_EMULATOR_HOST="${FIREBASE_AUTH_EMULATOR_HOST:-127.0.0.1:9099}"
GOOGLE_CLOUD_PROJECT="${GOOGLE_CLOUD_PROJECT:-gsm-dev-f70d0}"
```

If `API_BASE_URL` is already exported, respect it and do not start or stop an API process. Otherwise, the skill owns the API process for this run:

```bash
API_PORT="${API_PORT:-$((8000 + {N}))}"
API_BASE_URL="http://127.0.0.1:$API_PORT"
PID_FILE="/tmp/gsm-api-pr-{N}.pid"
LOG_FILE="/tmp/gsm-api-pr-{N}.log"
```

If `API_PORT` is already in use by a previous skill-owned process for this PR, stop that PID and restart it. If the port is in use by anything else, stop immediately. Do not kill arbitrary processes and do not choose a different port unless the user explicitly exported `API_PORT` or `API_BASE_URL`.

Start the API in the background:

```bash
test -f "$VENV/bin/activate" || {
  echo "ABORT: no venv found at $VENV. Run 'make venv && make install' in the main checkout."
  exit 1
}

if grep -q 'API_PORT' "$SCRIPT_ROOT/ops/Makefile"; then
  make -C "$SCRIPT_ROOT" VENV="$VENV" API_PORT="$API_PORT" api-dev-emu-auth >"$LOG_FILE" 2>&1 &
else
  (
    cd "$SCRIPT_ROOT" && \
    . "$VENV/bin/activate" && \
    export FIRESTORE_EMULATOR_HOST="$FIRESTORE_EMULATOR_HOST" && \
    export FIREBASE_AUTH_EMULATOR_HOST="$FIREBASE_AUTH_EMULATOR_HOST" && \
    export GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" && \
    export FIREBASE_PROJECT_ID="$GOOGLE_CLOUD_PROJECT" && \
    uvicorn app.main:app --reload --port "$API_PORT" --app-dir api
  ) >"$LOG_FILE" 2>&1 &
fi
echo $! >"$PID_FILE"
```

Wait up to 30 seconds for readiness:

```bash
for _ in $(seq 1 30); do
  if curl -fsS "$API_BASE_URL/health" >/dev/null; then
    break
  fi
  sleep 1
done
curl -fsS "$API_BASE_URL/health"
```

If the API never becomes healthy, stop immediately and report `$LOG_FILE`. Do not run the smoke script.

Preflight the emulators:

```bash
curl -fsS "http://$FIRESTORE_EMULATOR_HOST/v1/projects/$GOOGLE_CLOUD_PROJECT/databases/(default)/documents/" >/dev/null
FIREBASE_AUTH_EMULATOR_HOST="$FIREBASE_AUTH_EMULATOR_HOST" \
  GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" \
  bash scripts/get_emu_token.sh user_ignatios -t >/dev/null
```

If either emulator preflight fails, stop immediately. If the skill started the API, stop only that skill-owned API process. Tell the user to start `make emu-all`.

---

## Step 6 — Run the script

```bash
API_BASE_URL="$API_BASE_URL" \
FIRESTORE_EMULATOR_HOST="$FIRESTORE_EMULATOR_HOST" \
FIREBASE_AUTH_EMULATOR_HOST="$FIREBASE_AUTH_EMULATOR_HOST" \
GOOGLE_CLOUD_PROJECT="$GOOGLE_CLOUD_PROJECT" \
bash tests/smoke/pr-{N}.sh
```

Capture the full output. Parse the summary line at the end.

If the skill started the API process, stop only that skill-owned process after the smoke script completes.

---

## Step 7 — Report results

Print a clean summary:

```
Smoke test results — PR #{N}: {title}
──────────────────────────────────────
  ✓ {test name}
  ✓ {test name}
  ✗ {test name}
    expected: false
    actual:   null

{N} passed, {M} failed
```

If all passed: report success and note the script is saved at `tests/smoke/pr-{N}.sh` for future regression runs.

If any failed: show the failure details and suggest whether the issue is in the implementation or in the test setup (emulator not seeded, wrong user, etc.).

---

## Notes

- Run from the checkout/worktree containing `tests/smoke/pr-{N}.sh` — the script uses relative paths to `scripts/get_emu_token.sh`
- If the Firestore/Auth emulators are not running, connection errors will appear immediately — tell the user to run `make emu-all` first
- The skill starts a PR-scoped API by default on `API_PORT=8000+PR_NUMBER` (for example, PR 284 uses `8284`) and stops only the process it started
- The saved script at `tests/smoke/pr-{N}.sh` is always committed in Step 4.5 — it becomes the regression test for that endpoint and must land in `main` alongside the feature
- Scripts are idempotent by design (teardown resets Firestore state) so they can be run repeatedly
