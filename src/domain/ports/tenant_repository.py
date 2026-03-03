from typing import Protocol

from src.domain.entities import Tenant


class TenantRepository(Protocol):
    def get_by_slug(self, slug: str) -> Tenant | None: ...

    def create(self, tenant: Tenant) -> Tenant: ...

    def list_active(self) -> list[Tenant]: ...
