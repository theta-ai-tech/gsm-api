# Security: Access Model, Auth & CORS

> How GSM authenticates callers, authorizes resource access, locks down Firestore, and
> scopes CORS. Implementation lives in `api/app/security.py` and `api/app/main.py`.

## Access model (REST-only)

GSM uses a REST-only access model (confirmed 2026-06-13):

```
iOS client → FastAPI REST endpoints → Firebase Admin SDK → Firestore
```

- The iOS client never reads or writes Firestore directly via the Firebase SDK.
- All data access goes through the FastAPI API.
- The Firebase Admin SDK bypasses Firestore security rules in both production and emulator.

## Authentication (Firebase ID tokens)

Clients call endpoints with `Authorization: Bearer <id_token>`, where the token is a Firebase ID
token minted after sign-in (client SDK or custom-token exchange).
- **Dev:** use the Auth emulator (`FIREBASE_AUTH_EMULATOR_HOST`) or a service account to mint custom tokens.
- **Prod:** Firebase issues tokens; audience (`aud`) and issuer (`iss`) must match the project ID.

`get_current_user` (FastAPI dependency):
1. Parse the `Authorization` header; reject missing/invalid formats (**401**).
2. Verify the ID token via Firebase Admin (`verify_id_token`), enforcing issuer/audience.
3. Normalize roles from claims (`roles` or `role`, string or list).
4. Return `CurrentUser` (uid, email, roles, …) for downstream helpers.

Authorization helpers assume `get_current_user` already succeeded — they handle **403** only,
never **401**.

## Authorization helpers

**Ownership**
- `is_owner(user, target_uid) -> bool` — convenience `user.uid == target_uid` check.
- `require_self(user, target_uid)` — raises 403 if caller is not the target (used on `/users/{uid}`).

**Global roles (token claims)**
- `require_roles(user, roles)` — all roles required; empty list is a no-op.
- `require_any_role(user, roles)` — at least one required; empty list is a no-op.
- `is_admin(user)` — true for admin-like aliases (admin/administrator/superadmin).

**League membership (Firestore-backed)**
- `RoleService` — injectable wrapper reading `leagues/{leagueId}/members/{uid}` and league
  `ownerUid`. Methods: `is_league_member`, `get_league_member_role`, `get_league_owner_uid`.
- `require_membership(user, league_id, role_service, required_role=None)` — allows access if the
  user has the required role in claims, **or** is the league owner, **or** has a membership doc
  (matching `required_role` when provided); raises 403 otherwise.
- `require_league_member(required_role=None)` — dependency factory:
  `dependencies=[Depends(require_league_member("admin"))]`.

```python
@app.get("/users/{uid}")
def get_user(uid: str, current_user: CurrentUser = Depends(get_current_user)):
    require_self(current_user, uid)
    ...

@app.post("/leagues/{league_id}/members",
          dependencies=[Depends(require_league_member("admin"))])
def add_member(league_id: str, current_user: CurrentUser = Depends(get_current_user)):
    ...
```

Tests can override dependencies and inject a `FakeRoleService`; see `tests/unit/test_security.py`
and `tests/unit/test_routes_authz.py`.

## Firestore security rules

`firestore.rules` contains `allow read, write: if false` — deny-all for direct clients. This is
correct because no client needs direct Firestore access; the Admin SDK still works normally.

**When to update:** if direct Firebase SDK access is ever added (e.g. real-time notifications or a
live feed), update the rules *before* deploying to include per-collection, per-field grants that:
- allow users to read their own `users/{uid}` doc and subcollections,
- block writes to server-authoritative fields (`rankings.*`, `registrationTier`, `playTab`, `stats`),
- allow users to read `leagues/*` and `matches/*` they participate in (by UID membership).

**Dev rules & smoke testing.** `firestore.rules.dev` is allow-all for local debugging;
`firebase.smoke.json` references it. Smoke scripts (`tests/smoke/pr-*.sh`) make direct Firestore
REST calls that enforce rules, so:

```bash
make emu-smoke   # allow-all rules — use when running smoke scripts
make emu-all     # deny-all rules — use for all other dev work
```

Integration tests (`make test`) are unaffected — they use `google.cloud.firestore.Client`, which
bypasses rules in the emulator regardless of the active rules file.

```bash
bash scripts/verify_firestore_rules.sh   # after `make emu-all` (deny-all active)
make deploy-rules-dev                     # deploy rules to dev
firebase deploy --only firestore:rules --project gsm-prod   # prod, with care
```

## CORS

CORS is scoped to browser frontends; native/mobile apps and server-to-server calls (no `Origin`
header) are unaffected.
- **Env-driven origins:** `CORS_ORIGINS` (dev `http://localhost:3000,http://127.0.0.1:3000`;
  prod `https://app.gamesetmatch.io`).
- **Credentials toggle:** `CORS_ALLOW_CREDENTIALS` (default `0`) — we use Bearer tokens, not cookies.
- **Wiring:** `CORSMiddleware` in `app/main.py`, headers limited to `Authorization` + `Content-Type`.

A browser sends `Origin` (and optional `OPTIONS` preflight); the middleware checks it against
`settings.cors_origins` and, if allowed, returns `Access-Control-Allow-Origin`. Calls without an
`Origin` (mobile, curl, server-to-server) skip CORS entirely. Covered by `tests/unit/test_cors.py`.

```bash
# Allowed preflight → 200 + Access-Control-Allow-Origin
curl -i -X OPTIONS "http://localhost:8000/users/abc" \
  -H "Origin: http://localhost:3000" -H "Access-Control-Request-Method: GET"
```
