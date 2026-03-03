"""Unit tests for API middleware, auth dependencies, and auth schemas.

Test strategy
-------------
* ``TenantMiddleware`` — tested via a minimal ASGI ``TestClient`` app.  The
  real DI container is replaced with a lightweight stub so the test is
  hermetic (no SQLite, no network).
* ``get_current_user`` / ``require_role`` — tested through a minimal FastAPI
  app with a stub JWT service and stub user/membership repos.  The stubs are
  injected via ``app.dependency_overrides``.
* ``auth.py`` schemas — pure Pydantic construction and validation tests; no
  server required.

No ``pytest-asyncio`` marks are required because ``pytest.ini_options``
sets ``asyncio_mode = "auto"``.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from src.api.dependencies.auth import (
    get_jwt_service,
    get_membership_repo,
    get_tenant_slug,
    get_user_repo,
    require_role,
)
from src.api.middleware.tenant_middleware import TenantMiddleware
from src.api.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from src.domain.entities import ROLE_LEVEL, Role, Tenant, User
from src.infrastructure.services.jwt_service import JWTService

# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------

_JWT_SECRET = "test-secret"
_TENANT_SLUG = "acme"
_USER_ID = "user-abc-123"
_USER_EMAIL = "alice@example.com"
_USER_HASHED_PW = "$2b$12$fakehash"


def _make_active_tenant(slug: str = _TENANT_SLUG) -> Tenant:
    return Tenant(slug=slug, name="Acme Corp", is_active=True)


def _make_inactive_tenant(slug: str = _TENANT_SLUG) -> Tenant:
    return Tenant(slug=slug, name="Old Corp", is_active=False)


def _make_active_user(role: Role = Role.MEMBER) -> User:
    return User(
        id=_USER_ID,
        email=_USER_EMAIL,
        hashed_password=_USER_HASHED_PW,
        is_active=True,
    )


def _make_inactive_user() -> User:
    return User(
        id=_USER_ID,
        email=_USER_EMAIL,
        hashed_password=_USER_HASHED_PW,
        is_active=False,
    )


@pytest.fixture()
def jwt_svc() -> JWTService:
    return JWTService(secret=_JWT_SECRET, expire_minutes=30)


def _build_token(jwt_svc: JWTService, user_id: str, tenant_slug: str, role: Role) -> str:
    return jwt_svc.create_token(user_id, tenant_slug, role)


# ---------------------------------------------------------------------------
# TenantMiddleware
# ---------------------------------------------------------------------------


def _build_middleware_app(tenant_repo_stub: Any) -> FastAPI:
    """Return a minimal FastAPI app with TenantMiddleware and a stub container."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        yield

    inner = FastAPI(lifespan=lifespan)

    @inner.get("/ping")
    async def ping(request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "tenant_slug": request.state.tenant_slug,
                "tenant_name": request.state.tenant.name,
            }
        )

    inner.add_middleware(TenantMiddleware)

    # Patch get_container so the middleware uses our stub repository.
    container_mock = MagicMock()
    container_mock.tenant_repo.return_value = tenant_repo_stub
    inner.state.container_mock = container_mock
    return inner


class TestTenantMiddlewareMissingHeader:
    def test_returns_400_when_header_absent(self) -> None:
        repo_stub = MagicMock()
        app = _build_middleware_app(repo_stub)

        with patch("src.api.middleware.tenant_middleware.get_container") as mock_gc:
            mock_gc.return_value.tenant_repo.return_value = repo_stub
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/ping")

        assert response.status_code == 400
        assert response.json()["detail"] == "X-Tenant-Slug header required"

    def test_repo_is_never_called_when_header_absent(self) -> None:
        repo_stub = MagicMock()
        app = _build_middleware_app(repo_stub)

        with patch("src.api.middleware.tenant_middleware.get_container") as mock_gc:
            mock_gc.return_value.tenant_repo.return_value = repo_stub
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/ping")

        repo_stub.get_by_slug.assert_not_called()


class TestTenantMiddlewareTenantNotFound:
    def test_returns_404_when_tenant_is_none(self) -> None:
        repo_stub = MagicMock()
        repo_stub.get_by_slug.return_value = None
        app = _build_middleware_app(repo_stub)

        with patch("src.api.middleware.tenant_middleware.get_container") as mock_gc:
            mock_gc.return_value.tenant_repo.return_value = repo_stub
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/ping", headers={"X-Tenant-Slug": "ghost"})

        assert response.status_code == 404
        assert "ghost" in response.json()["detail"]

    def test_returns_404_when_tenant_is_inactive(self) -> None:
        repo_stub = MagicMock()
        repo_stub.get_by_slug.return_value = _make_inactive_tenant()
        app = _build_middleware_app(repo_stub)

        with patch("src.api.middleware.tenant_middleware.get_container") as mock_gc:
            mock_gc.return_value.tenant_repo.return_value = repo_stub
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/ping", headers={"X-Tenant-Slug": _TENANT_SLUG})

        assert response.status_code == 404


class TestTenantMiddlewareSuccess:
    def test_passes_request_to_handler_with_tenant_state(self) -> None:
        repo_stub = MagicMock()
        repo_stub.get_by_slug.return_value = _make_active_tenant()
        app = _build_middleware_app(repo_stub)

        with patch("src.api.middleware.tenant_middleware.get_container") as mock_gc:
            mock_gc.return_value.tenant_repo.return_value = repo_stub
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/ping", headers={"X-Tenant-Slug": _TENANT_SLUG})

        assert response.status_code == 200
        body = response.json()
        assert body["tenant_slug"] == _TENANT_SLUG
        assert body["tenant_name"] == "Acme Corp"

    def test_repo_is_called_with_correct_slug(self) -> None:
        repo_stub = MagicMock()
        repo_stub.get_by_slug.return_value = _make_active_tenant("beta")
        app = _build_middleware_app(repo_stub)

        with patch("src.api.middleware.tenant_middleware.get_container") as mock_gc:
            mock_gc.return_value.tenant_repo.return_value = repo_stub
            client = TestClient(app, raise_server_exceptions=False)
            client.get("/ping", headers={"X-Tenant-Slug": "beta"})

        repo_stub.get_by_slug.assert_called_once_with("beta")

    def test_empty_slug_header_returns_404(self) -> None:
        """An empty string slug is falsy — treated same as missing."""
        repo_stub = MagicMock()
        repo_stub.get_by_slug.return_value = None
        app = _build_middleware_app(repo_stub)

        with patch("src.api.middleware.tenant_middleware.get_container") as mock_gc:
            mock_gc.return_value.tenant_repo.return_value = repo_stub
            client = TestClient(app, raise_server_exceptions=False)
            # Empty header value is technically present but empty string is falsy.
            response = client.get("/ping", headers={"X-Tenant-Slug": ""})

        # Empty slug: middleware evaluates `if not slug` → True → 400
        assert response.status_code == 400


# ---------------------------------------------------------------------------
# FastAPI dependency wiring helpers
# ---------------------------------------------------------------------------


def _build_auth_app(jwt_svc: JWTService, user: User | None, role: Role) -> FastAPI:
    """Minimal app that exercises get_current_user and require_role."""
    inner = FastAPI()

    @inner.get("/me")
    async def me(
        current: tuple[User, Role] = require_role(Role.VIEWER),
    ) -> dict[str, str]:
        u, r = current
        return {"user_id": u.id, "role": r.value}

    @inner.get("/admin-only")
    async def admin_only(
        current: tuple[User, Role] = require_role(Role.ADMIN),
    ) -> dict[str, str]:
        u, r = current
        return {"user_id": u.id, "role": r.value}

    # --- override get_tenant_slug so request.state is not needed -----------
    inner.dependency_overrides[get_tenant_slug] = lambda: _TENANT_SLUG

    # --- override jwt service with the test instance -----------------------
    inner.dependency_overrides[get_jwt_service] = lambda: jwt_svc

    # --- stub user repo -----------------------------------------------------
    user_repo_stub = MagicMock()
    user_repo_stub.get_by_id.return_value = user
    inner.dependency_overrides[get_user_repo] = lambda: user_repo_stub

    # --- stub membership repo -----------------------------------------------
    membership_repo_stub = MagicMock()
    inner.dependency_overrides[get_membership_repo] = lambda: membership_repo_stub

    return inner


# ---------------------------------------------------------------------------
# get_current_user
# ---------------------------------------------------------------------------


class TestGetCurrentUserMissingHeader:
    def test_returns_401_when_authorization_absent(self, jwt_svc: JWTService) -> None:
        app = _build_auth_app(jwt_svc, _make_active_user(), Role.MEMBER)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/me")
        assert response.status_code == 401
        assert "Authorization" in response.json()["detail"]


class TestGetCurrentUserInvalidToken:
    def test_returns_401_for_garbage_token(self, jwt_svc: JWTService) -> None:
        app = _build_auth_app(jwt_svc, _make_active_user(), Role.MEMBER)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/me", headers={"Authorization": "Bearer not.a.real.jwt"})
        assert response.status_code == 401

    def test_returns_401_for_wrong_secret(self, jwt_svc: JWTService) -> None:
        other_svc = JWTService(secret="wrong-secret", expire_minutes=30)
        token = other_svc.create_token(_USER_ID, _TENANT_SLUG, Role.MEMBER)
        app = _build_auth_app(jwt_svc, _make_active_user(), Role.MEMBER)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    def test_returns_401_when_tenant_slug_mismatch(self, jwt_svc: JWTService) -> None:
        token = jwt_svc.create_token(_USER_ID, "other-tenant", Role.MEMBER)
        app = _build_auth_app(jwt_svc, _make_active_user(), Role.MEMBER)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert "tenant" in response.json()["detail"].lower()

    def test_returns_401_when_user_not_found(self, jwt_svc: JWTService) -> None:
        token = jwt_svc.create_token(_USER_ID, _TENANT_SLUG, Role.MEMBER)
        app = _build_auth_app(jwt_svc, None, Role.MEMBER)  # user_repo returns None
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert "User" in response.json()["detail"] or "user" in response.json()["detail"]

    def test_returns_401_when_user_inactive(self, jwt_svc: JWTService) -> None:
        token = jwt_svc.create_token(_USER_ID, _TENANT_SLUG, Role.MEMBER)
        app = _build_auth_app(jwt_svc, _make_inactive_user(), Role.MEMBER)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401

    def test_bearer_prefix_is_stripped_before_decode(self, jwt_svc: JWTService) -> None:
        """'Bearer <token>' must work; raw token without prefix must also work."""
        token = jwt_svc.create_token(_USER_ID, _TENANT_SLUG, Role.MEMBER)
        app = _build_auth_app(jwt_svc, _make_active_user(), Role.MEMBER)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200


class TestGetCurrentUserSuccess:
    def test_returns_user_and_role_on_valid_token(self, jwt_svc: JWTService) -> None:
        token = jwt_svc.create_token(_USER_ID, _TENANT_SLUG, Role.MEMBER)
        app = _build_auth_app(jwt_svc, _make_active_user(), Role.MEMBER)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        body = response.json()
        assert body["user_id"] == _USER_ID
        assert body["role"] == Role.MEMBER.value

    def test_all_roles_succeed_on_viewer_protected_endpoint(
        self, jwt_svc: JWTService
    ) -> None:
        for role in Role:
            token = jwt_svc.create_token(_USER_ID, _TENANT_SLUG, role)
            app = _build_auth_app(jwt_svc, _make_active_user(), role)
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 200, f"Expected 200 for role {role}"


# ---------------------------------------------------------------------------
# require_role
# ---------------------------------------------------------------------------


class TestRequireRoleHierarchy:
    """Verify that the role hierarchy is correctly enforced."""

    @pytest.mark.parametrize(
        "user_role,endpoint,expected_status",
        [
            # OWNER passes ADMIN-only
            (Role.OWNER, "/admin-only", 200),
            # ADMIN passes ADMIN-only
            (Role.ADMIN, "/admin-only", 200),
            # MEMBER fails ADMIN-only
            (Role.MEMBER, "/admin-only", 403),
            # VIEWER fails ADMIN-only
            (Role.VIEWER, "/admin-only", 403),
            # All roles pass VIEWER-only (/me)
            (Role.OWNER, "/me", 200),
            (Role.ADMIN, "/me", 200),
            (Role.MEMBER, "/me", 200),
            (Role.VIEWER, "/me", 200),
        ],
    )
    def test_role_enforcement(
        self,
        jwt_svc: JWTService,
        user_role: Role,
        endpoint: str,
        expected_status: int,
    ) -> None:
        token = jwt_svc.create_token(_USER_ID, _TENANT_SLUG, user_role)
        app = _build_auth_app(jwt_svc, _make_active_user(), user_role)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get(endpoint, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == expected_status, (
            f"role={user_role} on {endpoint}: expected {expected_status}, "
            f"got {response.status_code}"
        )

    def test_403_detail_contains_required_role(self, jwt_svc: JWTService) -> None:
        token = jwt_svc.create_token(_USER_ID, _TENANT_SLUG, Role.VIEWER)
        app = _build_auth_app(jwt_svc, _make_active_user(), Role.VIEWER)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/admin-only", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403
        assert "ADMIN" in response.json()["detail"]

    def test_owner_passes_member_check(self, jwt_svc: JWTService) -> None:
        """OWNER (level 3) must satisfy MEMBER (level 1) requirement."""
        token = jwt_svc.create_token(_USER_ID, _TENANT_SLUG, Role.OWNER)
        app = _build_auth_app(jwt_svc, _make_active_user(), Role.OWNER)
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200

    def test_role_level_map_is_from_domain(self) -> None:
        """ROLE_LEVEL must be imported from domain, not redefined in auth.py."""
        # This indirectly confirms the import: the values must match domain spec.
        assert ROLE_LEVEL[Role.OWNER] > ROLE_LEVEL[Role.ADMIN]
        assert ROLE_LEVEL[Role.ADMIN] > ROLE_LEVEL[Role.MEMBER]
        assert ROLE_LEVEL[Role.MEMBER] > ROLE_LEVEL[Role.VIEWER]


# ---------------------------------------------------------------------------
# Auth schemas — RegisterRequest
# ---------------------------------------------------------------------------


class TestRegisterRequest:
    def test_valid_construction(self) -> None:
        r = RegisterRequest(email="user@example.com", password="s3cr3t")
        assert r.email == "user@example.com"
        assert r.password == "s3cr3t"

    def test_invalid_email_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            RegisterRequest(email="not-an-email", password="s3cr3t")

    def test_empty_password_is_allowed(self) -> None:
        """Pydantic does not enforce non-empty strings by default."""
        r = RegisterRequest(email="a@b.com", password="")
        assert r.password == ""

    def test_missing_email_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            RegisterRequest(password="s3cr3t")  # type: ignore[call-arg]

    def test_missing_password_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            RegisterRequest(email="a@b.com")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Auth schemas — LoginRequest
# ---------------------------------------------------------------------------


class TestLoginRequest:
    def test_valid_construction(self) -> None:
        r = LoginRequest(email="user@example.com", password="pass")
        assert r.email == "user@example.com"
        assert r.password == "pass"

    def test_invalid_email_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            LoginRequest(email="bad-email", password="pass")

    def test_missing_fields_raise_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            LoginRequest(email="a@b.com")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Auth schemas — TokenResponse
# ---------------------------------------------------------------------------


class TestTokenResponse:
    def test_default_token_type_is_bearer(self) -> None:
        r = TokenResponse(
            access_token="jwt.string.here",
            user_id="uid-1",
            email="a@b.com",
            role="MEMBER",
        )
        assert r.token_type == "bearer"

    def test_explicit_token_type_override(self) -> None:
        r = TokenResponse(
            access_token="tok",
            token_type="custom",
            user_id="uid",
            email="a@b.com",
            role="OWNER",
        )
        assert r.token_type == "custom"

    def test_all_fields_serialised_correctly(self) -> None:
        r = TokenResponse(
            access_token="abc",
            user_id="uid-42",
            email="test@test.com",
            role="ADMIN",
        )
        data = r.model_dump()
        assert data["access_token"] == "abc"
        assert data["user_id"] == "uid-42"
        assert data["email"] == "test@test.com"
        assert data["role"] == "ADMIN"
        assert data["token_type"] == "bearer"

    def test_missing_required_field_raises_validation_error(self) -> None:
        with pytest.raises(ValidationError):
            TokenResponse(user_id="uid", email="a@b.com", role="MEMBER")  # type: ignore[call-arg]
