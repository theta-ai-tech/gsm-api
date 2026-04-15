---
name: pre-merge-checks
description: Pre-merge CI gate for GSM PRs — syncs the branch with main, runs lint/type/test locally, and validates GitHub CI status. Invoke this inside the autopilot developer cron BEFORE `gh pr merge`. Pass PR_NUMBER and WORKTREE_PATH as arguments. Returns PRE_MERGE_VERDICT: PASS or FAIL on the last line. Also use this manually any time you want to confirm a branch is safe to merge: "run pre-merge checks", "is the PR safe to merge?", "check CI before merging".
---

You are running the pre-merge gate for a GSM API pull request.

## Why this matters

Two things can silently break a merge:
1. **Local breakage** — lint, types, or tests fail in the current worktree state.
2. **Stale branch** — another PR landed on main after this branch was cut, leaving unformatted or incompatible files in the branch that CI catches but the merge doesn't fix.

Both must be green before the squash merge runs.

---

## Inputs

Extract from the invocation context:
- `PR_NUMBER` — the pull request number (e.g. 247)
- `WORKTREE_PATH` — absolute path to the feature branch worktree (e.g. `/Users/ignatioscharalampidis/Documents/theta/dev/gsm/gsm-api/.claude/worktrees/my-branch`)
- `MAIN_REPO` — always `/Users/ignatioscharalampidis/Documents/theta/dev/gsm/gsm-api`

---

## Step 1 — Sync branch with main

Merge the latest main into the worktree branch so that any files changed by other PRs since this branch was cut are included before CI and local checks run:

```bash
cd {WORKTREE_PATH}
git fetch origin main
git merge origin/main --no-edit 2>&1
```

**If conflicts:** Stop immediately and output:
```
PRE_MERGE_VERDICT: FAIL
Reason: Merge conflict with main. Resolve manually before retrying.
```

**If new commits were added** (git merge wasn't a no-op), push the branch:
```bash
git push
```
Then sleep 30 seconds before checking CI to give GitHub Actions time to pick up the new push.

**If already up to date:** Continue immediately.

---

## Step 2 — Local lint and type checks

Run from the main repo root (where `.venv` lives), targeting the worktree's files via the shared venv:

```bash
make -C {MAIN_REPO} fmt format type 2>&1
```

If any of these fail, capture the error output, then stop:
```
PRE_MERGE_VERDICT: FAIL
Reason: Local lint/type check failed.
<error output>
```

---

## Step 3 — Local tests (emulator-gated)

Check whether the Firestore emulator is running:
```bash
curl -s --connect-timeout 2 http://127.0.0.1:8082 > /dev/null 2>&1 && echo "up" || echo "down"
```

**If up:** Run the full test suite:
```bash
make -C {MAIN_REPO} test 2>&1
```
If tests fail, stop:
```
PRE_MERGE_VERDICT: FAIL
Reason: Test suite failed. Fix failing tests before merging.
<failing test output>
```

**If down:** Log a warning (`⚠️ Emulator not running — skipping integration tests`) and continue. Don't block the merge solely because the emulator is offline; CI covers this.

---

## Step 4 — GitHub CI status

Fetch the current check state:
```bash
gh pr view {PR_NUMBER} --json statusCheckRollup 2>&1
```

Parse `.statusCheckRollup[]`. Evaluate each check:

| Conclusion | Status | Action |
|------------|--------|--------|
| `FAILURE` | any | **FAIL** — name the failing check |
| `SUCCESS` | `COMPLETED` | OK |
| any | `IN_PROGRESS` or `QUEUED` | Wait 30s and retry (up to 3 times total) |
| `SKIPPED` or `NEUTRAL` | any | Treat as OK |

If after 3 retries checks are still pending, output:
```
PRE_MERGE_VERDICT: FAIL
Reason: CI checks still pending after 90s. Wait for them to complete before merging.
```

If any check has `conclusion == "FAILURE"`:
```
PRE_MERGE_VERDICT: FAIL
Reason: GitHub CI check "{name}" failed. Review the run logs before merging.
URL: {detailsUrl}
```

---

## Step 5 — Verdict

If all four steps passed, output on the final line:
```
PRE_MERGE_VERDICT: PASS
```

The autopilot developer cron reads this line. It proceeds with `gh pr merge --squash` only on `PASS`. On `FAIL`, it logs the reason and waits for the next cycle without attempting the merge.
