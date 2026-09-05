SHELL := /bin/bash

.PHONY: help setup setup-backend setup-frontend lint typecheck test test-unit test-integration frontend-build compose-validate db-upgrade db-downgrade clean-start ci

help:
	@printf '%s\n' \
	  'setup             Install backend and frontend dependencies' \
	  'lint              Run backend lint checks' \
	  'typecheck         Run backend static typing checks' \
	  'test              Run backend unit tests' \
	  'test-integration  Run database integration tests (requires services)' \
	  'frontend-build    Build the React frontend' \
	  'compose-validate  Validate Docker Compose configuration' \
	  'db-upgrade        Apply all database migrations' \
	  'clean-start       Rebuild and start from clean Docker state' \
	  'ci                 Run local CI-equivalent checks'

setup: setup-backend setup-frontend

setup-backend:
	python -m pip install -e 'backend[dev]'

setup-frontend:
	cd frontend && npm install --no-audit --no-fund

lint:
	ruff check backend

typecheck:
	mypy backend/app

test: test-unit

test-unit:
	pytest backend/tests -m 'not integration'

test-integration:
	pytest backend/tests -m integration

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

ci: lint typecheck test-unit frontend-build compose-validate
