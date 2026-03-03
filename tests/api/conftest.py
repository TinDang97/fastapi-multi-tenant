"""Shared fixtures for tests/api/ integration tests.

Strategy
--------
TenantMiddleware is a Starlette BaseHTTPMiddleware — it cannot be bypassed via
``dependency_overrides``.  It calls ``get_container().tenant_repo().get_by_slug()``
on every request, so the container must hold a real (in-memory) registry engine
seeded with the test tenant.

Challenge: ``TestClient`` used as a context manager fires the FastAPI
``lifespan`` event, which calls ``init_container()`` in ``src.main``.  That
replaces the container we set up in the fixture.

Fix: The ``setup_registry`` fixture monkeypatches ``src.main.init_container``
so that when the lifespan calls it, it re-wires the pre-built container
(with our in-memory registry engine override) instead of constructing a new
one from disk-backed settings.

Layout of in-memory databases per test
---------------------------------------
    registry_engine  → TenantModel table only (tenant catalogue)
    tenant_engine    → UserModel + MembershipModel tables (per-tenant data)

The ``tenant_engine`` is injected into FastAPI's dependency graph via
``dependency_overrides`` so routes use the same in-memory state that the
test manipulates directly.

The ``JWTService`` fixture uses the same secret as ``get_jwt_service``
override so that tokens minted in test fixtures are accepted by
``get_current_user``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from src.api.dependencies.auth import (
    get_jwt_service,
    get_membership_repo,
    get_user_repo,
)
from src.domain.entities import Role, Tenant, TenantMembership, User
from src.infrastructure.models.membership_model import MembershipModel  # noqa: F401
from src.infrastructure.models.tenant_model import TenantModel
from src.infrastructure.models.user_model import UserModel  # noqa: F401
from src.infrastructure.repositories.membership_repository import SQLiteMembershipRepository
from src.infrastructure.repositories.tenant_repository import SQLiteTenantRepository
from src.infrastructure.repositories.user_repository import SQLiteUserRepository
from src.infrastructure.services.jwt_service import JWTService
from src.infrastructure.services.password_service import PasswordService
from src.main import app

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_TENANT_SLUG = "test-tenant"
TEST_JWT_SECRET = "test-secret-32-chars-exactly-here"
TEST_JWT_EXPIRE = 60


# ---------------------------------------------------------------------------
# Core registry + container fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def setup_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Seed an in-memory registry and wire the DI container for each test.

    Steps
    -----
    1. Reset the settings singleton so the test env values are used.
    2. Reset the container singleton.
    3. Build a fresh in-memory registry engine and seed TEST_TENANT_SLUG.
    4. Call ``init_container()`` then override ``registry_engine`` with our
       in-memory engine so TenantMiddleware resolves the test tenant.
    5. Monkeypatch ``src.main.init_container`` so the FastAPI lifespan event
       (which fires when TestClient starts) re-wires the *existing* container
       instead of replacing it with a fresh disk-backed one.
    6. On teardown, reset the container override and the container singleton.
    """
    import src.config as cfg_mod
    import src.container as container_mod

    # Set test environment values before the settings singleton is read.
    monkeypatch.setenv("JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("REGISTRY_DB_PATH", ":memory:")
    monkeypatch.setenv("TENANT_DB_DIR", "/tmp/test-api-tenants")
    monkeypatch.setenv("JWT_EXPIRE_MINUTES", str(TEST_JWT_EXPIRE))
    monkeypatch.setattr(cfg_mod, "_settings", None)

    # Start from a clean container state.
    monkeypatch.setattr(container_mod, "_container", None)

    # Build the in-memory registry engine and seed the test tenant.
    reg_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(reg_engine, tables=[TenantModel.__table__])

    SQLiteTenantRepository(reg_engine).create(
        Tenant(
            slug=TEST_TENANT_SLUG,
            name="Test Tenant",
            is_active=True,
            created_at=datetime.now(UTC),
        )
    )

    # Build and wire the DI container with our in-memory registry engine.
    container = container_mod.init_container()
    container.registry_engine.override(reg_engine)
    container.wire(packages=["src.api.dependencies", "src.api.middleware"])

    # Patch init_container in src.main so when the lifespan fires it
    # re-wires the existing container instead of replacing it.
    def _lifespan_safe_init() -> container_mod.ApplicationContainer:
        assert container_mod._container is not None, "Container must be initialised before lifespan"
        container_mod._container.wire(packages=["src.api.dependencies", "src.api.middleware"])
        return container_mod._container

    monkeypatch.setattr("src.main.init_container", _lifespan_safe_init)

    yield  # type: ignore[misc]

    container.registry_engine.reset_override()
    container.unwire()
    monkeypatch.setattr(container_mod, "_container", None)


# ---------------------------------------------------------------------------
# Per-test tenant engine (users + memberships)
# ---------------------------------------------------------------------------


@pytest.fixture()
def tenant_engine():
    """In-memory SQLite engine with users + memberships tables.

    Function-scoped so each test begins with an empty tenant database.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[UserModel.__table__, MembershipModel.__table__],
    )
    return engine


@pytest.fixture()
def user_repo(tenant_engine):
    """SQLiteUserRepository bound to the per-test in-memory tenant engine."""
    return SQLiteUserRepository(tenant_engine)


@pytest.fixture()
def membership_repo(tenant_engine):
    """SQLiteMembershipRepository bound to the per-test in-memory tenant engine."""
    return SQLiteMembershipRepository(tenant_engine)


# ---------------------------------------------------------------------------
# Auth services
# ---------------------------------------------------------------------------


@pytest.fixture()
def jwt_service() -> JWTService:
    """JWTService configured with the test secret — matches the override injected via client."""
    return JWTService(secret=TEST_JWT_SECRET, expire_minutes=TEST_JWT_EXPIRE)


@pytest.fixture()
def password_service() -> PasswordService:
    """Real PasswordService for hashing/verifying passwords in test seed helpers."""
    return PasswordService()


# ---------------------------------------------------------------------------
# TestClient with dependency overrides wired to in-memory tenant state
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(user_repo, membership_repo, jwt_service) -> TestClient:
    """TestClient with:
    - In-memory user + membership repos injected via dependency_overrides
    - X-Tenant-Slug: test-tenant header pre-set on every request

    Dependency overrides are cleared after each test to prevent bleed between
    tests sharing the same session.
    """
    app.dependency_overrides[get_user_repo] = lambda: user_repo
    app.dependency_overrides[get_membership_repo] = lambda: membership_repo
    app.dependency_overrides[get_jwt_service] = lambda: jwt_service

    with TestClient(
        app,
        raise_server_exceptions=True,
        headers={"X-Tenant-Slug": TEST_TENANT_SLUG},
    ) as tc:
        yield tc

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Seed helpers used by individual test modules
# ---------------------------------------------------------------------------


def seed_user(
    user_repo: SQLiteUserRepository,
    membership_repo: SQLiteMembershipRepository,
    password_service: PasswordService,
    email: str,
    plain_password: str,
    role: Role,
    tenant_slug: str = TEST_TENANT_SLUG,
    is_active: bool = True,
) -> tuple[User, TenantMembership]:
    """Create a user + membership directly in the in-memory tenant database.

    Returns the created ``(User, TenantMembership)`` so tests can reference IDs
    without re-querying the repository.
    """
    user = user_repo.create(
        User(
            id=User.generate_id(),
            email=email,
            hashed_password=password_service.hash(plain_password),
            is_active=is_active,
        )
    )
    membership = membership_repo.assign_role(
        TenantMembership(user_id=user.id, tenant_slug=tenant_slug, role=role)
    )
    return user, membership


def make_token(
    jwt_service: JWTService,
    user: User,
    role: Role,
    tenant_slug: str = TEST_TENANT_SLUG,
) -> str:
    """Issue a signed JWT for a user — convenience wrapper for test assertions."""
    return jwt_service.create_token(user.id, tenant_slug, role)
