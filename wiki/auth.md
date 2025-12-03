# Auth Helpers Overview

This service uses FastAPI dependencies plus small helpers to gate access to user and league resources. This page documents what exists, why, and how to use it.

## Current User Model
- `CurrentUser`: Pydantic model built from Firebase ID token claims (uid, email, roles, etc.).
- Retrieved via dependency `get_current_user` (checks Authorization header, verifies token).

## Authentication Basics (Bearer + Firebase ID tokens)
- Clients call endpoints with `Authorization: Bearer <id_token>`.
- Tokens are Firebase ID tokens minted after sign-in (client SDK or custom token exchange).
  - In dev, use the Auth emulator (`FIREBASE_AUTH_EMULATOR_HOST`) or a service account to mint custom tokens.
  - In prod, Firebase issues tokens; Audience (`aud`) and Issuer (`iss`) must match `project_id`/settings.
- `get_current_user` workflow:
  1) Parse `Authorization` header; reject missing/invalid formats (401).
  2) Verify ID token via Firebase Admin (`verify_id_token`), enforcing issuer/audience.
  3) Normalize roles from claims (`roles` or `role`, string or list).
  4) Return `CurrentUser` for downstream helpers.
- Helpers (`require_self`, role checks, membership checks) assume `get_current_user` has already succeeded; they only handle authorization (403), not authentication (401).

## Ownership Helpers
- `is_owner(user, target_uid) -> bool`: convenience check for `user.uid == target_uid`.
- `require_self(user, target_uid)`: raises 403 if caller is not the target. Used on `/users/{uid}`.
  - Why: enforce “only the user can read their profile” pattern across endpoints.

## Role Helpers (global claims)
- `require_roles(user, roles)`: all roles required; empty list is a no-op.
- `require_any_role(user, roles)`: at least one role required; empty list is a no-op.
- `is_admin(user)`: true if roles contain admin-like aliases (admin/administrator/superadmin).
  - Why: lightweight guardrails for staff-only routes without touching Firestore.
  - Example: `require_roles(current_user, ["admin", "editor"])`

## League Membership & Roles (Firestore-backed)
- `RoleService`: injectable wrapper around Firestore.
  - Reads membership docs at `leagues/{leagueId}/members/{uid}` with optional `role` field.
  - Reads league owner via `ownerUid` (or `owner_uid`) on `leagues/{leagueId}`.
  - Methods: `is_league_member`, `get_league_member_role`, `get_league_owner_uid`.
- `require_membership(user, league_id, role_service, required_role=None)`: allows access if:
  1) User has required role in token claims, OR
  2) User is league owner, OR
  3) Membership doc exists (and matches `required_role` when provided).
  - Raises 403 otherwise.
  - Example: `require_membership(current_user, league_id, role_service, "admin")`
- `require_league_member(required_role=None)`: dependency factory for routes.
  - Usage: `dependencies=[Depends(require_league_member("admin"))]`
  - Works with `get_role_service` + `get_current_user` dependencies; easy to override in tests.

## Example Route Usage
```python
@app.get("/users/{uid}")
def get_user(uid: str, current_user: CurrentUser = Depends(get_current_user)):
    require_self(current_user, uid)
    ...

@app.post("/leagues/{league_id}/members", dependencies=[Depends(require_league_member("admin"))])
def add_member(league_id: str, current_user: CurrentUser = Depends(get_current_user)):
    ...

@app.delete("/leagues/{league_id}/members/{uid}", dependencies=[Depends(require_league_member("admin"))])
def remove_member(league_id: str, uid: str, current_user: CurrentUser = Depends(get_current_user)):
    ...
```

## Testing Patterns
- Unit tests can inject `FakeRoleService` and override dependencies:
  ```python
  app.dependency_overrides[get_current_user] = lambda: CurrentUser(uid="u1", roles=["admin"])
  app.dependency_overrides[get_role_service] = lambda: FakeRoleService(member=True, member_role="admin")
  client = TestClient(app)
  ```
- See `tests/unit/test_security.py` and `tests/unit/test_routes_authz.py` for examples covering global roles, league membership, and dependency wiring.
