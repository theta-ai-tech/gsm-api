# ===== GSM API Dev Makefile =====

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
.PHONY: api-dev
api-dev:
	$(ACT) && uvicorn app.main:app --reload --port 8000 --app-dir api

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

.PHONY: type
type:
	$(ACT) && mypy api


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

