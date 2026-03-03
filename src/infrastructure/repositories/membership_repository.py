"""SQLite-backed implementation of the MembershipRepository port.

Operates against a per-tenant database (``data/tenants/{slug}.db``).

``assign_role`` performs an upsert: if a ``(user_id, tenant_slug)`` row
already exists it updates the ``role`` column in-place; otherwise a new row
is inserted.  SQLModel's ``session.merge()`` implements this via SQLAlchemy's
identity-map merge, which maps to an INSERT-or-UPDATE at the DB level.
"""

from __future__ import annotations

from sqlalchemy import Engine
from sqlmodel import Session, select

from src.domain.entities import TenantMembership
from src.infrastructure.models.membership_model import (
    MembershipModel,
    membership_entity_to_model,
    membership_model_to_entity,
)


class SQLiteMembershipRepository:
    """Implements :class:`~src.domain.ports.membership_repository.MembershipRepository`.

    Each public method opens and closes its own session so the repository is
    safe to use across threads without sharing state.

    Args:
        engine: A sync :class:`sqlalchemy.Engine` bound to a tenant database.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_membership(self, user_id: str, tenant_slug: str) -> TenantMembership | None:
        """Return the membership for a specific user in a specific tenant.

        The composite primary key ``(user_id, tenant_slug)`` is used for a
        single-row lookup — no full-table scan.

        Args:
            user_id: UUID string identifying the user.
            tenant_slug: Slug of the tenant to query within.

        Returns:
            A domain :class:`TenantMembership` entity, or ``None`` if the
            user has no membership in this tenant.
        """
        with Session(self._engine) as session:
            model = session.get(MembershipModel, (user_id, tenant_slug))
            return membership_model_to_entity(model) if model else None

    def assign_role(self, membership: TenantMembership) -> TenantMembership:
        """Upsert a membership row, inserting or updating the role.

        If a row with the same ``(user_id, tenant_slug)`` composite key already
        exists, its ``role`` is updated to the new value.  If no row exists a
        new one is inserted.  The operation is atomic within a single
        transaction.

        SQLAlchemy's ``session.merge()`` loads any existing state from the
        identity map (or the database) and applies the supplied field values,
        producing the correct INSERT-or-UPDATE behaviour.

        Args:
            membership: Domain entity carrying the desired role.

        Returns:
            The persisted domain :class:`TenantMembership` entity (refreshed
            from DB).
        """
        with Session(self._engine) as session:
            model = membership_entity_to_model(membership)
            merged = session.merge(model)
            session.commit()
            session.refresh(merged)
            return membership_model_to_entity(merged)

    def list_members(self, tenant_slug: str) -> list[TenantMembership]:
        """Return all memberships that belong to the given tenant.

        A single indexed query against ``tenant_slug`` fetches all rows; no
        per-row follow-up queries are issued (no N+1).

        Args:
            tenant_slug: Slug of the tenant whose members to list.

        Returns:
            A list of domain :class:`TenantMembership` entities (may be empty).
        """
        with Session(self._engine) as session:
            stmt = select(MembershipModel).where(
                MembershipModel.tenant_slug == tenant_slug
            )
            models = session.exec(stmt).all()
            return [membership_model_to_entity(m) for m in models]
