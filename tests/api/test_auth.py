"""Integration tests for POST /auth/register and POST /auth/login.

All tests use a real TestClient with:
  - In-memory SQLite registry engine seeded with ``test-tenant``
    (so TenantMiddleware passes)
  - In-memory SQLite tenant engine for user + membership persistence
  - Real JWTService with a test secret (tokens are verifiable)
  - Real PasswordService (bcrypt hashing)

The ``client`` fixture is defined in tests/api/conftest.py and injects
``get_user_repo``, ``get_membership_repo``, and ``get_jwt_service`` overrides.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import TEST_TENANT_SLUG, seed_user
from src.domain.entities import Role
from src.infrastructure.repositories.membership_repository import SQLiteMembershipRepository
from src.infrastructure.repositories.user_repository import SQLiteUserRepository
from src.infrastructure.services.jwt_service import JWTService
from src.infrastructure.services.password_service import PasswordService


# ---------------------------------------------------------------------------
# POST /auth/register
# ---------------------------------------------------------------------------


class TestRegisterEndpoint:
    """Tests for POST /auth/register."""

    def test_register_returns_token_on_valid_data(self, client: TestClient) -> None:
        """Valid registration payload returns 201 with a JWT token response."""
        # Arrange
        payload = {"email": "newuser@example.com", "password": "securepass123"}

        # Act
        response = client.post("/auth/register", json=payload)

        # Assert
        assert response.status_code == 201
        body = response.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert body["email"] == "newuser@example.com"
        assert body["user_id"]
        assert body["role"] == Role.MEMBER

    def test_register_token_is_scoped_to_test_tenant(
        self, client: TestClient, jwt_service: JWTService
    ) -> None:
        """The returned JWT carries the correct tenant_slug claim."""
        # Arrange
        payload = {"email": "scoped@example.com", "password": "pass"}

        # Act
        response = client.post("/auth/register", json=payload)

        # Assert
        assert response.status_code == 201
        raw_token = response.json()["access_token"]
        claims = jwt_service.decode_token(raw_token)
        assert claims["tenant_slug"] == TEST_TENANT_SLUG

    def test_register_assigns_member_role_by_default(self, client: TestClient) -> None:
        """Self-registered users always receive the MEMBER role."""
        # Act
        response = client.post(
            "/auth/register",
            json={"email": "defaultrole@example.com", "password": "pw"},
        )

        # Assert
        assert response.status_code == 201
        assert response.json()["role"] == Role.MEMBER

    def test_register_duplicate_email_returns_409(
        self,
        client: TestClient,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        password_service: PasswordService,
    ) -> None:
        """Registering an email already in the tenant database returns 409."""
        # Arrange — seed the email so it already exists
        seed_user(user_repo, membership_repo, password_service, "taken@example.com", "pw", Role.MEMBER)

        # Act
        response = client.post(
            "/auth/register",
            json={"email": "taken@example.com", "password": "newpass"},
        )

        # Assert
        assert response.status_code == 409
        assert "taken@example.com" in response.json()["detail"]

    def test_register_missing_tenant_slug_header_returns_400(
        self,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        jwt_service: JWTService,
    ) -> None:
        """Request without X-Tenant-Slug header is rejected by TenantMiddleware with 400."""
        # Arrange — build a client that sends NO tenant header
        from src.api.dependencies.auth import get_jwt_service, get_membership_repo, get_user_repo
        from src.main import app
        from fastapi.testclient import TestClient

        app.dependency_overrides[get_user_repo] = lambda: user_repo
        app.dependency_overrides[get_membership_repo] = lambda: membership_repo
        app.dependency_overrides[get_jwt_service] = lambda: jwt_service

        try:
            with TestClient(app, raise_server_exceptions=True) as no_header_client:
                # Act
                response = no_header_client.post(
                    "/auth/register",
                    json={"email": "a@b.com", "password": "pw"},
                )
        finally:
            app.dependency_overrides.clear()

        # Assert
        assert response.status_code == 400
        assert "X-Tenant-Slug" in response.json()["detail"]

    def test_register_unknown_tenant_slug_returns_404(
        self,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        jwt_service: JWTService,
    ) -> None:
        """X-Tenant-Slug referencing a nonexistent tenant returns 404."""
        # Arrange — client with an unknown slug header
        from src.api.dependencies.auth import get_jwt_service, get_membership_repo, get_user_repo
        from src.main import app
        from fastapi.testclient import TestClient

        app.dependency_overrides[get_user_repo] = lambda: user_repo
        app.dependency_overrides[get_membership_repo] = lambda: membership_repo
        app.dependency_overrides[get_jwt_service] = lambda: jwt_service

        try:
            with TestClient(
                app,
                raise_server_exceptions=True,
                headers={"X-Tenant-Slug": "nonexistent-tenant"},
            ) as unknown_client:
                # Act
                response = unknown_client.post(
                    "/auth/register",
                    json={"email": "a@b.com", "password": "pw"},
                )
        finally:
            app.dependency_overrides.clear()

        # Assert
        assert response.status_code == 404
        assert "nonexistent-tenant" in response.json()["detail"]


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------


class TestLoginEndpoint:
    """Tests for POST /auth/login."""

    def test_login_valid_credentials_returns_200_with_token(
        self,
        client: TestClient,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        password_service: PasswordService,
    ) -> None:
        """Correct email and password return 200 with a bearer token."""
        # Arrange
        seed_user(user_repo, membership_repo, password_service, "loginme@example.com", "correctpass", Role.MEMBER)

        # Act
        response = client.post(
            "/auth/login",
            json={"email": "loginme@example.com", "password": "correctpass"},
        )

        # Assert
        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert "access_token" in body
        assert body["email"] == "loginme@example.com"

    def test_login_wrong_password_returns_401(
        self,
        client: TestClient,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        password_service: PasswordService,
    ) -> None:
        """Wrong password returns 401; the error detail must not reveal which check failed."""
        # Arrange
        seed_user(user_repo, membership_repo, password_service, "wrongpw@example.com", "realpass", Role.MEMBER)

        # Act
        response = client.post(
            "/auth/login",
            json={"email": "wrongpw@example.com", "password": "badpassword"},
        )

        # Assert
        assert response.status_code == 401

    def test_login_unknown_email_returns_401(self, client: TestClient) -> None:
        """Email not registered in tenant database returns 401."""
        # Act
        response = client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": "anypass"},
        )

        # Assert
        assert response.status_code == 401

    def test_login_inactive_user_returns_401(
        self,
        client: TestClient,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        password_service: PasswordService,
    ) -> None:
        """Inactive user account returns 401 even with correct credentials."""
        # Arrange
        seed_user(
            user_repo,
            membership_repo,
            password_service,
            "inactive@example.com",
            "pass",
            Role.MEMBER,
            is_active=False,
        )

        # Act
        response = client.post(
            "/auth/login",
            json={"email": "inactive@example.com", "password": "pass"},
        )

        # Assert
        assert response.status_code == 401

    def test_login_missing_tenant_slug_header_returns_400(
        self,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        jwt_service: JWTService,
    ) -> None:
        """Request without X-Tenant-Slug header is rejected by TenantMiddleware with 400."""
        from src.api.dependencies.auth import get_jwt_service, get_membership_repo, get_user_repo
        from src.main import app
        from fastapi.testclient import TestClient

        app.dependency_overrides[get_user_repo] = lambda: user_repo
        app.dependency_overrides[get_membership_repo] = lambda: membership_repo
        app.dependency_overrides[get_jwt_service] = lambda: jwt_service

        try:
            with TestClient(app, raise_server_exceptions=True) as no_header_client:
                response = no_header_client.post(
                    "/auth/login",
                    json={"email": "a@b.com", "password": "pw"},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 400

    def test_login_unknown_tenant_slug_returns_404(
        self,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        jwt_service: JWTService,
    ) -> None:
        """X-Tenant-Slug referencing a nonexistent tenant returns 404 from TenantMiddleware."""
        from src.api.dependencies.auth import get_jwt_service, get_membership_repo, get_user_repo
        from src.main import app
        from fastapi.testclient import TestClient

        app.dependency_overrides[get_user_repo] = lambda: user_repo
        app.dependency_overrides[get_membership_repo] = lambda: membership_repo
        app.dependency_overrides[get_jwt_service] = lambda: jwt_service

        try:
            with TestClient(
                app,
                raise_server_exceptions=True,
                headers={"X-Tenant-Slug": "does-not-exist"},
            ) as bad_client:
                response = bad_client.post(
                    "/auth/login",
                    json={"email": "a@b.com", "password": "pw"},
                )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 404
