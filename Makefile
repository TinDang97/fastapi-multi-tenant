.DEFAULT_GOAL := help

.PHONY: help install dev test test-cov lint type-check \
        migrate-registry migrate-tenant migrate-all \
        create-tenant quality

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install all dependencies via uv
	uv sync

dev: ## Run development server with hot reload
	uv run fastapi dev src/main.py

test: ## Run the full test suite
	uv run pytest

test-cov: ## Run tests with coverage report
	uv run coverage run -m pytest
	uv run coverage report -m

lint: ## Lint and auto-fix with ruff
	uv run ruff check . --fix

type-check: ## Static type analysis with mypy
	uv run mypy src/

migrate-registry: ## Apply registry (public schema) migrations
	uv run alembic -c alembic_registry.ini upgrade head

migrate-tenant: ## Apply tenant migrations (requires TENANT_SLUG env var)
	@if [ -z "$(TENANT_SLUG)" ]; then \
		echo "Error: TENANT_SLUG is required. Usage: make migrate-tenant TENANT_SLUG=<slug>"; \
		exit 1; \
	fi
	TENANT_SLUG=$(TENANT_SLUG) uv run alembic -c alembic_tenant.ini upgrade head

migrate-all: ## Apply tenant migrations to all registered tenants
	uv run python -m scripts.migrate_all_tenants

create-tenant: ## Create a new tenant (requires slug= and email= args)
	@if [ -z "$(slug)" ]; then \
		echo "Error: slug is required. Usage: make create-tenant slug=<slug> email=<email>"; \
		exit 1; \
	fi
	@if [ -z "$(email)" ]; then \
		echo "Error: email is required. Usage: make create-tenant slug=<slug> email=<email>"; \
		exit 1; \
	fi
	uv run python -m scripts.create_tenant --slug $(slug) --email $(email)

quality: lint type-check test ## Run full quality gate (lint + type-check + test)
