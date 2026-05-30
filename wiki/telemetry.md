# Launch Telemetry Schema

## Overview

GSM emits structured telemetry events for the core play funnel to measure time-to-match
and user behavior. Events are serialized as compact JSON and emitted via `log_analytics_event`
in `api/app/logging.py`, which writes to Cloud Logging (structured log output). No separate
Firestore collection is required for MVP.

## Implementation Mechanism

- **Emitter**: `log_analytics_event()` in `api/app/logging.py`
- **Transport**: Python structured logger → Cloud Logging (JSON payload)
- **Queryability**: Cloud Logging → optional BigQuery export for dashboards
- **No Firestore writes**: events are logs, not documents

OBS-2 and OBS-3 will extend `log_analytics_event` with the following additional kwargs:
`match_type`, `region`, `venue_present`, `broadcast_id`, `offer_id`, `created_at`.
The extended signature (to be added in OBS-2):

```python
def log_analytics_event(
    logger: logging.Logger,
    *,
    event: str,
    uid: str,
    created_at: str,              # ISO8601 UTC string
    sport: str | None = None,
    match_type: str | None = None,
    region: str | None = None,
    venue_present: bool | None = None,
    broadcast_id: str | None = None,
    offer_id: str | None = None,
    match_id: str | None = None,
    # legacy params kept for journal events
    entry_type: str | None = None,
) -> None:
```

## Base Event Schema

Every telemetry event carries the following fields:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `event_type` | string | **required** | Event name from the catalogue below. Stored as `event` key for legacy compat. |
| `uid` | string | **required** | UID of the acting user (sender for offer events, the scheduling user for match events). |
| `created_at` | string (ISO8601 UTC) | **required** | Explicit event timestamp. Use `datetime.utcnow().isoformat() + "Z"`. |
| `sport` | string | optional | Sport enum value: `tennis`, `padel`, `pickleball`. |
| `match_type` | string | optional | `singles` or `doubles`. Derive from broadcast `broadcast_type` where match doesn't exist yet: `find_opponent` → `singles`, `find_fourth` → `doubles`. |
| `region` | string | optional | Region identifier (e.g. `athens`). Derived from `location.area` via `config/regions`. Log `null` if lookup is not available in the hot path. |
| `venue_present` | boolean | optional | `true` if a court/venue was specified (`courtStatus == "have_court"` with `courtLocation`, or a `courtId` on the match). |
| `broadcast_id` | string | conditional | Present for broadcast and offer events. |
| `offer_id` | string | conditional | Present for offer and match scheduling events. |
| `match_id` | string | conditional | Present for match and score events. |

## Event Catalogue

### broadcast_created
Emitted when a user taps "I'm Ready to Play" and creates a broadcast.

| Field | Value |
|-------|-------|
| `uid` | broadcast owner UID |
| `sport` | broadcast sport |
| `match_type` | derived from `broadcast_type` |
| `region` | derived from `location.area` (or null) |
| `venue_present` | `courtStatus == "have_court"` |
| `broadcast_id` | new broadcast document ID |

### offer_sent
Emitted when a user sends a match offer to a broadcaster.

| Field | Value |
|-------|-------|
| `uid` | sender UID (`from_uid`) |
| `sport` | offer sport |
| `match_type` | derived from target broadcast's `broadcast_type` |
| `region` | derived from `location.area` of target broadcast (or null) |
| `venue_present` | `courtLocation` is set on the offer |
| `broadcast_id` | target broadcast ID (if offer targets a broadcast) |
| `offer_id` | new offer document ID |

### offer_received
Emitted alongside `offer_sent` from the recipient's perspective. Same event emission point (`send_offer()`); use `to_uid` as `uid`.

| Field | Value |
|-------|-------|
| `uid` | recipient UID (`to_uid`) |
| `sport`, `match_type`, `region`, `venue_present`, `broadcast_id`, `offer_id` | same as `offer_sent` |

### offer_accepted
Emitted when the recipient accepts an offer.

| Field | Value |
|-------|-------|
| `uid` | accepting user UID |
| `sport` | offer sport |
| `match_type` | derived from broadcast or offer context |
| `region` | derived from `location.area` (or null) |
| `venue_present` | `courtLocation` is set on the accepted offer |
| `offer_id` | accepted offer document ID |
| `match_id` | newly created match document ID |

### match_scheduled
Emitted immediately after a match document is created (same transaction as `offer_accepted`). Emit once per match, with the scheduling user's UID.

| Field | Value |
|-------|-------|
| `uid` | the user who accepted the offer (match initiator) |
| `sport` | match sport |
| `match_type` | match `match_type` field |
| `region` | derived from context (or null) |
| `venue_present` | `courtId` or `courtLocation` is set on the match |
| `offer_id` | offer that created the match |
| `match_id` | new match document ID |

### score_submitted
Emitted when the first player submits their score (match moves to `pending_confirmation`).

| Field | Value |
|-------|-------|
| `uid` | submitting user UID |
| `sport` | match sport |
| `match_type` | match `match_type` |
| `match_id` | match document ID |
| `venue_present` | `courtId` is set on match |

### score_confirmed
Emitted when the second player confirms the score (match moves to `completed`).

| Field | Value |
|-------|-------|
| `uid` | confirming user UID |
| `sport` | match sport |
| `match_type` | match `match_type` |
| `match_id` | match document ID |
| `venue_present` | `courtId` is set on match |

### match_disputed
Emitted when a player disputes the submitted score.

| Field | Value |
|-------|-------|
| `uid` | disputing user UID |
| `sport` | match sport |
| `match_type` | match `match_type` |
| `match_id` | match document ID |

## Computed Metrics

These fields enable the following product metrics:

| Metric | How |
|--------|-----|
| Time-to-match | `match_scheduled.created_at` − `broadcast_created.created_at` (same broadcast_id) |
| Time-to-confirm | `score_confirmed.created_at` − `match_scheduled.created_at` (same match_id) |
| Offer acceptance rate | count(`offer_accepted`) / count(`offer_sent`) |
| Dispute rate | count(`match_disputed`) / count(`score_submitted`) |
| Doubles vs singles share | filter by `match_type` on any event |

## Singles + Doubles Compatibility

All events are compatible with both singles and doubles:
- `match_type` distinguishes the mode at query time.
- `uid` is always a single user UID (not a team). For doubles events, one event is emitted per submitting user.
- Fields like `offer_id`, `broadcast_id`, `match_id` are format-agnostic document IDs.
