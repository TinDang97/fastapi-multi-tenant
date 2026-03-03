"""Additional entity construction tests for the domain layer.

Tests in ``tests/test_domain.py`` cover the primary happy-path construction
of each entity and the exception hierarchy.  This module adds:
- Parametrized Role string value assertions (StrEnum contract).
- Boundary and edge-case construction for Tenant, User, and TenantMembership.
- Verification that ``User.generate_id()`` output format satisfies UUID v4.
- Confirmation that dataclass equality and identity semantics are correct.

No infrastructure dependencies — pure Python domain layer only.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from src.domain.entities import (
    Role,
    Tenant,
    TenantMembership,
    User,
)

# ---------------------------------------------------------------------------
# Role — StrEnum contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role,expected_value",
    [
        (Role.OWNER, "OWNER"),
        (Role.ADMIN, "ADMIN"),
        (Role.MEMBER, "MEMBER"),
        (Role.VIEWER, "VIEWER"),
    ],
)
def test_role_string_value(role: Role, expected_value: str) -> None:
    """Each Role member must compare equal to its string value (StrEnum contract)."""
    assert role == expected_value
    assert str(role) == expected_value


def test_role_is_str_subtype() -> None:
    """Role instances must be plain strings — required for JWT claim serialisation."""
    for role in Role:
        assert isinstance(role, str)


def test_role_constructed_from_string() -> None:
    """Role(value) must reconstruct the correct enum member from a string literal."""
    assert Role("OWNER") is Role.OWNER
    assert Role("ADMIN") is Role.ADMIN
    assert Role("MEMBER") is Role.MEMBER
    assert Role("VIEWER") is Role.VIEWER


def test_role_invalid_value_raises() -> None:
    """Constructing Role from an unknown string must raise ValueError."""
    with pytest.raises(ValueError):
        Role("SUPERUSER")


# ---------------------------------------------------------------------------
# Tenant — defaults and field constraints
# ---------------------------------------------------------------------------


def test_tenant_is_active_defaults_to_true() -> None:
    """Tenant.is_active must default to True when not supplied."""
    t = Tenant(slug="acme", name="Acme Corp")
    assert t.is_active is True


def test_tenant_created_at_defaults_to_utc_now() -> None:
    """Tenant.created_at auto-populated value must be timezone-aware (UTC)."""
    before = datetime.now(UTC)
    t = Tenant(slug="acme", name="Acme Corp")
    after = datetime.now(UTC)

    assert t.created_at.tzinfo is not None
    assert before <= t.created_at <= after


def test_tenant_created_at_default_is_not_shared_across_instances() -> None:
    """Each Tenant instance must receive its own default_factory datetime, not a shared object."""
    t1 = Tenant(slug="alpha", name="Alpha")
    t2 = Tenant(slug="beta", name="Beta")
    # Both are independent datetime objects — same reference would indicate a bug.
    assert t1.created_at is not t2.created_at


def test_tenant_explicit_fields_stored_correctly() -> None:
    """All constructor arguments must be stored verbatim on the dataclass."""
    ts = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)
    t = Tenant(slug="globex", name="Globex Corp", is_active=False, created_at=ts)
    assert t.slug == "globex"
    assert t.name == "Globex Corp"
    assert t.is_active is False
    assert t.created_at == ts


def test_tenant_equality_by_value() -> None:
    """Two Tenant dataclasses with identical fields must compare as equal."""
    ts = datetime(2025, 6, 1, tzinfo=UTC)
    t1 = Tenant(slug="same", name="Same Corp", is_active=True, created_at=ts)
    t2 = Tenant(slug="same", name="Same Corp", is_active=True, created_at=ts)
    assert t1 == t2


def test_tenant_inequality_when_slug_differs() -> None:
    """Tenant dataclasses differing in slug must not compare as equal."""
    ts = datetime(2025, 6, 1, tzinfo=UTC)
    t1 = Tenant(slug="a", name="Corp", is_active=True, created_at=ts)
    t2 = Tenant(slug="b", name="Corp", is_active=True, created_at=ts)
    assert t1 != t2


# ---------------------------------------------------------------------------
# User — id generation and defaults
# ---------------------------------------------------------------------------


def test_user_generate_id_is_uuid4_format() -> None:
    """generate_id() must return a lowercase hyphenated UUID v4 string."""
    uid = User.generate_id()
    parsed = uuid.UUID(uid)
    assert str(parsed) == uid
    assert parsed.version == 4


def test_user_generate_id_produces_unique_values() -> None:
    """Repeated calls to generate_id() must never collide (sample of 200)."""
    ids = [User.generate_id() for _ in range(200)]
    assert len(set(ids)) == 200


def test_user_is_active_defaults_to_true() -> None:
    """User.is_active must default to True when not supplied."""
    u = User(id=User.generate_id(), email="a@example.com", hashed_password="h")
    assert u.is_active is True


def test_user_is_active_can_be_set_false() -> None:
    """User.is_active must reflect the explicitly supplied False value."""
    u = User(id=User.generate_id(), email="b@example.com", hashed_password="h", is_active=False)
    assert u.is_active is False


def test_user_fields_stored_correctly() -> None:
    """All four User fields must be stored verbatim on the dataclass."""
    uid = User.generate_id()
    u = User(id=uid, email="c@example.com", hashed_password="bcrypt-hash")
    assert u.id == uid
    assert u.email == "c@example.com"
    assert u.hashed_password == "bcrypt-hash"


def test_user_equality_by_value() -> None:
    """Two User instances with identical fields must compare as equal."""
    uid = "fixed-uuid-value"
    u1 = User(id=uid, email="same@example.com", hashed_password="h", is_active=True)
    u2 = User(id=uid, email="same@example.com", hashed_password="h", is_active=True)
    assert u1 == u2


def test_user_inequality_when_id_differs() -> None:
    """User instances differing in id must not compare as equal."""
    u1 = User(id="id-1", email="same@example.com", hashed_password="h")
    u2 = User(id="id-2", email="same@example.com", hashed_password="h")
    assert u1 != u2


# ---------------------------------------------------------------------------
# TenantMembership — role storage and field access
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", list(Role))
def test_tenant_membership_stores_role_enum(role: Role) -> None:
    """TenantMembership.role must hold a Role enum member, not a bare string."""
    m = TenantMembership(user_id="uid", tenant_slug="t", role=role)
    assert m.role is role
    assert isinstance(m.role, Role)


def test_tenant_membership_role_value_is_string() -> None:
    """The role stored on TenantMembership must still behave as a string (StrEnum)."""
    m = TenantMembership(user_id="uid", tenant_slug="t", role=Role.ADMIN)
    assert m.role == "ADMIN"


def test_tenant_membership_fields_stored_correctly() -> None:
    """All three TenantMembership fields must be stored verbatim."""
    m = TenantMembership(user_id="user-42", tenant_slug="acme", role=Role.OWNER)
    assert m.user_id == "user-42"
    assert m.tenant_slug == "acme"
    assert m.role == Role.OWNER


def test_tenant_membership_equality_by_value() -> None:
    """Two TenantMembership instances with identical fields must compare as equal."""
    m1 = TenantMembership(user_id="u", tenant_slug="t", role=Role.MEMBER)
    m2 = TenantMembership(user_id="u", tenant_slug="t", role=Role.MEMBER)
    assert m1 == m2


def test_tenant_membership_inequality_when_role_differs() -> None:
    """Memberships for the same user/tenant but different roles must not be equal."""
    m1 = TenantMembership(user_id="u", tenant_slug="t", role=Role.ADMIN)
    m2 = TenantMembership(user_id="u", tenant_slug="t", role=Role.VIEWER)
    assert m1 != m2
