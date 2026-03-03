"""Integration tests for infrastructure repository implementations.

All tests use in-memory SQLite engines (``sqlite:///:memory:``), so there is
no filesystem I/O.  Each test function receives a freshly created engine with
the relevant schema already applied, making every test fully isolated.

Covered:
- SQLiteTenantRepository  (get_by_slug, create, list_active)
- SQLiteUserRepository    (get_by_id, get_by_email, create, DuplicateEmailError)
- SQLiteMembershipRepository (get_membership, assign_role upsert, list_members)
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine
from sqlmodel import SQLModel, create_engine

from src.domain.entities import Role, Tenant, TenantMembership, User
from src.domain.exceptions import DuplicateEmailError
from src.infrastructure.models.membership_model import (
    MembershipModel,
)
from src.infrastructure.models.tenant_model import TenantModel
from src.infrastructure.models.user_model import UserModel
from src.infrastructure.repositories.membership_repository import SQLiteMembershipRepository
from src.infrastructure.repositories.tenant_repository import SQLiteTenantRepository
from src.infrastructure.repositories.user_repository import SQLiteUserRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXED_TS = datetime(2024, 6, 15, 10, 0, 0, tzinfo=UTC)


def _make_registry_engine() -> Engine:
    """In-memory SQLite engine with the tenants table created."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine, tables=[TenantModel.__table__])
    return engine


def _make_tenant_engine() -> Engine:
    """In-memory SQLite engine with users and memberships tables created."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(
        engine, tables=[UserModel.__table__, MembershipModel.__table__]
    )
    return engine


def _acme_tenant() -> Tenant:
    return Tenant(slug="acme", name="Acme Corp", is_active=True, created_at=_FIXED_TS)


def _inactive_tenant() -> Tenant:
    return Tenant(slug="old", name="Old Corp", is_active=False, created_at=_FIXED_TS)


def _alice() -> User:
    return User(
        id="00000000-0000-0000-0000-000000000001",
        email="alice@example.com",
        hashed_password="$2b$12$hashed_alice",
        is_active=True,
    )


def _bob() -> User:
    return User(
        id="00000000-0000-0000-0000-000000000002",
        email="bob@example.com",
        hashed_password="$2b$12$hashed_bob",
        is_active=True,
    )


def _membership(
    user_id: str, tenant_slug: str = "acme", role: Role = Role.MEMBER
) -> TenantMembership:
    return TenantMembership(user_id=user_id, tenant_slug=tenant_slug, role=role)


# ---------------------------------------------------------------------------
# SQLiteTenantRepository
# ---------------------------------------------------------------------------


class TestSQLiteTenantRepositoryGetBySlug:
    def test_returns_none_when_slug_absent(self) -> None:
        repo = SQLiteTenantRepository(_make_registry_engine())
        assert repo.get_by_slug("nonexistent") is None

    def test_returns_entity_when_slug_exists(self) -> None:
        engine = _make_registry_engine()
        repo = SQLiteTenantRepository(engine)
        repo.create(_acme_tenant())
        result = repo.get_by_slug("acme")
        assert result is not None
        assert result.slug == "acme"

    def test_returns_domain_entity_not_orm_model(self) -> None:
        engine = _make_registry_engine()
        repo = SQLiteTenantRepository(engine)
        repo.create(_acme_tenant())
        result = repo.get_by_slug("acme")
        assert isinstance(result, Tenant)

    def test_all_fields_match(self) -> None:
        engine = _make_registry_engine()
        repo = SQLiteTenantRepository(engine)
        original = _acme_tenant()
        repo.create(original)
        result = repo.get_by_slug("acme")
        assert result is not None
        assert result.slug == original.slug
        assert result.name == original.name
        assert result.is_active == original.is_active

    def test_inactive_tenant_is_retrievable_by_slug(self) -> None:
        engine = _make_registry_engine()
        repo = SQLiteTenantRepository(engine)
        repo.create(_inactive_tenant())
        result = repo.get_by_slug("old")
        assert result is not None
        assert result.is_active is False


class TestSQLiteTenantRepositoryCreate:
    def test_create_returns_domain_entity(self) -> None:
        repo = SQLiteTenantRepository(_make_registry_engine())
        result = repo.create(_acme_tenant())
        assert isinstance(result, Tenant)

    def test_created_entity_has_correct_slug(self) -> None:
        repo = SQLiteTenantRepository(_make_registry_engine())
        result = repo.create(_acme_tenant())
        assert result.slug == "acme"

    def test_created_entity_is_persisted(self) -> None:
        engine = _make_registry_engine()
        repo = SQLiteTenantRepository(engine)
        repo.create(_acme_tenant())
        fetched = repo.get_by_slug("acme")
        assert fetched is not None

    def test_create_multiple_distinct_tenants(self) -> None:
        engine = _make_registry_engine()
        repo = SQLiteTenantRepository(engine)
        repo.create(_acme_tenant())
        repo.create(_inactive_tenant())
        assert repo.get_by_slug("acme") is not None
        assert repo.get_by_slug("old") is not None

    def test_created_entity_name_matches(self) -> None:
        repo = SQLiteTenantRepository(_make_registry_engine())
        result = repo.create(Tenant(slug="x", name="X Corp", created_at=_FIXED_TS))
        assert result.name == "X Corp"


class TestSQLiteTenantRepositoryListActive:
    def test_empty_db_returns_empty_list(self) -> None:
        repo = SQLiteTenantRepository(_make_registry_engine())
        assert repo.list_active() == []

    def test_only_active_tenants_returned(self) -> None:
        engine = _make_registry_engine()
        repo = SQLiteTenantRepository(engine)
        repo.create(_acme_tenant())
        repo.create(_inactive_tenant())
        active = repo.list_active()
        slugs = [t.slug for t in active]
        assert "acme" in slugs
        assert "old" not in slugs

    def test_returns_list_of_domain_entities(self) -> None:
        engine = _make_registry_engine()
        repo = SQLiteTenantRepository(engine)
        repo.create(_acme_tenant())
        active = repo.list_active()
        assert all(isinstance(t, Tenant) for t in active)

    def test_multiple_active_tenants_all_returned(self) -> None:
        engine = _make_registry_engine()
        repo = SQLiteTenantRepository(engine)
        for i in range(3):
            repo.create(Tenant(slug=f"slug-{i}", name=f"Tenant {i}", created_at=_FIXED_TS))
        active = repo.list_active()
        assert len(active) == 3

    def test_all_inactive_returns_empty_list(self) -> None:
        engine = _make_registry_engine()
        repo = SQLiteTenantRepository(engine)
        repo.create(_inactive_tenant())
        assert repo.list_active() == []


# ---------------------------------------------------------------------------
# SQLiteUserRepository
# ---------------------------------------------------------------------------


class TestSQLiteUserRepositoryGetById:
    def test_returns_none_when_id_absent(self) -> None:
        repo = SQLiteUserRepository(_make_tenant_engine())
        assert repo.get_by_id("00000000-0000-0000-0000-000000000099") is None

    def test_returns_entity_when_id_exists(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteUserRepository(engine)
        repo.create(_alice())
        result = repo.get_by_id("00000000-0000-0000-0000-000000000001")
        assert result is not None
        assert result.id == "00000000-0000-0000-0000-000000000001"

    def test_returns_domain_entity_not_orm_model(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteUserRepository(engine)
        repo.create(_alice())
        result = repo.get_by_id("00000000-0000-0000-0000-000000000001")
        assert isinstance(result, User)

    def test_all_fields_match(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteUserRepository(engine)
        original = _alice()
        repo.create(original)
        result = repo.get_by_id(original.id)
        assert result is not None
        assert result.id == original.id
        assert result.email == original.email
        assert result.hashed_password == original.hashed_password
        assert result.is_active == original.is_active


class TestSQLiteUserRepositoryGetByEmail:
    def test_returns_none_when_email_absent(self) -> None:
        repo = SQLiteUserRepository(_make_tenant_engine())
        assert repo.get_by_email("ghost@example.com") is None

    def test_returns_entity_when_email_exists(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteUserRepository(engine)
        repo.create(_alice())
        result = repo.get_by_email("alice@example.com")
        assert result is not None
        assert result.email == "alice@example.com"

    def test_returns_domain_entity_not_orm_model(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteUserRepository(engine)
        repo.create(_alice())
        result = repo.get_by_email("alice@example.com")
        assert isinstance(result, User)

    def test_email_lookup_is_case_sensitive(self) -> None:
        """SQLite LIKE is case-insensitive but equality (==) is case-sensitive."""
        engine = _make_tenant_engine()
        repo = SQLiteUserRepository(engine)
        repo.create(_alice())
        result = repo.get_by_email("Alice@Example.COM")
        assert result is None

    def test_does_not_return_wrong_user(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteUserRepository(engine)
        repo.create(_alice())
        repo.create(_bob())
        result = repo.get_by_email("bob@example.com")
        assert result is not None
        assert result.email == "bob@example.com"
        assert result.id != _alice().id


class TestSQLiteUserRepositoryCreate:
    def test_create_returns_domain_entity(self) -> None:
        repo = SQLiteUserRepository(_make_tenant_engine())
        result = repo.create(_alice())
        assert isinstance(result, User)

    def test_created_entity_is_persisted(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteUserRepository(engine)
        repo.create(_alice())
        result = repo.get_by_id("00000000-0000-0000-0000-000000000001")
        assert result is not None

    def test_duplicate_email_raises_duplicate_email_error(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteUserRepository(engine)
        repo.create(_alice())
        duplicate = User(
            id="00000000-0000-0000-0000-000000000099",
            email="alice@example.com",  # same email, different id
            hashed_password="other_hash",
        )
        with pytest.raises(DuplicateEmailError) as exc_info:
            repo.create(duplicate)
        assert exc_info.value.email == "alice@example.com"

    def test_duplicate_email_error_is_domain_error(self) -> None:
        from src.domain.exceptions import DomainError

        engine = _make_tenant_engine()
        repo = SQLiteUserRepository(engine)
        repo.create(_alice())
        duplicate = User(
            id="00000000-0000-0000-0000-000000000099",
            email="alice@example.com",
            hashed_password="other_hash",
        )
        with pytest.raises(DomainError):
            repo.create(duplicate)

    def test_create_after_duplicate_error_succeeds_with_different_email(self) -> None:
        """Session must not be left in a bad state after IntegrityError rollback."""
        engine = _make_tenant_engine()
        repo = SQLiteUserRepository(engine)
        repo.create(_alice())
        duplicate = User(
            id="00000000-0000-0000-0000-000000000099",
            email="alice@example.com",
            hashed_password="other_hash",
        )
        with pytest.raises(DuplicateEmailError):
            repo.create(duplicate)
        # A subsequent create with a different email must succeed.
        result = repo.create(_bob())
        assert result.email == "bob@example.com"

    def test_created_entity_fields_match(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteUserRepository(engine)
        original = _alice()
        result = repo.create(original)
        assert result.id == original.id
        assert result.email == original.email
        assert result.hashed_password == original.hashed_password
        assert result.is_active == original.is_active


class TestSQLiteUserRepositoryDeleteById:
    def test_delete_existing_user_returns_true(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteUserRepository(engine)
        repo.create(_alice())
        result = repo.delete_by_id("00000000-0000-0000-0000-000000000001")
        assert result is True

    def test_delete_nonexistent_user_returns_false(self) -> None:
        repo = SQLiteUserRepository(_make_tenant_engine())
        result = repo.delete_by_id("00000000-0000-0000-0000-000000000099")
        assert result is False

    def test_deleted_user_is_not_retrievable_by_id(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteUserRepository(engine)
        repo.create(_alice())
        repo.delete_by_id("00000000-0000-0000-0000-000000000001")
        assert repo.get_by_id("00000000-0000-0000-0000-000000000001") is None

    def test_deleted_user_is_not_retrievable_by_email(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteUserRepository(engine)
        repo.create(_alice())
        repo.delete_by_id("00000000-0000-0000-0000-000000000001")
        assert repo.get_by_email("alice@example.com") is None

    def test_delete_does_not_affect_other_users(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteUserRepository(engine)
        repo.create(_alice())
        repo.create(_bob())
        repo.delete_by_id("00000000-0000-0000-0000-000000000001")
        assert repo.get_by_id("00000000-0000-0000-0000-000000000002") is not None

    def test_double_delete_returns_false_on_second_call(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteUserRepository(engine)
        repo.create(_alice())
        repo.delete_by_id("00000000-0000-0000-0000-000000000001")
        assert repo.delete_by_id("00000000-0000-0000-0000-000000000001") is False


# ---------------------------------------------------------------------------
# SQLiteMembershipRepository
# ---------------------------------------------------------------------------


class TestSQLiteMembershipRepositoryGetMembership:
    def test_returns_none_when_absent(self) -> None:
        repo = SQLiteMembershipRepository(_make_tenant_engine())
        assert repo.get_membership("uid-x", "acme") is None

    def test_returns_entity_when_present(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteMembershipRepository(engine)
        repo.assign_role(_membership("uid-1"))
        result = repo.get_membership("uid-1", "acme")
        assert result is not None
        assert result.user_id == "uid-1"
        assert result.tenant_slug == "acme"

    def test_returns_domain_entity_not_orm_model(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteMembershipRepository(engine)
        repo.assign_role(_membership("uid-1"))
        result = repo.get_membership("uid-1", "acme")
        assert isinstance(result, TenantMembership)

    def test_all_fields_match(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteMembershipRepository(engine)
        original = TenantMembership(user_id="uid-1", tenant_slug="acme", role=Role.ADMIN)
        repo.assign_role(original)
        result = repo.get_membership("uid-1", "acme")
        assert result is not None
        assert result.user_id == original.user_id
        assert result.tenant_slug == original.tenant_slug
        assert result.role is original.role

    def test_different_slug_returns_none(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteMembershipRepository(engine)
        repo.assign_role(_membership("uid-1", tenant_slug="acme"))
        assert repo.get_membership("uid-1", "other") is None

    def test_different_user_id_returns_none(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteMembershipRepository(engine)
        repo.assign_role(_membership("uid-1"))
        assert repo.get_membership("uid-2", "acme") is None


class TestSQLiteMembershipRepositoryAssignRole:
    def test_assign_returns_domain_entity(self) -> None:
        repo = SQLiteMembershipRepository(_make_tenant_engine())
        result = repo.assign_role(_membership("uid-1"))
        assert isinstance(result, TenantMembership)

    def test_assign_new_role_is_persisted(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteMembershipRepository(engine)
        repo.assign_role(_membership("uid-1", role=Role.VIEWER))
        result = repo.get_membership("uid-1", "acme")
        assert result is not None
        assert result.role is Role.VIEWER

    def test_assign_role_upserts_existing_membership(self) -> None:
        """Second assign_role call must update, not insert a duplicate row."""
        engine = _make_tenant_engine()
        repo = SQLiteMembershipRepository(engine)
        repo.assign_role(_membership("uid-1", role=Role.MEMBER))
        repo.assign_role(_membership("uid-1", role=Role.ADMIN))
        result = repo.get_membership("uid-1", "acme")
        assert result is not None
        assert result.role is Role.ADMIN

    def test_upsert_does_not_create_duplicate_rows(self) -> None:
        """After two assigns with same key, list_members must return only one entry."""
        engine = _make_tenant_engine()
        repo = SQLiteMembershipRepository(engine)
        repo.assign_role(_membership("uid-1", role=Role.MEMBER))
        repo.assign_role(_membership("uid-1", role=Role.OWNER))
        members = repo.list_members("acme")
        user_ids = [m.user_id for m in members]
        assert user_ids.count("uid-1") == 1

    def test_returned_entity_has_updated_role(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteMembershipRepository(engine)
        repo.assign_role(_membership("uid-1", role=Role.VIEWER))
        result = repo.assign_role(_membership("uid-1", role=Role.OWNER))
        assert result.role is Role.OWNER

    def test_all_roles_can_be_assigned(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteMembershipRepository(engine)
        for i, role in enumerate(Role):
            uid = f"uid-{i}"
            repo.assign_role(_membership(uid, role=role))
            result = repo.get_membership(uid, "acme")
            assert result is not None
            assert result.role is role


class TestSQLiteMembershipRepositoryListMembers:
    def test_empty_returns_empty_list(self) -> None:
        repo = SQLiteMembershipRepository(_make_tenant_engine())
        assert repo.list_members("acme") == []

    def test_returns_members_of_requested_tenant_only(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteMembershipRepository(engine)
        repo.assign_role(_membership("uid-1", tenant_slug="acme"))
        repo.assign_role(_membership("uid-2", tenant_slug="beta"))
        members = repo.list_members("acme")
        assert len(members) == 1
        assert members[0].user_id == "uid-1"

    def test_returns_list_of_domain_entities(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteMembershipRepository(engine)
        repo.assign_role(_membership("uid-1"))
        members = repo.list_members("acme")
        assert all(isinstance(m, TenantMembership) for m in members)

    def test_multiple_members_all_returned(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteMembershipRepository(engine)
        for i in range(4):
            repo.assign_role(_membership(f"uid-{i}"))
        members = repo.list_members("acme")
        assert len(members) == 4

    def test_tenant_with_no_members_returns_empty(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteMembershipRepository(engine)
        repo.assign_role(_membership("uid-1", tenant_slug="other"))
        assert repo.list_members("acme") == []

    def test_all_roles_preserved_in_list(self) -> None:
        engine = _make_tenant_engine()
        repo = SQLiteMembershipRepository(engine)
        role_map = {}
        for i, role in enumerate(Role):
            uid = f"uid-{i}"
            repo.assign_role(_membership(uid, role=role))
            role_map[uid] = role
        members = repo.list_members("acme")
        for m in members:
            assert m.role is role_map[m.user_id]


# ---------------------------------------------------------------------------
# database.py engine factories
# ---------------------------------------------------------------------------


class TestCreateRegistryEngine:
    def test_engine_is_created(self, tmp_path: pytest.TempPathFactory) -> None:
        from src.infrastructure.database import create_registry_engine

        db_file = str(tmp_path / "sub" / "registry.db")  # type: ignore[operator]
        engine = create_registry_engine(db_file)
        assert engine is not None

    def test_parent_directory_is_created(self, tmp_path: pytest.TempPathFactory) -> None:
        from pathlib import Path

        from src.infrastructure.database import create_registry_engine

        db_file = str(tmp_path / "deep" / "nested" / "registry.db")  # type: ignore[operator]
        create_registry_engine(db_file)
        assert Path(db_file).parent.exists()

    def test_engine_url_is_sqlite(self, tmp_path: pytest.TempPathFactory) -> None:
        from src.infrastructure.database import create_registry_engine

        db_file = str(tmp_path / "registry.db")  # type: ignore[operator]
        engine = create_registry_engine(db_file)
        assert "sqlite" in str(engine.url)

    def test_engine_allows_ddl(self, tmp_path: pytest.TempPathFactory) -> None:
        """Verify tables can be created against the returned engine."""
        from src.infrastructure.database import create_registry_engine

        db_file = str(tmp_path / "registry.db")  # type: ignore[operator]
        engine = create_registry_engine(db_file)
        SQLModel.metadata.create_all(engine, tables=[TenantModel.__table__])
        repo = SQLiteTenantRepository(engine)
        assert repo.list_active() == []


class TestCreateTenantEngine:
    def test_engine_is_created(self, tmp_path: pytest.TempPathFactory) -> None:
        from src.infrastructure.database import create_tenant_engine

        engine = create_tenant_engine(str(tmp_path), "acme")  # type: ignore[arg-type]
        assert engine is not None

    def test_db_file_path_contains_slug(self, tmp_path: pytest.TempPathFactory) -> None:
        from src.infrastructure.database import create_tenant_engine

        engine = create_tenant_engine(str(tmp_path), "my-tenant")  # type: ignore[arg-type]
        assert "my-tenant" in str(engine.url)

    def test_tenant_directory_is_created(self, tmp_path: pytest.TempPathFactory) -> None:
        from pathlib import Path

        from src.infrastructure.database import create_tenant_engine

        db_dir = str(tmp_path / "tenants")  # type: ignore[operator]
        create_tenant_engine(db_dir, "acme")
        assert Path(db_dir).exists()

    def test_engine_url_is_sqlite(self, tmp_path: pytest.TempPathFactory) -> None:
        from src.infrastructure.database import create_tenant_engine

        engine = create_tenant_engine(str(tmp_path), "acme")  # type: ignore[arg-type]
        assert "sqlite" in str(engine.url)

    def test_different_slugs_produce_different_urls(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        from src.infrastructure.database import create_tenant_engine

        e1 = create_tenant_engine(str(tmp_path), "alpha")  # type: ignore[arg-type]
        e2 = create_tenant_engine(str(tmp_path), "beta")  # type: ignore[arg-type]
        assert str(e1.url) != str(e2.url)

    def test_engine_allows_ddl(self, tmp_path: pytest.TempPathFactory) -> None:
        """Verify tables can be created against the returned engine."""
        from src.infrastructure.database import create_tenant_engine

        engine = create_tenant_engine(str(tmp_path), "acme")  # type: ignore[arg-type]
        SQLModel.metadata.create_all(
            engine, tables=[UserModel.__table__, MembershipModel.__table__]
        )
        repo = SQLiteUserRepository(engine)
        assert repo.get_by_email("nobody@example.com") is None
