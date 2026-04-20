---
name: review-pr
description: Review GitHub pull requests and post feedback comments without implementing fixes. Use when the user asks to review a PR, including `/review-pr`, `/review-pr <number>`, or `/review-pr <number> <reviewer>` where reviewer is `claude` (default) or `codex`. If multiple open PRs exist and no number is provided, ask the user which PR to review. Before reviewing, ask for business or domain context (for example specific docs or folders) that should guide the review. Delegates the actual review to either `gsm-code-reviewer` (Claude/Opus) or `gsm-codex-reviewer` (Codex/GPT-side) — the skill picks the agent; the agent does the thinking. Running different reviewers from different sessions lets you collect two independent reads on the same PR, one per model.
disable-model-invocation: true
---

This skill resolves the PR, the business context, and which reviewer to use, then hands off to the chosen agent. Keeping reviewer separate from author matters: an author running `/review-pr` on their own diff will rubber-stamp things a fresh reviewer catches. Keeping *two* reviewer agents — one Claude, one Codex — matters for a different reason: different models have different blind spots, and a second independent read is cheap insurance against either model's characteristic misses.

Run required `gh` commands directly. Do not ask for permission before executing `gh` CLI commands. Only ask the user to pick the PR (when ambiguous), the reviewer (when ambiguous), or to supply business context.

---

## Step 1 — Parse arguments

Arguments are positional: `/review-pr [<number>] [<reviewer>]` where `<reviewer>` is `claude` (default) or `codex`.

- `/review-pr` — resolve PR interactively, use `claude`.
- `/review-pr 123` — PR #123, use `claude`.
- `/review-pr 123 codex` — PR #123, use `codex`.
- `/review-pr codex` — resolve PR interactively, use `codex`. (If the single token looks like a reviewer name, treat it as the reviewer; otherwise treat it as the PR number.)
- `/review-pr 123 claude` — explicit Claude for PR #123.

Anything else for the reviewer slot → stop and ask which of `claude` or `codex` the user wants. Don't guess.

## Step 2 — Determine the target PR

1. If a PR number was given, use it directly.
2. Otherwise, list open PRs:

```bash
gh pr list --state open --limit 30 --json number,title,author,updatedAt,url
```

3. If there are no open PRs, inform the user and stop.
4. If there is one open PR, show it and ask for confirmation.
5. If there are multiple open PRs, ask the user to choose the PR number. Do not auto-select.

---

## Step 3 — Ask for business context

Before dispatching the reviewer, ask:

"Is there any business knowledge, product rule, or specific folder/doc I should point the reviewer at first (for example `wiki/`, `spec/`, `arch/`, `plans/`, or app folders)?"

Capture whatever the user gives you verbatim. You'll pass it into the agent brief — the agent shouldn't have to guess what the user thinks is important.

If the user says "no, just review it", note that and proceed with defaults (the reviewer will consult `wiki/` on its own based on what the diff touches).

---

## Step 4 — Verify reviewer token

Whichever reviewer agent you dispatch posts comments as `iggy-theta-tech` via `$GSM_REVIEWER_TOKEN`. Check it's exported before delegating:

```bash
test -n "$GSM_REVIEWER_TOKEN" && echo "ok" || echo "missing"
```

If missing, stop and tell the user to export it. Posting review comments as `ignacioch` (the author) defeats the purpose — downstream (autopilot, human eyeballs) distinguishes review vs author by GitHub account.

---

## Step 5 — Delegate to the chosen reviewer

Map the reviewer argument to the agent:

| Reviewer | Agent | Backing model |
|----------|-------|---------------|
| `claude` (default) | `gsm-code-reviewer` | Claude / Opus |
| `codex` | `gsm-codex-reviewer` | Codex / GPT-side |

Dispatch the chosen agent with a focused brief:

> Review PR #`<N>` on `theta-ai-tech/gsm-api`. Business context the user called out: `<whatever they said, or "none — use defaults">`. Check correctness, regressions, edge cases, security, Firestore cost, and test coverage for the diff. Post inline comments where precise and one summary comment tagged `[Claude review]` or `[Codex review]` as appropriate. Use `$GSM_REVIEWER_TOKEN` so comments post as `iggy-theta-tech`. Do not approve or request changes. End your response with the `REVIEW_VERDICT: <CLEAN|NITS|CONCERNS|BLOCKING>` line.

Only one agent runs per invocation. The user running two sessions (one `claude`, one `codex`) is how the two independent reads are collected — the skill does not fan out by itself.

The agent does the work. This skill does not read the diff itself — that would defeat the "fresh eyes" point of separating the persona.

---

## Step 6 — Report back

Surface to the user:
- PR reviewed (number + link)
- Reviewer used (`claude` or `codex`)
- Verdict line from the agent (CLEAN / NITS / CONCERNS / BLOCKING)
- Count of comments posted
- Top findings, one line each, lifted from the agent's summary

Keep the report short — the GitHub PR itself is the durable artefact. This is just a pointer. If the user also ran the other reviewer in a parallel session, that review shows up in the PR thread tagged distinctly — they'll see both independently.

---

## What this skill does not do

- Does not fix code. The reviewer agent comments; the author fixes.
- Does not approve or request changes on GitHub. The autopilot or a human makes that call.
- Does not run smoke tests. `/smoke-test` (via `gsm-qa-tester`) is the parallel lane.

## How this fits with `/autopilot`

This skill works in two modes and both are fine:

- **Manual / parallel sessions** — human runs `/next-issue` in session A, `/smoke-test` in session B, `/review-pr` in session C. Each session holds one persona.
- **`/autopilot`** — one outer session dispatches `gsm-backend-developer`, then `gsm-qa-tester`, then `gsm-code-reviewer` via the Agent tool. Each agent still gets its own isolated context, so the reviewer still reads the diff with fresh eyes — the persona separation is preserved by agent dispatch, not by session boundary.

The invariant that matters is **persona isolation, not session isolation**. Never have the developer agent run `/review-pr` on its own diff (inline or as itself), because that collapses the two personas and the review loses its point.
