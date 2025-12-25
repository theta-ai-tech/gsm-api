# Repositories (Data Access Layer)

We implement the query contracts through small repository classes (e.g., `UsersRepo`, `MatchesRepo`,
`JournalRepo`). The naming is intentional: a “Repo” is a data-access layer for a domain aggregate,
not a raw Firestore collection or list. Repos encapsulate Firestore details (paths, filters, ordering,
pagination) and return domain models rather than raw documents.

These repositories implement the contracts described in `wiki/queries.md`.

This keeps route handlers thin and lets us evolve Firestore schemas or query details behind a
stable, testable API.

## How repos map to query contracts
- `UsersRepo.get_private_profile(uid)` → returns `PrivateUserProfile` (Q1).
- `UsersRepo.get_public_profile(uid)` → returns `PublicUserProfile` (Q1, public view).
- `MatchesRepo.list_upcoming_for_user(uid, ...)` → implements Q2.
- `MatchesRepo.list_completed_for_user(uid, ...)` → implements Q3.
- `MatchesRepo.list_upcoming_for_league(league_id, ...)` → implements Q4 (upcoming).
- `MatchesRepo.list_completed_for_league(league_id, ...)` → implements Q4 (completed).
- `JournalRepo.list_entries(uid, ...)` → implements Q5.
