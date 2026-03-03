"""Shared pytest fixtures for the full test suite.

Fixture design principles:
- Engines use StaticPool so the same in-memory connection is reused across
  all ``with engine.connect()`` / ``Session`` calls within a single test.
  Without StaticPool, each new connection opens a fresh in-memory database
  and loses all previously created tables.
- Tables are created selectively per engine to match the real deployment
  topology (registry DB holds tenants; tenant DB holds users + memberships).
- JWT token fixtures are convenience helpers for API/middleware tests that
  need pre-signed bearer tokens; they depend on the ``jwt_service`` fixture
  so secrets and expiry are consistent across one test run.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from src.domain.entities import Role
from src.infrastructure.models.membership_model import MembershipModel
from src.infrastructure.models.tenant_model import TenantModel
from src.infrastructure.models.user_model import UserModel
from src.infrastructure.services.jwt_service import JWTService

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_JWT_SECRET = "test-secret-32-chars-exactly-here"
TEST_JWT_EXPIRE = 60


# ---------------------------------------------------------------------------
# Engine fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def registry_engine() -> Engine:
    """In-memory SQLite engine containing only the tenants table.

    Mirrors the production registry database that stores the tenant
    catalogue.  StaticPool ensures all sessions within the same test see
    the same in-memory state.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine, tables=[TenantModel.__table__])  # type: ignore[attr-defined]
    return engine


@pytest.fixture()
def tenant_engine() -> Engine:
    """In-memory SQLite engine containing the users and memberships tables.

    Mirrors a per-tenant database file.  StaticPool ensures all sessions
    within the same test share the same in-memory state.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(
        engine,
        tables=[UserModel.__table__, MembershipModel.__table__],  # type: ignore[attr-defined]
    )
    return engine


# ---------------------------------------------------------------------------
# Service fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def jwt_service() -> JWTService:
    """JWTService instance wired with test-only secret and expiry."""
    return JWTService(secret=TEST_JWT_SECRET, expire_minutes=TEST_JWT_EXPIRE)


# ---------------------------------------------------------------------------
# Token fixtures
# ---------------------------------------------------------------------------


def _make_token(jwt_service: JWTService, user_id: str, tenant_slug: str, role: Role) -> str:
    """Create a signed JWT for the given identity — shared by all token fixtures."""
    return jwt_service.create_token(user_id, tenant_slug, role)


@pytest.fixture()
def owner_token(jwt_service: JWTService) -> str:
    """Signed JWT for an OWNER of ``test-tenant``."""
    return _make_token(jwt_service, "owner-user-id", "test-tenant", Role.OWNER)


@pytest.fixture()
def admin_token(jwt_service: JWTService) -> str:
    """Signed JWT for an ADMIN of ``test-tenant``."""
    return _make_token(jwt_service, "admin-user-id", "test-tenant", Role.ADMIN)


@pytest.fixture()
def member_token(jwt_service: JWTService) -> str:
    """Signed JWT for a MEMBER of ``test-tenant``."""
    return _make_token(jwt_service, "member-user-id", "test-tenant", Role.MEMBER)


@pytest.fixture()
def viewer_token(jwt_service: JWTService) -> str:
    """Signed JWT for a VIEWER of ``test-tenant``."""
    return _make_token(jwt_service, "viewer-user-id", "test-tenant", Role.VIEWER)
