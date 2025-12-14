# --- Config ---
PROJECT_ID := gsm-dev-f70d0
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
.PHONY: help
help:
	@echo "make venv             - create virtual env"
	@echo "make install          - install api deps"
	@echo "make api-dev          - run FastAPI locally (no emulator)"
	@echo "make emu-firestore    - start Firestore emulator"
	@echo "make emu-all          - start Firestore + Auth emulators"
	@echo "make api-dev-emu      - run API against Firestore emulator"
	@echo "make api-dev-emu-auth - run API against Firestore + Auth emulators"
	@echo "make seed             - seed example data into emulator"
	@echo "make test             - run tests"
	@echo "make fmt              - lint/format (ruff)"
	@echo "make type             - type check (mypy)"

# --- Python env ---
.PHONY: venv
venv:
	$(PYTHON) -m venv $(VENV)

.PHONY: install
install:
	$(ACT) && pip install --upgrade pip && pip install -e api[dev]

# --- API local runs ---
# Local dev against Firestore emulator; sets FIREBASE_PROJECT_ID, GOOGLE_CLOUD_PROJECT, FIRESTORE_EMULATOR_HOST
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
.PHONY: api-dev-real
api-dev-real:
	$(ACT) && \
	export FIREBASE_PROJECT_ID=$(PROJECT_ID) && \
	export GOOGLE_CLOUD_PROJECT=$(PROJECT_ID) && \
	uvicorn app.main:app --reload --port 8000 --app-dir api

.PHONY: api-dev-emu
api-dev-emu:
	$(ACT) && \
	export FIRESTORE_EMULATOR_HOST=$(EMU_FS) && \
	export GOOGLE_CLOUD_PROJECT=$(PROJECT_ID) && \
	uvicorn app.main:app --reload --port 8000 --app-dir api

.PHONY: api-dev-emu-auth
api-dev-emu-auth:
	$(ACT) && \
	export FIRESTORE_EMULATOR_HOST=$(EMU_FS) && \
	export FIREBASE_AUTH_EMULATOR_HOST=$(EMU_AUTH) && \
	export GOOGLE_CLOUD_PROJECT=$(PROJECT_ID) && \
	export FIREBASE_PROJECT_ID=$(PROJECT_ID) && \
	uvicorn app.main:app --reload --port 8000 --app-dir api

# --- Emulators ---
.PHONY: emu-firestore
emu-firestore:
	firebase emulators:start --only firestore

.PHONY: emu-all
emu-all:
	firebase emulators:start --only firestore,auth

# --- Dev utilities ---
.PHONY: seed
seed:
	$(ACT) && \
	export FIRESTORE_EMULATOR_HOST=$(EMU_FS) && \
	export GOOGLE_CLOUD_PROJECT=$(PROJECT_ID) && \
	python tests/integration/seed_emulator.py

.PHONY: test
test:
	$(ACT) && pytest -q

.PHONY: fmt
fmt:
	$(ACT) && ruff check --fix api tests

.PHONY: format
format:
	$(ACT) && ruff format api tests

.PHONY: type
type:
	$(ACT) && mypy api

.PHONY: test-unit
test-unit:
	pytest -q tests/unit

.PHONY: test-int
test-int:
	export CORS_ORIGIN="http://localhost:3000" && \
	export FIRESTORE_EMULATOR_HOST=$(EMU_FS) && \
	export FIREBASE_AUTH_EMULATOR_HOST=$(EMU_AUTH) && \
	export GOOGLE_CLOUD_PROJECT=$(PROJECT_ID) && \
	export FIREBASE_PROJECT_ID=$(PROJECT_ID) && \
	pytest -q tests/integration
    
.PHONY: docker-build
docker-build:
	docker build -t gsm-api:dev .

# For Apple Silicon, build an amd64 image (closer to Cloud Run)
.PHONY: docker-build-amd64
docker-build-amd64:
	docker build --platform=linux/amd64 -t gsm-api:dev .

.PHONY: docker-run
docker-run:
	docker run --rm -p 8080:8080 --name gsm-api gsm-api:dev

.PHONY: docker-stop
docker-stop:
	- docker stop gsm-api || true

# --- Mac-only helpers to start/stop Docker Desktop ---
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

.PHONY: docker-down
docker-down:
	@osascript -e 'quit app "Docker"' || true
	@echo "Docker asked to quit (running containers will stop)."
