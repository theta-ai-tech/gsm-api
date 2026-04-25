---
name: next-issue
description: Pick up the next GitHub issue end-to-end inside an isolated git worktree. Verifies the previous branch is merged, removes its worktree, syncs main, creates a new branch + worktree under `.claude/worktrees/{branch}`, implements the issue there, commits, and raises a PR. The main checkout stays on `main` throughout.
disable-model-invocation: true
---

You are helping the user pick up, implement, and ship the next GitHub issue end-to-end.

All implementation work happens inside an **isolated git worktree** under `.claude/worktrees/{branch_name}`. The main checkout stays on `main` throughout — read/write to the worktree path explicitly, never `git checkout` the feature branch in the main repo.

Define these path variables up front and substitute them throughout:

- `MAIN_REPO_ROOT` = the gsm-api repo root (e.g. `/Users/ignatioscharalampidis/Documents/theta/dev/gsm/gsm-api`). Resolve once with `git -C $(pwd) rev-parse --show-toplevel` if you are not sure.
- `BRANCH_NAME` = set in Step 5 once the new branch is derived.
- `WORKTREE_PATH` = `{MAIN_REPO_ROOT}/.claude/worktrees/{BRANCH_NAME}` (set once `BRANCH_NAME` is known).

Follow these steps **in order**, stopping and informing the user if any step fails or requires a decision.

---

## Step 1 — Verify the previous branch is fully merged

1. From `MAIN_REPO_ROOT`, run `git -C {MAIN_REPO_ROOT} worktree list --porcelain` to see if a previous run left a worktree under `.claude/worktrees/`.
2. If a previous worktree exists, capture its branch as `OLD_BRANCH` and its path as `OLD_WORKTREE_PATH`.
3. If no leftover worktree, run `git -C {MAIN_REPO_ROOT} branch --show-current` — if the main checkout is on a non-`main` branch (legacy state from before worktree adoption), treat that as `OLD_BRANCH`.
4. If `OLD_BRANCH` is empty or `main`, skip to Step 4.
5. Verify the old branch is merged: `gh pr list --head {OLD_BRANCH} --state merged --json number,title,mergedAt`.
6. If **no merged PR** is found, report the status (open PR? no PR at all?) and **stop**. Do not delete the branch, remove the worktree, or touch main.

---

## Step 2 — Sync main

```bash
git -C {MAIN_REPO_ROOT} checkout main
git -C {MAIN_REPO_ROOT} pull origin main
```

---

## Step 3 — Clean up the old worktree and branch

If a worktree existed for the old branch, remove it first:

```bash
git -C {MAIN_REPO_ROOT} worktree remove {OLD_WORKTREE_PATH} --force
```

Then delete the branch locally and on the remote:

```bash
git -C {MAIN_REPO_ROOT} branch -d {OLD_BRANCH}
git -C {MAIN_REPO_ROOT} push origin --delete {OLD_BRANCH}
```

If `git branch -d` fails because the branch is not fully merged locally (can happen when the merge happened on GitHub), use `-D` instead and explain why to the user.

---

## Step 4 — Determine the target issue

**If the user called `/next-issue <issue-number>`:** use that number directly — skip the lookup below.

**Otherwise:** find the next issue automatically using this priority order:

### 4a — Check the sprint tracker first

1. Read `{MAIN_REPO_ROOT}/.agent/SPRINT.md` and look at the **"In Sprint"** table.
2. Find the first row whose **Status** is `📋 Planned` (not `✅ Done`, not `🚧 In Progress`).
3. If a planned issue is found, use that issue number as the target. Fetch its details from GitHub: `gh issue view <number> --json number,title,labels`.

### 4b — Fall back to GitHub if the sprint is complete

If **all** rows in the "In Sprint" table are `✅ Done` (no planned items remain):
1. Tell the user: _"All sprint items are done. Picking the next issue from GitHub."_
2. Get the most recently merged PR: `gh pr list --state merged --limit 1 --json number,title,body`.
3. Extract the issue number it closes (look for `Closes #N`, `Fixes #N`, or `Resolves #N` in the PR body; also check the PR title for `(#N)` patterns).
4. The target issue is `N + 1`.
5. Fetch that issue: `gh issue view <N+1> --json number,title,labels`.

---

Show the user the chosen issue (number + title + labels) and ask for confirmation before proceeding.

---

## Step 5 — Create the new branch and worktree

Derive a branch name from the issue:
- Format: `<label-slug>-<short-title-slug>-<issue-number>`
- Use the most specific label as the slug (e.g. `tab3-lab`, `tab2`, `api`). If no useful label, omit the prefix.
- Slugify the title: lowercase, replace spaces/special chars with `-`, trim to ~40 chars, drop common filler words (the, a, an, for, with, on, to, in, of).
- Example: issue #91 "Add match history pagination" with label `api` → `api-add-match-history-pagination-91`

Set `BRANCH_NAME` to this value, then `WORKTREE_PATH = {MAIN_REPO_ROOT}/.claude/worktrees/{BRANCH_NAME}`.

Create the branch (formally linked to the issue) **without** checking it out in the main repo:

```bash
gh issue develop <number> --name {BRANCH_NAME}
```

Fetch the new branch and create the isolated worktree:

```bash
git -C {MAIN_REPO_ROOT} fetch origin {BRANCH_NAME}
git -C {MAIN_REPO_ROOT} worktree add {WORKTREE_PATH} {BRANCH_NAME}
```

From here on, **all file edits, git commands, and shell tool invocations target `WORKTREE_PATH`** (use `git -C {WORKTREE_PATH} ...` and absolute paths under `{WORKTREE_PATH}` for Read/Edit/Write).

---

## Step 6 — Implement the issue (inside the worktree)

1. Fetch the full issue body: `gh issue view <number> --json body,title,labels,comments`.
2. Read any relevant existing code from `{WORKTREE_PATH}` before making changes.
3. Implement the required changes in `{WORKTREE_PATH}` following the project's and agent's coding conventions (see CLAUDE.md and the agent's file).
4. Run lint/format/type-check **against the worktree's files**, reusing the main checkout's venv (worktrees don't have their own `.venv`):

   ```bash
   make -C {WORKTREE_PATH} VENV={MAIN_REPO_ROOT}/.venv fmt format type
   ```

   Why this shape: `make -C {WORKTREE_PATH}` runs the Makefile with the working directory set to the worktree, so the `api` and `tests` paths in the `fmt`/`format`/`type` recipes resolve to the worktree's source. The `VENV=...` override redirects `. $(VENV)/bin/activate` to the main checkout's venv (the only one that has the deps installed). Fix any errors before proceeding.

---

## Step 6.5 — Run tests

Check whether the Firestore emulator is up:

```bash
curl -s --connect-timeout 2 http://127.0.0.1:8082 > /dev/null 2>&1 && echo "up" || echo "down"
```

**If up:** run the full test suite **against the worktree's files** using the main checkout's venv:

```bash
PYTHONPATH={WORKTREE_PATH}/api make -C {WORKTREE_PATH} VENV={MAIN_REPO_ROOT}/.venv test
```

Why this shape:
- `make -C {WORKTREE_PATH}` runs the `test` target with `$PWD` = worktree, so pytest collects from the worktree's `tests/` directory and `tools` imports resolve to the worktree's `tools/`.
- `VENV={MAIN_REPO_ROOT}/.venv` redirects `. $(VENV)/bin/activate` to the main checkout's venv (worktrees don't carry `.venv`).
- `PYTHONPATH={WORKTREE_PATH}/api` is the critical bit: the editable install in the main venv registers `app` pointing at `{MAIN_REPO_ROOT}/api/app`, so without this override `import app` would resolve to the main checkout's source, not the worktree's. Putting `{WORKTREE_PATH}/api` first on `PYTHONPATH` makes Python pick the worktree's `app` package ahead of the editable install — so the new code on the branch is what gets exercised.

Sanity check: verify the test run actually loaded code from the worktree. Either run a one-liner before `make test`:

```bash
PYTHONPATH={WORKTREE_PATH}/api {MAIN_REPO_ROOT}/.venv/bin/python -c "import app, os; print(os.path.dirname(app.__file__))"
```

…and confirm the printed path starts with `{WORKTREE_PATH}/api/app` (not `{MAIN_REPO_ROOT}/api/app`). If it points at the main checkout, abort and investigate before committing.

All tests must pass before proceeding to commit. If any tests fail, fix them now (in the worktree) — do not commit broken code.

**If down:** stop and tell the user:
> The Firestore emulator is not running. Start it with `make emu-all` and `make api-dev-emu-auth` in separate terminals, then re-run `/next-issue`. Alternatively, confirm you want to skip tests and proceed anyway.

Only continue without tests if the user explicitly confirms.

---

## Step 7 — Commit

Stage and commit all changes from inside the worktree:

```bash
git -C {WORKTREE_PATH} add <relevant files>
git -C {WORKTREE_PATH} commit -m "<type>: <short imperative description> (#<issue-number>)"
```

Follow the commit style in CLAUDE.md: short imperative title with scope, e.g. `feat: SE-12 GET /me/lab/dashboard endpoint (#89)`.

---

## Step 8 — Raise a PR

Push the branch and open a pull request from inside the worktree:

```bash
git -C {WORKTREE_PATH} push -u origin {BRANCH_NAME}
(cd {WORKTREE_PATH} && gh pr create --title "<type>: <description> (#<issue-number>)" --body "...")
```

PR body must include (per project memory):
- **Context & Technical Overview** — what / why / tech dive for fresh-context reviewers
- A short summary of what was implemented
- An **Acceptance criteria** checklist
- `Closes #<issue-number>`

---

## Step 8.5 — Generate smoke test script

Check whether the PR body contains a "How to test manually" section:

```bash
gh pr view <PR-number> --json body --jq '.body' | grep -i "how to test manually"
```

**If the section exists:** invoke the `/smoke-test` skill to generate `tests/smoke/pr-{N}.sh` inside the worktree. The skill parses the PR and translates every step (including Firestore UI edits) into runnable bash. Do NOT run it — just generate the file.

Then commit and push it from the worktree:

```bash
git -C {WORKTREE_PATH} add tests/smoke/pr-{N}.sh
git -C {WORKTREE_PATH} commit -m "test: add smoke test script for PR #{N}"
git -C {WORKTREE_PATH} push
```

**If no manual test section:** skip this step.

---

## Step 9 — Update the sprint tracker

After the PR is created, update `{MAIN_REPO_ROOT}/.agent/SPRINT.md` (the main checkout's copy on `main`, **not** the worktree's copy) if the issue is in the current sprint:

1. Read `{MAIN_REPO_ROOT}/.agent/SPRINT.md` and find the row for `#<issue-number>` in the **"In Sprint"** table.
2. Update the row:
   - Set **Status** to `🚧 In Progress`
   - Set **Branch** to the branch name
3. Add a **PR** column to the "In Sprint" table if it doesn't exist yet. Set it to `#<PR-number>` for this issue's row (use `—` for other rows that don't have a PR yet).

This ensures that when an agent later needs to find the PR for an in-progress issue (e.g. to review PR comments), it can look it up directly from SPRINT.md.

---

## Step 10 — Report

Summarise what was done:
- Old branch deleted (local + remote) and old worktree removed
- New branch + worktree created at `{WORKTREE_PATH}`
- Issue implemented and committed inside the worktree
- PR raised: link to the new PR
- Sprint tracker updated with PR link

The worktree at `{WORKTREE_PATH}` is left in place so any review-comment fixes can be made there. The next `/next-issue` run will clean it up automatically once this PR is merged.
