# Tab 1 State Machine (/me/state)

## Core state diagram


```mermaid
stateDiagram-v2
    [*] --> DISCOVERY

    DISCOVERY --> BROADCAST_ACTIVE: POST /me/broadcast
    BROADCAST_ACTIVE --> DISCOVERY: DELETE /me/broadcast\nor broadcast TTL expired

    DISCOVERY --> OUTGOING_OFFER_PENDING: POST /me/offers (direct challenge)
    BROADCAST_ACTIVE --> OUTGOING_OFFER_PENDING: POST /me/offers (while broadcasting)
    OUTGOING_OFFER_PENDING --> DISCOVERY: offer expired/declined/cancelled\n(no broadcast)
    OUTGOING_OFFER_PENDING --> BROADCAST_ACTIVE: offer expired/declined/cancelled\n(broadcast still active)

    DISCOVERY --> INCOMING_OFFER_PENDING: offer received (no broadcast)
    INCOMING_OFFER_PENDING --> DISCOVERY: offer expired/declined

    OUTGOING_OFFER_PENDING --> MATCH_SCHEDULED: offer accepted
    INCOMING_OFFER_PENDING --> MATCH_SCHEDULED: POST /me/offers/{id}/accept
    BROADCAST_ACTIVE --> MATCH_SCHEDULED: POST /me/offers/{id}/accept\n(cancel broadcast + decline others)

    MATCH_SCHEDULED --> POST_MATCH_LOG_AVAILABLE: scheduledAt passed

    POST_MATCH_LOG_AVAILABLE --> POST_MATCH_WAITING_OPPONENT: user submitted result first
    POST_MATCH_LOG_AVAILABLE --> POST_MATCH_CONFIRM_REQUIRED: opponent submitted result first

    POST_MATCH_CONFIRM_REQUIRED --> POST_MATCH_WAITING_OPPONENT: user confirmed
    POST_MATCH_CONFIRM_REQUIRED --> MATCH_DISPUTED: user rejected/opposing result
    POST_MATCH_WAITING_OPPONENT --> MATCH_DISPUTED: conflicting opponent submission

    MATCH_DISPUTED --> POST_MATCH_WAITING_OPPONENT: dispute resolved in user's favor pending opponent
    MATCH_DISPUTED --> DISCOVERY: dispute closed/finalized
    POST_MATCH_WAITING_OPPONENT --> DISCOVERY: completion finalized
```

## Offer queue behavior

When a user is in `BROADCAST_ACTIVE`, incoming offers **do not change the state**. Instead they accumulate in `playTab.pendingIncomingOfferIds` on the user doc. The `/me/state` payload includes the list of pending offers so the UI can display a chooser.

Accepting any offer from BROADCAST_ACTIVE transitions directly to MATCH_SCHEDULED, which also:
- Cancels the active broadcast (status → `matched`)
- Declines all other pending offers (status → `declined`)
- Clears `playTab.pendingIncomingOfferIds`

## Time-based transitions

These transitions cannot be driven by Firestore triggers alone (no "cron" on doc fields). They are handled by **freshness reconciliation** on GET /me/state:

| Stale state | Condition | Corrected state |
|---|---|---|
| `BROADCAST_ACTIVE` | `broadcast.expiresAt < now` | → `DISCOVERY` |
| `OUTGOING_OFFER_PENDING` | `offer.expiresAt < now` | → `DISCOVERY` or `BROADCAST_ACTIVE` |
| `INCOMING_OFFER_PENDING` | `offer.expiresAt < now` | → `DISCOVERY` |
| `MATCH_SCHEDULED` | `match.scheduledAt < now` | → `POST_MATCH_LOG_AVAILABLE` |

The API reads the persisted `playTab.state`, checks the relevant timestamps, and corrects + writes back if stale. This ensures the client always sees accurate state.
