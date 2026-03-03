from typing import Protocol

from src.domain.entities import TenantMembership


class MembershipRepository(Protocol):
    def get_membership(self, user_id: str, tenant_slug: str) -> TenantMembership | None: ...

    def assign_role(self, membership: TenantMembership) -> TenantMembership: ...

    def list_members(self, tenant_slug: str) -> list[TenantMembership]: ...
