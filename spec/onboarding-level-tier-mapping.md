# Onboarding: Level → Tier Mapping

## Overview

When a new user registers via `POST /me`, they self-assess their skill level per sport.
The backend translates that self-assessment into an immutable `registrationTier`, which
sets the scoring floor for that sport. The client cannot supply `registrationTier` directly.

## Level → Tier Table

| Self-assessed Level | Assigned `registrationTier` |
|---------------------|------------------------------|
| `beginner`          | `amateur`                    |
| `intermediate`      | `intermediate`               |
| `advanced`          | `advanced`                   |
| `pro`               | `competitive`                |

The mapping is implemented via `LEVEL_TO_TIER` in `api/app/services/onboarding_service.py`.

## Initial Points

The initial `pts` for each sport ranking is set to `tier_config.get_floor(registrationTier)`,
i.e. the minimum points boundary for the assigned tier. This is read from `config/tiers` in
Firestore at registration time using `TierConfigRepo`.

## Email Resolution

Firebase tokens do not always carry an `email` claim (e.g. phone-auth or some federated
providers omit it). The resolution order is:

1. Use `email` from the Firebase ID token if present (`CurrentUser.email`).
2. Else use `email` from the request body (optional field).
3. If neither is available → `422 Unprocessable Entity`.

The client should always supply `email` in the request body when the auth provider may not
include it in the token.

## Immutability of `registrationTier`

`registrationTier` is set once at registration and has no update path in any API endpoint.
It represents the historical tier floor and is used by the scoring system as a reference point.
