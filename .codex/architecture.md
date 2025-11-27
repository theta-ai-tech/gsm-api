# GSM – Architecture (Dev Phase)

## Purpose
High-level view of the GSM backend: HTTP API, event triggers, data store, auth, and CI/CD.

## Components
- **API:** FastAPI container on **Cloud Run** (region: `europe-west8`)  
- **Triggers:** **Cloud Functions Gen 2** for Firestore/PubSub events (same region)  
- **Data Store:** **Firestore** (Native mode)  
- **Container Registry:** **Artifact Registry** (Docker)  
- **Auth:** **Firebase Auth** (clients sign in → send **ID token** to API)  
- **CI/CD:** GitHub Actions → build/push image → deploy to Cloud Run via **Workload Identity Federation (WIF)**

## Runtime Flow (request path)
1. Client signs in with Firebase → obtains **ID token**.  
2. Client calls API with `Authorization: Bearer <ID_TOKEN>`.  
3. FastAPI dependency verifies token via `firebase_admin.auth.verify_id_token`.  
4. Handler uses `request.state.uid` to authorize and query Firestore.  
5. Response returned.  

## Why this architecture
- **Portability & repeatability:** containerized API  
- **Autoscaling & managed ops:** Cloud Run/Functions  
- **Native events:** Functions Gen2 (Firestore/Storage/PubSub)  
- **Secure CI/CD:** WIF (no long-lived JSON keys)  

## Decision Notes
- Cloud Run kept **public** in dev; **route-level** auth enforces protection.  
- Everything colocated in `europe-west8` to minimize latency.  


