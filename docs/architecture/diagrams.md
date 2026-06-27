# Architecture Diagrams

Mermaid diagrams render natively on GitHub. Keep these in sync with
[`overview.md`](overview.md), [`triggers.md`](triggers.md), and
[`../api/play-tab-state-machine.md`](../api/play-tab-state-machine.md) (the canonical Play state
machine; not duplicated here).

## System context

```mermaid
flowchart LR
    subgraph Client
      iOS["iOS app (SwiftUI)"]
    end
    subgraph GCP["Google Cloud"]
      FBAuth["Firebase Auth"]
      API["GSM API (FastAPI on Cloud Run)"]
      FS[("Firestore")]
      CF["Cloud Functions Gen 2\n(triggers)"]
      FCM["Firebase Cloud Messaging"]
      Logs["Cloud Logging\n(+ optional BigQuery)"]
    end

    iOS -- "sign in" --> FBAuth
    FBAuth -- "ID token" --> iOS
    iOS -- "HTTPS + Bearer token" --> API
    API -- "verify_id_token" --> FBAuth
    API -- "Admin SDK read/write" --> FS
    API -- "structured events" --> Logs
    FS -- "document-write triggers" --> CF
    CF -- "update denormalized caches" --> FS
    CF -- "push" --> FCM
    FCM -- "notification" --> iOS
```

The iOS client never reads or writes Firestore directly — all access is through the API
(see [`security.md`](security.md)).

## Request flow (layered)

```mermaid
flowchart TD
    Req["HTTP request + Bearer token"] --> MW["Middleware:\nrequest-id, timing, CORS"]
    MW --> Auth["get_current_user\n(verify ID token)"]
    Auth --> Router["routers/* (thin HTTP)"]
    Router --> Service["services/* (business logic)"]
    Service --> Repo["repos/* (Firestore access)"]
    Repo --> Mapper["mappers (camelCase ↔ snake_case)"]
    Mapper --> FS[("Firestore")]
    Service -. "state changes" .-> Txn["Firestore transaction\n(multi-doc, atomic)"]
    Txn --> FS
    Service -. "funnel events" .-> Log["log_analytics_event → Cloud Logging"]
```

## Write → trigger fan-out

```mermaid
flowchart TD
    W["API transaction writes\nmatches / leagues.members / notificationIntents"] --> FS[("Firestore")]

    FS -->|"matches/{id} write"| T1["Match triggers"]
    T1 --> C1["Update users.upcomingMatches /\ncompletedMatches caches"]

    FS -->|"leagues/{id}/members/{uid} write"| T2["League-member triggers"]
    T2 --> C2["Upsert/remove users.leaguesActive /\nleaguesCompleted summaries"]

    FS -->|"users/{uid}/notificationIntents/{id} create"| T3["Notification trigger"]
    T3 --> R["Read users.deviceTokens"]
    R --> Send["FCM multicast"]
    Send --> Prune["Prune invalid tokens"]

    classDef kill fill:#fff3cd,stroke:#856404;
    T1:::kill
    T2:::kill
    T3:::kill
```

All trigger handlers respect the `GSM_TRIGGERS_ENABLED` kill switch (highlighted). Details in
[`triggers.md`](triggers.md).

## Match lifecycle

The match status lifecycle (`scheduled → pending_confirmation → completed / disputed / cancelled`)
is documented with its diagram in [`match-lifecycle.md`](match-lifecycle.md). The Play-tab UI state
machine that sits on top of it is in
[`../api/play-tab-state-machine.md`](../api/play-tab-state-machine.md).
