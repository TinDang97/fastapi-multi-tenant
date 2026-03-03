"""Use case: authenticate a user within a tenant and issue a JWT."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.domain.entities import Role, User
from src.domain.exceptions import AuthenticationError
from src.domain.ports.membership_repository import MembershipRepository
from src.domain.ports.user_repository import UserRepository


@dataclass
class LoginCommand:
    """Input data for a login attempt.

    Attributes:
        email: The user's email address.
        plain_password: Raw password supplied by the user.
        tenant_slug: The tenant scope for this authentication.
    """

    email: str
    plain_password: str
    tenant_slug: str


@dataclass
class LoginResult:
    """Output from a successful login.

    Attributes:
        token: Signed JWT scoped to the user and tenant.
        user: The authenticated :class:`~src.domain.entities.User`.
        role: The user's :class:`~src.domain.entities.Role` within the tenant.
    """

    token: str
    user: User
    role: Role


class LoginUseCase:
    """Verify credentials and issue a signed JWT for the requesting tenant.

    Args:
        user_repo: Port satisfying :class:`~src.domain.ports.user_repository.UserRepository`.
        membership_repo: Port satisfying
            :class:`~src.domain.ports.membership_repository.MembershipRepository`.
        password_service: Service with ``verify(plain: str, hashed: str) -> bool`` interface.
        jwt_service: Service with
            ``create_token(user_id: str, tenant_slug: str, role: Role) -> str`` interface.
    """

    def __init__(
        self,
        user_repo: UserRepository,
        membership_repo: MembershipRepository,
        password_service: Any,
        jwt_service: Any,
    ) -> None:
        self._user_repo = user_repo
        self._membership_repo = membership_repo
        self._password_service = password_service
        self._jwt_service = jwt_service

    def execute(self, cmd: LoginCommand) -> LoginResult:
        """Verify credentials and return a signed JWT with tenant-scoped role.

        Authentication fails with :class:`~src.domain.exceptions.AuthenticationError`
        for any of the following conditions to avoid leaking which checks failed:
        - Email not found
        - User is inactive
        - Password does not match
        - No membership exists for the tenant

        Args:
            cmd: :class:`LoginCommand` carrying login input.

        Returns:
            :class:`LoginResult` with the JWT token, user entity, and resolved role.

        Raises:
            AuthenticationError: When any credential or membership check fails.
        """
        user = self._user_repo.get_by_email(cmd.email)
        if user is None:
            raise AuthenticationError("Invalid credentials")

        if not user.is_active:
            raise AuthenticationError("Account is inactive")

        if not self._password_service.verify(cmd.plain_password, user.hashed_password):
            raise AuthenticationError("Invalid credentials")

        membership = self._membership_repo.get_membership(user.id, cmd.tenant_slug)
        if membership is None:
            raise AuthenticationError("No membership for this tenant")

        token = self._jwt_service.create_token(user.id, cmd.tenant_slug, membership.role)
        return LoginResult(token=token, user=user, role=membership.role)
