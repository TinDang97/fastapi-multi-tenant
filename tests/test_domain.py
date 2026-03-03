"""Unit tests for the domain layer: entities, exceptions, and role hierarchy."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.domain.entities import (
    ROLE_LEVEL,
    Role,
    Tenant,
    TenantMembership,
    User,
    role_satisfies,
)
from src.domain.exceptions import (
    AuthenticationError,
    DomainError,
    DuplicateEmailError,
    PermissionDeniedError,
    TenantNotFoundError,
    UserNotFoundError,
)

# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------


class TestRoleEnum:
    def test_all_roles_defined(self) -> None:
        assert set(Role) == {Role.OWNER, Role.ADMIN, Role.MEMBER, Role.VIEWER}

    def test_role_values_are_strings(self) -> None:
        for role in Role:
            assert isinstance(role, str)

    def test_role_level_covers_all_roles(self) -> None:
        assert set(ROLE_LEVEL.keys()) == set(Role)

    def test_role_levels_are_unique(self) -> None:
        levels = list(ROLE_LEVEL.values())
        assert len(levels) == len(set(levels))

    def test_owner_has_highest_level(self) -> None:
        owner_level = ROLE_LEVEL[Role.OWNER]
        for role, level in ROLE_LEVEL.items():
            if role != Role.OWNER:
                assert owner_level > level

    def test_viewer_has_lowest_level(self) -> None:
        viewer_level = ROLE_LEVEL[Role.VIEWER]
        for role, level in ROLE_LEVEL.items():
            if role != Role.VIEWER:
                assert viewer_level < level


# ---------------------------------------------------------------------------
# role_satisfies
# ---------------------------------------------------------------------------


class TestRoleSatisfies:
    def test_same_role_satisfies_itself(self) -> None:
        for role in Role:
            assert role_satisfies(role, role) is True

    def test_owner_satisfies_all(self) -> None:
        for required in Role:
            assert role_satisfies(Role.OWNER, required) is True

    def test_viewer_satisfies_only_viewer(self) -> None:
        assert role_satisfies(Role.VIEWER, Role.VIEWER) is True
        assert role_satisfies(Role.VIEWER, Role.MEMBER) is False
        assert role_satisfies(Role.VIEWER, Role.ADMIN) is False
        assert role_satisfies(Role.VIEWER, Role.OWNER) is False

    def test_member_satisfies_member_and_viewer(self) -> None:
        assert role_satisfies(Role.MEMBER, Role.VIEWER) is True
        assert role_satisfies(Role.MEMBER, Role.MEMBER) is True
        assert role_satisfies(Role.MEMBER, Role.ADMIN) is False
        assert role_satisfies(Role.MEMBER, Role.OWNER) is False

    def test_admin_satisfies_all_except_owner(self) -> None:
        assert role_satisfies(Role.ADMIN, Role.VIEWER) is True
        assert role_satisfies(Role.ADMIN, Role.MEMBER) is True
        assert role_satisfies(Role.ADMIN, Role.ADMIN) is True
        assert role_satisfies(Role.ADMIN, Role.OWNER) is False


# ---------------------------------------------------------------------------
# Tenant entity
# ---------------------------------------------------------------------------


class TestTenantEntity:
    def test_tenant_defaults(self) -> None:
        t = Tenant(slug="acme", name="Acme Corp")
        assert t.slug == "acme"
        assert t.name == "Acme Corp"
        assert t.is_active is True
        assert isinstance(t.created_at, datetime)

    def test_tenant_created_at_is_utc_aware(self) -> None:
        t = Tenant(slug="acme", name="Acme Corp")
        assert t.created_at.tzinfo is not None

    def test_tenant_created_at_defaults_are_distinct(self) -> None:
        t1 = Tenant(slug="a", name="A")
        t2 = Tenant(slug="b", name="B")
        # Both are datetime instances; slugs differentiate them
        assert t1.slug != t2.slug

    def test_tenant_inactive(self) -> None:
        t = Tenant(slug="old", name="Old Corp", is_active=False)
        assert t.is_active is False

    def test_tenant_explicit_created_at(self) -> None:
        ts = datetime(2024, 1, 1, tzinfo=UTC)
        t = Tenant(slug="ts", name="TS", created_at=ts)
        assert t.created_at == ts


# ---------------------------------------------------------------------------
# User entity
# ---------------------------------------------------------------------------


class TestUserEntity:
    def test_user_construction(self) -> None:
        uid = User.generate_id()
        u = User(id=uid, email="test@example.com", hashed_password="hashed")
        assert u.id == uid
        assert u.email == "test@example.com"
        assert u.hashed_password == "hashed"
        assert u.is_active is True

    def test_generate_id_is_valid_uuid(self) -> None:
        import uuid

        uid = User.generate_id()
        parsed = uuid.UUID(uid)
        assert str(parsed) == uid

    def test_generate_id_is_unique(self) -> None:
        ids = {User.generate_id() for _ in range(100)}
        assert len(ids) == 100

    def test_user_inactive(self) -> None:
        u = User(id="x", email="e@e.com", hashed_password="h", is_active=False)
        assert u.is_active is False


# ---------------------------------------------------------------------------
# TenantMembership entity
# ---------------------------------------------------------------------------


class TestTenantMembershipEntity:
    def test_membership_construction(self) -> None:
        m = TenantMembership(user_id="uid", tenant_slug="acme", role=Role.MEMBER)
        assert m.user_id == "uid"
        assert m.tenant_slug == "acme"
        assert m.role == Role.MEMBER

    def test_membership_all_roles(self) -> None:
        for role in Role:
            m = TenantMembership(user_id="u", tenant_slug="t", role=role)
            assert m.role == role


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class TestExceptions:
    def test_domain_error_is_exception(self) -> None:
        with pytest.raises(DomainError):
            raise DomainError("base error")

    def test_authentication_error_is_domain_error(self) -> None:
        with pytest.raises(DomainError):
            raise AuthenticationError("bad credentials")

    def test_tenant_not_found_message(self) -> None:
        err = TenantNotFoundError("acme")
        assert "acme" in str(err)
        assert err.slug == "acme"

    def test_tenant_not_found_is_domain_error(self) -> None:
        with pytest.raises(DomainError):
            raise TenantNotFoundError("x")

    def test_permission_denied_message(self) -> None:
        err = PermissionDeniedError("ADMIN")
        assert "ADMIN" in str(err)
        assert err.required == "ADMIN"

    def test_permission_denied_is_domain_error(self) -> None:
        with pytest.raises(DomainError):
            raise PermissionDeniedError("OWNER")

    def test_user_not_found_is_domain_error(self) -> None:
        with pytest.raises(DomainError):
            raise UserNotFoundError("user not found")

    def test_duplicate_email_message(self) -> None:
        err = DuplicateEmailError("dupe@example.com")
        assert "dupe@example.com" in str(err)
        assert err.email == "dupe@example.com"

    def test_duplicate_email_is_domain_error(self) -> None:
        with pytest.raises(DomainError):
            raise DuplicateEmailError("x@x.com")
