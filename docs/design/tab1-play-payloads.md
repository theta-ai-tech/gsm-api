# Tab 1 PLAY — /me/state Payload Examples

> ⚠️ **Design / decision record — non-canonical.** This document captures intent and history and is *not* kept in lockstep with the code. For current behavior, defer to the canonical docs under [`../README.md`](../README.md).

Full JSON response examples for each `PlayTabStateEnum` mode.
See `docs/api/play-tab-state-machine.md` for the envelope definition.

---

## DISCOVERY

Default browse state. No active broadcast, offer, or match.

```json
{
  "mode": "DISCOVERY",
  "server_time": "2026-02-03T10:00:00Z",
  "primary": {
    "broadcast_id": null,
    "match_id": null,
    "active_offer_ids": []
  },
  "payload": {},
  "annotations": {},
  "ui_events": []
}
```

---

## BROADCAST_ACTIVE

User has an active availability broadcast. Offers queue up and are included in the payload.

```json
{
  "mode": "BROADCAST_ACTIVE",
  "server_time": "2026-02-03T10:00:00Z",
  "primary": {
    "broadcast_id": "broadcast_abc",
    "match_id": null,
    "active_offer_ids": ["offer_1", "offer_2"]
  },
  "payload": {
    "broadcast_id": "broadcast_abc",
    "sport": "tennis",
    "match_type": "singles",
    "broadcast_type": "find_opponent",
    "partner_uid": null,
    "availability": "today",
    "court_status": "have_court",
    "court_location": "Central Court, Athens",
    "venue_ref": {
      "venueId": "ten_twenty_club",
      "placeId": null,
      "name": "Ten Twenty Club",
      "coordinates": {"lat": 37.8362, "lng": 23.7627}
    },
    "expires_at": "2026-02-03T16:00:00Z",
    "created_at": "2026-02-03T08:00:00Z",
    "pending_offers": [
      {
        "offer_id": "offer_1",
        "from_uid": "user_456",
        "from_name": "Sam",
        "from_ranking": {"sport": "tennis", "pts": 1100},
        "proposed_time": "2026-02-03T18:00:00Z",
        "message": "Up for a game?",
        "expires_at": "2026-02-03T10:05:00Z",
        "created_at": "2026-02-03T10:00:00Z"
      },
      {
        "offer_id": "offer_2",
        "from_uid": "user_789",
        "from_name": "Jamie",
        "from_ranking": {"sport": "tennis", "pts": 950},
        "proposed_time": "2026-02-03T17:00:00Z",
        "message": null,
        "expires_at": "2026-02-03T10:04:00Z",
        "created_at": "2026-02-03T09:59:00Z"
      }
    ]
  },
  "annotations": {},
  "ui_events": []
}
```

### Doubles variant (find_fourth broadcast)

```json
{
  "mode": "BROADCAST_ACTIVE",
  "server_time": "2026-02-03T10:00:00Z",
  "primary": {
    "broadcast_id": "broadcast_dbl_abc",
    "match_id": null,
    "active_offer_ids": []
  },
  "payload": {
    "broadcast_id": "broadcast_dbl_abc",
    "sport": "padel",
    "match_type": "doubles",
    "broadcast_type": "find_fourth",
    "partner_uid": "user_partner_1",
    "partner_name": "Chris",
    "availability": "today",
    "court_status": "have_court",
    "court_location": "Flisvos Padel Academy",
    "venue_ref": {
      "venueId": "venue_flisvos",
      "placeId": "ChIJFlisvos",
      "name": "Flisvos Padel Academy",
      "coordinates": {"lat": 37.93, "lng": 23.68}
    },
    "expires_at": "2026-02-03T16:00:00Z",
    "created_at": "2026-02-03T08:00:00Z",
    "pending_offers": []
  },
  "annotations": {},
  "ui_events": []
}
```

---

## OUTGOING_OFFER_PENDING

User sent a challenge and is waiting for the recipient to respond.

```json
{
  "mode": "OUTGOING_OFFER_PENDING",
  "server_time": "2026-02-03T10:05:00Z",
  "primary": {
    "broadcast_id": null,
    "match_id": null,
    "active_offer_ids": ["offer_123"]
  },
  "payload": {
    "offer_id": "offer_123",
    "to_uid": "user_789",
    "to_name": "Jamie",
    "to_ranking": {"sport": "tennis", "pts": 950},
    "sport": "tennis",
    "proposed_time": "2026-02-03T18:00:00Z",
    "court_location": "Central Court, Athens",
    "message": "Let's play!",
    "expires_at": "2026-02-03T10:10:00Z",
    "created_at": "2026-02-03T10:05:00Z"
  },
  "annotations": {},
  "ui_events": []
}
```

---

## INCOMING_OFFER_PENDING

User received a direct challenge (no active broadcast) and must respond.

```json
{
  "mode": "INCOMING_OFFER_PENDING",
  "server_time": "2026-02-03T10:01:00Z",
  "primary": {
    "broadcast_id": null,
    "match_id": null,
    "active_offer_ids": ["offer_456"]
  },
  "payload": {
    "offer_id": "offer_456",
    "from_uid": "user_456",
    "from_name": "Sam",
    "from_ranking": {"sport": "tennis", "pts": 1100},
    "sport": "tennis",
    "proposed_time": "2026-02-03T18:00:00Z",
    "court_location": "Central Court, Athens",
    "message": "Up for a game?",
    "expires_at": "2026-02-03T10:06:00Z",
    "created_at": "2026-02-03T10:01:00Z"
  },
  "annotations": {},
  "ui_events": []
}
```

---

## MATCH_SCHEDULED

A confirmed upcoming match is the primary focus. Discovery UI is replaced by the logistics card.

```json
{
  "mode": "MATCH_SCHEDULED",
  "server_time": "2026-02-03T12:00:00Z",
  "primary": {
    "broadcast_id": null,
    "match_id": "match_789",
    "active_offer_ids": []
  },
  "payload": {
    "match_id": "match_789",
    "sport": "tennis",
    "scheduled_at": "2026-02-03T18:00:00Z",
    "court_id": "court_4",
    "court_name": "Central Court",
    "court_geo": {"lat": 37.9838, "lng": 23.7275},
    "opponent": {
      "uid": "user_456",
      "name": "Sam",
      "profile_url": "https://example.com/sam.png",
      "ranking": {"sport": "tennis", "pts": 1100}
    }
  },
  "annotations": {},
  "ui_events": []
}
```

### Doubles variant

`match_type` is `doubles` and `participants` contains 4 entries — 2 per team. Use `participants`
for rendering team labels; `opponent` still carries the lead opponent for singles-style "vs."
display.

```json
{
  "mode": "MATCH_SCHEDULED",
  "server_time": "2026-02-03T12:00:00Z",
  "primary": {
    "broadcast_id": null,
    "match_id": "match_dbl_999",
    "active_offer_ids": []
  },
  "payload": {
    "match_id": "match_dbl_999",
    "sport": "padel",
    "match_type": "doubles",
    "scheduled_at": "2026-02-03T18:00:00Z",
    "venue_ref": {
      "venueId": "venue_flisvos",
      "placeId": "ChIJFlisvos",
      "name": "Flisvos Padel Academy",
      "coordinates": {"lat": 37.93, "lng": 23.68}
    },
    "opponent": {
      "uid": "user_456",
      "name": "Sam",
      "profile_url": null,
      "ranking": {"sport": "padel", "pts": 1100}
    },
    "participants": [
      {"uid": "user_123", "name": "Alex", "team": "A", "role": "player"},
      {"uid": "user_partner_1", "name": "Chris", "team": "A", "role": "player"},
      {"uid": "user_456", "name": "Sam", "team": "B", "role": "player"},
      {"uid": "user_789", "name": "Jordan", "team": "B", "role": "player"}
    ]
  },
  "annotations": {},
  "ui_events": []
}
```

---

## POST_MATCH_LOG_AVAILABLE

Match time has passed. User can submit their result via the score dial.

```json
{
  "mode": "POST_MATCH_LOG_AVAILABLE",
  "server_time": "2026-02-03T18:35:00Z",
  "primary": {
    "broadcast_id": null,
    "match_id": "match_789",
    "active_offer_ids": []
  },
  "payload": {
    "match_id": "match_789",
    "sport": "tennis",
    "scheduled_at": "2026-02-03T18:00:00Z",
    "opponent": {
      "uid": "user_456",
      "name": "Sam"
    }
  },
  "annotations": {},
  "ui_events": []
}
```

### Doubles fields

For doubles matches, the payload also includes `match_type: "doubles"` and a `participants` list
(same shape as MATCH_SCHEDULED). The base envelope is otherwise identical.

---

## POST_MATCH_WAITING_OPPONENT

User has submitted their result and is waiting for the opponent to confirm.

```json
{
  "mode": "POST_MATCH_WAITING_OPPONENT",
  "server_time": "2026-02-03T20:10:00Z",
  "primary": {
    "broadcast_id": null,
    "match_id": "match_789",
    "active_offer_ids": []
  },
  "payload": {
    "match_id": "match_789",
    "submitted_score": {
      "sets": [{"p1_games": 6, "p2_games": 4}, {"p1_games": 6, "p2_games": 3}],
      "winner_uid": "user_123"
    },
    "opponent": {
      "uid": "user_456",
      "name": "Sam"
    }
  },
  "annotations": {},
  "ui_events": []
}
```

### Doubles fields

For doubles matches, the payload also includes `match_type: "doubles"` and a `participants` list
(same shape as MATCH_SCHEDULED). The base envelope is otherwise identical.

---

## POST_MATCH_CONFIRM_REQUIRED

Opponent submitted their result first. This user must confirm or reject.

```json
{
  "mode": "POST_MATCH_CONFIRM_REQUIRED",
  "server_time": "2026-02-03T20:15:00Z",
  "primary": {
    "broadcast_id": null,
    "match_id": "match_789",
    "active_offer_ids": []
  },
  "payload": {
    "match_id": "match_789",
    "opponent_score": {
      "sets": [{"p1_games": 6, "p2_games": 4}, {"p1_games": 6, "p2_games": 3}],
      "winner_uid": "user_456"
    },
    "opponent": {
      "uid": "user_456",
      "name": "Sam"
    }
  },
  "annotations": {},
  "ui_events": []
}
```

### Doubles fields

For doubles matches, the payload also includes `match_type: "doubles"` and a `participants` list
(same shape as MATCH_SCHEDULED). The base envelope is otherwise identical.

---

## MATCH_DISPUTED

Conflicting post-match submissions. Requires dispute resolution.

```json
{
  "mode": "MATCH_DISPUTED",
  "server_time": "2026-02-03T20:20:00Z",
  "primary": {
    "broadcast_id": null,
    "match_id": "match_789",
    "active_offer_ids": []
  },
  "payload": {
    "match_id": "match_789",
    "my_score": {
      "sets": [{"p1_games": 6, "p2_games": 4}, {"p1_games": 6, "p2_games": 3}],
      "winner_uid": "user_123"
    },
    "opponent_score": {
      "sets": [{"p1_games": 4, "p2_games": 6}, {"p1_games": 6, "p2_games": 3}, {"p1_games": 7, "p2_games": 5}],
      "winner_uid": "user_456"
    },
    "opponent": {
      "uid": "user_456",
      "name": "Sam"
    }
  },
  "annotations": {},
  "ui_events": []
}
```
