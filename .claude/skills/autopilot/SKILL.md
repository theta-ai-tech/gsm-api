---
name: autopilot
description: Fully autonomous PR delivery cycle — picks up the next sprint issue, implements it, creates a PR, then launches two independent background agents (developer + reviewer) that loop every 10 minutes until the PR is approved and merge-ready. Use this when you want hands-free issue delivery: "run on autopilot", "autonomous PR", "self-driving sprint", "ship the next issue automatically", or any request to implement + review an issue without manual intervention. The developer agent addresses review comments each cycle; the reviewer agent posts findings or approves when satisfied. Both self-terminate when the PR is done.
---

You are orchestrating a fully autonomous PR delivery cycle for the GSM project. Your job is three steps: implement the next issue, set up a developer loop, set up a reviewer loop — then exit. The two loops run independently on cron timers until the PR is closed.

---

## Preflight — Verify reviewer token

Before doing anything else, check that the reviewer token is available:

```bash
echo ${GSM_REVIEWER_TOKEN:0:4}
```

If the output is empty or blank, stop immediately and tell the user:

> `GSM_REVIEWER_TOKEN` is not set. Export it in your shell (`~/.zshrc`) before running autopilot:
> ```bash
> export GSM_REVIEWER_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxx
> ```
> The reviewer account is `iggy-theta-tech`. It must have Write access to `theta-ai-tech/gsm-api`.

Also verify the token is valid and the account has repo access:

```bash
GH_TOKEN=$GSM_REVIEWER_TOKEN gh api user --jq '.login'
```

The output must be `iggy-theta-tech`. If it fails or returns a different username, stop and report the error.

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

**If there is a formal APPROVED review from `iggy-theta-tech`:**
  Check with:
    gh pr view {PR_NUMBER} --json reviews --jq '.reviews[] | select(.author.login=="iggy-theta-tech" and .state=="APPROVED")'
  If that returns a non-empty result, proceed to merge:
    gh pr merge {PR_NUMBER} --squash
  Verify the merge succeeded: gh pr view {PR_NUMBER} --json state,mergedAt
  If state is MERGED:
    Update the sprint tracker (inline — do not call /post-merge):
      1. Read .agent/SPRINT.md
      2. Find the row for this issue in the "In Sprint" table and set its Status to ✅ Done
      3. Add a row to "Done This Sprint": | #ISSUE | title | #PR_NUMBER | YYYY-MM-DD (today) |
         If the table only has a placeholder row, replace it.
    Clean up the worktree: git worktree remove {WORKTREE_PATH} --force
    Pull latest main: git -C /Users/ignatioscharalampidis/Documents/theta/dev/gsm/gsm-api pull origin main
  Call CronDelete with id=MY_CRON_ID. Stop.
  If the merge command fails (e.g. branch protection not met), log the error and wait for the next cycle — do not retry more than once per cycle.

**Otherwise — check for unresolved review comments:**
  1. Get the timestamp of the most recent commit from the commits list.
  2. Find all PR comments with createdAt AFTER that timestamp.
  3. If there are such comments:
     - Work inside the worktree: cd {WORKTREE_PATH}
     - Read each comment and implement the requested fix in the codebase.
     - Run: make fmt format type (from {WORKTREE_PATH}) to ensure lint/types pass.
     - Check if the Firestore emulator is up:
         curl -s --connect-timeout 2 http://127.0.0.1:8082 > /dev/null 2>&1 && echo "up" || echo "down"
       If up: run `make test` from the MAIN repo root (not the worktree) — `.venv` lives there:
         make -C /Users/ignatioscharalampidis/Documents/theta/dev/gsm/gsm-api test
       If tests fail, fix them in the worktree before pushing.
       If down: log a warning ("emulator not running — skipping tests") and continue.
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
All gh commands in this agent run as iggy-theta-tech via GH_TOKEN=$GSM_REVIEWER_TOKEN.

Run: GH_TOKEN=$GSM_REVIEWER_TOKEN gh pr view {PR_NUMBER} --json state,reviews,url

**If state is MERGED or CLOSED:**
  Call CronDelete with id=MY_CRON_ID. Stop.

**If `iggy-theta-tech` has already posted an APPROVED review on this PR:**
  Check with:
    GH_TOKEN=$GSM_REVIEWER_TOKEN gh pr view {PR_NUMBER} --json reviews --jq '.reviews[] | select(.author.login=="iggy-theta-tech" and .state=="APPROVED")'
  If non-empty, Call CronDelete with id=MY_CRON_ID. Stop.

**Otherwise — run QA then code review:**

  Both gates must pass before approving. Run them in order.

  ## Gate 1: QA smoke tests (gsm-qa-tester)

  Delegate to the gsm-qa-tester agent with the PR number.
  The agent will run tests/smoke/pr-{PR_NUMBER}.sh (or generate it from the PR),
  post a QA comment to the PR as iggy-theta-tech, and return a verdict line:
    QA_VERDICT: PASS | FAIL | SKIP | NO_TESTS

  Parse the last line of the agent's output for the verdict.

  **If QA_VERDICT is FAIL:**
    The QA agent has already posted a comment with failure details.
    Post a review requesting changes:
      GH_TOKEN=$GSM_REVIEWER_TOKEN gh pr review {PR_NUMBER} --request-changes \
        --body "QA smoke tests failed — see QA comment above for details. Addressing these before code review."
    Wait for the next cycle.

  **If QA_VERDICT is PASS, SKIP, or NO_TESTS:**
    Continue to Gate 2.

  ## Gate 2: Code review (Codex)

  Step 1: Fetch the diff and PR context (read-only, default gh auth):
    gh pr diff {PR_NUMBER}
    gh pr view {PR_NUMBER} --json body,title,comments,reviews

  Step 2: Invoke Codex as a subagent to analyse the diff.
    Pass it the diff and this instruction:
      "Review this PR diff for correctness, style, test coverage, and GSM project conventions.
       Do NOT post anything to GitHub. Return your findings as structured text:
       - A verdict: APPROVE or REQUEST_CHANGES
       - A list of specific issues (if any), each with file, line, and suggested fix
       - A summary comment body suitable for posting as a GitHub review"

  Step 3: Post Codex findings and take action. All gh commands use GH_TOKEN=$GSM_REVIEWER_TOKEN.

  **If Codex verdict is APPROVE:**
    GH_TOKEN=$GSM_REVIEWER_TOKEN gh pr review {PR_NUMBER} --approve --body "<Codex summary>"
    Verify:
      GH_TOKEN=$GSM_REVIEWER_TOKEN gh pr view {PR_NUMBER} --json reviews \
        --jq '.reviews[] | select(.author.login=="iggy-theta-tech") | .state'
    The output must be "APPROVED". If it is, call CronDelete with id=MY_CRON_ID. Stop.

  **If Codex verdict is REQUEST_CHANGES:**
    GH_TOKEN=$GSM_REVIEWER_TOKEN gh pr review {PR_NUMBER} --request-changes \
      --body "<Codex summary with issues>"
    Wait for the next cycle — the developer cron will pick up the comments and push fixes.
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
- `gh pr merge --squash` requires a formal `APPROVED` review from `iggy-theta-tech` before it runs. If the merge fails, the developer loop logs the error and waits for the next cycle.
- After a successful merge, `git pull origin main` is run in the main working directory to keep it in sync.
- The two loops communicate only through GitHub — PR state, commits, and review comments are the shared message bus.
- **Reviewer default:** `/codex:review --base <branch>` is used for all reviews. To override to `/review-pr` instead, the user can say so when invoking `/autopilot`.
- **Worktrees:** Each issue is implemented in an isolated worktree at `.claude/worktrees/{branch_name}`. The main working directory stays on `main` throughout. The worktree is removed automatically after merge.
