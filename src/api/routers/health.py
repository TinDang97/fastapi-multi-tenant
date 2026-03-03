"""Health check router — tenant-aware liveness probe."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.dependencies.auth import get_tenant_slug

router = APIRouter(tags=["ops"])


@router.get("/health")
def health(tenant_slug: str = Depends(get_tenant_slug)) -> dict[str, str]:
    """Return liveness status and the active tenant slug.

    Intended for load-balancer and uptime-monitor health checks.  The
    ``tenant`` field confirms that ``TenantMiddleware`` has correctly
    populated ``request.state.tenant_slug`` for the current request.

    Args:
        tenant_slug: Active tenant resolved from request state via dependency.

    Returns:
        A JSON object with ``status`` (``"ok"``) and ``tenant`` fields.
    """
    return {"status": "ok", "tenant": tenant_slug}
