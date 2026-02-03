# /me/state Modes (Tab 1)

This page defines the mode enum and the intended high-level meaning for Tab 1.
It is the source of truth for the UI-router contract before detailed payload logic.

## Enum
`PlayTabStateEnum` values:
- `DISCOVERY`
- `BROADCAST_ACTIVE`
- `OUTGOING_OFFER_PENDING`
- `INCOMING_OFFER_PENDING`
- `MATCH_SCHEDULED`
- `POST_MATCH_LOG_AVAILABLE`
- `POST_MATCH_WAITING_OPPONENT`
- `POST_MATCH_CONFIRM_REQUIRED`
- `MATCH_DISPUTED`

## Mode intent
- `DISCOVERY`: default browse state; map + challengable player list.
- `BROADCAST_ACTIVE`: user has an active availability broadcast.
- `OUTGOING_OFFER_PENDING`: user sent an offer and is waiting for response before expiry.
- `INCOMING_OFFER_PENDING`: user received an offer and must respond before expiry.
- `MATCH_SCHEDULED`: a confirmed upcoming match is the primary focus.
- `POST_MATCH_LOG_AVAILABLE`: match time passed; user can submit/log result.
- `POST_MATCH_WAITING_OPPONENT`: user logged result and is waiting for opponent action.
- `POST_MATCH_CONFIRM_REQUIRED`: opponent logged result and this user must confirm/reject.
- `MATCH_DISPUTED`: conflicting post-match submissions requiring dispute resolution flow.

## Response envelope (draft)
The endpoint keeps a stable generic envelope:
- `mode`
- `serverTime`
- `primary` (stable IDs)
- `payload` (mode-specific minimal fields)
- `annotations` (mainly discovery UI hints)
- `uiEvents` (transient notices; not modes)

See `arch/me_state_machine.md` for high-level transitions.
