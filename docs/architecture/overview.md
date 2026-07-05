# Architecture Overview

**GSM (GameSetMatch)** is the backend for a social sports app for tennis, padel, and pickleball.
It minimizes "time-to-court" by removing friction from finding, scheduling, scoring, and tracking
matches — plus formal leagues, a global amateur ranking, and a personal improvement journal.

> Companion: [`diagrams.md`](diagrams.md) for the visual system context, request flow, and trigger
> fan-out. This page is the prose orientation for engineers.

## Technology stack

| Concern | Choice |
|---|---|
| Language / framework | Python 3.11+, FastAPI, Pydantic v2, Uvicorn |
| Database | Firestore (Native mode) with denormalized caches |
| Auth | Firebase Auth — Bearer ID tokens verified via `firebase_admin.auth.verify_id_token` |
| Compute | Cloud Run (europe-west8) |
| Event triggers | Cloud Functions Gen 2 (`functions/`) |
| Push | Firebase Cloud Messaging (FCM) |
| CI/CD | GitHub Actions with Workload Identity Federation |

## Architectural principles

- **REST-only access.** Clients never touch Firestore directly; all reads/writes go through the
  FastAPI API using the Firebase Admin SDK. See [`security.md`](security.md).
- **Layered request path.** `routers/` (thin HTTP) → `services/` (business logic) →
  `repos/` (Firestore data access) → `models/` (Pydantic). Routers stay thin; repos hide Firestore
  details and return domain models.
- **Denormalized caches.** User docs carry `playTab`, `leaguesActive/Completed`, `upcomingMatches`,
  `completedMatches`, etc., so home/profile screens are a single document read. Caches are
  maintained by Cloud Functions triggers, not by the read path. See [`triggers.md`](triggers.md).
- **Transactional writes.** Multi-document state transitions use Firestore transactions for
  atomicity.
- **Freshness reconciliation.** Time-based transitions (broadcast/offer expiry, match start) are
  corrected on read by GET endpoints, so clients always see accurate state without a cron.
  See [`../api/play-tab-state-machine.md`](../api/play-tab-state-machine.md).
- **camelCase ↔ snake_case boundary.** Firestore documents use camelCase; Python models use
  snake_case. Mappers in `repos/mappers.py` translate at the boundary.

## Component layout

```
api/app/
  main.py          # FastAPI app entrypoint; mounts routers, middleware (request-id, timing, CORS)
  routers/         # HTTP endpoints (one module per domain — see below)
  services/        # Business logic (play, league, scoring, onboarding, clubhouse, scouting, …)
  repos/           # Firestore data access (users, matches, offers, broadcasts, leagues, …)
  models/          # Pydantic models & enums
  dependencies/    # FastAPI dependency injection
  security.py      # Auth & authorization helpers
functions/         # Cloud Functions Gen 2 triggers (match, league, journal, notification, scoring, scheduled)
tools/             # Operational scripts (seed, cache rebuild, query checks)
scripts/           # Deployment & smoke-test shell scripts
```

## API surface by domain

The API is organized around the app's four tabs plus shared resources. Full reference:
[`../api/endpoints.md`](../api/endpoints.md).

| Domain | Prefix | Purpose |
|---|---|---|
| Onboarding | `POST /me` | First-run profile/preferences creation. |
| **Tab 1 — Play** | `/me` | `GET /me/state` (UI router), `GET /me/discovery`, broadcasts, offers (accept/decline/cancel). |
| **Tab 2 — Improve** | `/me` | Journal CRUD (`/me/journal`), `GET /me/stats`, `PUT /me/north-star`. |
| **Tab 3 — Lab** | `/me/lab` | Progression, dashboard, skill-DNA, rivalry, scouting, leaderboard, ticker, training-plan. |
| **Tab 4 — Clubhouse** | `/me/clubhouse` | `GET /me/clubhouse/profile`. |
| Matches | `/matches` | `POST /matches/{id}/verify-score`. |
| Leagues | `/leagues` | List/detail, standings, league matches. |
| Venues | `/venues` | List & search courts/venues. |
| Device tokens | `/me/device-tokens` | Register/unregister FCM tokens for push. |
| Health | `/health`, `/ready` | Liveness & readiness probes (public). |

## Data model at a glance

Core Firestore collections: `users/{uid}` (with `journalEntries`, `notificationIntents`,
`deviceTokens`), `leagues/{leagueId}` (with `members/{uid}`), `matches/{matchId}`,
`broadcasts/{broadcastId}`, `offers/{offerId}`, `venues/{venueId}`. Full field-level reference:
[`../data/data-dictionary.md`](../data/data-dictionary.md); query/index contracts:
[`../data/queries-and-indexes.md`](../data/queries-and-indexes.md).

## Where things happen
- **Read a screen** → GET endpoint → service → repo → (mostly) a single denormalized user-doc read.
- **Change state** (broadcast/offer/match/score) → POST endpoint → service runs a Firestore
  transaction across the affected docs.
- **Propagate to caches & push** → Cloud Functions triggers fire on the resulting Firestore writes
  and update denormalized caches / deliver FCM notifications, out of band from the request.
