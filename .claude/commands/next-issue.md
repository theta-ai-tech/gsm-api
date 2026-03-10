# /next-issue

You are helping the user transition from a completed branch to a fresh branch for the next GitHub issue.

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

## Step 4 — Fetch the next issue

Run `gh issue list --state open --limit 20 --json number,title,labels,assignees` to get open issues.

Apply this priority order to pick the **next** issue:
1. Issues assigned to the current user (check via `gh api user --jq .login` first)
2. Issues with labels that match the project's current milestone or focus (e.g. `phase-1-scoring`, `tab3-lab`)
3. Lowest issue number among remaining candidates

Show the user the chosen issue (number + title + labels) and ask for confirmation before proceeding, unless there is only one obvious candidate.

---

## Step 5 — Create the new branch

Derive a branch name from the issue:
- Format: `<label-slug>-<short-title-slug>-<issue-number>`
- Use the most specific label as the slug (e.g. `tab3-lab`, `tab2`, `api`). If no useful label, omit the prefix.
- Slugify the title: lowercase, replace spaces/special chars with `-`, trim to ~40 chars, drop common filler words (the, a, an, for, with, on, to, in, of).
- Example: issue #91 "Add match history pagination" with label `api` → `api-add-match-history-pagination-91`

```bash
git checkout -b <new-branch>
```

---

## Step 6 — Report

Summarise what was done:
- Old branch deleted (local + remote)
- Now on `main` at commit (short SHA)
- New branch created: `<new-branch>`
- Linked issue: #number — title

Remind the user to run `gh issue develop <number> --checkout` if they want GitHub to formally link the branch to the issue, or confirm it's already linked.
