"""Integration tests for GET /health.

The health endpoint is public — no Authorization header required — but
TenantMiddleware must still resolve the X-Tenant-Slug header.

Tests cover:
  1. Known active tenant  → 200 {"status": "ok", "tenant": "<slug>"}
  2. Unknown tenant slug  → 404 from TenantMiddleware
  3. Missing header       → 400 from TenantMiddleware

Tests 2 and 3 require a client that bypasses the default ``X-Tenant-Slug``
header set by the shared ``client`` fixture, so they construct their own
short-lived TestClient without that header.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import TEST_TENANT_SLUG
from src.api.dependencies.auth import get_jwt_service, get_membership_repo, get_user_repo
from src.infrastructure.repositories.membership_repository import SQLiteMembershipRepository
from src.infrastructure.repositories.user_repository import SQLiteUserRepository
from src.infrastructure.services.jwt_service import JWTService
from src.main import app


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_200_with_tenant(self, client: TestClient) -> None:
        """Known tenant returns 200 with status=ok and the correct tenant slug."""
        # Act
        response = client.get("/health")

        # Assert
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["tenant"] == TEST_TENANT_SLUG

    def test_health_unknown_tenant_returns_404(
        self,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        jwt_service: JWTService,
    ) -> None:
        """X-Tenant-Slug referencing a tenant not in the registry returns 404."""
        # Arrange — client with a slug that was never seeded in the registry
        app.dependency_overrides[get_user_repo] = lambda: user_repo
        app.dependency_overrides[get_membership_repo] = lambda: membership_repo
        app.dependency_overrides[get_jwt_service] = lambda: jwt_service

        try:
            with TestClient(
                app,
                raise_server_exceptions=True,
                headers={"X-Tenant-Slug": "unknown-slug-xyz"},
            ) as bad_client:
                # Act
                response = bad_client.get("/health")
        finally:
            app.dependency_overrides.clear()

        # Assert
        assert response.status_code == 404
        assert "unknown-slug-xyz" in response.json()["detail"]

    def test_health_missing_header_returns_400(
        self,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        jwt_service: JWTService,
    ) -> None:
        """Request with no X-Tenant-Slug header is rejected by TenantMiddleware with 400."""
        # Arrange — client that sends no tenant header at all
        app.dependency_overrides[get_user_repo] = lambda: user_repo
        app.dependency_overrides[get_membership_repo] = lambda: membership_repo
        app.dependency_overrides[get_jwt_service] = lambda: jwt_service

        try:
            with TestClient(app, raise_server_exceptions=True) as headerless_client:
                # Act
                response = headerless_client.get("/health")
        finally:
            app.dependency_overrides.clear()

        # Assert
        assert response.status_code == 400
        assert "X-Tenant-Slug" in response.json()["detail"]

    def test_health_inactive_tenant_returns_404(
        self,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        jwt_service: JWTService,
    ) -> None:
        """An inactive tenant (is_active=False) is treated as not found — returns 404."""
        # Arrange — seed an inactive tenant directly into the registry via the container
        import src.container as container_mod
        from datetime import UTC, datetime
        from src.domain.entities import Tenant

        container = container_mod.get_container()
        tenant_repo = container.tenant_repo()
        tenant_repo.create(
            Tenant(
                slug="inactive-tenant",
                name="Inactive Tenant",
                is_active=False,
                created_at=datetime.now(UTC),
            )
        )

        app.dependency_overrides[get_user_repo] = lambda: user_repo
        app.dependency_overrides[get_membership_repo] = lambda: membership_repo
        app.dependency_overrides[get_jwt_service] = lambda: jwt_service

        try:
            with TestClient(
                app,
                raise_server_exceptions=True,
                headers={"X-Tenant-Slug": "inactive-tenant"},
            ) as inactive_client:
                # Act
                response = inactive_client.get("/health")
        finally:
            app.dependency_overrides.clear()

        # Assert
        assert response.status_code == 404
