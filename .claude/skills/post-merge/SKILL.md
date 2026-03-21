---
name: post-merge
description: Update .agent/SPRINT.md after a PR is merged — moves the issue from "In Sprint" to "Done This Sprint" with the PR number and merge date. Use this skill after merging a PR, when the user says "update the sprint", "mark it done", "PR was merged", or "/post-merge".
disable-model-invocation: true
---

You are updating the sprint tracker after a PR has been merged. The goal is to move the completed issue from the "In Sprint" table to the "Done This Sprint" table in `.agent/SPRINT.md`.

Follow these steps **in order**, stopping and informing the user if any step fails.

---

## Step 1 — Identify the merged PR

**If the user called `/post-merge <PR-number>`:** use that PR number directly.

**Otherwise:** find the most recently merged PR automatically:

```bash
gh pr list --state merged --limit 1 --json number,title,body,mergedAt
```

Show the user the PR (number + title + merge date) and confirm before proceeding.

---

## Step 2 — Extract the closed issue number

From the PR body and title, extract the issue number using these patterns (in priority order):

1. `Closes #N`, `Fixes #N`, or `Resolves #N` in the PR body
2. `(#N)` in the PR title (common in this project's commit style)

If no issue number is found, ask the user which issue this PR completed.

---

## Step 3 — Read the current sprint file

Read `.agent/SPRINT.md` and locate:
- The issue row in the **"In Sprint"** table matching `#<issue-number>`
- The **"Done This Sprint"** table where the row will be moved

If the issue is not found in the "In Sprint" table, tell the user and ask how to proceed (it may already have been moved, or it may not be in this sprint).

---

## Step 4 — Update the sprint tracker

**Do NOT remove the row from the "In Sprint" table.** Instead, update it in place and also add an entry to "Done This Sprint":

1. **Update** the matching row in the "In Sprint" table:
   - Set **Status** to `✅ Done`
   - Keep all other columns (Title, Est., Branch, PR) unchanged

2. **Add** a new row to the "Done This Sprint" table with these columns:

   | Issue | Title | PR | Merged |
   |-------|-------|----|--------|
   | #N | (title from the original row) | #PR-number | YYYY-MM-DD |

3. If the "Done This Sprint" table only has the placeholder row (`| — | — | — | — |`), replace it with the new entry.

4. If there are multiple placeholder rows in other tables (like "Blocked / Carry-over"), leave them as-is — only touch the two tables involved.

---

## Step 5 — Report

Tell the user what was updated:
- Which issue was moved (#N — title)
- Which PR closed it (#PR)
- Merge date
