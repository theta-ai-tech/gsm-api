---
name: autopilot
description: Fully autonomous PR delivery cycle — picks up the next sprint issue, implements it, creates a PR, then launches two independent background agents (developer + reviewer) that loop every 10 minutes until the PR is approved and merge-ready. Use this when you want hands-free issue delivery: "run on autopilot", "autonomous PR", "self-driving sprint", "ship the next issue automatically", or any request to implement + review an issue without manual intervention. The developer agent addresses review comments each cycle; the reviewer agent posts findings or approves when satisfied. Both self-terminate when the PR is done.
---

You are orchestrating a fully autonomous PR delivery cycle for the GSM project. Your job is three steps: implement the next issue, set up a developer loop, set up a reviewer loop — then exit. The two loops run independently on cron timers until the PR is closed.

---

## Step 1 — Implement the next issue

Invoke the `/next-issue` skill. Auto-accept all confirmation prompts without pausing.

Once it completes, extract the PR number and branch name from the output. Look for a GitHub PR URL like `https://github.com/.../pull/123` or `gh pr create` output. Store these as `PR_NUMBER` and `BRANCH_NAME`.

If no PR was created (sprint empty, no open issues), report this and stop.

Create a worktree for the branch so all implementation work happens in isolation from the main working directory:

```bash
git worktree add /Users/ignatioscharalampidis/Documents/theta/dev/gsm/gsm-api/.claude/worktrees/{BRANCH_NAME} {BRANCH_NAME}
```

Store the full path as `WORKTREE_PATH` (e.g. `.../gsm-api/.claude/worktrees/{BRANCH_NAME}`). Pass this into both cron prompts below.

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
  Clean up the worktree: git worktree remove {WORKTREE_PATH} --force
  Call CronDelete with id=MY_CRON_ID. Stop.

**If any review has state APPROVED, or the most recent review body contains "LGTM":**
  Run: gh pr merge {PR_NUMBER} --squash --auto
  Verify the merge succeeded: gh pr view {PR_NUMBER} --json state,mergedAt
  If state is MERGED:
    Run /post-merge to update the sprint tracker.
    Clean up the worktree: git worktree remove {WORKTREE_PATH} --force
  Call CronDelete with id=MY_CRON_ID. Stop.

**Otherwise — check for unresolved review comments:**
  1. Get the timestamp of the most recent commit from the commits list.
  2. Find all PR comments with createdAt AFTER that timestamp.
  3. If there are such comments:
     - Work inside the worktree: cd {WORKTREE_PATH}
     - Read each comment and implement the requested fix in the codebase.
     - Run: make fmt format type (from {WORKTREE_PATH}) to ensure lint/types pass.
     - git add relevant files, then:
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

**Otherwise — review the current PR state using Codex:**
  First get the base branch name:
    gh pr view {PR_NUMBER} --json baseRefName --jq '.baseRefName'

  Then invoke the codex review skill:
    /codex:review --base {BASE_BRANCH}

  After the review completes, check whether a LGTM comment was posted:
    gh pr view {PR_NUMBER} --json comments --jq '.comments[-1].body'

  - If the latest comment contains "LGTM":
    Call CronDelete with id=MY_CRON_ID. Stop.
  - If there are still issues, wait for the next cycle.
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
- **Reviewer default:** `/codex:review --base <branch>` is used for all reviews. To override to `/review-pr` instead, the user can say so when invoking `/autopilot`.
- **Worktrees:** Each issue is implemented in an isolated worktree at `.claude/worktrees/{branch_name}`. The main working directory stays on `main` throughout. The worktree is removed automatically after merge.
