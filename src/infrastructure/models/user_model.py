from __future__ import annotations

from sqlmodel import Field, SQLModel

from src.domain.entities import User


class UserModel(SQLModel, table=True):
    """ORM model for the users table stored in the per-tenant SQLite database.

    Each tenant database is a separate file at ``data/tenants/{slug}.db``.
    No ``schema=`` argument — SQLite does not support PostgreSQL-style schemas.
    No foreign keys referencing other database files (cross-DB FKs are
    unsupported in SQLite).
    """

    __tablename__ = "users"

    id: str = Field(primary_key=True, max_length=36)
    email: str = Field(index=True, unique=True, max_length=254)
    hashed_password: str
    is_active: bool = Field(default=True)


# ---------------------------------------------------------------------------
# Mapper functions — the only boundary between ORM rows and domain entities.
# Nothing outside this module should reference UserModel directly.
# ---------------------------------------------------------------------------


def user_model_to_entity(model: UserModel) -> User:
    """Convert a ``UserModel`` ORM row to a ``User`` domain entity."""
    return User(
        id=model.id,
        email=model.email,
        hashed_password=model.hashed_password,
        is_active=model.is_active,
    )


def user_entity_to_model(entity: User) -> UserModel:
    """Convert a ``User`` domain entity to a ``UserModel`` ORM row."""
    return UserModel(
        id=entity.id,
        email=entity.email,
        hashed_password=entity.hashed_password,
        is_active=entity.is_active,
    )
