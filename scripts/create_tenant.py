#!/usr/bin/env python
"""Create a new tenant with an initial OWNER user.

Steps performed:
1. Insert the tenant row into the registry database.
2. Run Alembic tenant migrations to create the per-tenant ``.db`` file and schema.
3. Create the owner ``User`` record inside the tenant database.
4. Assign the ``OWNER`` role via a ``TenantMembership`` record.

Usage:
    uv run python -m scripts.create_tenant --slug acme --email owner@acme.com
    uv run python -m scripts.create_tenant --slug acme --email owner@acme.com --name "Acme Corp"
    uv run python -m scripts.create_tenant --slug acme --email owner@acme.com --password s3cr3t

Environment variables:
    REGISTRY_DB_PATH   Path to registry.db  (default: data/registry.db)
    TENANT_DB_DIR      Directory for per-tenant .db files  (default: data/tenants)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import uuid
from datetime import UTC, datetime


def _resolve_uv() -> str:
    """Return the absolute path to the ``uv`` executable.

    Raises:
        SystemExit: If ``uv`` cannot be located on PATH.
    """
    uv_path = shutil.which("uv")
    if uv_path is None:
        print("Error: 'uv' executable not found on PATH.", file=sys.stderr)
        sys.exit(1)
    return uv_path


def _register_tenant(registry_db: str, slug: str, name: str) -> None:
    """Insert a new tenant row into the registry database.

    Bootstraps the ``tenants`` table via SQLModel metadata if it does not yet
    exist, then delegates to :class:`SQLiteTenantRepository` for the actual
    insert.

    Args:
        registry_db: Filesystem path to ``registry.db``.
        slug: Unique tenant identifier.
        name: Human-readable display name for the tenant.

    Raises:
        SystemExit: If a tenant with the same slug already exists.
    """
    from sqlalchemy.exc import IntegrityError
    from sqlmodel import SQLModel

    from src.domain.entities import Tenant
    from src.infrastructure.database import create_registry_engine
    from src.infrastructure.models.tenant_model import (
        TenantModel,  # noqa: F401 — registers metadata
    )
    from src.infrastructure.repositories.tenant_repository import SQLiteTenantRepository

    reg_engine = create_registry_engine(registry_db)
    SQLModel.metadata.create_all(reg_engine)

    repo = SQLiteTenantRepository(reg_engine)

    existing = repo.get_by_slug(slug)
    if existing is not None:
        print(f"Error: tenant '{slug}' already exists.", file=sys.stderr)
        sys.exit(1)

    tenant = Tenant(slug=slug, name=name, is_active=True, created_at=datetime.now(UTC))
    try:
        repo.create(tenant)
    except IntegrityError:
        # Race condition: another process inserted the same slug between the
        # get_by_slug check and the insert.
        print(f"Error: tenant '{slug}' already exists (concurrent insert).", file=sys.stderr)
        sys.exit(1)

    print(f"Created tenant: {slug}")


def _run_tenant_migrations(uv_path: str, slug: str, tenant_db_dir: str) -> None:
    """Run ``alembic upgrade head`` for the newly created tenant.

    Args:
        uv_path: Absolute path to the ``uv`` executable.
        slug: Tenant slug used to route Alembic to the correct .db file.
        tenant_db_dir: Directory containing per-tenant .db files.

    Raises:
        SystemExit: If the Alembic subprocess exits with a non-zero code.
    """
    result = subprocess.run(  # noqa: S603
        [uv_path, "run", "alembic", "-c", "alembic_tenant.ini", "upgrade", "head"],
        env={**os.environ, "TENANT_SLUG": slug, "TENANT_DB_DIR": tenant_db_dir},
        check=False,
    )
    if result.returncode != 0:
        print(f"Migration failed for tenant: {slug}", file=sys.stderr)
        sys.exit(1)


def _create_owner(slug: str, tenant_db_dir: str, email: str, plain_password: str) -> None:
    """Create the owner user and assign the OWNER role in the tenant database.

    Args:
        slug: Tenant slug identifying the target database file.
        tenant_db_dir: Directory containing per-tenant .db files.
        email: Email address for the owner account.
        plain_password: Plaintext password that will be hashed before storage.

    Raises:
        SystemExit: If a user with the given email already exists in the tenant
            database.
    """
    from src.domain.entities import Role, TenantMembership, User
    from src.domain.exceptions import DuplicateEmailError
    from src.infrastructure.database import create_tenant_engine
    from src.infrastructure.repositories.membership_repository import SQLiteMembershipRepository
    from src.infrastructure.repositories.user_repository import SQLiteUserRepository
    from src.infrastructure.services.password_service import PasswordService

    tenant_engine = create_tenant_engine(tenant_db_dir, slug)
    user_repo = SQLiteUserRepository(tenant_engine)
    membership_repo = SQLiteMembershipRepository(tenant_engine)
    password_svc = PasswordService()

    user = User(
        id=str(uuid.uuid4()),
        email=email,
        hashed_password=password_svc.hash(plain_password),
        is_active=True,
    )

    try:
        created_user = user_repo.create(user)
    except DuplicateEmailError:
        print(f"Error: email '{email}' already registered in tenant '{slug}'.", file=sys.stderr)
        sys.exit(1)

    membership = TenantMembership(
        user_id=created_user.id,
        tenant_slug=slug,
        role=Role.OWNER,
    )
    membership_repo.assign_role(membership)

    print(f"Created OWNER user: {email}")


def main() -> None:
    """Entry point: parse arguments and orchestrate tenant creation."""
    parser = argparse.ArgumentParser(
        description="Create a new tenant with an initial OWNER user."
    )
    parser.add_argument("--slug", required=True, help="Unique tenant slug (e.g. 'acme')")
    parser.add_argument("--email", required=True, help="Owner's email address")
    parser.add_argument(
        "--name",
        default=None,
        help="Tenant display name (defaults to slug)",
    )
    parser.add_argument(
        "--password",
        default="changeme123",
        help="Owner's initial password (change immediately in production)",
    )
    args = parser.parse_args()

    slug: str = args.slug
    email: str = args.email
    name: str = args.name or slug
    password: str = args.password
    registry_db: str = os.environ.get("REGISTRY_DB_PATH", "data/registry.db")
    tenant_db_dir: str = os.environ.get("TENANT_DB_DIR", "data/tenants")

    uv_path = _resolve_uv()

    # Step 1: register tenant in registry.db
    _register_tenant(registry_db, slug, name)

    # Step 2: run Alembic migrations to create the tenant .db file and schema
    _run_tenant_migrations(uv_path, slug, tenant_db_dir)

    # Step 3: create owner user + assign OWNER role
    _create_owner(slug, tenant_db_dir, email, password)

    print(f"Tenant '{slug}' is ready. Default password: {password}")
    print("Change the password immediately in production!")


if __name__ == "__main__":
    main()
