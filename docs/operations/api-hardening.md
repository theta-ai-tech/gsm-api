# API hardening for public traffic (#377)

The API faces the public internet via the iOS app. This doc records the hardening
decisions and how they're implemented.

---

## 1. Rate limiting

**Decision: app-level, per-uid, in-process fixed-window limiter on write endpoints.**
No new infrastructure (Cloud Armor / API Gateway) is required for launch — the
cheapest adequate option is a limiter inside the app.

Implementation: `api/app/rate_limit.py`. Attached to the mutating endpoints via the
route decorator's `dependencies=[Depends(rate_limit("<bucket>"))]`, so the endpoint
signature is unchanged and an unauthenticated caller is rejected (401) before the
limiter runs.

| Endpoint(s) | Bucket | Budget |
|---|---|---|
| `POST/DELETE /me/broadcast` | `broadcast` | 30 / 60s per uid |
| `POST /me/offers`, `.../accept`, `.../decline`, `.../cancel` | `offer` | 30 / 60s per uid |
| `POST /matches/{id}/verify-score` | `verify_score` | 30 / 60s per uid |
| `POST/PATCH/DELETE /me/journal…`, `PUT /me/north-star` | `journal` | 30 / 60s per uid |

Over-budget requests get **HTTP 429** with a `Retry-After` header (in seconds).

**Journal note.** `POST /me/journal` also has a *durable, global* per-hour cap in
`JournalService` (`JournalRateLimitError`, Firestore-backed). The in-memory limiter
is complementary: it catches bursts per instance; the durable cap catches sustained
abuse across instances.

**Tradeoff (documented, accepted for launch).** The in-memory limiter is
**per-instance**. Cloud Run may run several instances, so the effective global limit
is `budget × instance_count`. It bounds abuse from a single client rather than
enforcing a precise global quota.

**Toggle.** `GSM_RATE_LIMIT_ENABLED` (default `1`/enabled). Set `0` to disable (the
test suite does this by default; dedicated tests opt back in).

**Operator upgrade (when global quotas are needed):** front Cloud Run with **Cloud
Armor** (per-IP rate rules) or **API Gateway**, or move the counter to a shared
store (Memorystore/Redis). Sketch:
```bash
# Cloud Armor per-IP throttle (operator action — not run by CI)
gcloud compute security-policies create gsm-api-armor --project <PROJECT_ID>
gcloud compute security-policies rules create 1000 \
  --security-policy gsm-api-armor --project <PROJECT_ID> \
  --action throttle --rate-limit-threshold-count 100 \
  --rate-limit-threshold-interval-sec 60 \
  --conform-action allow --exceed-action deny-429 \
  --enforce-on-key IP
# Attach via a Serverless NEG + external HTTPS LB fronting the Cloud Run service.
```

---

## 2. CORS

**Decision: locked to an explicit allow-list; wildcard never permitted.**

- Origins come from `CORS_ORIGINS` (comma-separated). Empty (the default) means the
  CORS middleware is not installed at all — correct for a mobile API, since the iOS
  client is not a browser and needs no CORS headers.
- A `*` origin is **stripped and logged** (`sanitize_cors_origins` in
  `api/app/settings.py`); it is never handed to the CORS middleware.
- Allowed headers are limited to `Authorization`, `Content-Type`.

Set `CORS_ORIGINS` only if a browser-based internal tool needs access.

---

## 3. Auth coverage

**Decision: every route requires a Firebase ID token except the health probes.**

- `GET /health`, `GET /ready` are the only public API routes.
- `tests/unit/test_auth_coverage.py` walks every route's dependency tree and fails
  if any route (present or future) lacks `get_current_user` — a regression guard
  against accidentally shipping an unauthenticated endpoint (including any
  debug/seed route). Seeding is done via `tools/` scripts, never over HTTP; there
  are no debug/seed endpoints in the app.

Anonymous requests receive **401** everywhere except the health probes.

---

## 4. Firestore security rules

**Decision: deny-all direct client access (already in place — confirmed).**

`firestore.rules` denies all direct client reads/writes. The access model is
iOS → FastAPI → Firebase Admin SDK → Firestore, and the Admin SDK bypasses rules,
so the API keeps working while direct client access is denied. `firestore.rules.dev`
(permissive) is local-emulator-only and never deployed (see `firestore-deploy.md`).
`scripts/verify_firestore_rules.sh` asserts the deny-all behavior against the
emulator.

---

## Acceptance criteria mapping
- Abusive write loops get 429s → rate limiter on all write endpoints (§1).
- Anonymous requests get 401 everywhere except health → auth-coverage guard (§3).
- CORS locked, no wildcard → §2.
- Rules deny direct client access → §4.
