"""Use case: resolve a tenant by slug."""

from __future__ import annotations

from src.domain.entities import Tenant
from src.domain.exceptions import TenantNotFoundError
from src.domain.ports.tenant_repository import TenantRepository


class GetTenantUseCase:
    """Resolve a tenant by slug, enforcing the active status check.

    Args:
        tenant_repo: Port satisfying :class:`~src.domain.ports.tenant_repository.TenantRepository`.
    """

    def __init__(self, tenant_repo: TenantRepository) -> None:
        self._tenant_repo = tenant_repo

    def execute(self, slug: str) -> Tenant:
        """Return the tenant identified by *slug*.

        Args:
            slug: URL-safe tenant identifier.

        Returns:
            The active :class:`~src.domain.entities.Tenant`.

        Raises:
            TenantNotFoundError: When no tenant matches *slug* or the tenant is inactive.
        """
        tenant = self._tenant_repo.get_by_slug(slug)
        if tenant is None or not tenant.is_active:
            raise TenantNotFoundError(slug)
        return tenant
