"""Unit tests for infrastructure ORM models and their mapper functions.

Each test covers the round-trip identity: entity → model → entity must
produce an object equal to the original.  Individual field mappings are
verified separately so a single wrong field produces a clear failure.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.domain.entities import Role, Tenant, TenantMembership, User
from src.infrastructure.models.membership_model import (
    MembershipModel,
    membership_entity_to_model,
    membership_model_to_entity,
)
from src.infrastructure.models.tenant_model import (
    TenantModel,
    tenant_entity_to_model,
    tenant_model_to_entity,
)
from src.infrastructure.models.user_model import (
    UserModel,
    user_entity_to_model,
    user_model_to_entity,
)

# ---------------------------------------------------------------------------
# TenantModel
# ---------------------------------------------------------------------------


class TestTenantModelToEntity:
    def _make_model(self) -> TenantModel:
        return TenantModel(
            slug="acme",
            name="Acme Corp",
            is_active=True,
            created_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC),
        )

    def test_slug_is_mapped(self) -> None:
        entity = tenant_model_to_entity(self._make_model())
        assert entity.slug == "acme"

    def test_name_is_mapped(self) -> None:
        entity = tenant_model_to_entity(self._make_model())
        assert entity.name == "Acme Corp"

    def test_is_active_is_mapped(self) -> None:
        model = self._make_model()
        model.is_active = False
        entity = tenant_model_to_entity(model)
        assert entity.is_active is False

    def test_created_at_is_mapped(self) -> None:
        model = self._make_model()
        entity = tenant_model_to_entity(model)
        assert entity.created_at == datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)

    def test_returns_tenant_type(self) -> None:
        entity = tenant_model_to_entity(self._make_model())
        assert isinstance(entity, Tenant)


class TestTenantEntityToModel:
    def _make_entity(self) -> Tenant:
        return Tenant(
            slug="beta",
            name="Beta Inc",
            is_active=True,
            created_at=datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC),
        )

    def test_slug_is_mapped(self) -> None:
        model = tenant_entity_to_model(self._make_entity())
        assert model.slug == "beta"

    def test_name_is_mapped(self) -> None:
        model = tenant_entity_to_model(self._make_entity())
        assert model.name == "Beta Inc"

    def test_is_active_is_mapped(self) -> None:
        entity = self._make_entity()
        entity.is_active = False
        model = tenant_entity_to_model(entity)
        assert model.is_active is False

    def test_created_at_is_mapped(self) -> None:
        model = tenant_entity_to_model(self._make_entity())
        assert model.created_at == datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)

    def test_returns_tenant_model_type(self) -> None:
        model = tenant_entity_to_model(self._make_entity())
        assert isinstance(model, TenantModel)


class TestTenantRoundTrip:
    def test_entity_model_entity_round_trip(self) -> None:
        original = Tenant(
            slug="gamma",
            name="Gamma Ltd",
            is_active=True,
            created_at=datetime(2026, 3, 2, 8, 30, 0, tzinfo=UTC),
        )
        recovered = tenant_model_to_entity(tenant_entity_to_model(original))
        assert recovered == original

    def test_model_entity_model_round_trip(self) -> None:
        original = TenantModel(
            slug="delta",
            name="Delta LLC",
            is_active=False,
            created_at=datetime(2023, 11, 20, 17, 45, 0, tzinfo=UTC),
        )
        recovered = tenant_entity_to_model(tenant_model_to_entity(original))
        assert recovered.slug == original.slug
        assert recovered.name == original.name
        assert recovered.is_active == original.is_active
        assert recovered.created_at == original.created_at


# ---------------------------------------------------------------------------
# UserModel
# ---------------------------------------------------------------------------


class TestUserModelToEntity:
    def _make_model(self) -> UserModel:
        return UserModel(
            id="00000000-0000-0000-0000-000000000001",
            email="alice@example.com",
            hashed_password="$2b$12$hashed",
            is_active=True,
        )

    def test_id_is_mapped(self) -> None:
        entity = user_model_to_entity(self._make_model())
        assert entity.id == "00000000-0000-0000-0000-000000000001"

    def test_email_is_mapped(self) -> None:
        entity = user_model_to_entity(self._make_model())
        assert entity.email == "alice@example.com"

    def test_hashed_password_is_mapped(self) -> None:
        entity = user_model_to_entity(self._make_model())
        assert entity.hashed_password == "$2b$12$hashed"

    def test_is_active_is_mapped(self) -> None:
        model = self._make_model()
        model.is_active = False
        entity = user_model_to_entity(model)
        assert entity.is_active is False

    def test_returns_user_type(self) -> None:
        entity = user_model_to_entity(self._make_model())
        assert isinstance(entity, User)


class TestUserEntityToModel:
    def _make_entity(self) -> User:
        return User(
            id="00000000-0000-0000-0000-000000000002",
            email="bob@example.com",
            hashed_password="$2b$12$anotherhash",
            is_active=True,
        )

    def test_id_is_mapped(self) -> None:
        model = user_entity_to_model(self._make_entity())
        assert model.id == "00000000-0000-0000-0000-000000000002"

    def test_email_is_mapped(self) -> None:
        model = user_entity_to_model(self._make_entity())
        assert model.email == "bob@example.com"

    def test_hashed_password_is_mapped(self) -> None:
        model = user_entity_to_model(self._make_entity())
        assert model.hashed_password == "$2b$12$anotherhash"

    def test_is_active_is_mapped(self) -> None:
        entity = self._make_entity()
        entity.is_active = False
        model = user_entity_to_model(entity)
        assert model.is_active is False

    def test_returns_user_model_type(self) -> None:
        model = user_entity_to_model(self._make_entity())
        assert isinstance(model, UserModel)


class TestUserRoundTrip:
    def test_entity_model_entity_round_trip(self) -> None:
        original = User(
            id="00000000-0000-0000-0000-000000000003",
            email="carol@example.com",
            hashed_password="$2b$12$carols_hash",
            is_active=True,
        )
        recovered = user_model_to_entity(user_entity_to_model(original))
        assert recovered == original

    def test_model_entity_model_round_trip(self) -> None:
        original = UserModel(
            id="00000000-0000-0000-0000-000000000004",
            email="dan@example.com",
            hashed_password="$2b$12$dans_hash",
            is_active=False,
        )
        recovered = user_entity_to_model(user_model_to_entity(original))
        assert recovered.id == original.id
        assert recovered.email == original.email
        assert recovered.hashed_password == original.hashed_password
        assert recovered.is_active == original.is_active


# ---------------------------------------------------------------------------
# MembershipModel
# ---------------------------------------------------------------------------


class TestMembershipModelToEntity:
    def _make_model(self, role: str = "OWNER") -> MembershipModel:
        return MembershipModel(
            user_id="00000000-0000-0000-0000-000000000010",
            tenant_slug="acme",
            role=role,
        )

    def test_user_id_is_mapped(self) -> None:
        entity = membership_model_to_entity(self._make_model())
        assert entity.user_id == "00000000-0000-0000-0000-000000000010"

    def test_tenant_slug_is_mapped(self) -> None:
        entity = membership_model_to_entity(self._make_model())
        assert entity.tenant_slug == "acme"

    def test_role_owner_is_mapped_to_enum(self) -> None:
        entity = membership_model_to_entity(self._make_model("OWNER"))
        assert entity.role is Role.OWNER

    def test_role_admin_is_mapped_to_enum(self) -> None:
        entity = membership_model_to_entity(self._make_model("ADMIN"))
        assert entity.role is Role.ADMIN

    def test_role_member_is_mapped_to_enum(self) -> None:
        entity = membership_model_to_entity(self._make_model("MEMBER"))
        assert entity.role is Role.MEMBER

    def test_role_viewer_is_mapped_to_enum(self) -> None:
        entity = membership_model_to_entity(self._make_model("VIEWER"))
        assert entity.role is Role.VIEWER

    def test_invalid_role_string_raises_value_error(self) -> None:
        model = self._make_model("SUPERUSER")
        with pytest.raises(ValueError):
            membership_model_to_entity(model)

    def test_returns_tenant_membership_type(self) -> None:
        entity = membership_model_to_entity(self._make_model())
        assert isinstance(entity, TenantMembership)


class TestMembershipEntityToModel:
    def _make_entity(self, role: Role = Role.MEMBER) -> TenantMembership:
        return TenantMembership(
            user_id="00000000-0000-0000-0000-000000000011",
            tenant_slug="beta",
            role=role,
        )

    def test_user_id_is_mapped(self) -> None:
        model = membership_entity_to_model(self._make_entity())
        assert model.user_id == "00000000-0000-0000-0000-000000000011"

    def test_tenant_slug_is_mapped(self) -> None:
        model = membership_entity_to_model(self._make_entity())
        assert model.tenant_slug == "beta"

    def test_role_enum_stored_as_string(self) -> None:
        model = membership_entity_to_model(self._make_entity(Role.ADMIN))
        assert model.role == "ADMIN"
        assert isinstance(model.role, str)

    def test_all_roles_stored_as_their_value(self) -> None:
        for role in Role:
            model = membership_entity_to_model(self._make_entity(role))
            assert model.role == role.value

    def test_returns_membership_model_type(self) -> None:
        model = membership_entity_to_model(self._make_entity())
        assert isinstance(model, MembershipModel)


class TestMembershipRoundTrip:
    def test_entity_model_entity_round_trip(self) -> None:
        original = TenantMembership(
            user_id="00000000-0000-0000-0000-000000000012",
            tenant_slug="gamma",
            role=Role.OWNER,
        )
        recovered = membership_model_to_entity(membership_entity_to_model(original))
        assert recovered == original

    def test_model_entity_model_round_trip(self) -> None:
        original = MembershipModel(
            user_id="00000000-0000-0000-0000-000000000013",
            tenant_slug="delta",
            role="VIEWER",
        )
        recovered = membership_entity_to_model(membership_model_to_entity(original))
        assert recovered.user_id == original.user_id
        assert recovered.tenant_slug == original.tenant_slug
        assert recovered.role == original.role

    @pytest.mark.parametrize("role", list(Role))
    def test_all_roles_survive_round_trip(self, role: Role) -> None:
        original = TenantMembership(
            user_id="00000000-0000-0000-0000-000000000099",
            tenant_slug="omega",
            role=role,
        )
        recovered = membership_model_to_entity(membership_entity_to_model(original))
        assert recovered.role is role


# ---------------------------------------------------------------------------
# __init__.py public exports
# ---------------------------------------------------------------------------


class TestModelsPackageExports:
    def test_tenant_model_exported(self) -> None:
        from src.infrastructure.models import TenantModel as T

        assert T is TenantModel

    def test_user_model_exported(self) -> None:
        from src.infrastructure.models import UserModel as U

        assert U is UserModel

    def test_membership_model_exported(self) -> None:
        from src.infrastructure.models import MembershipModel as M

        assert M is MembershipModel
