"""Unit tests for all application-layer use cases.

All external dependencies (repositories, services) are replaced with
lightweight fakes. No database, no network, no global state.
"""

from __future__ import annotations

import pytest

from src.application.use_cases.create_user import CreateUserCommand, CreateUserUseCase
from src.application.use_cases.get_tenant import GetTenantUseCase
from src.application.use_cases.list_users import ListUsersUseCase
from src.application.use_cases.login import LoginCommand, LoginUseCase
from src.application.use_cases.register_user import RegisterUserCommand, RegisterUserUseCase
from src.domain.entities import Role, Tenant, TenantMembership, User
from src.domain.exceptions import (
    AuthenticationError,
    DuplicateEmailError,
    TenantNotFoundError,
)

# ---------------------------------------------------------------------------
# Fake helpers
# ---------------------------------------------------------------------------


def _make_user(
    email: str = "user@example.com",
    hashed_password: str = "hashed",  # noqa: S107
    is_active: bool = True,
) -> User:
    return User(
        id=User.generate_id(),
        email=email,
        hashed_password=hashed_password,
        is_active=is_active,
    )


def _make_tenant(slug: str = "acme", is_active: bool = True) -> Tenant:
    return Tenant(slug=slug, name="Acme Corp", is_active=is_active)


def _make_membership(
    user_id: str, tenant_slug: str = "acme", role: Role = Role.MEMBER
) -> TenantMembership:
    return TenantMembership(user_id=user_id, tenant_slug=tenant_slug, role=role)


class FakeTenantRepo:
    def __init__(self, tenant: Tenant | None = None) -> None:
        self._tenant = tenant

    def get_by_slug(self, slug: str) -> Tenant | None:
        if self._tenant and self._tenant.slug == slug:
            return self._tenant
        return None

    def create(self, tenant: Tenant) -> Tenant:
        self._tenant = tenant
        return tenant

    def list_active(self) -> list[Tenant]:
        if self._tenant and self._tenant.is_active:
            return [self._tenant]
        return []


class FakeUserRepo:
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


class FakeMembershipRepo:
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
    """Records the last hashed value for assertion; verify checks prefix convention."""

    def hash(self, plain_password: str) -> str:
        return f"hashed:{plain_password}"

    def verify(self, plain_password: str, hashed_password: str) -> bool:
        return hashed_password == f"hashed:{plain_password}"


class FakeJWTService:
    def create_token(self, user_id: str, tenant_slug: str, role: Role) -> str:
        return f"token:{user_id}:{tenant_slug}:{role}"

    def decode_token(self, token: str) -> dict[str, str]:
        _, user_id, tenant_slug, role = token.split(":")
        return {"sub": user_id, "tenant_slug": tenant_slug, "role": role}


# ---------------------------------------------------------------------------
# GetTenantUseCase
# ---------------------------------------------------------------------------


class TestGetTenantUseCase:
    def _make_uc(self, tenant: Tenant | None = None) -> GetTenantUseCase:
        return GetTenantUseCase(tenant_repo=FakeTenantRepo(tenant))

    def test_returns_active_tenant(self) -> None:
        tenant = _make_tenant("acme", is_active=True)
        result = self._make_uc(tenant).execute("acme")
        assert result.slug == "acme"

    def test_raises_when_slug_not_found(self) -> None:
        uc = self._make_uc(tenant=None)
        with pytest.raises(TenantNotFoundError) as exc_info:
            uc.execute("ghost")
        assert exc_info.value.slug == "ghost"

    def test_raises_when_tenant_is_inactive(self) -> None:
        inactive = _make_tenant("acme", is_active=False)
        uc = self._make_uc(inactive)
        with pytest.raises(TenantNotFoundError) as exc_info:
            uc.execute("acme")
        assert exc_info.value.slug == "acme"

    def test_raises_on_wrong_slug(self) -> None:
        tenant = _make_tenant("acme")
        uc = self._make_uc(tenant)
        with pytest.raises(TenantNotFoundError):
            uc.execute("other")

    def test_error_message_contains_slug(self) -> None:
        uc = self._make_uc(tenant=None)
        with pytest.raises(TenantNotFoundError) as exc_info:
            uc.execute("missing-slug")
        assert "missing-slug" in str(exc_info.value)


# ---------------------------------------------------------------------------
# RegisterUserUseCase
# ---------------------------------------------------------------------------


class TestRegisterUserUseCase:
    def _make_uc(self, existing_users: list[User] | None = None) -> RegisterUserUseCase:
        return RegisterUserUseCase(
            user_repo=FakeUserRepo(existing_users),
            membership_repo=FakeMembershipRepo(),
            password_service=FakePasswordService(),
        )

    def test_returns_result_with_user_and_membership(self) -> None:
        uc = self._make_uc()
        cmd = RegisterUserCommand(
            email="new@example.com", plain_password="pass123", tenant_slug="acme"
        )
        result = uc.execute(cmd)
        assert result.user.email == "new@example.com"
        assert result.membership.role == Role.MEMBER
        assert result.membership.tenant_slug == "acme"

    def test_password_is_hashed_before_storage(self) -> None:
        uc = self._make_uc()
        cmd = RegisterUserCommand(
            email="new@example.com", plain_password="secret", tenant_slug="acme"
        )
        result = uc.execute(cmd)
        assert result.user.hashed_password == "hashed:secret"
        assert result.user.hashed_password != "secret"

    def test_membership_links_to_created_user(self) -> None:
        uc = self._make_uc()
        cmd = RegisterUserCommand(email="new@example.com", plain_password="p", tenant_slug="acme")
        result = uc.execute(cmd)
        assert result.membership.user_id == result.user.id

    def test_raises_duplicate_email_error(self) -> None:
        existing = _make_user("taken@example.com")
        uc = self._make_uc([existing])
        cmd = RegisterUserCommand(email="taken@example.com", plain_password="p", tenant_slug="acme")
        with pytest.raises(DuplicateEmailError) as exc_info:
            uc.execute(cmd)
        assert exc_info.value.email == "taken@example.com"

    def test_duplicate_email_error_not_swallowed(self) -> None:
        """DuplicateEmailError must propagate; use case must not catch it."""
        existing = _make_user("dup@example.com")
        uc = self._make_uc([existing])
        cmd = RegisterUserCommand(email="dup@example.com", plain_password="p", tenant_slug="t")
        with pytest.raises(DuplicateEmailError):
            uc.execute(cmd)

    def test_user_is_active_by_default(self) -> None:
        uc = self._make_uc()
        cmd = RegisterUserCommand(email="a@b.com", plain_password="p", tenant_slug="t")
        result = uc.execute(cmd)
        assert result.user.is_active is True

    def test_assigns_member_role_regardless_of_tenant(self) -> None:
        uc = self._make_uc()
        for slug in ("alpha", "beta", "gamma"):
            cmd = RegisterUserCommand(email=f"u@{slug}.com", plain_password="p", tenant_slug=slug)
            result = uc.execute(cmd)
            assert result.membership.role == Role.MEMBER

    def test_generated_user_id_is_unique(self) -> None:
        uc = self._make_uc()
        ids = set()
        for i in range(10):
            cmd = RegisterUserCommand(email=f"u{i}@x.com", plain_password="p", tenant_slug="t")
            result = uc.execute(cmd)
            ids.add(result.user.id)
        assert len(ids) == 10


# ---------------------------------------------------------------------------
# LoginUseCase
# ---------------------------------------------------------------------------


class TestLoginUseCase:
    def _make_uc(
        self,
        users: list[User] | None = None,
        memberships: list[TenantMembership] | None = None,
    ) -> LoginUseCase:
        return LoginUseCase(
            user_repo=FakeUserRepo(users),
            membership_repo=FakeMembershipRepo(memberships),
            password_service=FakePasswordService(),
            jwt_service=FakeJWTService(),
        )

    def _registered_user(
        self,
        email: str = "user@example.com",
        plain: str = "correct",
        tenant_slug: str = "acme",
        role: Role = Role.MEMBER,
        is_active: bool = True,
    ) -> tuple[User, TenantMembership]:
        user = User(
            id=User.generate_id(),
            email=email,
            hashed_password=f"hashed:{plain}",
            is_active=is_active,
        )
        membership = _make_membership(user.id, tenant_slug, role)
        return user, membership

    def test_returns_token_user_and_role(self) -> None:
        user, membership = self._registered_user()
        uc = self._make_uc([user], [membership])
        cmd = LoginCommand(email=user.email, plain_password="correct", tenant_slug="acme")
        result = uc.execute(cmd)
        assert result.token.startswith("token:")
        assert result.user.id == user.id
        assert result.role == Role.MEMBER

    def test_token_encodes_correct_claims(self) -> None:
        user, membership = self._registered_user(role=Role.ADMIN)
        uc = self._make_uc([user], [membership])
        cmd = LoginCommand(email=user.email, plain_password="correct", tenant_slug="acme")
        result = uc.execute(cmd)
        assert f":{user.id}:" in result.token
        assert ":acme:" in result.token
        assert f":{Role.ADMIN}" in result.token

    def test_wrong_password_raises_authentication_error(self) -> None:
        user, membership = self._registered_user()
        uc = self._make_uc([user], [membership])
        cmd = LoginCommand(email=user.email, plain_password="wrong", tenant_slug="acme")
        with pytest.raises(AuthenticationError):
            uc.execute(cmd)

    def test_unknown_email_raises_authentication_error(self) -> None:
        uc = self._make_uc(users=[], memberships=[])
        cmd = LoginCommand(email="ghost@example.com", plain_password="p", tenant_slug="acme")
        with pytest.raises(AuthenticationError):
            uc.execute(cmd)

    def test_inactive_user_raises_authentication_error(self) -> None:
        user, membership = self._registered_user(is_active=False)
        uc = self._make_uc([user], [membership])
        cmd = LoginCommand(email=user.email, plain_password="correct", tenant_slug="acme")
        with pytest.raises(AuthenticationError):
            uc.execute(cmd)

    def test_missing_membership_raises_authentication_error(self) -> None:
        user, _ = self._registered_user()
        uc = self._make_uc([user], memberships=[])
        cmd = LoginCommand(email=user.email, plain_password="correct", tenant_slug="acme")
        with pytest.raises(AuthenticationError):
            uc.execute(cmd)

    def test_role_from_membership_is_returned(self) -> None:
        for role in Role:
            user, membership = self._registered_user(role=role)
            uc = self._make_uc([user], [membership])
            cmd = LoginCommand(email=user.email, plain_password="correct", tenant_slug="acme")
            result = uc.execute(cmd)
            assert result.role == role

    def test_authentication_error_not_leaking_which_check_failed_for_unknown_email(self) -> None:
        uc = self._make_uc()
        with pytest.raises(AuthenticationError) as exc_info:
            uc.execute(LoginCommand(email="no@no.com", plain_password="p", tenant_slug="t"))
        # Must be AuthenticationError — not a more specific exception
        assert type(exc_info.value) is AuthenticationError


# ---------------------------------------------------------------------------
# CreateUserUseCase
# ---------------------------------------------------------------------------


class TestCreateUserUseCase:
    def _make_uc(self, existing_users: list[User] | None = None) -> CreateUserUseCase:
        return CreateUserUseCase(
            user_repo=FakeUserRepo(existing_users),
            membership_repo=FakeMembershipRepo(),
            password_service=FakePasswordService(),
        )

    def test_creates_user_with_requested_role(self) -> None:
        uc = self._make_uc()
        cmd = CreateUserCommand(
            email="admin@acme.com", plain_password="pw", role=Role.ADMIN, tenant_slug="acme"
        )
        result = uc.execute(cmd)
        assert result.membership.role == Role.ADMIN

    def test_creates_user_for_every_role(self) -> None:
        for i, role in enumerate(Role):
            uc = self._make_uc()
            cmd = CreateUserCommand(
                email=f"u{i}@acme.com", plain_password="pw", role=role, tenant_slug="acme"
            )
            result = uc.execute(cmd)
            assert result.membership.role == role

    def test_password_is_hashed(self) -> None:
        uc = self._make_uc()
        cmd = CreateUserCommand(
            email="a@b.com", plain_password="mypassword", role=Role.VIEWER, tenant_slug="t"
        )
        result = uc.execute(cmd)
        assert result.user.hashed_password == "hashed:mypassword"

    def test_raises_duplicate_email_error(self) -> None:
        existing = _make_user("taken@acme.com")
        uc = self._make_uc([existing])
        cmd = CreateUserCommand(
            email="taken@acme.com", plain_password="pw", role=Role.MEMBER, tenant_slug="acme"
        )
        with pytest.raises(DuplicateEmailError) as exc_info:
            uc.execute(cmd)
        assert exc_info.value.email == "taken@acme.com"

    def test_membership_links_to_user(self) -> None:
        uc = self._make_uc()
        cmd = CreateUserCommand(
            email="x@x.com", plain_password="pw", role=Role.OWNER, tenant_slug="t"
        )
        result = uc.execute(cmd)
        assert result.membership.user_id == result.user.id

    def test_membership_slug_matches_command(self) -> None:
        uc = self._make_uc()
        cmd = CreateUserCommand(
            email="x@x.com", plain_password="pw", role=Role.MEMBER, tenant_slug="my-tenant"
        )
        result = uc.execute(cmd)
        assert result.membership.tenant_slug == "my-tenant"

    def test_user_is_active_by_default(self) -> None:
        uc = self._make_uc()
        cmd = CreateUserCommand(
            email="a@b.com", plain_password="pw", role=Role.MEMBER, tenant_slug="t"
        )
        result = uc.execute(cmd)
        assert result.user.is_active is True


# ---------------------------------------------------------------------------
# ListUsersUseCase
# ---------------------------------------------------------------------------


class TestListUsersUseCase:
    def _make_uc(
        self,
        users: list[User] | None = None,
        memberships: list[TenantMembership] | None = None,
    ) -> ListUsersUseCase:
        return ListUsersUseCase(
            user_repo=FakeUserRepo(users),
            membership_repo=FakeMembershipRepo(memberships),
        )

    def test_returns_empty_list_when_no_members(self) -> None:
        uc = self._make_uc()
        result = uc.execute("acme")
        assert result == []

    def test_returns_all_members_with_roles(self) -> None:
        u1 = _make_user("a@acme.com")
        u2 = _make_user("b@acme.com")
        m1 = _make_membership(u1.id, "acme", Role.ADMIN)
        m2 = _make_membership(u2.id, "acme", Role.MEMBER)
        uc = self._make_uc([u1, u2], [m1, m2])
        result = uc.execute("acme")
        assert len(result) == 2
        user_ids = {r.user.id for r in result}
        assert user_ids == {u1.id, u2.id}

    def test_roles_are_correctly_paired(self) -> None:
        u1 = _make_user("a@acme.com")
        m1 = _make_membership(u1.id, "acme", Role.OWNER)
        uc = self._make_uc([u1], [m1])
        result = uc.execute("acme")
        assert result[0].role == Role.OWNER
        assert result[0].user.id == u1.id

    def test_filters_by_tenant_slug(self) -> None:
        u1 = _make_user("a@acme.com")
        u2 = _make_user("b@other.com")
        m1 = _make_membership(u1.id, "acme", Role.MEMBER)
        m2 = _make_membership(u2.id, "other", Role.ADMIN)
        uc = self._make_uc([u1, u2], [m1, m2])
        acme_results = uc.execute("acme")
        assert len(acme_results) == 1
        assert acme_results[0].user.id == u1.id

    def test_skips_orphaned_membership_without_user_record(self) -> None:
        """When a user_id in a membership has no matching User, that entry is skipped."""
        membership_with_no_user = TenantMembership(
            user_id="non-existent-id", tenant_slug="acme", role=Role.MEMBER
        )
        uc = self._make_uc(users=[], memberships=[membership_with_no_user])
        result = uc.execute("acme")
        assert result == []

    def test_partial_orphan_returns_only_resolved_users(self) -> None:
        real_user = _make_user("real@acme.com")
        real_membership = _make_membership(real_user.id, "acme", Role.ADMIN)
        orphan_membership = TenantMembership(user_id="ghost", tenant_slug="acme", role=Role.MEMBER)
        uc = self._make_uc([real_user], [real_membership, orphan_membership])
        result = uc.execute("acme")
        assert len(result) == 1
        assert result[0].user.id == real_user.id

    def test_empty_tenant_returns_empty_list(self) -> None:
        u1 = _make_user("a@other.com")
        m1 = _make_membership(u1.id, "other", Role.MEMBER)
        uc = self._make_uc([u1], [m1])
        result = uc.execute("acme")
        assert result == []
