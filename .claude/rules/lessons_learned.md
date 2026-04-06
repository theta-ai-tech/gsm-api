# Lessons Learned

- When one service action can emit multiple ticker event types, scope test assertions to the event type under test instead of asserting on total `ticker_repo.add` calls or total `ticker` documents.
- When writing manual testing instructions in PR descriptions that reference seeded match IDs, always use the actual IDs from `tools/seed_data.py`. The only seeded match in `PENDING_CONFIRMATION` status is `match_pending` (underscore). Do not invent IDs like `match_001`.
