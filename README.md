# FastAPI Multi-Tenant Boilerplate

Production-grade FastAPI scaffold for multi-tenant SaaS applications.
**SQLite-per-tenant** isolation, Clean Architecture, RBAC, HTMX + Jinja2 UI, and full DI wiring via `dependency-injector`.

---

## Stack

| Layer | Technology |
|---|---|
| Framework | FastAPI 0.115+ |
| ORM | SQLModel (SQLAlchemy 2.x core) |
| Migrations | Alembic (two independent envs) |
| Multi-tenancy | SQLite database-per-tenant |
| Auth | JWT (`python-jose`), Bcrypt (`passlib`) |
| DI | `dependency-injector` |
| UI | HTMX + Jinja2 (server-side rendering) |
| Package manager | `uv` |
| Python | 3.12+ |

---

## Architecture

Clean Architecture with strict layer import rules:

```
domain/          ← pure Python only (no framework imports)
   │
application/     ← domain + port interfaces only
   │
infrastructure/  ← SQLModel, Alembic, SQLite adapters
   │
api/             ← FastAPI routers, middleware, dependency factories
```

Import violations across layers are treated as bugs.
The DI container wires `infrastructure/` implementations to `application/` port interfaces at startup — use cases never instantiate infrastructure directly.

---

## Multi-Tenancy Model

```
data/
├── registry.db           ← shared tenant catalogue
└── tenants/
    ├── acme.db           ← complete isolation per tenant
    └── beta.db
```

- Every request carries an `X-Tenant-Slug` header (or `tenant_slug` cookie / `?tenant=` query param).
- `TenantMiddleware` resolves the slug → verifies the tenant is active → writes `request.state.tenant_slug`.
- Route dependencies create a per-request SQLAlchemy `Engine` pointing at `data/tenants/{slug}.db`.
- Alembic maintains two independent migration environments: `alembic/registry/` and `alembic/tenant/`.

---

## RBAC

Four roles with a strict integer hierarchy:

| Role | Level | Permissions |
|------|-------|-------------|
| `OWNER` | 3 | All operations |
| `ADMIN` | 2 | Create / delete users, view |
| `MEMBER` | 1 | View only |
| `VIEWER` | 0 | View only |

A user can hold different roles in different tenants. RBAC is enforced at the API layer via `require_role()` FastAPI dependencies — never inside use cases.

Permission matrix:

| Route | Min Role |
|-------|----------|
| `GET /health` | public |
| `POST /auth/register` | public |
| `POST /auth/login` | public |
| `GET /` | public |
| `GET /users` | VIEWER |
| `POST /users` | ADMIN |
| `DELETE /users/{id}` | ADMIN |

---

## Directory Structure

```
fastapi-multi-tenant/
├── pyproject.toml
├── Makefile
├── .env.example
├── alembic_registry.ini          # Alembic config → registry.db
├── alembic_tenant.ini            # Alembic config → data/tenants/{slug}.db
├── alembic/
│   ├── registry/versions/        # Registry migrations
│   └── tenant/versions/          # Per-tenant migrations
├── src/
│   ├── main.py                   # FastAPI app, lifespan, exception handlers
│   ├── config.py                 # Settings from environment variables
│   ├── container.py              # DI container (ApplicationContainer)
│   ├── domain/
│   │   ├── entities.py           # Tenant, User, TenantMembership, Role
│   │   ├── exceptions.py         # Domain exceptions
│   │   └── ports/                # Repository + service Protocol interfaces
│   ├── application/
│   │   └── use_cases/            # LoginUseCase, RegisterUserUseCase, ...
│   ├── infrastructure/
│   │   ├── database.py           # create_registry_engine / create_tenant_engine
│   │   ├── models/               # SQLModel ORM models
│   │   ├── repositories/         # SQLite repository implementations
│   │   └── services/             # JWTService, PasswordService
│   └── api/
│       ├── middleware/           # TenantMiddleware
│       ├── dependencies/         # get_current_user, require_role, repo factories
│       ├── schemas/              # Pydantic request/response models
│       ├── routers/              # auth, users, health, pages
│       └── templates.py          # Jinja2 environment
├── templates/                    # Jinja2 HTML templates
│   ├── base.html
│   ├── index.html
│   ├── auth/{login,register}.html
│   ├── errors/403.html
│   └── users/{list,_row}.html
├── static/                       # CSS, JS, static assets
├── scripts/
│   ├── create_tenant.py          # Bootstrap a new tenant
│   └── migrate_all_tenants.py    # Apply migrations to all active tenants
├── data/                         # Runtime databases (git-ignored)
│   ├── registry.db
│   └── tenants/
├── docs/
│   └── manual-test.md            # Step-by-step browser testing guide
└── tests/
    ├── conftest.py               # Engine + JWT fixtures
    ├── api/                      # Integration tests (TestClient)
    ├── application/              # Use case unit tests
    └── domain/                   # Entity + RBAC unit tests
```

---

## Quick Start

### 1. Install dependencies

```bash
uv sync
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — set JWT_SECRET to a strong random value
```

### 3. Run registry migration

```bash
make migrate-registry
# Creates data/registry.db with the tenants table
```

### 4. Create your first tenant

```bash
make create-tenant slug=acme email=owner@acme.com
# Creates data/tenants/acme.db, runs migrations, seeds owner user
# Default password: changeme123  (pass password=<pw> to override)
```

### 5. Start the dev server

```bash
make dev
# Listening on http://localhost:8000
```

### 6. Open the UI

Navigate to `http://localhost:8000/?tenant=acme` (sets the `tenant_slug` cookie) then go to `/auth/login`.

Or set the header manually with a browser extension (e.g. ModHeader):

```
X-Tenant-Slug: acme
```

---

## API Reference

### Authentication

All API requests require `X-Tenant-Slug` header (or `tenant_slug` cookie).
Protected routes additionally require `Authorization: Bearer <token>` header (or `access_token` cookie).

#### `POST /auth/register`

Register a new user. Assigns `MEMBER` role automatically.

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "X-Tenant-Slug: acme" \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@acme.com", "password": "secret123"}'
```

Response `201`:
```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "user_id": "<uuid>",
  "email": "alice@acme.com",
  "role": "MEMBER"
}
```

Errors: `409` duplicate email · `400` missing tenant header · `404` unknown tenant

#### `POST /auth/login`

```bash
curl -X POST http://localhost:8000/auth/login \
  -H "X-Tenant-Slug: acme" \
  -H "Content-Type: application/json" \
  -d '{"email": "owner@acme.com", "password": "changeme123"}'
```

Response `200`: same shape as register.
Errors: `401` invalid credentials · `400` missing header · `404` unknown tenant

### User Management

#### `GET /users`

List all users in the tenant. Requires VIEWER or above.

```bash
curl http://localhost:8000/users \
  -H "X-Tenant-Slug: acme" \
  -H "Authorization: Bearer <token>"
# Returns full HTML page
```

#### `POST /users`

Create a user with an explicit role. Requires ADMIN or above. Form-encoded.

```bash
curl -X POST http://localhost:8000/users \
  -H "X-Tenant-Slug: acme" \
  -H "Authorization: Bearer <token>" \
  -d "email=bob@acme.com&password=secret&role=MEMBER"
# Returns <tr> partial (HTMX swap)  status 201
```

Valid roles: `OWNER` · `ADMIN` · `MEMBER` · `VIEWER`
Errors: `409` duplicate email · `422` invalid role · `403` insufficient role

#### `DELETE /users/{user_id}`

Remove a user. Requires ADMIN or above.

```bash
curl -X DELETE http://localhost:8000/users/<uuid> \
  -H "X-Tenant-Slug: acme" \
  -H "Authorization: Bearer <token>"
# Returns empty 200 on success, 404 if not found
```

### Health Check

```bash
curl http://localhost:8000/health -H "X-Tenant-Slug: acme"
# {"status": "ok", "tenant": "acme"}
```

---

## Development Commands

```bash
make install          # uv sync
make dev              # uv run fastapi dev src/main.py
make test             # uv run pytest
make test-cov         # pytest with coverage report
make lint             # uv run ruff check . --fix
make type-check       # uv run mypy src/
make quality          # lint + type-check + test (full gate)

# Migrations
make migrate-registry              # Apply registry migrations
make migrate-tenant slug=acme      # Apply migrations for one tenant
make migrate-all                   # Apply to all active tenants

# Tenant management
make create-tenant slug=<slug> email=<email>
make create-tenant slug=acme email=owner@acme.com password=mypassword
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REGISTRY_DB_PATH` | `data/registry.db` | Path to the tenant registry SQLite file |
| `TENANT_DB_DIR` | `data/tenants` | Directory for per-tenant `.db` files |
| `JWT_SECRET` | `dev-secret-change-in-production` | HMAC key for JWT signing — **must be changed in production** |
| `JWT_EXPIRE_MINUTES` | `60` | JWT token lifetime in minutes |
| `ENV` | `development` | Deployment environment label |

---

## DI Container

`ApplicationContainer` in `src/container.py` wires all providers:

| Provider | Type | Description |
|----------|------|-------------|
| `registry_engine` | Singleton | SQLAlchemy engine for `registry.db` |
| `tenant_repo` | Factory | `SQLiteTenantRepository` bound to registry engine |
| `user_repo` | Factory | `SQLiteUserRepository` (per-request engine injected at call time) |
| `membership_repo` | Factory | `SQLiteMembershipRepository` (per-request engine injected at call time) |
| `password_service` | Singleton | `PasswordService` (bcrypt context) |
| `jwt_service` | Singleton | `JWTService` (JWT sign/verify) |

Tenant-scoped repos (`user_repo`, `membership_repo`) are declared as container `Factory` providers but receive the per-request `Engine` at resolution time via the `Provide[...provider]` pattern — no global state.

---

## Testing

```bash
uv run pytest            # 429 tests
uv run pytest tests/api/ # integration tests only
uv run pytest tests/domain/ tests/application/ # unit tests only
```

Test strategy:
- **Domain tests** — entity construction, RBAC hierarchy (all 16 role pairs)
- **Application tests** — use case logic with in-memory fakes (no HTTP)
- **API tests** — `TestClient` with `dependency_overrides` for repos, in-memory SQLite for registry

Every test gets a fresh in-memory SQLite database (via `StaticPool`). No disk I/O, no shared state between tests.

---

## Adding a New Tenant

```bash
# 1. Create the tenant
make create-tenant slug=beta email=owner@beta.com

# 2. Run migrations (already done by create-tenant, but explicit for CI)
make migrate-tenant slug=beta

# 3. Verify
curl http://localhost:8000/health -H "X-Tenant-Slug: beta"
# {"status": "ok", "tenant": "beta"}
```

---

## Adding a New Migration

```bash
# Registry schema change
uv run alembic -c alembic_registry.ini revision --autogenerate -m "add column"

# Tenant schema change
TENANT_SLUG=acme uv run alembic -c alembic_tenant.ini revision --autogenerate -m "add column"

# Apply to all active tenants
make migrate-all
```

---

## HTMX Integration

The UI is server-rendered Jinja2 with HTMX for partial updates. No JavaScript build step.

- `GET /` · `GET /auth/login` · `GET /auth/register` → full HTML pages
- `POST /auth/login` with `HX-Request: true` → `200` + `HX-Redirect: /users` + `access_token` cookie
- `POST /users` with `HX-Request: true` → `<tr>` partial swapped into the table
- `DELETE /users/{id}` → empty `200`; HTMX removes the row

All protected routes read the JWT from the `access_token` cookie (set by the login flow) or the `Authorization` header. `base.html` sets `hx-headers` with `{"Authorization": "Bearer <token>"}` automatically.

---

## Production Checklist

- [ ] Set `JWT_SECRET` to a 32+ character random string
- [ ] Set `ENV=production`
- [ ] Use a reverse proxy (nginx/Caddy) in front of uvicorn
- [ ] Enable HTTPS and set `Secure` flag on cookies
- [ ] Consider PostgreSQL for concurrent write workloads (SQLite write-locks entire file)
- [ ] Set up log aggregation (the app logs to stdout)
- [ ] Run `make quality` in CI before deploy

---

## License

[LICENCE](LICENCE.md)
