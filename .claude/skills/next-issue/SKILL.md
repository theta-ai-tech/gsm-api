---
name: next-issue
description: Transition from a completed branch to a fresh branch for the next GitHub issue. Verifies the current branch is merged, deletes it, pulls main, creates a new branch, implements the issue, commits, and raises a PR.
disable-model-invocation: true
---

You are helping the user pick up, implement, and ship the next GitHub issue end-to-end.

Follow these steps **in order**, stopping and informing the user if any step fails or requires a decision.

---

## Step 1 — Verify the current branch is fully merged

1. Get the current branch name via `git branch --show-current`.
2. If already on `main`, skip to Step 4.
3. Use `gh pr list --head <branch> --state merged --json number,title,mergedAt` to check whether a merged PR exists for this branch.
4. If **no merged PR** is found:
   - Report the status (open PR? no PR at all?) and **stop**. Do not delete the branch or touch main.

---

## Step 2 — Switch to main and sync

```bash
git checkout main
git pull origin main
```

---

## Step 3 — Delete the old branch

Delete locally and on the remote:

```bash
git branch -d <old-branch>
git push origin --delete <old-branch>
```

If `git branch -d` fails because the branch is not fully merged locally (can happen when the merge happened on GitHub), use `-D` instead and explain why to the user.

---

## Step 4 — Determine the target issue

**If the user called `/next-issue <issue-number>`:** use that number directly — skip the lookup below.

**Otherwise:** find the issue number automatically:
1. Get the most recently merged PR: `gh pr list --state merged --limit 1 --json number,title,body`.
2. Extract the issue number it closes (look for `Closes #N`, `Fixes #N`, or `Resolves #N` in the PR body; also check the PR title for `(#N)` patterns).
3. The target issue is `N + 1`.
4. Fetch that issue: `gh issue view <N+1> --json number,title,labels`.

Show the user the chosen issue (number + title + labels) and ask for confirmation before proceeding.

---

## Step 5 — Create the new branch

Derive a branch name from the issue:
- Format: `<label-slug>-<short-title-slug>-<issue-number>`
- Use the most specific label as the slug (e.g. `tab3-lab`, `tab2`, `api`). If no useful label, omit the prefix.
- Slugify the title: lowercase, replace spaces/special chars with `-`, trim to ~40 chars, drop common filler words (the, a, an, for, with, on, to, in, of).
- Example: issue #91 "Add match history pagination" with label `api` → `api-add-match-history-pagination-91`

Use `gh issue develop` to create the branch and formally link it to the issue in one step:

```bash
gh issue develop <number> --name <new-branch> --checkout
```

---

## Step 6 — Implement the issue

1. Fetch the full issue body: `gh issue view <number> --json body,title,labels,comments`.
2. Read any relevant existing code before making changes.
3. Implement the required changes following the project's coding conventions (see CLAUDE.md).
4. Run `make fmt format type` and fix any errors before proceeding.

---

## Step 7 — Commit

Stage and commit all changes:

```bash
git add <relevant files>
git commit -m "<type>: <short imperative description> (#<issue-number>)"
```

Follow the commit style in CLAUDE.md: short imperative title with scope, e.g. `feat: SE-12 GET /me/lab/dashboard endpoint (#89)`.

---

## Step 8 — Raise a PR

Push the branch and open a pull request:

```bash
git push -u origin <new-branch>
gh pr create --title "<type>: <description> (#<issue-number>)" --body "..."
```

PR body should include:
- A short summary of what was implemented
- `Closes #<issue-number>`

---

## Step 9 — Update the sprint tracker

After the PR is created, update `.agent/SPRINT.md` to link the PR to the issue:

1. Read `.agent/SPRINT.md` and find the row for `#<issue-number>` in the **"In Sprint"** table.
2. Update the row:
   - Set **Status** to `🚧 In Progress`
   - Set **Branch** to the branch name
3. Add a **PR** column to the "In Sprint" table if it doesn't exist yet. Set it to `#<PR-number>` for this issue's row (use `—` for other rows that don't have a PR yet).

This ensures that when an agent later needs to find the PR for an in-progress issue (e.g. to review PR comments), it can look it up directly from SPRINT.md.

---

## Step 10 — Report

Summarise what was done:
- Old branch deleted (local + remote)
- Issue implemented and committed
- PR raised: link to the new PR
- Sprint tracker updated with PR link
