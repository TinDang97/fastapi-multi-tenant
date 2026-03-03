"""Integration tests for GET /users, POST /users, and DELETE /users/{user_id}.

All tests use the ``client`` fixture from tests/api/conftest.py which:
  - Wires a real in-memory registry so TenantMiddleware resolves test-tenant
  - Wires in-memory user + membership repos into FastAPI's dependency graph
  - Includes X-Tenant-Slug: test-tenant on every request

JWT tokens are minted via the real JWTService with the test secret so
``get_current_user`` can decode and validate them end-to-end.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.api.conftest import TEST_TENANT_SLUG, make_token, seed_user
from src.domain.entities import Role
from src.infrastructure.repositories.membership_repository import SQLiteMembershipRepository
from src.infrastructure.repositories.user_repository import SQLiteUserRepository
from src.infrastructure.services.jwt_service import JWTService
from src.infrastructure.services.password_service import PasswordService


# ---------------------------------------------------------------------------
# GET /users
# ---------------------------------------------------------------------------


class TestGetUsersEndpoint:
    """Tests for GET /users — requires VIEWER role minimum."""

    def test_get_users_without_token_returns_401(self, client: TestClient) -> None:
        """Request with no Authorization header returns 401."""
        # Act — no Authorization header sent
        response = client.get("/users")

        # Assert
        assert response.status_code == 401

    def test_get_users_with_viewer_token_returns_200_html(
        self,
        client: TestClient,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        password_service: PasswordService,
        jwt_service: JWTService,
    ) -> None:
        """VIEWER-scoped token returns 200 with an HTML body containing a table."""
        # Arrange
        user, _ = seed_user(
            user_repo, membership_repo, password_service,
            "viewer@example.com", "pass", Role.VIEWER,
        )
        token = make_token(jwt_service, user, Role.VIEWER)

        # Act
        response = client.get("/users", headers={"Authorization": f"Bearer {token}"})

        # Assert
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "<table" in response.text.lower()

    def test_get_users_with_member_token_returns_200(
        self,
        client: TestClient,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        password_service: PasswordService,
        jwt_service: JWTService,
    ) -> None:
        """MEMBER-scoped token satisfies the VIEWER minimum and returns 200."""
        # Arrange
        user, _ = seed_user(
            user_repo, membership_repo, password_service,
            "member@example.com", "pass", Role.MEMBER,
        )
        token = make_token(jwt_service, user, Role.MEMBER)

        # Act
        response = client.get("/users", headers={"Authorization": f"Bearer {token}"})

        # Assert
        assert response.status_code == 200

    def test_get_users_with_admin_token_returns_200(
        self,
        client: TestClient,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        password_service: PasswordService,
        jwt_service: JWTService,
    ) -> None:
        """ADMIN-scoped token satisfies the VIEWER minimum and returns 200."""
        # Arrange
        user, _ = seed_user(
            user_repo, membership_repo, password_service,
            "admin@example.com", "pass", Role.ADMIN,
        )
        token = make_token(jwt_service, user, Role.ADMIN)

        # Act
        response = client.get("/users", headers={"Authorization": f"Bearer {token}"})

        # Assert
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# POST /users
# ---------------------------------------------------------------------------


class TestPostUsersEndpoint:
    """Tests for POST /users — requires ADMIN role minimum."""

    def test_post_users_with_member_token_returns_403(
        self,
        client: TestClient,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        password_service: PasswordService,
        jwt_service: JWTService,
    ) -> None:
        """MEMBER role is below ADMIN minimum — returns 403."""
        # Arrange
        member, _ = seed_user(
            user_repo, membership_repo, password_service,
            "member@example.com", "pass", Role.MEMBER,
        )
        token = make_token(jwt_service, member, Role.MEMBER)

        # Act
        response = client.post(
            "/users",
            data={"email": "new@example.com", "password": "pw", "role": "VIEWER"},
            headers={"Authorization": f"Bearer {token}"},
        )

        # Assert
        assert response.status_code == 403

    def test_post_users_with_viewer_token_returns_403(
        self,
        client: TestClient,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        password_service: PasswordService,
        jwt_service: JWTService,
    ) -> None:
        """VIEWER role is below ADMIN minimum — returns 403."""
        # Arrange
        viewer, _ = seed_user(
            user_repo, membership_repo, password_service,
            "viewer@example.com", "pass", Role.VIEWER,
        )
        token = make_token(jwt_service, viewer, Role.VIEWER)

        # Act
        response = client.post(
            "/users",
            data={"email": "new@example.com", "password": "pw", "role": "VIEWER"},
            headers={"Authorization": f"Bearer {token}"},
        )

        # Assert
        assert response.status_code == 403

    def test_post_users_with_admin_token_returns_201_html(
        self,
        client: TestClient,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        password_service: PasswordService,
        jwt_service: JWTService,
    ) -> None:
        """ADMIN creates a new user; response is 201 HTML partial with a table row."""
        # Arrange
        admin, _ = seed_user(
            user_repo, membership_repo, password_service,
            "admin@example.com", "pass", Role.ADMIN,
        )
        token = make_token(jwt_service, admin, Role.ADMIN)

        # Act
        response = client.post(
            "/users",
            data={"email": "created@example.com", "password": "newpass", "role": "MEMBER"},
            headers={"Authorization": f"Bearer {token}"},
        )

        # Assert
        assert response.status_code == 201
        assert "text/html" in response.headers["content-type"]
        assert "<tr" in response.text.lower()

    def test_post_users_without_token_returns_401(self, client: TestClient) -> None:
        """No Authorization header returns 401 before RBAC check runs."""
        # Act
        response = client.post(
            "/users",
            data={"email": "x@example.com", "password": "pw", "role": "MEMBER"},
        )

        # Assert
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# DELETE /users/{user_id}
# ---------------------------------------------------------------------------


class TestDeleteUserEndpoint:
    """Tests for DELETE /users/{user_id} — requires ADMIN role minimum."""

    def test_delete_user_with_admin_token_returns_200(
        self,
        client: TestClient,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        password_service: PasswordService,
        jwt_service: JWTService,
    ) -> None:
        """ADMIN deletes an existing user — returns 200 empty body."""
        # Arrange
        admin, _ = seed_user(
            user_repo, membership_repo, password_service,
            "admin@example.com", "pass", Role.ADMIN,
        )
        target, _ = seed_user(
            user_repo, membership_repo, password_service,
            "target@example.com", "pass", Role.MEMBER,
        )
        token = make_token(jwt_service, admin, Role.ADMIN)

        # Act
        response = client.delete(
            f"/users/{target.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Assert
        assert response.status_code == 200

    def test_delete_user_removes_user_from_repo(
        self,
        client: TestClient,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        password_service: PasswordService,
        jwt_service: JWTService,
    ) -> None:
        """After a successful DELETE, the user no longer exists in the repo."""
        # Arrange
        admin, _ = seed_user(
            user_repo, membership_repo, password_service,
            "admin@example.com", "pass", Role.ADMIN,
        )
        target, _ = seed_user(
            user_repo, membership_repo, password_service,
            "gone@example.com", "pass", Role.MEMBER,
        )
        token = make_token(jwt_service, admin, Role.ADMIN)

        # Act
        client.delete(f"/users/{target.id}", headers={"Authorization": f"Bearer {token}"})

        # Assert
        assert user_repo.get_by_id(target.id) is None

    def test_delete_user_with_viewer_token_returns_403(
        self,
        client: TestClient,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        password_service: PasswordService,
        jwt_service: JWTService,
    ) -> None:
        """VIEWER role is below ADMIN minimum — returns 403."""
        # Arrange
        viewer, _ = seed_user(
            user_repo, membership_repo, password_service,
            "viewer@example.com", "pass", Role.VIEWER,
        )
        target, _ = seed_user(
            user_repo, membership_repo, password_service,
            "target@example.com", "pass", Role.MEMBER,
        )
        token = make_token(jwt_service, viewer, Role.VIEWER)

        # Act
        response = client.delete(
            f"/users/{target.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Assert
        assert response.status_code == 403

    def test_delete_user_unknown_id_returns_404(
        self,
        client: TestClient,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        password_service: PasswordService,
        jwt_service: JWTService,
    ) -> None:
        """Deleting a user ID that does not exist returns 404."""
        # Arrange
        admin, _ = seed_user(
            user_repo, membership_repo, password_service,
            "admin@example.com", "pass", Role.ADMIN,
        )
        token = make_token(jwt_service, admin, Role.ADMIN)

        # Act
        response = client.delete(
            "/users/nonexistent-uuid-0000",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Assert
        assert response.status_code == 404

    def test_delete_user_with_member_token_returns_403(
        self,
        client: TestClient,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        password_service: PasswordService,
        jwt_service: JWTService,
    ) -> None:
        """MEMBER role is below ADMIN minimum — returns 403."""
        # Arrange
        member, _ = seed_user(
            user_repo, membership_repo, password_service,
            "member@example.com", "pass", Role.MEMBER,
        )
        target, _ = seed_user(
            user_repo, membership_repo, password_service,
            "target@example.com", "pass", Role.VIEWER,
        )
        token = make_token(jwt_service, member, Role.MEMBER)

        # Act
        response = client.delete(
            f"/users/{target.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        # Assert
        assert response.status_code == 403

    def test_delete_user_without_token_returns_401(
        self,
        client: TestClient,
        user_repo: SQLiteUserRepository,
        membership_repo: SQLiteMembershipRepository,
        password_service: PasswordService,
    ) -> None:
        """No Authorization header returns 401 before RBAC check runs."""
        # Arrange
        target, _ = seed_user(
            user_repo, membership_repo, password_service,
            "target@example.com", "pass", Role.MEMBER,
        )

        # Act — no Authorization header
        response = client.delete(f"/users/{target.id}")

        # Assert
        assert response.status_code == 401
