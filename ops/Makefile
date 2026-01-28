# --- Config ---
PROJECT_ID := gsm-dev-f70d0
DEV_PROJECT_ID ?= $(PROJECT_ID)
FIRESTORE_HOST := 127.0.0.1
FIRESTORE_PORT := 8082
AUTH_HOST := 127.0.0.1
AUTH_PORT := 9099

EMU_FS := $(FIRESTORE_HOST):$(FIRESTORE_PORT)
EMU_AUTH := $(AUTH_HOST):$(AUTH_PORT)

PYTHON := python3
VENV := .venv
ACT := . $(VENV)/bin/activate

# --- Help ---
# Show available targets
.PHONY: help
help:
	@echo "make venv             - create virtual env"
	@echo "make install          - install api deps"
	@echo "make api-dev          - run FastAPI locally (no emulator)"
	@echo "make api-dev-real     - run API against real Firestore"
	@echo "make emu-firestore    - start Firestore emulator"
	@echo "make emu-all          - start Firestore + Auth emulators"
	@echo "make api-dev-emu      - run API against Firestore emulator"
	@echo "make api-dev-emu-auth - run API against Firestore + Auth emulators"
	@echo "make seed             - seed example data into emulator"
	@echo "make seed-emu         - seed emulator with GSM sample data"
	@echo "make check-queries    - run repo query checks against emulator"
	@echo "make check-queries-emu - run repo query checks against emulator"
	@echo "make test             - run all tests (requires emulators)"
	@echo "make test-int         - run integration tests (requires emulators)"
	@echo "make test-integration - run integration tests (requires emulators)"
	@echo "make test-unit        - run unit tests"
	@echo "make test-tools       - run tools tests"
	@echo "make fmt              - lint/format (ruff)"
	@echo "make format           - formatter pass (ruff)"
	@echo "make type             - type check (mypy)"
	@echo "make docs-check       - validate internal doc links/anchors"
	@echo "make docker-build     - build dev Docker image"
	@echo "make docker-build-amd64 - build amd64 Docker image"
	@echo "make docker-run       - run Docker image locally"
	@echo "make docker-stop      - stop local Docker container"
	@echo "make docker-up        - start Docker Desktop (macOS)"
	@echo "make docker-down      - stop Docker Desktop (macOS)"
	@echo "make functions-venv   - create venv for Firebase Functions and install deps"
	@echo "make deploy-functions - deploy Firebase Functions (dev project)"
	@echo "make smoke-functions  - curl GSM_PING_URL to verify deployed function"
	@echo "make deploy-indexes-dev - deploy Firestore indexes to dev project"

# --- Python env ---
# Create virtual env
.PHONY: venv
venv:
	$(PYTHON) -m venv $(VENV)

# Install dependencies
.PHONY: install
install:
	$(ACT) && pip install --upgrade pip && pip install -e api[dev]

# --- Functions env ---
.PHONY: functions-venv
functions-venv:
	@cd functions && \
	python3.11 -m venv venv && \
	./venv/bin/pip install --upgrade pip && \
	./venv/bin/pip install -r requirements.txt

.PHONY: deploy-functions
deploy-functions:
	@./scripts/deploy_functions.sh --project $(DEV_PROJECT_ID)

.PHONY: smoke-functions
smoke-functions:
	@test -n "$(GSM_PING_URL)" || { echo "Set GSM_PING_URL to the gsm_ping HTTPS URL."; exit 1; }
	@curl -sS "$(GSM_PING_URL)" && echo

# --- API local runs ---
# Local dev against Firestore emulator; sets FIREBASE_PROJECT_ID, GOOGLE_CLOUD_PROJECT, FIRESTORE_EMULATOR_HOST
# Run API locally (no auth emulator)
.PHONY: api-dev
api-dev:
	$(ACT) && \
	export FIREBASE_PROJECT_ID=$(PROJECT_ID) && \
	export GOOGLE_CLOUD_PROJECT=$(PROJECT_ID) && \
	export FIRESTORE_EMULATOR_HOST=$(EMU_FS) && \
	uvicorn app.main:app --reload --port 8000 --app-dir api

# Local dev against real Firestore in the dev project (no emulator); optional/debugging.
# Requires Application Default Credentials: either `gcloud auth application-default login`
# or GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/your-dev-sa.json (outside the repo; never committed).
# Run API locally against real Firestore
.PHONY: api-dev-real
api-dev-real:
	$(ACT) && \
	export FIREBASE_PROJECT_ID=$(PROJECT_ID) && \
	export GOOGLE_CLOUD_PROJECT=$(PROJECT_ID) && \
	uvicorn app.main:app --reload --port 8000 --app-dir api

# Run API against Firestore emulator
.PHONY: api-dev-emu
api-dev-emu:
	$(ACT) && \
	export FIRESTORE_EMULATOR_HOST=$(EMU_FS) && \
	export GOOGLE_CLOUD_PROJECT=$(PROJECT_ID) && \
	uvicorn app.main:app --reload --port 8000 --app-dir api

# Run API against Firestore + Auth emulators
.PHONY: api-dev-emu-auth
api-dev-emu-auth:
	$(ACT) && \
	export FIRESTORE_EMULATOR_HOST=$(EMU_FS) && \
	export FIREBASE_AUTH_EMULATOR_HOST=$(EMU_AUTH) && \
	export GOOGLE_CLOUD_PROJECT=$(PROJECT_ID) && \
	export FIREBASE_PROJECT_ID=$(PROJECT_ID) && \
	uvicorn app.main:app --reload --port 8000 --app-dir api

# --- Emulators ---
# Start Firestore emulator
.PHONY: emu-firestore
emu-firestore:
	firebase emulators:start --only firestore

# Start Firestore + Auth emulators
.PHONY: emu-all
emu-all:
	firebase emulators:start --only firestore,auth

# --- Dev utilities ---
# Seed example data into emulator (legacy)
.PHONY: seed
seed:
	$(ACT) && \
	export FIRESTORE_EMULATOR_HOST=$(EMU_FS) && \
	export GOOGLE_CLOUD_PROJECT=$(PROJECT_ID) && \
	python tests/integration/seed_emulator.py

# Seed Firestore emulator with sample GSM data (C2)
.PHONY: seed-emu
seed-emu:
	$(ACT) && \
	export FIRESTORE_EMULATOR_HOST=$(EMU_FS) && \
	export GOOGLE_CLOUD_PROJECT=$(PROJECT_ID) && \
	python -m tools.seed_firestore --env=emu

# Run repo query checks against emulator (C3.3)
.PHONY: check-queries
check-queries:
	$(ACT) && \
	export FIRESTORE_EMULATOR_HOST=$(EMU_FS) && \
	export GOOGLE_CLOUD_PROJECT=$(PROJECT_ID) && \
	python -m tools.check_queries

# Run repo query checks against emulator (C3.4)
.PHONY: check-queries-emu
check-queries-emu: check-queries
.PHONY: test
# Run full test suite (unit + tools + integration)
.PHONY: test
test:
	$(ACT) && \
	export CORS_ORIGIN="http://localhost:3000" && \
	export FIRESTORE_EMULATOR_HOST=$(EMU_FS) && \
	export FIREBASE_AUTH_EMULATOR_HOST=$(EMU_AUTH) && \
	export GOOGLE_CLOUD_PROJECT=$(PROJECT_ID) && \
	export FIREBASE_PROJECT_ID=$(PROJECT_ID) && \
	pytest -q

# Lint and autofix (ruff)
.PHONY: fmt
fmt:
	$(ACT) && ruff check --fix api tests

# Format code (ruff)
.PHONY: format
format:
	$(ACT) && ruff format api tests

# Type check (mypy)
.PHONY: type
type:
	$(ACT) && mypy --no-incremental api

# Docs link/anchor check
.PHONY: docs-check
docs-check:
	$(PYTHON) -m tools.docs_check

# Run unit tests
.PHONY: test-unit
test-unit:
	pytest -q tests/unit

# Run tools tests
.PHONY: test-tools
test-tools:
	pytest -q tests/tools

# Run integration tests (requires emulators)
.PHONY: test-int
test-int:
	export CORS_ORIGIN="http://localhost:3000" && \
	export FIRESTORE_EMULATOR_HOST=$(EMU_FS) && \
	export FIREBASE_AUTH_EMULATOR_HOST=$(EMU_AUTH) && \
	export GOOGLE_CLOUD_PROJECT=$(PROJECT_ID) && \
	export FIREBASE_PROJECT_ID=$(PROJECT_ID) && \
	pytest -q tests/integration

# Run integration tests (requires emulators)
.PHONY: test-integration
test-integration: test-int

# Deploy Firestore indexes to dev project
.PHONY: deploy-indexes-dev
deploy-indexes-dev:
	@echo "Deploying Firestore indexes to dev project: $(DEV_PROJECT_ID)"
	firebase deploy --only firestore:indexes --project $(DEV_PROJECT_ID)
    
# Build Docker image
.PHONY: docker-build
docker-build:
	docker build -t gsm-api:dev .

# For Apple Silicon, build an amd64 image (closer to Cloud Run)
# Build amd64 Docker image
.PHONY: docker-build-amd64
docker-build-amd64:
	docker build --platform=linux/amd64 -t gsm-api:dev .

# Run Docker image locally
.PHONY: docker-run
docker-run:
	docker run --rm -p 8080:8080 --name gsm-api gsm-api:dev

# Stop local Docker container
.PHONY: docker-stop
docker-stop:
	- docker stop gsm-api || true

# --- Mac-only helpers to start/stop Docker Desktop ---
# Start Docker Desktop (macOS)
.PHONY: docker-up
docker-up:
	@command -v docker >/dev/null 2>&1 || { echo "Docker CLI not found. Install Docker Desktop first."; exit 1; }
	@pgrep -x "Docker" >/dev/null 2>&1 || open -a Docker
	@echo "Waiting for Docker Desktop to be ready..."
	@i=0; \
	while ! docker info >/dev/null 2>&1; do \
	  i=$$((i+1)); [ $$i -gt 60 ] && { echo "Docker did not become ready in time"; exit 1; }; \
	  sleep 1; \
	done
	@echo "Docker is up."

# Stop Docker Desktop (macOS)
.PHONY: docker-down
docker-down:
	@osascript -e 'quit app "Docker"' || true
	@echo "Docker asked to quit (running containers will stop)."
