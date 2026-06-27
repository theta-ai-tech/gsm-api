---
name: plan-next-issue
description: First half of the two-phase issue pickup workflow. Verifies the previous branch is merged, syncs main, cleans up the old worktree, picks the next sprint issue, creates the feature branch + worktree, then deeply reads the issue and relevant existing code to write a detailed implementation plan at {WORKTREE_PATH}/.claude-plan.md. Run this on Opus 4.6 — it is the research and planning phase. The plan is the handoff artifact to /implement-next-issue, which does the actual coding on Sonnet. Use when starting new work: "/plan-next-issue", "plan next issue", "pick up next issue and plan it".
---

# plan-next-issue

This is the **planning half** of a two-phase workflow. Your job is to do all the research, make all the key implementation decisions, and write a plan detailed enough that a separate session (running `/implement-next-issue`) can execute it without re-researching anything.

You are running on Opus. Use that capacity for genuine deep reading of the codebase — don't skim. The plan you write is the only thing the implementing session will have.

Define these path variables up front and substitute them throughout:

- `MAIN_REPO_ROOT` = the gsm-api repo root. Resolve with `git -C $(pwd) rev-parse --show-toplevel` if unsure.
- `BRANCH_NAME` = set in Step 5 once derived from the issue.
- `WORKTREE_PATH` = `{MAIN_REPO_ROOT}/.claude/worktrees/{BRANCH_NAME}` (set once BRANCH_NAME is known).

Follow these steps **in order**. Stop and inform the user if any step fails.

---

## Step 1 — Scan existing worktrees (informational only)

1. Run `git -C {MAIN_REPO_ROOT} worktree list --porcelain` to list all worktrees under `.claude/worktrees/`.
2. For any worktrees that exist, note their branches and PR status — but **do not block or stop**.
3. If there are merged branches with stale worktrees, clean them up:
   ```bash
   git -C {MAIN_REPO_ROOT} worktree remove {STALE_WORKTREE_PATH} --force
   git -C {MAIN_REPO_ROOT} branch -D {STALE_BRANCH}
   ```
4. Branches that are still `🚧 In Progress` (open PRs or no PR yet) are left untouched — parallel worktrees are allowed.
5. Continue to Step 2 regardless of how many active worktrees exist.

---

## Step 2 — Sync main

```bash
git -C {MAIN_REPO_ROOT} checkout main
git -C {MAIN_REPO_ROOT} pull origin main
```

---

## Step 3 — (Skipped — no single old worktree to clean up)

This step is intentionally skipped. Stale merged worktrees are handled in Step 1; active in-progress worktrees are left as-is.

---

## Step 4 — Determine the target issue

**If called as `/plan-next-issue <issue-number>`:** use that number directly.

**Otherwise:** find the next issue automatically:

### 4a — Sprint tracker first

1. Read `{MAIN_REPO_ROOT}/.agent/SPRINT.md`, "In Sprint" table.
2. Find the first row with Status `📋 Planned`.
3. Fetch its details: `gh issue view <number> --json number,title,labels`.

### 4b — Fall back to GitHub if sprint is complete

If all rows are `✅ Done`:
1. Tell the user: _"All sprint items are done. Picking the next issue from GitHub."_
2. `gh pr list --state merged --limit 1 --json number,title,body` → extract closed issue N → target is N+1.
3. `gh issue view <N+1> --json number,title,labels`.

Show the user the chosen issue (number + title + labels) and ask for confirmation before proceeding.

---

## Step 5 — Create the new branch and worktree

Derive branch name:
- Format: `<label-slug>-<short-title-slug>-<issue-number>`
- Use the most specific label as the slug. If no useful label, omit the prefix.
- Slugify the title: lowercase, replace spaces/special chars with `-`, trim to ~40 chars, drop filler words (the, a, an, for, with, on, to, in, of).

Set `BRANCH_NAME` and `WORKTREE_PATH`, then:

```bash
gh issue develop <number> --name {BRANCH_NAME}
git -C {MAIN_REPO_ROOT} fetch origin {BRANCH_NAME}
git -C {MAIN_REPO_ROOT} worktree add {WORKTREE_PATH} {BRANCH_NAME}
```

---

## Step 6 — Deep research and planning

This is the core of this skill. Take your time — this is where Opus earns its place.

### 6a — Gather all context

Fetch the full issue including comments:
```bash
gh issue view <number> --json number,title,body,labels,comments
```

Then read the relevant existing code. What to read depends on the issue, but for a typical backend issue:
- The wiki doc for the affected area (`docs/data/data-dictionary.md`, `docs/data/data-dictionary.md`, `docs/api/endpoints.md`, etc.)
- The existing model, repo, service, and router files that the issue touches
- Any related tests that already exist
- `tools/seed_data.py` if the issue touches data seeding
- `functions/` if the issue touches triggers

Read actual file content — don't just list filenames. You need to understand the existing patterns deeply enough to write a plan that a Sonnet model can follow without guessing.

### 6b — Write the implementation plan

Write the plan to `{WORKTREE_PATH}/.claude-plan.md`. This file is the sole handoff artifact. The implementing session will have no context other than this file.

The plan must include every piece of information the implementing session needs — it should not have to fetch the issue from GitHub, read the wiki, or make any judgment calls. You've already done all of that.

Structure:

```markdown
# Implementation Plan

## Session Variables
- ISSUE_NUMBER: <N>
- ISSUE_TITLE: <title>
- BRANCH_NAME: <branch>
- WORKTREE_PATH: <absolute path>
- MAIN_REPO_ROOT: <absolute path>
- PLANNED_AT: <ISO timestamp>

## Issue Summary
<2–3 sentence summary of what the issue asks for and why it exists>

## Full Issue Body
<paste the full issue body here verbatim>

## Existing Code Analysis
<What's already in the codebase that's relevant. What patterns exist. What the issue is adding/changing relative to what's there. Any gaps or inconsistencies you noticed.>

## Implementation Approach
<The step-by-step plan. Be specific. If there are multiple ways to solve something, pick one and explain why.>

## Files to Create or Modify

### Create
- `{path}`: <what to put in it and why>

### Modify
- `{path}`: <exactly what to change and why>

## Test Strategy
<What tests to write. What existing tests to run. What edge cases to cover. Whether unit tests or integration tests are needed.>

## Gotchas and Watch-outs
<Dependencies between changes. Things that could go wrong. Subtle invariants to preserve. Edge cases from the issue or codebase.>

## Definition of Done
<A checklist derived directly from the issue's acceptance criteria, plus any you identified during research.>
```

Be thorough in "Existing Code Analysis" and "Gotchas" — these are where Sonnet is most likely to make mistakes if left on its own.

---

## Step 7 — Update sprint tracker

Update `{MAIN_REPO_ROOT}/.agent/SPRINT.md` (main checkout's copy, **not** the worktree's):
1. Find the row for `#<issue-number>` in the "In Sprint" table.
2. Set **Status** to `🚧 In Progress`.
3. Set **Branch** to `{BRANCH_NAME}`.
4. Leave **PR** as `—` (no PR yet — that's set by `/implement-next-issue`).

---

## Step 8 — Report

Tell the user:
- Which issue was chosen and confirmed
- Worktree created at `{WORKTREE_PATH}`
- Plan written to `{WORKTREE_PATH}/.claude-plan.md`
- Sprint tracker updated
- **Next step:** switch to Sonnet 4.6 and run `/implement-next-issue`
