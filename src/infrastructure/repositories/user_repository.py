"""SQLite-backed implementation of the UserRepository port.

Operates against a per-tenant database (``data/tenants/{slug}.db``).
Duplicate email violations are translated from :class:`sqlalchemy.exc.IntegrityError`
to the domain exception :class:`~src.domain.exceptions.DuplicateEmailError`,
keeping ORM details confined to this module.
"""

from __future__ import annotations

from sqlalchemy import Engine
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from src.domain.entities import User
from src.domain.exceptions import DuplicateEmailError
from src.infrastructure.models.user_model import (
    UserModel,
    user_entity_to_model,
    user_model_to_entity,
)


class SQLiteUserRepository:
    """Implements :class:`~src.domain.ports.user_repository.UserRepository`.

    Each public method opens and closes its own session so the repository is
    safe to use across threads without sharing state.

    Args:
        engine: A sync :class:`sqlalchemy.Engine` bound to a tenant database.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def get_by_id(self, user_id: str) -> User | None:
        """Return the user with the given primary-key ID, or ``None``.

        Args:
            user_id: UUID string identifying the user.

        Returns:
            A domain :class:`User` entity, or ``None`` if not found.
        """
        with Session(self._engine) as session:
            model = session.get(UserModel, user_id)
            return user_model_to_entity(model) if model else None

    def get_by_email(self, email: str) -> User | None:
        """Return the user with the given email address, or ``None``.

        The query uses the indexed ``email`` column for an efficient lookup.

        Args:
            email: Email address to look up.

        Returns:
            A domain :class:`User` entity, or ``None`` if not found.
        """
        with Session(self._engine) as session:
            stmt = select(UserModel).where(UserModel.email == email)
            model = session.exec(stmt).first()
            return user_model_to_entity(model) if model else None

    def create(self, user: User) -> User:
        """Persist a new user and return the saved entity.

        Args:
            user: Domain entity to persist.  ``email`` must be unique within
                the tenant database.

        Returns:
            The persisted domain :class:`User` entity (refreshed from DB).

        Raises:
            DuplicateEmailError: If a user with the same email already exists
                in this tenant's database.
        """
        with Session(self._engine) as session:
            model = user_entity_to_model(user)
            session.add(model)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                raise DuplicateEmailError(user.email) from None
            session.refresh(model)
            return user_model_to_entity(model)

    def delete_by_id(self, user_id: str) -> bool:
        """Delete the user with the given primary-key ID.

        Args:
            user_id: UUID string identifying the user to delete.

        Returns:
            ``True`` if the user was found and deleted, ``False`` if no user
            with *user_id* exists in this tenant's database.
        """
        with Session(self._engine) as session:
            model = session.get(UserModel, user_id)
            if model is None:
                return False
            session.delete(model)
            session.commit()
            return True
