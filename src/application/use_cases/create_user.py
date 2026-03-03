"""Use case: admin-initiated user creation with an explicit role."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.domain.entities import Role, TenantMembership, User
from src.domain.exceptions import DuplicateEmailError
from src.domain.ports.membership_repository import MembershipRepository
from src.domain.ports.user_repository import UserRepository


@dataclass
class CreateUserCommand:
    """Input data for admin-created user.

    Attributes:
        email: The new user's email address. Must be unique across the system.
        plain_password: Raw password; hashed before persistence.
        role: The :class:`~src.domain.entities.Role` to assign within the tenant.
        tenant_slug: The tenant the user is being added to.
    """

    email: str
    plain_password: str
    role: Role
    tenant_slug: str


@dataclass
class CreateUserResult:
    """Output from a successful admin user creation.

    Attributes:
        user: The persisted :class:`~src.domain.entities.User`.
        membership: The assigned :class:`~src.domain.entities.TenantMembership`.
    """

    user: User
    membership: TenantMembership


class CreateUserUseCase:
    """Admin-only creation of a user with an explicitly specified role.

    Unlike self-registration, the caller controls the assigned role. This use
    case is intended to be invoked only after the caller's own role has been
    verified to be ADMIN or OWNER at the API layer.

    Args:
        user_repo: Port satisfying :class:`~src.domain.ports.user_repository.UserRepository`.
        membership_repo: Port satisfying
            :class:`~src.domain.ports.membership_repository.MembershipRepository`.
        password_service: Service with ``hash(plain: str) -> str`` interface.
    """

    def __init__(
        self,
        user_repo: UserRepository,
        membership_repo: MembershipRepository,
        password_service: Any,
    ) -> None:
        self._user_repo = user_repo
        self._membership_repo = membership_repo
        self._password_service = password_service

    def execute(self, cmd: CreateUserCommand) -> CreateUserResult:
        """Hash password, persist user, assign the requested role.

        Args:
            cmd: :class:`CreateUserCommand` carrying creation input.

        Returns:
            :class:`CreateUserResult` containing the created user and membership.

        Raises:
            DuplicateEmailError: When *cmd.email* is already registered.
        """
        if self._user_repo.get_by_email(cmd.email) is not None:
            raise DuplicateEmailError(cmd.email)

        hashed = self._password_service.hash(cmd.plain_password)
        user = User(
            id=User.generate_id(),
            email=cmd.email,
            hashed_password=hashed,
        )
        user = self._user_repo.create(user)

        membership = TenantMembership(
            user_id=user.id,
            tenant_slug=cmd.tenant_slug,
            role=cmd.role,
        )
        membership = self._membership_repo.assign_role(membership)

        return CreateUserResult(user=user, membership=membership)
