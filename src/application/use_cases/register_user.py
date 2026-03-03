"""Use case: self-service user registration within a tenant."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.domain.entities import Role, TenantMembership, User
from src.domain.exceptions import DuplicateEmailError
from src.domain.ports.membership_repository import MembershipRepository
from src.domain.ports.user_repository import UserRepository


@dataclass
class RegisterUserCommand:
    """Input data for user self-registration.

    Attributes:
        email: The registrant's email address. Must be unique across the system.
        plain_password: Raw password; hashed before persistence.
        tenant_slug: The tenant the user is joining.
    """

    email: str
    plain_password: str
    tenant_slug: str


@dataclass
class RegisterUserResult:
    """Output from a successful registration.

    Attributes:
        user: The persisted :class:`~src.domain.entities.User`.
        membership: The assigned :class:`~src.domain.entities.TenantMembership` with MEMBER role.
    """

    user: User
    membership: TenantMembership


class RegisterUserUseCase:
    """Register a new user and assign the default MEMBER role within the tenant.

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

    def execute(self, cmd: RegisterUserCommand) -> RegisterUserResult:
        """Hash password, persist user, assign MEMBER role.

        Args:
            cmd: :class:`RegisterUserCommand` carrying registration input.

        Returns:
            :class:`RegisterUserResult` containing the created user and membership.

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
            role=Role.MEMBER,
        )
        membership = self._membership_repo.assign_role(membership)

        return RegisterUserResult(user=user, membership=membership)
