# GSM – Data Model (initial)

## users/{uid}
- `uid` (doc id)
- `name`, `email`, `profileUrl`, `phone`
- `rankings`: `{ tennis, padel, pickleball }`
- `preferences`:
  - `area` (int)
  - `level`: `{ tennis, padel, pickleball }`
  - `sports`: string[]

## References (stored elsewhere)
- **Matches**: completed/upcoming – stored separately; link by IDs (or subcollections later)
- **Leagues**: active/completed – stored separately; link by IDs
- **Journal**: stored separately – link by IDs

## API patterns (planned)
- `GET /users/{uid}` → 404 if not found, 403 if uid mismatch
- `PUT /users/{uid}` → create/update self
- `PATCH /users/{uid}` → partial update