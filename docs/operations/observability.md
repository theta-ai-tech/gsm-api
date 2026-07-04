# Observability, Readiness & Telemetry

> Health/readiness probes, request tracing, slow-request logging, and the structured
> analytics funnel. Emitter: `log_analytics_event()` in `api/app/logging.py`.

## Liveness vs readiness
- `GET /health` (liveness): public; no external deps; returns 200 if the process is up.
- `GET /ready` (readiness): public; performs a minimal Firestore touch (emulator in dev/CI, real
  Firestore in prod); returns 200 when reachable, 503 otherwise.

## Request IDs & slow-request logging
- Every request gets an `X-Request-Id` (incoming header or generated) echoed in the response.
  Use it to correlate logs for a single request across the stack.
- Timing middleware measures each request; if duration exceeds the threshold (currently 500ms) it
  logs path, method, status, duration, threshold, and `request_id`.

## Auth regression tests & CI
Regression tests for `GET /users/{uid}` lock in current auth behavior (401 no/invalid token; 403
valid token with uid mismatch; 200 valid token, matching uid). GitHub Actions CI runs the unit
suite — auth regression, health/readiness, and observability tests (request id + timing middleware).

---

## Funnel telemetry

GSM emits structured telemetry events for the core play funnel (broadcast → offer → match → score)
to measure time-to-match and user behavior. Events are compact JSON emitted via
`log_analytics_event` to Cloud Logging (structured log output). No Firestore collection is required.

- **Transport:** Python structured logger → Cloud Logging (JSON payload)
- **Queryability:** Cloud Logging → optional BigQuery export for dashboards
- **No Firestore writes:** events are logs, not documents

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
    entry_type: str | None = None,  # legacy, kept for journal events
) -> None:
```

### Base event schema

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `event_type` | string | **required** | Event name from the catalogue. Stored as `event` key for legacy compat. |
| `uid` | string | **required** | Acting user (sender for offer events; scheduling user for match events). |
| `created_at` | string (ISO8601 UTC) | **required** | Explicit event timestamp (`datetime.utcnow().isoformat() + "Z"`). |
| `sport` | string | optional | `tennis`, `padel`, `pickleball`. |
| `match_type` | string | optional | `singles` or `doubles`. Where no match exists yet, derive from broadcast `broadcast_type`: `find_opponent` → `singles`, `find_fourth` → `doubles`. |
| `region` | string | optional | Region id (e.g. `athens`), derived from `location.area`. `null` if lookup isn't in the hot path. |
| `venue_present` | boolean | optional | `true` if a court/venue was specified. |
| `broadcast_id` | string | conditional | Broadcast, offer, and match-scheduling events. |
| `offer_id` | string | conditional | Offer and match-scheduling events. |
| `match_id` | string | conditional | Match and score events. |

### Event catalogue

| Event | Emitted when | `uid` | Key fields |
|---|---|---|---|
| `broadcast_created` | User taps "I'm Ready to Play" | broadcast owner | sport, match_type, region, venue_present (`courtStatus == have_court`), broadcast_id |
| `offer_sent` | User sends a match offer | sender (`from_uid`) | sport, match_type, region, venue_present (`courtLocation` set), broadcast_id, offer_id |
| `offer_received` | Alongside `offer_sent`, recipient POV (same emission point) | recipient (`to_uid`) | same as `offer_sent` |
| `offer_accepted` | Recipient accepts an offer | accepting user | sport, match_type, region, venue_present, offer_id, match_id |
| `match_scheduled` | Match doc created (same txn as `offer_accepted`); once per match | accepting user | sport, match_type, region, venue_present (`courtId`/`courtLocation`), broadcast_id (`offer.broadcastId`; null for direct), offer_id, match_id |
| `score_submitted` | First player submits score (→ `pending_confirmation`) | submitting user | sport, match_type, match_id, venue_present (`courtId`) |
| `score_confirmed` | Second player confirms (→ `completed`) | confirming user | sport, match_type, match_id, venue_present |
| `match_disputed` | A player disputes the score | disputing user | sport, match_type, match_id |

### Computed metrics

| Metric | How |
|--------|-----|
| Time-to-match | `match_scheduled.created_at` − `broadcast_created.created_at` (same `broadcast_id`) |
| Time-to-confirm | `score_confirmed.created_at` − `match_scheduled.created_at` (same `match_id`) |
| Offer acceptance rate | count(`offer_accepted`) / count(`offer_sent`) |
| Dispute rate | count(`match_disputed`) / count(`score_submitted`) |
| Doubles vs singles share | filter by `match_type` on any event |

All events are singles/doubles-compatible: `match_type` distinguishes the mode at query time,
`uid` is always a single user (one event per submitting user for doubles), and `offer_id` /
`broadcast_id` / `match_id` are format-agnostic document IDs.
