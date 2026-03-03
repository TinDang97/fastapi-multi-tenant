"""SQLite-backed implementation of the TenantRepository port.

Operates against the registry database (``registry.db``) which holds
the canonical list of tenants.  All database interaction goes through a
sync SQLModel :class:`Session` opened per-operation — no session is kept
open across method calls.
"""

from __future__ import annotations

from sqlalchemy import Engine
from sqlmodel import Session, select

from src.domain.entities import Tenant
from src.infrastructure.models.tenant_model import (
    TenantModel,
    tenant_entity_to_model,
    tenant_model_to_entity,
)


class SQLiteTenantRepository:
    """Implements :class:`~src.domain.ports.tenant_repository.TenantRepository`.

    Each public method opens and closes its own session so the repository is
    safe to use across threads without sharing state.

    Args:
        engine: A sync :class:`sqlalchemy.Engine` bound to ``registry.db``.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_by_slug(self, slug: str) -> Tenant | None:
        """Return the tenant with the given slug, or ``None`` if absent.

        Args:
            slug: The tenant's unique identifier.

        Returns:
            A domain :class:`Tenant` entity, or ``None``.
        """
        with Session(self._engine) as session:
            model = session.get(TenantModel, slug)
            return tenant_model_to_entity(model) if model else None

    def create(self, tenant: Tenant) -> Tenant:
        """Persist a new tenant and return the saved entity.

        Args:
            tenant: Domain entity to persist.  The ``slug`` must be unique.

        Returns:
            The persisted domain :class:`Tenant` entity (refreshed from DB).

        Raises:
            sqlalchemy.exc.IntegrityError: If a tenant with the same slug
                already exists.
        """
        with Session(self._engine) as session:
            model = tenant_entity_to_model(tenant)
            session.add(model)
            session.commit()
            session.refresh(model)
            return tenant_model_to_entity(model)

    def list_active(self) -> list[Tenant]:
        """Return all tenants with ``is_active == True``.

        Returns:
            A list of domain :class:`Tenant` entities (may be empty).
        """
        with Session(self._engine) as session:
            stmt = select(TenantModel).where(TenantModel.is_active == True)  # noqa: E712
            models = session.exec(stmt).all()
            return [tenant_model_to_entity(m) for m in models]
