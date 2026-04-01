---
name: autopilot
description: Fully autonomous PR delivery cycle — picks up the next sprint issue, implements it, creates a PR, then launches two independent background agents (developer + reviewer) that loop every 10 minutes until the PR is approved and merge-ready. Use this when you want hands-free issue delivery: "run on autopilot", "autonomous PR", "self-driving sprint", "ship the next issue automatically", or any request to implement + review an issue without manual intervention. The developer agent addresses review comments each cycle; the reviewer agent posts findings or approves when satisfied. Both self-terminate when the PR is done.
---

You are orchestrating a fully autonomous PR delivery cycle for the GSM project. Your job is three steps: implement the next issue, set up a developer loop, set up a reviewer loop — then exit. The two loops run independently on cron timers until the PR is closed.

---

## Step 1 — Implement the next issue

Invoke the `/next-issue` skill. Auto-accept all confirmation prompts without pausing.

Once it completes, extract the PR number from the output. Look for a GitHub PR URL like `https://github.com/.../pull/123` or `gh pr create` output. Store this as `PR_NUMBER`.

If no PR was created (sprint empty, no open issues), report this and stop.

---

## Step 2 — Create the developer loop (Cron A)

Create a recurring cron every 10 minutes with this exact prompt (substitute the real PR number for `{PR_NUMBER}`):

```
AUTOPILOT_TAG: autopilot-dev-pr-{PR_NUMBER}

You are the developer agent in an autonomous PR cycle.

## Self-identification (run this first)
Call CronList. Find the entry whose prompt contains the text:
  AUTOPILOT_TAG: autopilot-dev-pr-{PR_NUMBER}
Save that entry's id as MY_CRON_ID. You will use it to self-terminate.

## Check PR state
Run: gh pr view {PR_NUMBER} --json state,reviews,comments,commits,headRefName

**If state is MERGED or CLOSED:**
  Call CronDelete with id=MY_CRON_ID. Stop.

**If any review has state APPROVED, or the most recent review body contains "LGTM":**
  Run: gh pr merge {PR_NUMBER} --squash --auto
  Verify the merge succeeded: gh pr view {PR_NUMBER} --json state,mergedAt
  If state is MERGED, run /post-merge to update the sprint tracker.
  Call CronDelete with id=MY_CRON_ID. Stop.

**Otherwise — check for unresolved review comments:**
  1. Get the timestamp of the most recent commit from the commits list.
  2. Find all PR comments with createdAt AFTER that timestamp.
  3. If there are such comments:
     - Read each one and implement the requested fix in the codebase.
     - Run: make fmt format type (inside the project venv) to ensure lint/types pass.
     - Run: git add -p (stage relevant changes) then:
       git commit -m "fix: address review comments on PR #{PR_NUMBER}"
       git push
  4. If there are no new comments since the last push, do nothing and wait for the next cycle.
```

Use cron expression `*/10 * * * *` and `recurring: true`.

---

## Step 3 — Create the reviewer loop (Cron B)

Create a recurring cron every 10 minutes, offset by ~5 minutes from Cron A (use `*/10 * * * *` — the natural timing drift will offset the two after the first cycle, or you can pick `3-58/10 * * * *` for a slight offset).

Use this exact prompt (substitute the real PR number):

```
AUTOPILOT_TAG: autopilot-review-pr-{PR_NUMBER}

You are the reviewer agent in an autonomous PR cycle.

## Self-identification (run this first)
Call CronList. Find the entry whose prompt contains the text:
  AUTOPILOT_TAG: autopilot-review-pr-{PR_NUMBER}
Save that entry's id as MY_CRON_ID. You will use it to self-terminate.

## Check PR state
Run: gh pr view {PR_NUMBER} --json state,reviews,url

**If state is MERGED or CLOSED:**
  Call CronDelete with id=MY_CRON_ID. Stop.

**If you have already posted an APPROVED review on this PR (check reviews list for your prior approval):**
  Call CronDelete with id=MY_CRON_ID. Stop.

**Otherwise — review the current PR state:**
  Run /review-pr {PR_NUMBER} use codex.

  After posting any findings:
  - If all prior findings from previous cycles appear to be addressed (new commits pushed, prior comment threads resolved) AND no new issues were found in this cycle:
    Run: gh pr review {PR_NUMBER} --approve --body "LGTM — all findings addressed. Approved by autopilot reviewer."
    Call CronDelete with id=MY_CRON_ID. Stop.
  - If there are still issues, post your findings as review comments and wait for the next cycle.
```

Use `recurring: true`.

---

## Step 4 — Report and exit

Once both crons are registered, report:

- **PR:** #{PR_NUMBER} + URL
- **Cron A (developer):** job ID, fires every 10 min
- **Cron B (reviewer):** job ID, fires every 10 min
- **To monitor:** `gh pr view {PR_NUMBER} --json state,reviews,comments` or `CronList` (active entries = still running; gone = self-terminated = done)

Then exit. Do not wait. The crons run independently.

---

## Notes

- Both crons are session-bound (they die if this Claude session ends). For persistence across restarts, set `durable: true` when creating them.
- `gh pr merge --squash --auto` will queue the merge but may be blocked by branch protection rules requiring human approval. If it fails, the developer loop will report the error in its run but continue polling.
- The two loops communicate only through GitHub — PR state, commits, and review comments are the shared message bus.
