.DEFAULT_GOAL := help

PYTHON ?= python3
COMPOSE ?= docker compose
SMOKE_IMAGE ?= document-intelligence-smoke:local

.PHONY: help quickstart setup up logs test smoke-extract smoke-rag test-rag-real

help:
	@printf '%s\n' \
	  'make quickstart    Prompt for Gemini and build/start Compose in one step' \
	  'make setup         Create .env interactively without overwriting an existing file' \
	  'make up            Build and start this Compose project (may recreate its services)' \
	  'make logs          Follow this Compose project’s application logs' \
	  'make test          Run pytest locally; see README for prerequisites' \
	  'make smoke-extract Build an image and run isolated extraction checks' \
	  'make smoke-rag     Run isolated ingestion/RAG checks with a simulated generator' \
	  'make test-rag-real Run an isolated synthetic RAG check with real Gemini (external call)'

quickstart:
	@$(PYTHON) scripts/setup_env.py --gemini
	$(COMPOSE) up --build -d

setup:
	@$(PYTHON) scripts/setup_env.py

up:
	$(COMPOSE) up --build -d

logs:
	$(COMPOSE) logs -f app

test:
	uv run --extra dev pytest -q tests/unit tests/integration

smoke-extract:
	docker build -t $(SMOKE_IMAGE) .
	SMOKE_IMAGE=$(SMOKE_IMAGE) SMOKE_PACKAGED_APP=1 bash scripts/smoke/ejecutar.sh all

smoke-rag:
	docker build -t $(SMOKE_IMAGE) .
	@docker image inspect qdrant/qdrant:v1.13.6 >/dev/null 2>&1 || docker pull qdrant/qdrant:v1.13.6
	SMOKE_IMAGE=$(SMOKE_IMAGE) SMOKE_PACKAGED_APP=1 SMOKE_ASK_FAKE=1 bash scripts/smoke/ingestion.sh

test-rag-real:
	docker build -t $(SMOKE_IMAGE) .
	@docker image inspect qdrant/qdrant:v1.13.6 >/dev/null 2>&1 || docker pull qdrant/qdrant:v1.13.6
	SMOKE_IMAGE=$(SMOKE_IMAGE) bash scripts/smoke/rag_e2e.sh --gemini
