---
name: smoke-test
description: Run or generate smoke tests for a GSM API pull request. Use this whenever someone says "smoke test PR #N", "run manual tests for PR", "verify the manual test steps", "test this PR against the emulator", or when the qa-tester agent needs to validate a PR. The skill checks for an existing test script first (regression mode) — if found, runs it directly. If not, it reads the PR's "How to test manually" section, generates a self-contained bash script at tests/smoke/pr-{N}.sh translating all steps (including Firestore UI edits) into runnable commands, runs it, and reports PASS/FAIL per step.
---

You are generating and running smoke tests for a GSM API pull request against the local Firestore emulator.

Assumes the emulator stack is already running (`make emu-all` + `make api-dev-emu-auth`). If steps fail with connection errors, tell the user and stop.

---

## Step 1 — Resolve the PR number

Accept any of: `smoke-test 244`, `smoke-test PR #244`, `smoke-test https://github.com/.../pull/244`. Extract the integer PR number.

---

## Step 2 — Check for an existing script

```bash
ls tests/smoke/pr-{N}.sh 2>/dev/null
```

**If the script exists:** skip to Step 5 — run it directly. No re-parsing needed.

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
# Requires: make emu-all + make api-dev-emu-auth running

set -uo pipefail

PASS=0
FAIL=0
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
API="http://localhost:8000"
FIRESTORE="http://127.0.0.1:8080/v1/projects/gsm-dev-f70d0/databases/(default)/documents"

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
TOKEN=$(bash "$REPO_ROOT/scripts/get_emu_token.sh" {USER_ID} 2>/dev/null | tail -1)
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

## Step 5 — Run the script

```bash
bash tests/smoke/pr-{N}.sh
```

Capture the full output. Parse the summary line at the end.

---

## Step 6 — Report results

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

- Run from the repo root — the script uses relative paths to `scripts/get_emu_token.sh`
- If the emulator stack isn't running, connection errors will appear immediately — tell the user to run `make emu-all` + `make api-dev-emu-auth` first (or `/start-emulators` once that skill exists)
- The saved script at `tests/smoke/pr-{N}.sh` is always committed in Step 4.5 — it becomes the regression test for that endpoint and must land in `main` alongside the feature
- Scripts are idempotent by design (teardown resets Firestore state) so they can be run repeatedly
