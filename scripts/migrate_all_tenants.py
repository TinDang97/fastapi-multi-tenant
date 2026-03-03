#!/usr/bin/env python
"""Run Alembic tenant migrations for all active tenants.

Reads the active tenant slugs from the registry database, then invokes
``alembic -c alembic_tenant.ini upgrade head`` once per slug, passing
``TENANT_SLUG`` and ``TENANT_DB_DIR`` as environment variables so that
``alembic/tenant/env.py`` can route to the correct per-tenant SQLite file.

Usage:
    uv run python -m scripts.migrate_all_tenants

Environment variables:
    REGISTRY_DB_PATH   Path to registry.db  (default: data/registry.db)
    TENANT_DB_DIR      Directory for per-tenant .db files  (default: data/tenants)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


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


def _read_active_slugs(registry_db: str) -> list[str]:
    """Query the registry database and return all active tenant slugs.

    Uses a raw SQLAlchemy engine rather than importing SQLModel models so
    that this function stays independent of the full application stack.

    Args:
        registry_db: Filesystem path to ``registry.db``.

    Returns:
        A list of slug strings (may be empty).

    Raises:
        SystemExit: If the tenants table does not exist (registry not
            initialised) or the database file is inaccessible.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import OperationalError

    engine = create_engine(
        f"sqlite:///{registry_db}",
        connect_args={"check_same_thread": False},
    )
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT slug FROM tenants WHERE is_active = 1")
            ).fetchall()
    except OperationalError as exc:
        print(f"Error reading registry database '{registry_db}': {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        engine.dispose()

    return [row[0] for row in rows]


def _migrate_tenant(uv_path: str, slug: str, tenant_db_dir: str) -> bool:
    """Run ``alembic upgrade head`` for a single tenant slug.

    Args:
        uv_path: Absolute path to the ``uv`` executable.
        slug: Tenant slug to migrate.
        tenant_db_dir: Directory containing per-tenant .db files.

    Returns:
        ``True`` if migration succeeded, ``False`` otherwise.
    """
    result = subprocess.run(  # noqa: S603
        [uv_path, "run", "alembic", "-c", "alembic_tenant.ini", "upgrade", "head"],
        env={**os.environ, "TENANT_SLUG": slug, "TENANT_DB_DIR": tenant_db_dir},
        check=False,
    )
    return result.returncode == 0


def main() -> None:
    """Entry point: migrate all active tenants in the registry."""
    registry_db = os.environ.get("REGISTRY_DB_PATH", "data/registry.db")
    tenant_db_dir = os.environ.get("TENANT_DB_DIR", "data/tenants")

    slugs = _read_active_slugs(registry_db)

    if not slugs:
        print("No active tenants found.", file=sys.stderr)
        return

    uv_path = _resolve_uv()

    for slug in slugs:
        print(f"Migrating tenant: {slug}")
        success = _migrate_tenant(uv_path, slug, tenant_db_dir)
        if not success:
            print(f"Migration failed for tenant: {slug}", file=sys.stderr)
            sys.exit(1)

    print(f"Migrated {len(slugs)} tenant(s).")


if __name__ == "__main__":
    main()
