from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Field, SQLModel

from src.domain.entities import Tenant


class TenantModel(SQLModel, table=True):
    """ORM model for the tenants table stored in registry.db.

    SQLite does not support schemas; the table lives in the top-level
    registry database with no ``schema=`` argument.
    """

    __tablename__ = "tenants"

    slug: str = Field(primary_key=True, max_length=100)
    name: str = Field(max_length=200)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Mapper functions — the only boundary between ORM rows and domain entities.
# Nothing outside this module should reference TenantModel directly.
# ---------------------------------------------------------------------------


def tenant_model_to_entity(model: TenantModel) -> Tenant:
    """Convert a ``TenantModel`` ORM row to a ``Tenant`` domain entity."""
    return Tenant(
        slug=model.slug,
        name=model.name,
        is_active=model.is_active,
        created_at=model.created_at,
    )


def tenant_entity_to_model(entity: Tenant) -> TenantModel:
    """Convert a ``Tenant`` domain entity to a ``TenantModel`` ORM row."""
    return TenantModel(
        slug=entity.slug,
        name=entity.name,
        is_active=entity.is_active,
        created_at=entity.created_at,
    )
