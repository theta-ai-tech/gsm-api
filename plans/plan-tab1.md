# Epic E — Tab 1 PLAY: Endpoints & Documentation

## Design Decisions
- **Broadcasts & Offers**: Top-level Firestore collections (`broadcasts/{id}`, `offers/{id}`)
- **State source**: Persisted `playTab` map on user doc, synced by API transactions (triggers later as backstops)
- **Write scope**: GET /me/state + core writes (broadcast CRUD, offer send/accept/decline/cancel)
- **Broadcast limit**: One active broadcast per user at a time
- **Offer flow**: Broadcast stays live while offers queue up; user picks from multiple challengers
- **Freshness**: GET /me/state reconciles time-based expirations on read (broadcast TTL, offer expiry, scheduledAt)

---

## Issues

### E1: Documentation — Firestore schema for broadcasts & offers
Add `broadcasts/{broadcastId}` and `offers/{offerId}` collection schemas to `wiki/DATA_DICTIONARY.md` and `wiki/dbschema.md`.

**Files**:
- `wiki/DATA_DICTIONARY.md` — Add broadcasts + offers collection field tables, enums, examples
- `wiki/dbschema.md` — Add broadcasts + offers collection entries

---

### E2: Documentation — playTab field on users/{uid}
Add the new `playTab` cache map to the user doc schema.

**Files**:
- `wiki/DATA_DICTIONARY.md` — Add playTab fields to users collection
- `wiki/dbschema.md` — Add playTab to users collection sketch

---

### E3: Documentation — New enums
Document `BroadcastStatusEnum`, `AvailabilityEnum`, `CourtStatusEnum`, `OfferStatusEnum` in the models wiki.

**Files**:
- `wiki/models.md` — Add new enums section
- `wiki/DATA_DICTIONARY.md` — Add enum definitions to Enums section

---

### E4: Documentation — Updated state machine diagram
Replace the existing state machine in `arch/me_state_machine.md` with a refined version that accounts for BROADCAST_ACTIVE coexisting with queued offers.

**Files**:
- `arch/me_state_machine.md` — Updated mermaid diagram with offer queue nuances + notes

---

### E5: Documentation — /me/state response envelope & mode payloads
Define the full response contract: envelope shape, mode-specific payload examples for all 9 states.

**Files**:
- `wiki/me-state.md` — Expand with envelope definition, payload per mode, examples
- `spec/tab1-play-payloads.md` — New file with full JSON examples per mode

---

### E6: Documentation — Endpoint specs for all Tab 1 endpoints
Document all 7 endpoints with method, path, auth, request/response shapes, errors.

**Files**:
- `wiki/endpoints.md` — Add all /me/* endpoint documentation

---

### E7: Code — New enums in models/enums.py
Add `BroadcastStatusEnum`, `AvailabilityEnum`, `CourtStatusEnum`, `OfferStatusEnum`.

**Files**:
- `api/app/models/enums.py`

---

### E8: Code — Pydantic models for play tab
Create request/response models: `MeStateResponse`, broadcast/offer request bodies, mode-specific payload models.

**Files**:
- `api/app/models/play.py` (new)

---

### E9: Code — BroadcastsRepo & OffersRepo
Firestore CRUD for broadcasts and offers collections.

**Files**:
- `api/app/repos/broadcasts_repo.py` (new)
- `api/app/repos/offers_repo.py` (new)
- `api/app/dependencies/repos.py` — Add get_broadcasts_repo(), get_offers_repo()

---

### E10: Code — PlayService (state computation + transactional writes)
Core business logic: state derivation, freshness reconciliation, broadcast/offer/match transitions.

**Files**:
- `api/app/services/play_service.py` (new)

---

### E11: Code — GET /me/state endpoint
Implement the read endpoint with freshness reconciliation.

**Files**:
- `api/app/routers/play.py` (new)
- `api/app/main.py` — Remove placeholder, include play router

---

### E12: Code — POST /me/broadcast + DELETE /me/broadcast
Create and cancel broadcast endpoints.

**Files**:
- `api/app/routers/play.py`

---

### E13: Code — POST /me/offers (send challenge)
Send an offer/challenge to another user.

**Files**:
- `api/app/routers/play.py`

---

### E14: Code — POST /me/offers/{offer_id}/accept, decline, cancel
Accept, decline, or cancel an offer.

**Files**:
- `api/app/routers/play.py`

---

### E15: Code — Unit tests
Tests for PlayService logic, router endpoints, state reconciliation.

**Files**:
- `tests/unit/test_play_service.py` (new)
- `tests/unit/test_play_router.py` (new)

---

## Detailed Specifications

### Firestore: broadcasts/{broadcastId}

| Field          | Type      | Required | Enum              | Notes                                    |
|----------------|-----------|----------|-------------------|------------------------------------------|
| ownerUid       | string    | yes      | —                 | Broadcaster's UID                        |
| sport          | string    | yes      | sport             | Sport enum                               |
| availability   | string    | yes      | availability      | `today` / `tomorrow` / `weekend`         |
| courtStatus    | string    | yes      | courtStatus       | `have_court` / `need_court`              |
| courtLocation  | string    | optional | —                 | Free-text location (if have_court)       |
| status         | string    | yes      | broadcastStatus   | `active` / `expired` / `cancelled` / `matched` |
| expiresAt      | timestamp | yes      | —                 | Hard cut-off TTL                         |
| createdAt      | timestamp | yes      | —                 | When broadcast was created               |
| ownerName      | string    | yes      | —                 | Denormalized for read                    |
| ownerRanking   | map       | optional | —                 | Denormalized `{sport, pts}`              |
| location       | map       | yes      | —                 | At least one of `area` or `geo` required |
| location.area  | number    | optional | —                 | Predefined area code (coarse filter)     |
| location.geo   | map       | optional | —                 | Jittered WGS84 `{lat, lng}`             |
| location.radiusKm | number | optional | —                 | Search radius in km (default 15)         |

### Firestore: offers/{offerId}

| Field          | Type      | Required | Enum         | Notes                                    |
|----------------|-----------|----------|--------------|------------------------------------------|
| fromUid        | string    | yes      | —            | Sender UID                               |
| toUid          | string    | yes      | —            | Recipient UID                            |
| broadcastId    | string    | optional | —            | If offer targets a broadcast             |
| sport          | string    | yes      | sport        | Sport enum                               |
| proposedTime   | timestamp | optional | —            | Suggested match time                     |
| courtLocation  | string    | optional | —            | Proposed court                           |
| message        | string    | optional | —            | Free-text message                        |
| status         | string    | yes      | offerStatus  | `pending` / `accepted` / `declined` / `expired` / `cancelled` |
| expiresAt      | timestamp | yes      | —            | Auto-expiry                              |
| createdAt      | timestamp | yes      | —            | When offer was created                   |
| fromName       | string    | yes      | —            | Denormalized                             |
| fromRanking    | map       | optional | —            | Denormalized `{sport, pts}`              |
| toName         | string    | yes      | —            | Denormalized                             |
| toRanking      | map       | optional | —            | Denormalized `{sport, pts}`              |
| matchId        | string    | optional | —            | Set when accepted, references created match |

### New field on users/{uid}: playTab

| Field                           | Type           | Notes                                     |
|---------------------------------|----------------|-------------------------------------------|
| playTab.state                   | string         | PlayTabStateEnum value (default: DISCOVERY) |
| playTab.activeBroadcastId       | string / null  | Current broadcast doc ID                   |
| playTab.activeMatchId           | string / null  | Current match doc ID (when scheduled+)     |
| playTab.activeOutgoingOfferId   | string / null  | Pending offer sent by this user            |
| playTab.pendingIncomingOfferIds | array\<string> | Pending offers received by this user       |
| playTab.updatedAt               | timestamp      | Last state transition time                 |

### Endpoints Summary

| # | Method | Path | Auth | Purpose | Issue |
|---|--------|------|------|---------|-------|
| 1 | GET    | `/me/state` | Bearer | Tab 1 home state + payload | E11 |
| 2 | POST   | `/me/broadcast` | Bearer | Start broadcasting availability | E12 |
| 3 | DELETE | `/me/broadcast` | Bearer | Cancel active broadcast | E12 |
| 4 | POST   | `/me/offers` | Bearer | Send a challenge/offer | E13 |
| 5 | POST   | `/me/offers/{offer_id}/accept` | Bearer | Accept incoming offer → creates match | E14 |
| 6 | POST   | `/me/offers/{offer_id}/decline` | Bearer | Decline incoming offer | E14 |
| 7 | POST   | `/me/offers/{offer_id}/cancel` | Bearer | Sender withdraws pending offer | E14 |

### State Machine (refined)

```
DISCOVERY
  |- POST /me/broadcast           -> BROADCAST_ACTIVE
  |- POST /me/offers              -> OUTGOING_OFFER_PENDING
  |- (receive offer, no broadcast) -> INCOMING_OFFER_PENDING

BROADCAST_ACTIVE
  |- (receive offers)              -> stays BROADCAST_ACTIVE (offers queue in pendingIncomingOfferIds)
  |- POST /me/offers/{id}/accept   -> MATCH_SCHEDULED (cancel broadcast + decline others)
  |- DELETE /me/broadcast          -> DISCOVERY (decline all pending offers)
  |- (broadcast TTL expires)       -> DISCOVERY (freshness reconciliation)

OUTGOING_OFFER_PENDING
  |- (offer accepted by recipient) -> MATCH_SCHEDULED
  |- (offer declined/expired)      -> DISCOVERY or BROADCAST_ACTIVE (if broadcast still active)
  |- POST /me/offers/{id}/cancel   -> DISCOVERY or BROADCAST_ACTIVE

INCOMING_OFFER_PENDING (no active broadcast)
  |- POST /me/offers/{id}/accept   -> MATCH_SCHEDULED
  |- POST /me/offers/{id}/decline  -> DISCOVERY
  |- (offer expires)               -> DISCOVERY

MATCH_SCHEDULED
  |- (scheduledAt passes)          -> POST_MATCH_LOG_AVAILABLE (freshness reconciliation)

POST_MATCH_LOG_AVAILABLE
  |- (user submits score)          -> POST_MATCH_WAITING_OPPONENT
  |- (opponent submits score)      -> POST_MATCH_CONFIRM_REQUIRED

POST_MATCH_CONFIRM_REQUIRED
  |- (user confirms)               -> POST_MATCH_WAITING_OPPONENT / completed -> DISCOVERY
  |- (user rejects)                -> MATCH_DISPUTED

POST_MATCH_WAITING_OPPONENT
  |- (opponent confirms)           -> completed -> DISCOVERY
  |- (conflicting submission)      -> MATCH_DISPUTED

MATCH_DISPUTED
  |- (resolved)                    -> DISCOVERY
```

### Response Envelope

```json
{
  "mode": "<PlayTabStateEnum>",
  "serverTime": "2026-02-03T10:00:00Z",
  "primary": {
    "broadcastId": "b_abc | null",
    "matchId": "m_123 | null",
    "activeOfferIds": ["o_1"]
  },
  "payload": { "/* mode-specific — see spec/tab1-play-payloads.md */" },
  "annotations": { "/* discovery-only UI hints */" },
  "uiEvents": [
    { "type": "offer_expired", "message": "Offer from Sam expired.", "meta": {"offerId": "o_1"} }
  ]
}
```

---

## Execution Order

Documentation first (E1-E6), then code (E7-E15). Each issue is reviewed and approved individually before implementation.
