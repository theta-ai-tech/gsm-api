---
name: review-pr
description: Review GitHub pull requests and post feedback comments without implementing fixes. Use when the user asks to review a PR, including `/review-pr` or `/review-pr <number>`. If multiple open PRs exist and no number is provided, ask the user which PR to review. Before reviewing, ask for business or domain context (for example specific docs or folders) that should guide the review. Prioritize fast functional validation over overly strict style policing.
disable-model-invocation: true
---

You are helping the user review pull requests and leave feedback comments only.

Run required `gh` commands directly. Do not ask the user for permission before executing `gh` CLI commands or posting review comments. Only ask the user for business/domain context or to choose the target PR when the PR number is not already known and cannot be inferred safely.

Follow these steps in order, stopping if a required decision is missing.

---

## Step 1 — Determine the target PR

1. If the user called `/review-pr <number>`, use that PR number directly.
2. Otherwise, list open PRs:

```bash
gh pr list --state open --limit 30 --json number,title,author,updatedAt,url
```

3. If there are no open PRs, inform the user and stop.
4. If there is one open PR, show it and ask for confirmation.
5. If there are multiple open PRs, ask the user to choose the PR number. Do not auto-select one.

---

## Step 2 — Ask for business context before reviewing

Ask this before reading the diff:

"Is there any business knowledge, product rule, or specific folder/doc I should read first (for example `wiki/`, `spec/`, `arch/`, `plans/`, or app folders)?"

If the user provides context paths, read them first and summarize the review assumptions.

---

## Step 3 — Review the PR changes

1. Read PR metadata:

```bash
gh pr view <number> --json number,title,body,baseRefName,headRefName,files,url
```

2. Read the code diff:

```bash
gh pr diff <number>
```

3. If needed for deeper inspection, check out the PR branch with `gh pr checkout <number>`, but do not edit files.
4. Evaluate for correctness, regressions, edge cases, security, performance, tests, readability, and alignment with provided business context.
5. If acceptance criteria exist (in PR body, linked issue, spec, or user instructions), run the relevant checks/tests for those criteria.
6. If acceptance-criteria checks pass, treat the PR as generally healthy and focus comments on obvious functional bugs or clearly missed cases.

---

## Step 4 — Add comments to the PR

1. Turn findings into concrete, actionable review comments.
2. Do not add comments for the sake of commenting; only post meaningful findings.
3. Prefer inline file/line review comments when a finding is local enough to attach precisely to a changed hunk. Use broader PR comments only for cross-cutting or non-local findings.
4. Post a review comment summary:

```bash
gh pr review <number> --comment --body "<review summary>"
```

5. Post additional comments for specific findings as needed:

```bash
gh pr comment <number> --body "<specific finding>"
```

6. Do not approve or request changes unless the user explicitly asks.

---

## Step 5 — Strict boundaries

- Do not fix code.
- Do not commit, push, or open follow-up PRs.
- Do not resolve comments.
- Suggest fixes in comments only.
- Avoid hyper-strict or nitpicky reviewing; optimize for fast, functionally correct deliverables.

---

## Step 6 — Report back to the user

Summarize:
- PR reviewed (number + link)
- How many comments were added
- Top findings by severity
