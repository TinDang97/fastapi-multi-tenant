from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import create_engine, pool, text
from sqlmodel import SQLModel

from alembic import context

# Import only tenant-scoped models so their table metadata is registered.
# The registry TenantModel must NOT be imported here — it lives in a separate DB.
from src.infrastructure.models.membership_model import MembershipModel  # noqa: F401
from src.infrastructure.models.user_model import UserModel  # noqa: F401

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata

TENANT_DB_DIR: str = os.environ.get("TENANT_DB_DIR", "data/tenants")
TENANT_SLUG: str | None = os.environ.get("TENANT_SLUG")


def get_url(slug: str) -> str:
    """Return the SQLite connection URL for the given tenant slug."""
    db_path = Path(TENANT_DB_DIR) / f"{slug}.db"
    return f"sqlite:///{db_path}"


def run_migrations_for_slug(slug: str) -> None:
    """Open a connection to a single tenant DB and run pending migrations."""
    url = get_url(slug)
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False},
        poolclass=pool.NullPool,
    )
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # required for SQLite ALTER TABLE support
        )
        with context.begin_transaction():
            context.run_migrations()


def run_migrations_offline() -> None:
    """Run migrations without a live DB connection.

    TENANT_SLUG is required for offline mode because there is no registry
    connection available to enumerate tenants.
    """
    if not TENANT_SLUG:
        raise ValueError(
            "TENANT_SLUG environment variable is required for offline migration mode."
        )
    context.configure(
        url=get_url(TENANT_SLUG),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,  # required for SQLite ALTER TABLE support
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against live DB connections.

    When TENANT_SLUG is set, migrates only that tenant's database.
    When TENANT_SLUG is unset, reads all active tenant slugs from registry.db
    and migrates each tenant database in sequence.
    """
    if TENANT_SLUG:
        run_migrations_for_slug(TENANT_SLUG)
        return

    # Enumerate all active tenants from the registry database.
    registry_path = os.environ.get("REGISTRY_DB_PATH", "data/registry.db")
    registry_url = f"sqlite:///{registry_path}"
    reg_engine = create_engine(
        registry_url,
        connect_args={"check_same_thread": False},
    )
    with reg_engine.connect() as reg_conn:
        rows = reg_conn.execute(
            text("SELECT slug FROM tenants WHERE is_active = 1")
        ).fetchall()

    for (slug,) in rows:
        run_migrations_for_slug(slug)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
