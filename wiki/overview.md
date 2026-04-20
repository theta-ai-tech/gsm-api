# GSM (Grand Slam Matchmaking) — Technical Specification

**Version**: 1.0
**Last Updated**: 2026-02-07

This document serves as the **golden source** technical specification for the GSM backend API. It provides a comprehensive reference for developers, architects, mobile teams, and new joiners.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Data Model](#data-model)
4. [Tab 1: PLAY — User Scenarios & Flows](#tab-1-play--user-scenarios--flows)
5. [API Endpoints Reference](#api-endpoints-reference)
6. [State Machine](#state-machine)
7. [Models & Types](#models--types)
8. [Development Guide](#development-guide)
9. [Appendices](#appendices)

---

## Overview

**GSM (Grand Slam Matchmaking)** is a next-generation social sports app for tennis, padel, and pickleball players. The platform enables:

- **Self-organized matches**: Find and challenge nearby players
- **Formal leagues**: Round-robin competitive leagues with prizes
- **Scoring system**: Global amateur ranking (ATP for Amateurs)
- **Personal journal**: Track progress, opponent analysis, AI insights

**Mission**: Become the global standard for amateur sports scoring and matchmaking.

**Core Value Proposition**: Minimize "Time-to-Court" by removing all friction from the matchmaking process.

---

## Architecture

### Technology Stack

- **Backend**: FastAPI (Python 3.11+) + Pydantic v2
- **Database**: Google Firestore (Native mode)
- **Authentication**: Firebase Auth (Bearer tokens)
- **Functions**: Cloud Functions for Firebase (denormalization triggers)
- **Real-time**: Client polling (future: WebSockets/FCM push)

### Key Architectural Principles

- **Denormalized caches**: User docs maintain `playTab`, `leagues_active`, `upcoming_matches` etc. for fast reads
- **Transactional writes**: All state transitions use Firestore transactions spanning multiple docs
- **Freshness reconciliation**: GET endpoints correct stale time-based state on read
- **Repository pattern**: Clean separation between Firestore (camelCase) and Pydantic (snake_case)

### Directory Structure

```
api/
├── app/
│   ├── models/          # Pydantic models (snake_case)
│   ├── repos/           # Firestore data access layer
│   ├── services/        # Business logic
│   ├── routers/         # HTTP endpoint handlers
│   ├── dependencies/    # FastAPI dependency injection
│   └── main.py          # App entry point
wiki/                    # Documentation (schemas, endpoints, queries)
arch/                    # Architecture diagrams and state machines
spec/                    # Product requirements and payload examples
```

See `arch/` folder for detailed component diagrams.

---

## Data Model

### Core Entities

- **Users** (`users/{uid}`): Profile, preferences, rankings, denormalized caches
- **Matches** (`matches/{matchId}`): Scheduled/completed matches with scores
- **Leagues** (`leagues/{leagueId}`): Round-robin tournaments
- **Journal Entries** (`journal/{entryId}`): User reflections and training logs
- **Broadcasts** (`broadcasts/{broadcastId}`): Availability announcements (Tab 1)
- **Offers** (`offers/{offerId}`): Challenge offers between players (Tab 1)

### Key Relationships

- Users ↔ Matches: Many-to-many via `participants` array
- Users ↔ Leagues: Many-to-many via `leagueMemberships` subcollection
- Broadcasts → User: One-to-one (one active broadcast per user)
- Offers → Users: Many-to-many (sender, recipient)
- Offers → Match: One-to-one (when accepted)

**Detailed Schema**: See `wiki/DATA_DICTIONARY.md` for complete Firestore field definitions and indexes.

---

## Tab 1: PLAY — User Scenarios & Flows

Tab 1 is the core matchmaking engine. It's a dynamic state machine that adapts the UI based on the user's current match lifecycle state.

### Scenario 1: Broadcast & Accept Challenge (Happy Path)

**Actors**: Alice (broadcaster), Bob (challenger)

**Flow**:

1. **Alice opens Tab 1**
   - Request: `GET /me/state`
   - Response: `{ "mode": "DISCOVERY", ... }`
   - UI: Shows map with nearby players and "I'M READY TO PLAY" FAB button

2. **Alice taps "I'M READY TO PLAY"**
   - Request: `POST /me/broadcast`
     ```json
     {
       "sport": "tennis",
       "availability": "today",
       "courtStatus": "have_court",
       "courtLocation": "Central Court, Athens",
       "expiresAt": "2026-02-07T18:00:00Z",
       "location": { "area": 101, "geo": {"lat": 37.98, "lng": 23.73}, "radiusKm": 10 }
     }
     ```
   - Backend:
     - Creates `broadcasts/{id}` doc (status=active)
     - Updates `users/{alice}.playTab.state = BROADCAST_ACTIVE`
     - Updates `users/{alice}.playTab.activeBroadcastId = {id}`
   - Response: `201` with broadcast details
   - **State Transition**: DISCOVERY → BROADCAST_ACTIVE

3. **Bob sees Alice's broadcast and sends challenge**
   - Request: `POST /me/offers`
     ```json
     {
       "toUid": "alice_uid",
       "sport": "tennis",
       "proposedTime": "2026-02-07T16:00:00Z",
       "courtLocation": "Central Court, Athens",
       "message": "Up for a game?"
     }
     ```
   - Backend:
     - Creates `offers/{id}` doc (status=pending, expiresAt=now+5min)
     - Updates `users/{bob}.playTab.state = OUTGOING_OFFER_PENDING`
     - Updates `users/{alice}.playTab.pendingIncomingOfferIds += {offerId}`
     - Alice stays in BROADCAST_ACTIVE (offers queue)
   - **Bob's State Transition**: DISCOVERY → OUTGOING_OFFER_PENDING
   - **Alice's State**: Stays BROADCAST_ACTIVE (offer queues)

4. **Alice polls and sees Bob's challenge**
   - Request: `GET /me/state`
   - Response:
     ```json
     {
       "mode": "BROADCAST_ACTIVE",
       "payload": {
         "broadcastId": "...",
         "pendingOffers": [
           {
             "offerId": "...",
             "fromUid": "bob_uid",
             "fromName": "Bob",
             "proposedTime": "2026-02-07T16:00:00Z",
             "message": "Up for a game?",
             "expiresAt": "2026-02-07T10:05:00Z"
           }
         ]
       }
     }
     ```
   - UI: Shows broadcast card with list of pending challengers

5. **Alice accepts Bob's offer**
   - Request: `POST /me/offers/{offerId}/accept`
   - Backend (in single Firestore transaction):
     - Updates `offers/{id}.status = accepted`, `offers/{id}.matchId = {newMatchId}`
     - Creates `matches/{newMatchId}` doc (status=scheduled, participants=[alice, bob])
     - Updates `broadcasts/{aliceBroadcastId}.status = matched` (cancels broadcast)
     - Declines all other pending offers for Alice
     - Updates `users/{alice}.playTab.state = MATCH_SCHEDULED`, clears broadcast/offer fields
     - Updates `users/{bob}.playTab.state = MATCH_SCHEDULED`, clears offer fields
   - Response: `200` with `{ "matchId": "...", "status": "accepted", "scheduledAt": "..." }`
   - **Both Users' State Transition**: → MATCH_SCHEDULED

6. **Both users poll and see match details**
   - Request: `GET /me/state`
   - Response:
     ```json
     {
       "mode": "MATCH_SCHEDULED",
       "payload": {
         "matchId": "...",
         "sport": "tennis",
         "scheduledAt": "2026-02-07T16:00:00Z",
         "opponent": { "uid": "...", "name": "...", "ranking": {...} }
       }
     }
     ```
   - UI: Discovery list vanishes, replaced by match logistics card with opponent details and GPS navigation

**Key Technical Details**:
- Broadcasts have TTL (`expiresAt`) configured by user
- Offers expire after 5 minutes (hardcoded initially)
- Multiple offers can queue while broadcast is active
- Accepting one offer → cancels broadcast + declines all other pending offers
- All state transitions use Firestore transactions for consistency

---

### Scenario 2: Direct Challenge (No Broadcast)

**Actors**: Charlie (challenger), Diana (recipient)

**Flow**:

1. **Charlie opens Tab 1** → `GET /me/state` → mode: `DISCOVERY`
2. **Charlie sees Diana on the map and taps "Challenge"**
   - Request: `POST /me/offers` (toUid=diana)
   - Backend:
     - Creates offer doc
     - Charlie: DISCOVERY → OUTGOING_OFFER_PENDING
     - Diana: DISCOVERY → INCOMING_OFFER_PENDING (if no active broadcast)
3. **Diana polls** → `GET /me/state` → mode: `INCOMING_OFFER_PENDING`
   - Payload includes Charlie's challenge
4. **Diana accepts** → `POST /me/offers/{id}/accept`
   - Creates match, both users → MATCH_SCHEDULED

**Difference from Scenario 1**: No broadcast involved. Diana's state immediately changes to INCOMING_OFFER_PENDING upon receiving the offer.

---

### Scenario 3: Broadcast Expires / User Cancels

**Flow**:

1. **Alice has active broadcast** → mode: `BROADCAST_ACTIVE`
2. **Option A: Alice cancels manually**
   - Request: `DELETE /me/broadcast`
   - Backend:
     - Updates `broadcasts/{id}.status = cancelled`
     - Declines all pending incoming offers
     - Alice → DISCOVERY
3. **Option B: Broadcast TTL expires**
   - Alice polls: `GET /me/state`
   - Backend detects `broadcast.expiresAt < now`
   - **Freshness reconciliation**:
     - Updates `broadcasts/{id}.status = expired`
     - Updates `users/{alice}.playTab.state = DISCOVERY`
   - Response: mode: `DISCOVERY` with `uiEvents: [{ "type": "broadcast_expired", ... }]`

**Key Point**: Time-based transitions (broadcast/offer expiry, match start time) are handled by **freshness reconciliation** on GET /me/state, ensuring clients always see accurate state even if background jobs haven't run.

---

### Scenario 4: Post-Match Flow

**Flow**:

1. **Match time passes** → `GET /me/state` detects `match.scheduledAt < now`
   - Both users: MATCH_SCHEDULED → POST_MATCH_LOG_AVAILABLE
2. **Alice logs result first** → `POST /matches/{id}/result`
   - Alice: POST_MATCH_LOG_AVAILABLE → POST_MATCH_WAITING_OPPONENT
   - Bob: POST_MATCH_LOG_AVAILABLE → POST_MATCH_CONFIRM_REQUIRED
3. **Bob confirms** → `POST /matches/{id}/confirm`
   - Both users: → DISCOVERY
   - Match status: completed
   - Scores update global rankings

*(Full post-match flow implementation is beyond Tab 1 scope — placeholder for future epics)*

---

## API Endpoints Reference

### Quick Reference Table

| Endpoint | Method | Purpose | Auth | State Transition |
|----------|--------|---------|------|------------------|
| `/health` | GET | Liveness probe | Public | — |
| `/ready` | GET | Readiness probe (Firestore check) | Public | — |
| `/users/{uid}` | GET | Get user profile | Required (self only) | — |
| `/me/state` | GET | Get current Tab 1 state | Required | None (read-only + freshness reconciliation) |
| `/me/broadcast` | POST | Start availability broadcast | Required | DISCOVERY → BROADCAST_ACTIVE |
| `/me/broadcast` | DELETE | Cancel active broadcast | Required | BROADCAST_ACTIVE → DISCOVERY |
| `/me/offers` | POST | Send challenge offer | Required | DISCOVERY/BROADCAST_ACTIVE → OUTGOING_OFFER_PENDING |
| `/me/offers/{id}/accept` | POST | Accept incoming offer | Required | INCOMING_OFFER_PENDING / BROADCAST_ACTIVE → MATCH_SCHEDULED |
| `/me/offers/{id}/decline` | POST | Decline incoming offer | Required | INCOMING_OFFER_PENDING → DISCOVERY (or BROADCAST_ACTIVE) |
| `/me/offers/{id}/cancel` | POST | Cancel outgoing offer | Required | OUTGOING_OFFER_PENDING → DISCOVERY (or BROADCAST_ACTIVE) |

**Detailed Specs**: See `wiki/endpoints.md` for full request/response schemas, error codes, and examples.

---

## State Machine

Tab 1 operates as a finite state machine with 9 states driven by user actions and time-based transitions.

### States (PlayTabStateEnum)

1. **DISCOVERY**: Default browse state (map + player list)
2. **BROADCAST_ACTIVE**: User has active availability broadcast
3. **OUTGOING_OFFER_PENDING**: User sent challenge, waiting for response
4. **INCOMING_OFFER_PENDING**: User received challenge, must respond
5. **MATCH_SCHEDULED**: Confirmed match is upcoming
6. **POST_MATCH_LOG_AVAILABLE**: Match time passed, can submit result
7. **POST_MATCH_WAITING_OPPONENT**: User logged result, waiting for opponent
8. **POST_MATCH_CONFIRM_REQUIRED**: Opponent logged result, user must confirm
9. **MATCH_DISPUTED**: Conflicting post-match submissions

### Key Transition Rules

- **Offer queueing**: BROADCAST_ACTIVE can coexist with pending incoming offers (they queue in `pendingIncomingOfferIds`)
- **Broadcast + outgoing offer**: User can send an offer while broadcasting → transitions to OUTGOING_OFFER_PENDING, broadcast remains active
- **Time-based corrections**: Expiry/match start time handled via freshness reconciliation on GET /me/state

**Full Diagram**: See `arch/me_state_machine.md` for mermaid state diagram, transition table, and repository operations per transition.

---

## Models & Types

### Pydantic Models (Python, snake_case)

All models extend `GsmBaseModel` with:
- `extra="forbid"` (reject unknown fields)
- `populate_by_name=True` (accept both snake_case and camelCase)
- `from_attributes=True` (Pydantic v2 compatibility)
- Automatic naive datetime → UTC normalization

### Core Enums

- Sports: `tennis`, `padel`, `pickleball`
- Levels: `beginner`, `intermediate`, `advanced`, `pro`
- PlayTabStateEnum: 9 states (see State Machine section)
- BroadcastStatusEnum: `active`, `expired`, `cancelled`, `matched`
- OfferStatusEnum: `pending`, `accepted`, `declined`, `expired`, `cancelled`
- AvailabilityEnum: `today`, `tomorrow`, `weekend`
- CourtStatusEnum: `have_court`, `need_court`

### Model Categories

**Common Value Objects** (`models/common.py`):
- `SportRanking`, `PerSportRankings`, `UserPreferences`
- `SetScore`, `MatchScore` (structured scoring)
- Summary models for leagues, matches, journal entries

**User Profiles** (`models/user.py`):
- `PublicUserProfile`: name, rankings, leagues (no email/phone)
- `PrivateUserProfile`: extends public + email, phone, preferences, upcoming/completed matches

**Play Tab** (`models/play.py`):
- Request/Response: `CreateBroadcastRequest`, `SendOfferRequest`, `OfferActionResponse`
- Domain: `Broadcast`, `Offer`, `GeoLocation`, `BroadcastLocation`
- Envelope: `MeStateResponse`, `MeStatePrimary`, `UIEvent`
- Payloads (9): `BroadcastActivePayload`, `OutgoingOfferPayload`, `IncomingOfferPayload`, `MatchScheduledPayload`, plus 5 post-match payloads

**Detailed Reference**: See `wiki/models.md` for complete model catalog.
**Payload Examples**: See `spec/tab1-play-payloads.md` for full JSON response examples per mode.

---

## Development Guide

### Local Setup

1. Install dependencies: `pip install -r requirements.txt`
2. Start Firestore emulator: `firebase emulators:start --only firestore`
3. Run API: `uvicorn api.app.main:app --reload --port 8000`
4. Test: `pytest tests/`

### Repository Pattern

All Firestore access goes through repo classes:
- **Input**: Pydantic models (snake_case)
- **Storage**: Firestore docs (camelCase)
- **Mappers**: `repos/mappers.py` converts between conventions

Example:
```python
# Repo method
def create_broadcast(self, broadcast: Broadcast) -> str:
    data = broadcast_to_firestore_dict(broadcast)  # snake → camel
    doc_ref = self.client.collection("broadcasts").document()
    doc_ref.set(data)
    return doc_ref.id
```

### Testing

- **Unit tests**: `tests/unit/` — Pure business logic (services)
- **Integration tests**: `tests/integration/` — Full endpoint flows with emulator
- Run: `pytest tests/unit` or `pytest tests/integration`

**Best Practices**:
- Mock Firestore for unit tests (use `MagicMock`)
- Use emulator for integration tests
- Test happy path + error cases (404, 409, 410, 422, etc.)

### Deployment

- API: Cloud Run (auto-scaling FastAPI container)
- Functions: Cloud Functions for Firestore triggers (D-series: denormalization)

See `wiki/functions.md` for trigger specifications.

---

## Appendices

### A. Authentication Flow

See `wiki/auth.md` for:
- Firebase ID token verification
- Custom claims (admin roles)
- CurrentUser dependency injection pattern

### B. Database Queries

See `wiki/queries.md` for:
- Firestore composite index requirements
- Cursor-based pagination patterns
- Array-contains queries for participant lookups

### C. Cloud Functions (Triggers)

See `wiki/functions.md` for:
- D-series: Denormalization triggers (update user caches on match/league/journal changes)
- Future: E-series for Tab 1 (broadcast/offer expiry cleanup)

### D. Related Documentation

- **Product Vision**: `docs/strategy/prd-idea.md` (original product concept — repo-root path)
- **Tab 1 PRD**: `docs/product/tab1-play-description.md` (strategic product requirements — repo-root path)
- **Firestore Schema**: `wiki/DATA_DICTIONARY.md` (complete field definitions)
- **Database Sketch**: `wiki/dbschema.md` (collection overview)
- **State Machine**: `arch/me_state_machine.md` (mermaid diagram + transition rules)
- **Match Lifecycle**: `arch/match_lifecycle.md` (post-match flow architecture)

---

**Document Maintenance**: This overview.md is the master reference. When updating detailed docs (wiki/\*, arch/\*, spec/\*), ensure this document stays in sync with high-level changes.
