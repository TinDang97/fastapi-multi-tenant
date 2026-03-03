from __future__ import annotations

from sqlmodel import Field, SQLModel

from src.domain.entities import Role, TenantMembership


class MembershipModel(SQLModel, table=True):
    """ORM model for the memberships table stored in the per-tenant SQLite database.

    Composite primary key ``(user_id, tenant_slug)`` enforces one role record
    per user per tenant at the database level.

    ``role`` is persisted as a plain string so the table remains portable;
    the mapper converts it to/from the ``Role`` enum at the boundary.

    No ``schema=`` argument — SQLite does not support PostgreSQL-style schemas.
    No foreign key to registry.db — cross-file FKs are unsupported in SQLite.
    """

    __tablename__ = "memberships"

    user_id: str = Field(primary_key=True, max_length=36)
    tenant_slug: str = Field(primary_key=True, max_length=100)
    role: str = Field(max_length=20)


# ---------------------------------------------------------------------------
# Mapper functions — the only boundary between ORM rows and domain entities.
# Nothing outside this module should reference MembershipModel directly.
# ---------------------------------------------------------------------------


def membership_model_to_entity(model: MembershipModel) -> TenantMembership:
    """Convert a ``MembershipModel`` ORM row to a ``TenantMembership`` domain entity.

    Raises ``ValueError`` if the stored role string does not correspond to a
    valid ``Role`` enum member, which indicates data corruption in the database.
    """
    return TenantMembership(
        user_id=model.user_id,
        tenant_slug=model.tenant_slug,
        role=Role(model.role),
    )


def membership_entity_to_model(entity: TenantMembership) -> MembershipModel:
    """Convert a ``TenantMembership`` domain entity to a ``MembershipModel`` ORM row."""
    return MembershipModel(
        user_id=entity.user_id,
        tenant_slug=entity.tenant_slug,
        role=entity.role.value,
    )
