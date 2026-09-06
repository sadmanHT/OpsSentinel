SHELL := /bin/bash

.PHONY: help setup setup-backend setup-frontend setup-chaoslab lint typecheck test test-unit test-integration chaoslab-test frontend-build compose-validate db-upgrade db-downgrade clean-start phase2-smoke ci

help:
	@printf '%s\n' \
	  'setup             Install backend, ChaosLab, and frontend dependencies' \
	  'lint              Run backend and ChaosLab lint checks' \
	  'typecheck         Run backend static typing checks' \
	  'test              Run backend and ChaosLab unit tests' \
	  'test-integration  Run database integration tests (requires services)' \
	  'phase2-smoke      Validate all five ChaosLab fault primitives (requires services)' \
	  'frontend-build    Build the React frontend' \
	  'compose-validate  Validate Docker Compose configuration' \
	  'db-upgrade        Apply all database migrations' \
	  'clean-start       Rebuild and start from clean Docker state' \
	  'ci                 Run local CI-equivalent non-container checks'

setup: setup-backend setup-chaoslab setup-frontend

setup-backend:
	python -m pip install -e 'backend[dev]'

setup-chaoslab:
	python -m pip install -e 'chaoslab[dev]'

setup-frontend:
	cd frontend && npm install --no-audit --no-fund

lint:
	ruff check backend chaoslab

typecheck:
	mypy backend/app

test: test-unit chaoslab-test

test-unit:
	pytest backend/tests -m 'not integration'

chaoslab-test:
	pytest chaoslab/tests

test-integration:
	pytest backend/tests -m integration

phase2-smoke:
	python scripts/phase2-smoke.py

frontend-build:
	cd frontend && npm run build

compose-validate:
	docker compose -f docker-compose.yml config >/dev/null
	docker compose -f docker-compose.yml -f docker-compose.test.yml config >/dev/null

db-upgrade:
	cd backend && alembic upgrade head

db-downgrade:
	cd backend && alembic downgrade -1

clean-start:
	docker compose down -v --remove-orphans
	docker compose build --no-cache
	docker compose up -d
	docker compose ps

ci: lint typecheck test-unit chaoslab-test frontend-build compose-validate
