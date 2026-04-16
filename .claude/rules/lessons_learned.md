# Lessons Learned

- When one service action can emit multiple ticker event types, scope test assertions to the event type under test instead of asserting on total `ticker_repo.add` calls or total `ticker` documents.
- When writing manual testing instructions in PR descriptions that reference seeded match IDs, always use the actual IDs from `tools/seed_data.py`. The only seeded match in `PENDING_CONFIRMATION` status is `match_pending` (underscore). Do not invent IDs like `match_001`.
- Before merging a PR, ensure the feature branch is rebased onto main if any other PRs landed after the branch was created. Stale branches carry unformatted files from older main states, causing CI lint failures even when the PR diff itself is clean. In the developer cron, run `git -C {WORKTREE_PATH} merge origin/main` before pushing the final commit when another PR has been merged since this branch was cut.
