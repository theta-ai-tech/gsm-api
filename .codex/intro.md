## Project outline

The project implements the backend for GSM - a web/mobile app that builds a social match making application with  features like leagues/matches and journal for self development.

## Context
We need a managed, autoscaling runtime for a containerized Python API, plus native event triggers for Firestore/Storage/PubSub.

## Decision
- **API:** Google Cloud Run (FastAPI container)
- **Triggers:** Cloud Functions Gen 2
- **Auth:** Firebase ID tokens verified in API (route-level)
- **CI/CD:** GitHub Actions → Artifact Registry → Cloud Run (WIF)
- **Region:** `europe-west8` for all serverless resources

## Alternatives considered
- AWS API Gateway + Lambda: cross-cloud complexity with Firestore (egress/cross-auth)
- Cloud Run for everything (no triggers): poorer DX for Firestore events

## Consequences
- Simple deployments & rollbacks (Cloud Run)
- Native triggers for data changes (Gen2)
- Public ingress in dev; security enforced at the app layer