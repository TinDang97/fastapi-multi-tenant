"""Unit tests for scripts.migrate_all_tenants and scripts.create_tenant.

All subprocess calls and Alembic invocations are patched so the tests run
without a real SQLite file or ``uv`` binary.  The registry/tenant databases
use in-memory SQLite engines to stay fast and isolated.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import Engine
from sqlmodel import SQLModel, create_engine

from src.domain.entities import Role, Tenant
from src.infrastructure.models.membership_model import MembershipModel
from src.infrastructure.models.tenant_model import TenantModel
from src.infrastructure.models.user_model import UserModel
from src.infrastructure.repositories.membership_repository import SQLiteMembershipRepository
from src.infrastructure.repositories.tenant_repository import SQLiteTenantRepository
from src.infrastructure.repositories.user_repository import SQLiteUserRepository

# ---------------------------------------------------------------------------
# Engine helpers
# ---------------------------------------------------------------------------

_CONNECT = {"check_same_thread": False}
_TENANT_TABLES = [UserModel.__table__, MembershipModel.__table__]


def _disk_registry_engine(db_path: str) -> Engine:
    engine = create_engine(f"sqlite:///{db_path}", connect_args=_CONNECT)
    SQLModel.metadata.create_all(engine, tables=[TenantModel.__table__])
    return engine


def _disk_tenant_engine(db_path: str) -> Engine:
    engine = create_engine(f"sqlite:///{db_path}", connect_args=_CONNECT)
    SQLModel.metadata.create_all(engine, tables=_TENANT_TABLES)
    return engine


# ---------------------------------------------------------------------------
# scripts.migrate_all_tenants — _read_active_slugs
# ---------------------------------------------------------------------------


class TestReadActiveSlugs:
    def test_returns_empty_list_when_no_active_tenants(self, tmp_path: Path) -> None:
        from scripts.migrate_all_tenants import _read_active_slugs

        db_path = str(tmp_path / "registry.db")
        engine = _disk_registry_engine(db_path)
        SQLiteTenantRepository(engine).create(
            Tenant(slug="old", name="Old Corp", is_active=False)
        )
        engine.dispose()

        assert _read_active_slugs(db_path) == []

    def test_returns_active_slugs_only(self, tmp_path: Path) -> None:
        from scripts.migrate_all_tenants import _read_active_slugs

        db_path = str(tmp_path / "registry.db")
        engine = _disk_registry_engine(db_path)
        repo = SQLiteTenantRepository(engine)
        repo.create(Tenant(slug="acme", name="Acme Corp", is_active=True))
        repo.create(Tenant(slug="beta", name="Beta Corp", is_active=True))
        repo.create(Tenant(slug="gone", name="Gone Corp", is_active=False))
        engine.dispose()

        result = _read_active_slugs(db_path)
        assert set(result) == {"acme", "beta"}

    def test_exits_1_when_registry_db_missing(self) -> None:
        from scripts.migrate_all_tenants import _read_active_slugs

        with pytest.raises(SystemExit) as exc_info:
            _read_active_slugs("/nonexistent/path/registry.db")
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# scripts.migrate_all_tenants — _migrate_tenant
# ---------------------------------------------------------------------------


class TestMigrateTenant:
    def test_returns_true_on_success(self) -> None:
        from scripts.migrate_all_tenants import _migrate_tenant

        result = MagicMock()
        result.returncode = 0
        with patch("scripts.migrate_all_tenants.subprocess.run", return_value=result):
            assert _migrate_tenant("/usr/bin/uv", "acme", "data/tenants") is True

    def test_returns_false_on_failure(self) -> None:
        from scripts.migrate_all_tenants import _migrate_tenant

        result = MagicMock()
        result.returncode = 1
        with patch("scripts.migrate_all_tenants.subprocess.run", return_value=result):
            assert _migrate_tenant("/usr/bin/uv", "acme", "data/tenants") is False

    def test_passes_tenant_slug_in_env(self) -> None:
        from scripts.migrate_all_tenants import _migrate_tenant

        result = MagicMock()
        result.returncode = 0
        with patch(
            "scripts.migrate_all_tenants.subprocess.run", return_value=result
        ) as mock_run:
            _migrate_tenant("/usr/bin/uv", "myslug", "data/tenants")
            assert mock_run.call_args.kwargs["env"]["TENANT_SLUG"] == "myslug"

    def test_passes_tenant_db_dir_in_env(self) -> None:
        from scripts.migrate_all_tenants import _migrate_tenant

        result = MagicMock()
        result.returncode = 0
        with patch(
            "scripts.migrate_all_tenants.subprocess.run", return_value=result
        ) as mock_run:
            _migrate_tenant("/usr/bin/uv", "acme", "/custom/path")
            assert mock_run.call_args.kwargs["env"]["TENANT_DB_DIR"] == "/custom/path"

    def test_subprocess_command_includes_alembic_upgrade_head(self) -> None:
        from scripts.migrate_all_tenants import _migrate_tenant

        result = MagicMock()
        result.returncode = 0
        with patch(
            "scripts.migrate_all_tenants.subprocess.run", return_value=result
        ) as mock_run:
            _migrate_tenant("/usr/bin/uv", "acme", "data/tenants")
            cmd = mock_run.call_args.args[0]
            assert "upgrade" in cmd
            assert "head" in cmd


# ---------------------------------------------------------------------------
# scripts.migrate_all_tenants — main
# ---------------------------------------------------------------------------


class TestMigrateAllTenantsMain:
    def test_no_active_tenants_prints_message_and_returns(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from scripts.migrate_all_tenants import main

        db_path = str(tmp_path / "registry.db")
        engine = _disk_registry_engine(db_path)
        engine.dispose()
        tenant_dir = str(tmp_path / "tenants")

        with (
            patch.dict(
                "os.environ",
                {"REGISTRY_DB_PATH": db_path, "TENANT_DB_DIR": tenant_dir},
            ),
            patch("scripts.migrate_all_tenants.shutil.which", return_value="/usr/bin/uv"),
        ):
            main()  # must not raise or call subprocess

        assert "No active tenants found" in capsys.readouterr().err

    def test_exits_1_when_migration_fails(self, tmp_path: Path) -> None:
        from scripts.migrate_all_tenants import main

        db_path = str(tmp_path / "registry.db")
        engine = _disk_registry_engine(db_path)
        SQLiteTenantRepository(engine).create(Tenant(slug="acme", name="Acme"))
        engine.dispose()
        tenant_dir = str(tmp_path / "tenants")

        failing = MagicMock()
        failing.returncode = 1

        with (
            patch.dict(
                "os.environ",
                {"REGISTRY_DB_PATH": db_path, "TENANT_DB_DIR": tenant_dir},
            ),
            patch("scripts.migrate_all_tenants.shutil.which", return_value="/usr/bin/uv"),
            patch("scripts.migrate_all_tenants.subprocess.run", return_value=failing),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()

        assert exc_info.value.code == 1

    def test_calls_subprocess_once_per_active_tenant(self, tmp_path: Path) -> None:
        from scripts.migrate_all_tenants import main

        db_path = str(tmp_path / "registry.db")
        engine = _disk_registry_engine(db_path)
        repo = SQLiteTenantRepository(engine)
        repo.create(Tenant(slug="alpha", name="Alpha"))
        repo.create(Tenant(slug="beta", name="Beta"))
        engine.dispose()
        tenant_dir = str(tmp_path / "tenants")

        success = MagicMock()
        success.returncode = 0

        with (
            patch.dict(
                "os.environ",
                {"REGISTRY_DB_PATH": db_path, "TENANT_DB_DIR": tenant_dir},
            ),
            patch("scripts.migrate_all_tenants.shutil.which", return_value="/usr/bin/uv"),
            patch(
                "scripts.migrate_all_tenants.subprocess.run", return_value=success
            ) as mock_run,
        ):
            main()

        assert mock_run.call_count == 2

    def test_summary_output_shows_tenant_count(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from scripts.migrate_all_tenants import main

        db_path = str(tmp_path / "registry.db")
        engine = _disk_registry_engine(db_path)
        SQLiteTenantRepository(engine).create(Tenant(slug="acme", name="Acme"))
        engine.dispose()
        tenant_dir = str(tmp_path / "tenants")

        success = MagicMock()
        success.returncode = 0

        with (
            patch.dict(
                "os.environ",
                {"REGISTRY_DB_PATH": db_path, "TENANT_DB_DIR": tenant_dir},
            ),
            patch("scripts.migrate_all_tenants.shutil.which", return_value="/usr/bin/uv"),
            patch("scripts.migrate_all_tenants.subprocess.run", return_value=success),
        ):
            main()

        assert "1 tenant(s)" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# scripts.create_tenant — _register_tenant
# ---------------------------------------------------------------------------


class TestRegisterTenant:
    def test_creates_tenant_in_registry(self, tmp_path: Path) -> None:
        from scripts.create_tenant import _register_tenant

        db_path = str(tmp_path / "registry.db")
        _register_tenant(db_path, "acme", "Acme Corp")

        engine = create_engine(f"sqlite:///{db_path}", connect_args=_CONNECT)
        tenant = SQLiteTenantRepository(engine).get_by_slug("acme")
        assert tenant is not None
        assert tenant.slug == "acme"
        assert tenant.name == "Acme Corp"

    def test_exits_1_on_duplicate_slug(self, tmp_path: Path) -> None:
        from scripts.create_tenant import _register_tenant

        db_path = str(tmp_path / "registry.db")
        _register_tenant(db_path, "acme", "Acme Corp")

        with pytest.raises(SystemExit) as exc_info:
            _register_tenant(db_path, "acme", "Acme Corp Again")
        assert exc_info.value.code == 1

    def test_different_slugs_both_persisted(self, tmp_path: Path) -> None:
        from scripts.create_tenant import _register_tenant

        db_path = str(tmp_path / "registry.db")
        _register_tenant(db_path, "alpha", "Alpha")
        _register_tenant(db_path, "beta", "Beta")

        engine = create_engine(f"sqlite:///{db_path}", connect_args=_CONNECT)
        repo = SQLiteTenantRepository(engine)
        assert repo.get_by_slug("alpha") is not None
        assert repo.get_by_slug("beta") is not None


# ---------------------------------------------------------------------------
# scripts.create_tenant — _run_tenant_migrations
# ---------------------------------------------------------------------------


class TestRunTenantMigrations:
    def test_exits_1_on_alembic_failure(self) -> None:
        from scripts.create_tenant import _run_tenant_migrations

        failing = MagicMock()
        failing.returncode = 1
        with (
            patch("scripts.create_tenant.subprocess.run", return_value=failing),
            pytest.raises(SystemExit) as exc_info,
        ):
            _run_tenant_migrations("/usr/bin/uv", "acme", "data/tenants")
        assert exc_info.value.code == 1

    def test_does_not_exit_on_success(self) -> None:
        from scripts.create_tenant import _run_tenant_migrations

        success = MagicMock()
        success.returncode = 0
        with patch("scripts.create_tenant.subprocess.run", return_value=success):
            _run_tenant_migrations("/usr/bin/uv", "acme", "data/tenants")

    def test_passes_slug_and_dir_in_env(self) -> None:
        from scripts.create_tenant import _run_tenant_migrations

        success = MagicMock()
        success.returncode = 0
        with patch(
            "scripts.create_tenant.subprocess.run", return_value=success
        ) as mock_run:
            _run_tenant_migrations("/usr/bin/uv", "myslug", "/db/tenants")
            env = mock_run.call_args.kwargs["env"]
            assert env["TENANT_SLUG"] == "myslug"
            assert env["TENANT_DB_DIR"] == "/db/tenants"


# ---------------------------------------------------------------------------
# scripts.create_tenant — _create_owner
# ---------------------------------------------------------------------------


class TestCreateOwner:
    def _prep_tenant_db(self, tmp_path: Path, slug: str) -> str:
        """Create tables in a fresh per-tenant .db file and return db_dir."""
        db_dir = str(tmp_path)
        engine = _disk_tenant_engine(f"{db_dir}/{slug}.db")
        engine.dispose()
        return db_dir

    def test_creates_user_in_tenant_db(self, tmp_path: Path) -> None:
        from scripts.create_tenant import _create_owner

        slug = "acme"
        db_dir = self._prep_tenant_db(tmp_path, slug)
        _create_owner(slug, db_dir, "owner@acme.com", "secret123")

        engine = _disk_tenant_engine(f"{db_dir}/{slug}.db")
        user = SQLiteUserRepository(engine).get_by_email("owner@acme.com")
        assert user is not None
        assert user.email == "owner@acme.com"

    def test_creates_owner_role_membership(self, tmp_path: Path) -> None:
        from scripts.create_tenant import _create_owner

        slug = "acme"
        db_dir = self._prep_tenant_db(tmp_path, slug)
        _create_owner(slug, db_dir, "owner@acme.com", "secret123")

        engine = _disk_tenant_engine(f"{db_dir}/{slug}.db")
        user = SQLiteUserRepository(engine).get_by_email("owner@acme.com")
        assert user is not None
        membership = SQLiteMembershipRepository(engine).get_membership(user.id, slug)
        assert membership is not None
        assert membership.role is Role.OWNER

    def test_hashes_password_before_storage(self, tmp_path: Path) -> None:
        from scripts.create_tenant import _create_owner

        from src.infrastructure.services.password_service import PasswordService

        slug = "acme"
        plain = "supersecret"
        db_dir = self._prep_tenant_db(tmp_path, slug)
        _create_owner(slug, db_dir, "owner@acme.com", plain)

        engine = _disk_tenant_engine(f"{db_dir}/{slug}.db")
        user = SQLiteUserRepository(engine).get_by_email("owner@acme.com")
        assert user is not None
        assert user.hashed_password != plain
        assert PasswordService().verify(plain, user.hashed_password)

    def test_exits_1_on_duplicate_email(self, tmp_path: Path) -> None:
        from scripts.create_tenant import _create_owner

        slug = "acme"
        db_dir = self._prep_tenant_db(tmp_path, slug)
        _create_owner(slug, db_dir, "owner@acme.com", "pass1")

        with pytest.raises(SystemExit) as exc_info:
            _create_owner(slug, db_dir, "owner@acme.com", "pass2")
        assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# scripts.create_tenant — main (integration-style, subprocess mocked)
# ---------------------------------------------------------------------------


class TestCreateTenantMain:
    def _run_main(self, args: list[str], env: dict[str, str]) -> None:
        """Invoke create_tenant.main with patched argv and env."""
        from scripts.create_tenant import main

        with patch.object(sys, "argv", ["create_tenant", *args]):
            with patch.dict("os.environ", env):
                main()

    def _stub_tenant_db(self, tenant_db_dir: str, slug: str) -> None:
        """Pre-create tenant tables to simulate a completed Alembic migration."""
        Path(tenant_db_dir).mkdir(parents=True, exist_ok=True)
        engine = _disk_tenant_engine(f"{tenant_db_dir}/{slug}.db")
        engine.dispose()

    def test_full_flow_creates_tenant_user_and_membership(self, tmp_path: Path) -> None:
        registry_db = str(tmp_path / "registry.db")
        tenant_db_dir = str(tmp_path / "tenants")
        self._stub_tenant_db(tenant_db_dir, "acme")

        success = MagicMock()
        success.returncode = 0

        with (
            patch("scripts.create_tenant.shutil.which", return_value="/usr/bin/uv"),
            patch("scripts.create_tenant.subprocess.run", return_value=success),
        ):
            self._run_main(
                [
                    "--slug", "acme",
                    "--email", "owner@acme.com",
                    "--name", "Acme Corp",
                    "--password", "p@ssw0rd",
                ],
                {"REGISTRY_DB_PATH": registry_db, "TENANT_DB_DIR": tenant_db_dir},
            )

        reg_engine = create_engine(f"sqlite:///{registry_db}", connect_args=_CONNECT)
        tenant = SQLiteTenantRepository(reg_engine).get_by_slug("acme")
        assert tenant is not None
        assert tenant.name == "Acme Corp"

        t_engine = create_engine(
            f"sqlite:///{tenant_db_dir}/acme.db", connect_args=_CONNECT
        )
        user = SQLiteUserRepository(t_engine).get_by_email("owner@acme.com")
        assert user is not None
        membership = SQLiteMembershipRepository(t_engine).get_membership(user.id, "acme")
        assert membership is not None
        assert membership.role is Role.OWNER

    def test_exits_1_on_duplicate_slug(self, tmp_path: Path) -> None:
        registry_db = str(tmp_path / "registry.db")
        tenant_db_dir = str(tmp_path / "tenants")
        self._stub_tenant_db(tenant_db_dir, "acme")

        success = MagicMock()
        success.returncode = 0

        with (
            patch("scripts.create_tenant.shutil.which", return_value="/usr/bin/uv"),
            patch("scripts.create_tenant.subprocess.run", return_value=success),
        ):
            self._run_main(
                ["--slug", "acme", "--email", "owner@acme.com"],
                {"REGISTRY_DB_PATH": registry_db, "TENANT_DB_DIR": tenant_db_dir},
            )

        with (
            patch("scripts.create_tenant.shutil.which", return_value="/usr/bin/uv"),
            patch("scripts.create_tenant.subprocess.run", return_value=success),
            pytest.raises(SystemExit) as exc_info,
        ):
            self._run_main(
                ["--slug", "acme", "--email", "other@acme.com"],
                {"REGISTRY_DB_PATH": registry_db, "TENANT_DB_DIR": tenant_db_dir},
            )

        assert exc_info.value.code == 1

    def test_slug_used_as_display_name_when_name_omitted(self, tmp_path: Path) -> None:
        registry_db = str(tmp_path / "registry.db")
        tenant_db_dir = str(tmp_path / "tenants")
        self._stub_tenant_db(tenant_db_dir, "acme")

        success = MagicMock()
        success.returncode = 0

        with (
            patch("scripts.create_tenant.shutil.which", return_value="/usr/bin/uv"),
            patch("scripts.create_tenant.subprocess.run", return_value=success),
        ):
            self._run_main(
                ["--slug", "acme", "--email", "owner@acme.com"],
                {"REGISTRY_DB_PATH": registry_db, "TENANT_DB_DIR": tenant_db_dir},
            )

        reg_engine = create_engine(f"sqlite:///{registry_db}", connect_args=_CONNECT)
        tenant = SQLiteTenantRepository(reg_engine).get_by_slug("acme")
        assert tenant is not None
        assert tenant.name == "acme"

    def test_exits_1_when_uv_not_found(self, tmp_path: Path) -> None:
        with (
            patch("scripts.create_tenant.shutil.which", return_value=None),
            pytest.raises(SystemExit) as exc_info,
        ):
            self._run_main(
                ["--slug", "x", "--email", "a@b.com"],
                {
                    "REGISTRY_DB_PATH": str(tmp_path / "r.db"),
                    "TENANT_DB_DIR": str(tmp_path / "t"),
                },
            )
        assert exc_info.value.code == 1
