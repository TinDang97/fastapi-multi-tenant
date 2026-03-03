"""Engine factory functions for registry and per-tenant SQLite databases.

All engines use synchronous SQLAlchemy — no async drivers required.
The registry engine targets a single ``registry.db`` file that stores the
``tenants`` table.  Tenant engines target isolated ``{slug}.db`` files under
the configured tenant directory.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine
from sqlmodel import create_engine


def create_registry_engine(db_path: str) -> Engine:
    """Create a sync SQLAlchemy engine for the registry database.

    The parent directory is created automatically if it does not exist.

    Args:
        db_path: Absolute or relative filesystem path to ``registry.db``.

    Returns:
        A configured :class:`sqlalchemy.Engine` instance.
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )


def create_tenant_engine(db_dir: str, tenant_slug: str) -> Engine:
    """Create a sync SQLAlchemy engine for a tenant-specific SQLite database.

    The tenant directory is created automatically if it does not exist.  Each
    tenant receives an isolated file named ``{tenant_slug}.db`` inside
    ``db_dir``.

    Args:
        db_dir: Directory that holds all per-tenant database files.
        tenant_slug: Unique slug identifying the tenant.

    Returns:
        A configured :class:`sqlalchemy.Engine` instance.
    """
    tenant_dir = Path(db_dir)
    tenant_dir.mkdir(parents=True, exist_ok=True)
    db_path = tenant_dir / f"{tenant_slug}.db"
    return create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
