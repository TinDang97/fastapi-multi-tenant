"""Use case: list all users in a tenant with their roles."""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.entities import Role, User
from src.domain.ports.membership_repository import MembershipRepository
from src.domain.ports.user_repository import UserRepository


@dataclass
class UserWithRole:
    """A user paired with their role in a specific tenant.

    Attributes:
        user: The :class:`~src.domain.entities.User` entity.
        role: The user's :class:`~src.domain.entities.Role` within the tenant.
    """

    user: User
    role: Role


class ListUsersUseCase:
    """Return all users belonging to a tenant, each paired with their role.

    Fetches memberships for the tenant, then resolves each member's User entity.
    Members whose User record cannot be found are silently skipped — this guards
    against referential inconsistency without crashing the listing.

    Args:
        user_repo: Port satisfying :class:`~src.domain.ports.user_repository.UserRepository`.
        membership_repo: Port satisfying
            :class:`~src.domain.ports.membership_repository.MembershipRepository`.
    """

    def __init__(
        self,
        user_repo: UserRepository,
        membership_repo: MembershipRepository,
    ) -> None:
        self._user_repo = user_repo
        self._membership_repo = membership_repo

    def execute(self, tenant_slug: str) -> list[UserWithRole]:
        """Return all users in the tenant with their resolved roles.

        Args:
            tenant_slug: Identifies the tenant whose members are listed.

        Returns:
            List of :class:`UserWithRole`, one per resolvable tenant member.
            Returns an empty list when the tenant has no members.
        """
        memberships = self._membership_repo.list_members(tenant_slug)
        result: list[UserWithRole] = []
        for membership in memberships:
            user = self._user_repo.get_by_id(membership.user_id)
            if user is None:
                continue
            result.append(UserWithRole(user=user, role=membership.role))
        return result
