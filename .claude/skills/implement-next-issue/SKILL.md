---
name: implement-next-issue
description: Second half of the two-phase issue pickup workflow. Reads the implementation plan from the active worktree (.claude-plan.md), delegates to gsm-backend-developer, runs tests, commits, raises a PR, generates a smoke test script, and updates the sprint tracker. Fails immediately if no worktree or plan file is found — run /plan-next-issue first. Run this on Sonnet 4.6. Use when ready to implement: "/implement-next-issue", "implement next issue", "implement the plan".
---

# implement-next-issue

This is the **implementation half** of a two-phase workflow. `/plan-next-issue` (Opus) has already picked the issue, created the worktree, researched the codebase, and written a detailed plan. Your job is to execute that plan.

**Do not proceed if either of these is missing:**
1. An active worktree under `{MAIN_REPO_ROOT}/.claude/worktrees/`
2. A `.claude-plan.md` file inside that worktree

Both must exist. If either is absent, stop immediately and tell the user to run `/plan-next-issue` first.

---

## Step 1 — Find the active worktree and load the plan

Run:
```bash
git -C {MAIN_REPO_ROOT} worktree list --porcelain
```

Find the worktree under `.claude/worktrees/`. Capture its path as `WORKTREE_PATH` and its branch as `BRANCH_NAME`.

If no worktree exists:
> No active worktree found. Run `/plan-next-issue` first to pick an issue and generate the implementation plan.

Check the plan file exists:
```bash
ls {WORKTREE_PATH}/.claude-plan.md
```

If not found:
> No implementation plan found at {WORKTREE_PATH}/.claude-plan.md. Run `/plan-next-issue` first.

Read the plan:
```
Read {WORKTREE_PATH}/.claude-plan.md
```

Extract from the plan's Session Variables section:
- `MAIN_REPO_ROOT`
- `ISSUE_NUMBER`
- `BRANCH_NAME`
- `WORKTREE_PATH`

Use these values for all subsequent steps — do not re-derive them.

---

## Step 2 — Implement (delegate to gsm-backend-developer)

Delegate implementation to the `gsm-backend-developer` agent. Pass the full plan content as context so the agent can work autonomously without fetching the issue or reading the wiki.

The agent must work **entirely inside `WORKTREE_PATH`**:
- All file reads/edits/writes at absolute paths under `{WORKTREE_PATH}`
- All git commands as `git -C {WORKTREE_PATH} ...`
- Lint/format/type-check: `make -C {WORKTREE_PATH} VENV={MAIN_REPO_ROOT}/.venv fmt format type`

The agent must **not** commit or push yet — that happens in Steps 3 and 4 below.

---

## Step 3 — Run tests

Check whether the Firestore emulator is up:
```bash
curl -s --connect-timeout 2 http://127.0.0.1:8082 > /dev/null 2>&1 && echo "up" || echo "down"
```

**If up:** run the full test suite against the worktree:
```bash
PYTHONPATH={WORKTREE_PATH}/api make -C {WORKTREE_PATH} VENV={MAIN_REPO_ROOT}/.venv test
```

Sanity-check that the worktree's code is what's being tested (not main):
```bash
PYTHONPATH={WORKTREE_PATH}/api {MAIN_REPO_ROOT}/.venv/bin/python -c "import app, os; print(os.path.dirname(app.__file__))"
```
The printed path must start with `{WORKTREE_PATH}/api/app`. If it shows `{MAIN_REPO_ROOT}/api/app`, stop and investigate.

All tests must pass before committing. Fix failures in the worktree if needed.

**If down:** stop and tell the user:
> The Firestore emulator is not running. Start it with `make emu-all` and `make api-dev-emu-auth` in separate terminals, then re-run `/implement-next-issue`. Or confirm explicitly to skip tests.

Only skip tests if the user explicitly confirms.

---

## Step 4 — Commit

Stage all changed files and commit from inside the worktree:
```bash
git -C {WORKTREE_PATH} add <relevant files>
git -C {WORKTREE_PATH} commit -m "<type>: <short imperative description> (#<issue-number>)"
```

Do **not** stage or commit `.claude-plan.md` — it is a planning artifact, not part of the feature.

Follow commit style: short imperative title with scope, e.g. `feat: LG-1 add league browse fields (#248)`.

---

## Step 5 — Raise a PR

Push the branch and open a PR:
```bash
git -C {WORKTREE_PATH} push -u origin {BRANCH_NAME}
(cd {WORKTREE_PATH} && gh pr create --title "<type>: <description> (#<issue-number>)" --body "...")
```

PR body must include:
- **Context & Technical Overview** — what / why / tech dive for fresh-context reviewers
- Summary of what was implemented
- **Acceptance Criteria** checklist (use the Definition of Done from the plan)
- `Closes #<issue-number>`

---

## Step 6 — Generate smoke test script

Check whether the PR body contains a "How to test manually" section:
```bash
gh pr view <PR-number> --json body --jq '.body' | grep -i "how to test manually"
```

**If the section exists:** invoke the `/smoke-test` skill to generate `tests/smoke/pr-{N}.sh` inside the worktree.

**IMPORTANT:** write to `{WORKTREE_PATH}/tests/smoke/pr-{N}.sh`, not to `{MAIN_REPO_ROOT}/tests/smoke/`. Verify the file is in the worktree before committing. If the skill wrote it to the main repo, move it:
```bash
mv {MAIN_REPO_ROOT}/tests/smoke/pr-{N}.sh {WORKTREE_PATH}/tests/smoke/pr-{N}.sh
```

Then commit and push from the worktree:
```bash
git -C {WORKTREE_PATH} add tests/smoke/pr-{N}.sh
git -C {WORKTREE_PATH} commit -m "test: add smoke test script for PR #{N}"
git -C {WORKTREE_PATH} push
```

**If no manual test section:** skip this step.

---

## Step 7 — Update sprint tracker

Update `{MAIN_REPO_ROOT}/.agent/SPRINT.md` (main checkout's copy, **not** the worktree's):
1. Find the row for `#<issue-number>` in the "In Sprint" table.
2. The Status should already be `🚧 In Progress` (set by `/plan-next-issue`). Leave it.
3. Set **PR** to `#<PR-number>`.

---

## Step 8 — Report

Summarise:
- Implementation complete, tests passed
- PR raised: link
- Smoke test generated (or skipped)
- Sprint tracker updated with PR number
- Worktree left at `{WORKTREE_PATH}` for review-comment fixes
