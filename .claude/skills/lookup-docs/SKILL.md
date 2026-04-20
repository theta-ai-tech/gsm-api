---
name: lookup-docs
description: Quickly find the right spec, wiki, or architecture doc for a given feature area in the GSM project. Use this skill whenever you need context about a feature before implementing, when looking up Firestore schema or field definitions, when checking how a state machine or trigger works, or when an agent needs to understand the product spec for a tab or feature. Trigger on questions like "what does the spec say about...", "where is the schema for...", "how does the match lifecycle work", or before starting work on any issue that touches an unfamiliar area. Also use proactively when delegating to subagents — include the relevant doc paths in the prompt so they don't waste time exploring.
---

This skill is a fast lookup index for the GSM project's documentation. Instead of exploring `wiki/`, `arch/`, `spec/`, and `plans/` each time, use the index below to jump straight to the right file.

## How to use

1. Identify the feature area from the user's question or the issue being worked on
2. Find the matching doc(s) in the index below
3. Read the doc(s) to get the context you need
4. When delegating to a subagent, include the relevant file paths in the prompt

## Index by topic

### Firestore & Data Model
| Topic | File |
|-------|------|
| All collections, fields, naming conventions | `wiki/DATA_DICTIONARY.md` |
| Collection schemas, example doc shapes | `wiki/dbschema.md` |
| Tab 2 schema extensions (journal, playTab cache) | `wiki/tab2-firestore-schema.md` |
| Query contracts (Q1–Q5) | `wiki/queries.md` |
| Composite indexes for queries | `wiki/firestore-queries-and-indexes.md` |
| Repository layer design | `wiki/repositories.md` |

### API & Endpoints
| Topic | File |
|-------|------|
| All endpoints, auth requirements, behavior | `wiki/endpoints.md` |
| Pydantic models, enums (SportEnum, etc.) | `wiki/models.md` |
| /me/state response envelope, PlayTabStateEnum | `wiki/me-state.md` |
| Tab 1 /me/state JSON payload examples | `spec/tab1-play-payloads.md` |

### Auth & Security
| Topic | File |
|-------|------|
| Firebase Auth, token verification, RBAC | `wiki/auth.md` |
| Auth testing patterns, emulator setup | `wiki/auth-testing.md` |
| CORS middleware config | `wiki/cors.md` |
| Credential management (local/CI/Cloud Run) | `wiki/credentials.md` |

### Triggers & Cloud Functions
| Topic | File |
|-------|------|
| D-series triggers overview (D1–D4) | `wiki/functions.md` |
| Functions deployment, rollback, smoke tests | `wiki/functions-deployment.md` |
| Match lifecycle state machine + onMatchWrite | `arch/match_lifecycle.md` |
| League member triggers (D3.1/D3.2) | `arch/league_member_triggers.md` |
| Tab 1 state machine (DISCOVERY → POST_MATCH) | `arch/me_state_machine.md` |

### Product Specs — by Tab

Product specs live in the top-level `docs/product/` folder, shared across all streams. Paths below are repo-root-relative.

| Tab | File |
|-----|------|
| Tab 1 PLAY — PRD, vision, core goal | `docs/product/tab1-play-description.md` |
| Tab 2 IMPROVE — journal, analytics, Skill DNA | `docs/product/tab2-improve-description.md` |
| Tab 3 LAB — scouting, rankings, intelligence | `docs/product/tab3-lab-description.md` |
| Tab 4 CLUBHOUSE — social, athlete card, feed | `docs/product/tab4-clubhouse-description.md` |
| Tab 4 follow-up features (post-MVP) | `docs/product/tab4-clubhouse-followup.md` |
| Master functional spec (all tabs, triggers, doubles) | `docs/product/functional-tab-spec-v1.4.md` |

### Strategy & Planning
| Topic | File |
|-------|------|
| Product vision, problem statement | `docs/strategy/prd-idea.md` |
| CEO-level review, MVP scope, timeline | `docs/strategy/strategic-product-review-v1.md` |
| Padel-first launch strategy, Athens beachhead | `docs/strategy/padel-launch-playbook-v1.md` |
| Tab 1 implementation plan (Epic E) | `plans/plan-tab1.md` |

### Ops & Observability
| Topic | File |
|-------|------|
| Probes, request IDs, slow request logging | `wiki/observability.md` |
| Operational tools runbook (seed, cache, deploy) | `wiki/tools.md` |
| Golden source technical spec (architecture overview) | `wiki/overview.md` |

## Quick lookup by issue prefix

When working on issues, use this mapping to find the relevant spec:

| Prefix | Area | Start with |
|--------|------|------------|
| LAB-* | Tab 3 Lab | `docs/product/tab3-lab-description.md` → `docs/product/functional-tab-spec-v1.4.md` |
| SE-* | Tab 2 Improve | `docs/product/tab2-improve-description.md` → `wiki/tab2-firestore-schema.md` |
| DBL-* | Doubles support | `docs/product/functional-tab-spec-v1.4.md` (doubles section) |
| Play/broadcast/offer | Tab 1 Play | `docs/product/tab1-play-description.md` → `arch/me_state_machine.md` |
| D-series triggers | Cloud Functions | `wiki/functions.md` → relevant `arch/*.md` |
| Schema/model changes | Data model | `wiki/DATA_DICTIONARY.md` → `wiki/dbschema.md` |
