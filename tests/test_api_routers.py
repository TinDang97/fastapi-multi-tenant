"""Unit / integration tests for the API routers.

Strategy
--------
* Use ``TestClient`` from Starlette/FastAPI against the main app with
  ``raise_server_exceptions=True``.
* The lifespan is skipped via ``TestClient(..., lifespan="off")`` so no real
  DB engines or DI container are initialised.
* All FastAPI dependencies that touch infrastructure are overridden via
  ``app.dependency_overrides`` with in-memory fakes.
* ``get_container().password_service()`` calls inside routers are patched via
  ``monkeypatch`` before each test class.

Covered
-------
health.py  — GET /health (tenant field present)
pages.py   — GET / (landing page 200)
auth.py    — POST /auth/register (success 201 + duplicate 409)
           — POST /auth/login    (success 200 + bad credentials 401)
users.py   — GET  /users  (viewer OK 200; unauthenticated 401)
           — POST /users  (admin OK 201; duplicate 409; bad role 422; viewer 403)
           — DELETE /users/{id} (found 200; not found 404; viewer 403)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api.dependencies.auth import (
    get_current_user,
    get_jwt_service,
    get_membership_repo,
    get_tenant_slug,
    get_user_repo,
)
from src.domain.entities import Role, TenantMembership, User
from src.main import app

# ---------------------------------------------------------------------------
# In-memory fakes
# ---------------------------------------------------------------------------


def _make_user(
    email: str = "user@example.com",
    is_active: bool = True,
) -> User:
    return User(
        id=User.generate_id(),
        email=email,
        hashed_password="hashed:secret",
        is_active=is_active,
    )


class FakeUserRepo:
    """In-memory user repository."""

    def __init__(self, users: list[User] | None = None) -> None:
        self._users: dict[str, User] = {u.id: u for u in (users or [])}
        self._by_email: dict[str, User] = {u.email: u for u in (users or [])}

    def get_by_id(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    def get_by_email(self, email: str) -> User | None:
        return self._by_email.get(email)

    def create(self, user: User) -> User:
        self._users[user.id] = user
        self._by_email[user.email] = user
        return user

    def delete_by_id(self, user_id: str) -> bool:
        if user_id not in self._users:
            return False
        user = self._users.pop(user_id)
        self._by_email.pop(user.email, None)
        return True


class FakeMembershipRepo:
    """In-memory membership repository."""

    def __init__(self, memberships: list[TenantMembership] | None = None) -> None:
        self._memberships: list[TenantMembership] = list(memberships or [])

    def get_membership(self, user_id: str, tenant_slug: str) -> TenantMembership | None:
        for m in self._memberships:
            if m.user_id == user_id and m.tenant_slug == tenant_slug:
                return m
        return None

    def assign_role(self, membership: TenantMembership) -> TenantMembership:
        self._memberships.append(membership)
        return membership

    def list_members(self, tenant_slug: str) -> list[TenantMembership]:
        return [m for m in self._memberships if m.tenant_slug == tenant_slug]


class FakePasswordService:
    def hash(self, plain: str) -> str:
        return f"hashed:{plain}"

    def verify(self, plain: str, hashed: str) -> bool:
        return hashed == f"hashed:{plain}"


class _FakeTenantRepo:
    """Returns a valid active Tenant for any slug — satisfies TenantMiddleware."""

    def get_by_slug(self, slug: str):  # noqa: ANN001, ANN201
        from datetime import UTC, datetime

        from src.domain.entities import Tenant

        return Tenant(slug=slug, name=slug, is_active=True, created_at=datetime.now(UTC))


class FakeJWTService:
    def create_token(self, user_id: str, tenant_slug: str, role: Role) -> str:
        return f"token:{user_id}:{tenant_slug}:{role}"

    def decode_token(self, token: str) -> dict[str, str]:
        _, user_id, tenant_slug, role = token.split(":")
        return {"sub": user_id, "tenant_slug": tenant_slug, "role": role}


# ---------------------------------------------------------------------------
# Dependency override helpers
# ---------------------------------------------------------------------------

_TENANT_SLUG = "acme"


def _build_client(
    user_repo: FakeUserRepo | None = None,
    membership_repo: FakeMembershipRepo | None = None,
    current_user: tuple[User, Role] | None = None,
) -> TestClient:
    """Build a TestClient with overridden FastAPI dependencies.

    Uses ``lifespan="off"`` to skip the real DI container startup.
    """
    _user_repo = user_repo or FakeUserRepo()
    _membership_repo = membership_repo or FakeMembershipRepo()
    _jwt_svc = FakeJWTService()

    app.dependency_overrides[get_tenant_slug] = lambda: _TENANT_SLUG
    app.dependency_overrides[get_user_repo] = lambda: _user_repo
    app.dependency_overrides[get_membership_repo] = lambda: _membership_repo
    app.dependency_overrides[get_jwt_service] = lambda: _jwt_svc

    if current_user is not None:
        app.dependency_overrides[get_current_user] = lambda: current_user

    client = TestClient(app, raise_server_exceptions=True)
    client.headers.update({"X-Tenant-Slug": _TENANT_SLUG})
    return client


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _FakeContainer:
    def __init__(self) -> None:
        self._password_svc = FakePasswordService()
        self._tenant_repo = _FakeTenantRepo()

    def password_service(self) -> FakePasswordService:
        return self._password_svc

    def tenant_repo(self) -> _FakeTenantRepo:
        return self._tenant_repo


@pytest.fixture(autouse=True)
def _patch_container(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch get_container() everywhere so no real DI container is needed."""
    fake = _FakeContainer()
    monkeypatch.setattr("src.api.routers.auth.get_container", lambda: fake)
    monkeypatch.setattr("src.api.routers.users.get_container", lambda: fake)
    monkeypatch.setattr("src.api.middleware.tenant_middleware.get_container", lambda: fake)


@pytest.fixture(autouse=True)
def _reset_overrides() -> None:  # type: ignore[return]
    yield
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# health.py tests
# ---------------------------------------------------------------------------


class TestHealthRouter:
    def test_health_returns_ok_and_tenant(self) -> None:
        client = _build_client()
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["tenant"] == _TENANT_SLUG


# ---------------------------------------------------------------------------
# pages.py tests
# ---------------------------------------------------------------------------


class TestPagesRouter:
    def test_index_returns_200_html(self) -> None:
        client = _build_client()
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


# ---------------------------------------------------------------------------
# auth.py tests — POST /auth/register
# ---------------------------------------------------------------------------


class TestRegisterRoute:
    def test_register_success_returns_201_with_token(self) -> None:
        client = _build_client()
        response = client.post(
            "/auth/register",
            json={"email": "new@acme.com", "password": "secret123"},
        )
        assert response.status_code == 201
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["email"] == "new@acme.com"
        assert body["role"] == Role.MEMBER
        assert body["access_token"].startswith("token:")

    def test_register_duplicate_email_returns_409(self) -> None:
        existing = _make_user("taken@acme.com")
        user_repo = FakeUserRepo([existing])
        client = _build_client(user_repo=user_repo)
        response = client.post(
            "/auth/register",
            json={"email": "taken@acme.com", "password": "pw"},
        )
        assert response.status_code == 409
        assert "taken@acme.com" in response.json()["detail"]

    def test_register_assigns_member_role(self) -> None:
        client = _build_client()
        response = client.post(
            "/auth/register",
            json={"email": "x@acme.com", "password": "pw"},
        )
        assert response.status_code == 201
        assert response.json()["role"] == Role.MEMBER

    def test_register_response_contains_user_id(self) -> None:
        client = _build_client()
        response = client.post(
            "/auth/register",
            json={"email": "y@acme.com", "password": "pw"},
        )
        assert response.status_code == 201
        assert response.json()["user_id"]

    def test_register_token_is_tenant_scoped(self) -> None:
        client = _build_client()
        response = client.post(
            "/auth/register",
            json={"email": "z@acme.com", "password": "pw"},
        )
        assert response.status_code == 201
        assert f":{_TENANT_SLUG}:" in response.json()["access_token"]


# ---------------------------------------------------------------------------
# auth.py tests — POST /auth/login
# ---------------------------------------------------------------------------


class TestLoginRoute:
    def _setup(
        self,
        email: str = "user@acme.com",
        plain: str = "secret",
        role: Role = Role.MEMBER,
        is_active: bool = True,
    ) -> tuple[FakeUserRepo, FakeMembershipRepo]:
        user = User(
            id=User.generate_id(),
            email=email,
            hashed_password=f"hashed:{plain}",
            is_active=is_active,
        )
        membership = TenantMembership(user_id=user.id, tenant_slug=_TENANT_SLUG, role=role)
        return FakeUserRepo([user]), FakeMembershipRepo([membership])

    def test_login_success_returns_200_with_token(self) -> None:
        user_repo, membership_repo = self._setup()
        client = _build_client(user_repo=user_repo, membership_repo=membership_repo)
        response = client.post(
            "/auth/login",
            json={"email": "user@acme.com", "password": "secret"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"].startswith("token:")
        assert body["email"] == "user@acme.com"

    def test_login_wrong_password_returns_401(self) -> None:
        user_repo, membership_repo = self._setup()
        client = _build_client(user_repo=user_repo, membership_repo=membership_repo)
        response = client.post(
            "/auth/login",
            json={"email": "user@acme.com", "password": "wrong"},
        )
        assert response.status_code == 401

    def test_login_unknown_email_returns_401(self) -> None:
        client = _build_client()
        response = client.post(
            "/auth/login",
            json={"email": "ghost@acme.com", "password": "pw"},
        )
        assert response.status_code == 401

    def test_login_inactive_user_returns_401(self) -> None:
        user_repo, membership_repo = self._setup(is_active=False)
        client = _build_client(user_repo=user_repo, membership_repo=membership_repo)
        response = client.post(
            "/auth/login",
            json={"email": "user@acme.com", "password": "secret"},
        )
        assert response.status_code == 401

    def test_login_no_membership_returns_401(self) -> None:
        user = User(
            id=User.generate_id(),
            email="nomember@acme.com",
            hashed_password="hashed:secret",
        )
        user_repo = FakeUserRepo([user])
        membership_repo = FakeMembershipRepo()
        client = _build_client(user_repo=user_repo, membership_repo=membership_repo)
        response = client.post(
            "/auth/login",
            json={"email": "nomember@acme.com", "password": "secret"},
        )
        assert response.status_code == 401

    def test_login_returns_correct_role(self) -> None:
        user_repo, membership_repo = self._setup(role=Role.ADMIN)
        client = _build_client(user_repo=user_repo, membership_repo=membership_repo)
        response = client.post(
            "/auth/login",
            json={"email": "user@acme.com", "password": "secret"},
        )
        assert response.status_code == 200
        assert response.json()["role"] == Role.ADMIN


# ---------------------------------------------------------------------------
# users.py tests — GET /users
# ---------------------------------------------------------------------------


class TestListUsersRoute:
    def test_viewer_can_list_users_returns_200_html(self) -> None:
        viewer = _make_user("viewer@acme.com")
        membership = TenantMembership(
            user_id=viewer.id, tenant_slug=_TENANT_SLUG, role=Role.VIEWER
        )
        user_repo = FakeUserRepo([viewer])
        membership_repo = FakeMembershipRepo([membership])
        client = _build_client(
            user_repo=user_repo,
            membership_repo=membership_repo,
            current_user=(viewer, Role.VIEWER),
        )
        response = client.get("/users")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_unauthenticated_returns_401(self) -> None:
        # No current_user override — get_current_user runs, finds no Authorization header.
        client = _build_client()
        response = client.get("/users")
        assert response.status_code == 401

    def test_member_can_list_users(self) -> None:
        member = _make_user("member@acme.com")
        membership = TenantMembership(
            user_id=member.id, tenant_slug=_TENANT_SLUG, role=Role.MEMBER
        )
        user_repo = FakeUserRepo([member])
        membership_repo = FakeMembershipRepo([membership])
        client = _build_client(
            user_repo=user_repo,
            membership_repo=membership_repo,
            current_user=(member, Role.MEMBER),
        )
        response = client.get("/users")
        assert response.status_code == 200

    def test_admin_can_list_users(self) -> None:
        admin = _make_user("admin@acme.com")
        client = _build_client(current_user=(admin, Role.ADMIN))
        response = client.get("/users")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# users.py tests — POST /users
# ---------------------------------------------------------------------------


class TestCreateUserRoute:
    def test_admin_creates_user_returns_201_html(self) -> None:
        admin = _make_user("admin@acme.com")
        client = _build_client(current_user=(admin, Role.ADMIN))
        response = client.post(
            "/users",
            data={"email": "new@acme.com", "password": "pw123", "role": Role.MEMBER},
        )
        assert response.status_code == 201
        assert "text/html" in response.headers["content-type"]

    def test_owner_creates_user_returns_201(self) -> None:
        owner = _make_user("owner@acme.com")
        client = _build_client(current_user=(owner, Role.OWNER))
        response = client.post(
            "/users",
            data={"email": "new2@acme.com", "password": "pw", "role": Role.VIEWER},
        )
        assert response.status_code == 201

    def test_admin_create_duplicate_email_returns_409(self) -> None:
        existing = _make_user("taken@acme.com")
        admin = _make_user("admin@acme.com")
        user_repo = FakeUserRepo([existing])
        client = _build_client(user_repo=user_repo, current_user=(admin, Role.ADMIN))
        response = client.post(
            "/users",
            data={"email": "taken@acme.com", "password": "pw", "role": Role.MEMBER},
        )
        assert response.status_code == 409

    def test_create_invalid_role_returns_422(self) -> None:
        admin = _make_user("admin@acme.com")
        client = _build_client(current_user=(admin, Role.ADMIN))
        response = client.post(
            "/users",
            data={"email": "x@acme.com", "password": "pw", "role": "SUPERUSER"},
        )
        assert response.status_code == 422

    def test_viewer_cannot_create_user_returns_403(self) -> None:
        viewer = _make_user("viewer@acme.com")
        client = _build_client(current_user=(viewer, Role.VIEWER))
        response = client.post(
            "/users",
            data={"email": "x@acme.com", "password": "pw", "role": Role.MEMBER},
        )
        assert response.status_code == 403

    def test_member_cannot_create_user_returns_403(self) -> None:
        member = _make_user("member@acme.com")
        client = _build_client(current_user=(member, Role.MEMBER))
        response = client.post(
            "/users",
            data={"email": "x@acme.com", "password": "pw", "role": Role.VIEWER},
        )
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# users.py tests — DELETE /users/{user_id}
# ---------------------------------------------------------------------------


class TestDeleteUserRoute:
    def test_admin_deletes_existing_user_returns_200(self) -> None:
        target = _make_user("target@acme.com")
        admin = _make_user("admin@acme.com")
        user_repo = FakeUserRepo([target])
        client = _build_client(user_repo=user_repo, current_user=(admin, Role.ADMIN))
        response = client.delete(f"/users/{target.id}")
        assert response.status_code == 200

    def test_owner_deletes_existing_user_returns_200(self) -> None:
        target = _make_user("target@acme.com")
        owner = _make_user("owner@acme.com")
        user_repo = FakeUserRepo([target])
        client = _build_client(user_repo=user_repo, current_user=(owner, Role.OWNER))
        response = client.delete(f"/users/{target.id}")
        assert response.status_code == 200

    def test_delete_nonexistent_user_returns_404(self) -> None:
        admin = _make_user("admin@acme.com")
        client = _build_client(current_user=(admin, Role.ADMIN))
        response = client.delete("/users/does-not-exist")
        assert response.status_code == 404

    def test_viewer_cannot_delete_returns_403(self) -> None:
        target = _make_user("target@acme.com")
        viewer = _make_user("viewer@acme.com")
        user_repo = FakeUserRepo([target])
        client = _build_client(user_repo=user_repo, current_user=(viewer, Role.VIEWER))
        response = client.delete(f"/users/{target.id}")
        assert response.status_code == 403

    def test_member_cannot_delete_returns_403(self) -> None:
        target = _make_user("target@acme.com")
        member = _make_user("member@acme.com")
        user_repo = FakeUserRepo([target])
        client = _build_client(user_repo=user_repo, current_user=(member, Role.MEMBER))
        response = client.delete(f"/users/{target.id}")
        assert response.status_code == 403

    def test_delete_removes_user_from_repo(self) -> None:
        target = _make_user("gone@acme.com")
        admin = _make_user("admin@acme.com")
        user_repo = FakeUserRepo([target])
        client = _build_client(user_repo=user_repo, current_user=(admin, Role.ADMIN))
        client.delete(f"/users/{target.id}")
        assert user_repo.get_by_id(target.id) is None

    def test_unauthenticated_delete_returns_401(self) -> None:
        target = _make_user("target@acme.com")
        user_repo = FakeUserRepo([target])
        # No current_user override; get_current_user checks Authorization header
        client = _build_client(user_repo=user_repo)
        response = client.delete(f"/users/{target.id}")
        assert response.status_code == 401
