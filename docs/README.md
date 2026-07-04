# GSM-API Documentation

The backend for **GameSetMatch (GSM)** — a social sports matchmaking app for tennis, padel, and
pickleball. FastAPI on Cloud Run, Firestore for data, Cloud Functions for triggers, Firebase Auth
for identity.

> **New here? Start with the path that matches you.** Each doc has one canonical home — if a topic
> belongs elsewhere, this index links to it rather than repeating it.

## I'm building a client (iOS / mobile)
You want to know how to call the API. Start here:

1. [**api/README.md**](api/README.md) — base URLs, auth flow, conventions, error model. *Read first.*
2. [**api/ios-integration.md**](api/ios-integration.md) — call patterns, token handling, polling vs push, worked examples.
3. [**api/endpoints.md**](api/endpoints.md) — full endpoint reference.
4. [**api/contracts.md**](api/contracts.md) — frozen mobile payload shapes.
5. [**api/play-tab-state-machine.md**](api/play-tab-state-machine.md) — the `GET /me/state` UI-router contract.
6. [**api/notifications.md**](api/notifications.md) — push notifications & intents from the client's POV.

## I'm working on the backend
- [**architecture/overview.md**](architecture/overview.md) — system overview, stack, principles, layout.
- [**architecture/diagrams.md**](architecture/diagrams.md) — system context, request flow, trigger fan-out.
- [**architecture/security.md**](architecture/security.md) — access model, auth, authorization, Firestore rules, CORS.
- [**architecture/triggers.md**](architecture/triggers.md) — Cloud Functions: caches, league summaries, push delivery.
- [**architecture/match-lifecycle.md**](architecture/match-lifecycle.md) — match state lifecycle.
- [**data/data-dictionary.md**](data/data-dictionary.md) — canonical Firestore field reference.
- [**data/models.md**](data/models.md) — Pydantic models & enums.
- [**data/queries-and-indexes.md**](data/queries-and-indexes.md) — repos, query contracts, composite indexes.
- [**development/local-setup.md**](development/local-setup.md) — run locally against the emulators + auth testing.
- [**development/testing.md**](development/testing.md) — test layout, markers, commands.

## I'm running the service
- [**operations/runbook.md**](operations/runbook.md) — operator playbook.
- [**operations/deployment.md**](operations/deployment.md) — Cloud Functions / Cloud Run deployment.
- [**operations/observability.md**](operations/observability.md) — health, readiness, tracing, telemetry funnel.
- [**operations/credentials.md**](operations/credentials.md) — credentials handling.
- [**operations/tools.md**](operations/tools.md) — operational scripts (seed, cache rebuild, query checks).

## Design & decision records (non-canonical)
[`design/`](design/) holds deeper design docs and historical analyses (AI training plan, scout of
the month, win-predictor heuristic, danger-zone data model, leagues gap analysis, the MVP roadmap,
Tab-1 plan/payloads, onboarding tier mapping, Tab-2 schema). These record *why* decisions were made
and are not kept in lockstep with the code — always defer to the canonical sections above for
current behavior.

---

## Map

```
docs/
├── api/            # ★ client/iOS-facing: how to call GSM
├── architecture/   # system design, security, triggers, diagrams
├── data/           # Firestore data model, Pydantic models, queries & indexes
├── operations/     # runbook, deployment, observability, credentials, tools
├── development/    # local setup, testing
└── design/         # non-canonical design & decision records
```

Process/workflow docs (sprint tracker, Claude Code skills/agents) live in `.agent/` and `.claude/`,
not here. The repo root [`README.md`](../README.md) covers the CI badge, quickstart, and agent roster.
