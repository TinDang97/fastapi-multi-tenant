# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Stack

- **Backend**: FastAPI, SQLModel (SQLAlchemy 2.x core), Alembic, Python 3.12+
- **Frontend**: HTMX + Jinja2 templates (server-side rendering, no separate SPA)
- **Multi-tenancy**: Schema-per-tenant (each tenant gets an isolated PostgreSQL schema)
- **Architecture**: Clean Architecture — strict layer boundaries enforced
- **DI**: Dependency injection via `dependency-injector` container (or equivalent)
- **Package manager**: `uv` (never pip/pip3)

## Commands

```bash
# Install dependencies
uv sync

# Run dev server
uv run fastapi dev src/main.py

# Run tests (all)
uv run pytest

# Run a single test file
uv run pytest tests/path/to/test_file.py -v

# Run a single test by name
uv run pytest -k "test_name" -v

# Lint + type check
uv run ruff check . --fix
uv run mypy src/

# Generate Alembic migration
uv run alembic revision --autogenerate -m "<description>"

# Run migrations (all tenants)
uv run python -m scripts.migrate_all_tenants

# Run migrations (single tenant schema)
uv run alembic upgrade head --schema <tenant_slug>
```

## Clean Architecture Layers

Layer boundaries are strict — import violations are bugs:

| Layer | Path | Allowed imports |
|-------|------|-----------------|
| `domain/` | Entities, value objects, domain events | Pure Python only. No fastapi, sqlmodel, alembic. |
| `application/` | Use cases, command/query handlers | `domain/` + port interfaces only |
| `infrastructure/` | DB repos, external adapters, SQLModel models | May use fastapi, sqlmodel, alembic |
| `api/` | FastAPI routers, request/response schemas | `application/` only — never domain directly |

The DI container wires `infrastructure/` implementations to `application/` port interfaces. Application layer never instantiates infrastructure directly.

## Multi-Tenant Schema Routing

- Every tenant has an isolated PostgreSQL schema identified by `tenant_slug`
- `alembic/env.py` controls schema routing — **this file is critical; do not edit casually**
- All SQLModel table definitions must include `schema=` in `__table_args__`
- The current tenant context is set per-request (middleware or DI scope) — never stored globally
- Migrations run per-schema; `public` schema is reserved for the tenant registry only
- Cross-schema foreign keys are **prohibited**

## DI Container

- Container is defined in `src/container.py` (or `src/infrastructure/container.py`)
- FastAPI route dependencies resolve from the container, not by direct instantiation
- Repository interfaces live in `application/ports/`; implementations in `infrastructure/repositories/`
- Tenant context is injected as a scoped dependency, not a global/thread-local

## HTMX Conventions

- Routes returning full HTML pages: `GET /path` → Jinja2 `TemplateResponse`
- Routes returning partial HTML for HTMX swaps: `GET|POST /path/fragment` → partial template
- JSON API routes (if any) are prefixed `/api/v1/`
- No JavaScript build step; static assets served directly from `static/`
