"""Starlette middleware that resolves the current tenant from the request.

Runs before every route handler.  Reads ``X-Tenant-Slug`` from request
headers, verifies the tenant exists and is active via the registry
repository, then writes ``request.state.tenant_slug`` and
``request.state.tenant`` so downstream dependencies can consume them
without touching the database again.

Failure modes
-------------
* Missing header           → 400 Bad Request
* Tenant not found / inactive → 404 Not Found
* All other paths          → control passed to the next middleware/handler
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from src.container import get_container


class TenantMiddleware(BaseHTTPMiddleware):
    """Attach tenant context to every inbound request.

    Args:
        app: The downstream ASGI application.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        """Validate the tenant identifier and populate request state.

        Lookup order (first match wins):
        1. ``X-Tenant-Slug`` HTTP header (API clients, curl)
        2. ``tenant_slug`` cookie (browser sessions after first visit)
        3. ``?tenant=`` query parameter (browser first-visit link)

        Args:
            request: The inbound HTTP request.
            call_next: Callable that forwards the request to the next layer.

        Returns:
            A ``JSONResponse`` error (400 or 404) or the downstream response.
        """
        slug = (
            request.headers.get("X-Tenant-Slug")
            or request.cookies.get("tenant_slug")
            or request.query_params.get("tenant")
        )
        if not slug:
            return JSONResponse(
                {"detail": "X-Tenant-Slug header required"},
                status_code=400,
            )

        tenant_repo = get_container().tenant_repo()
        tenant = tenant_repo.get_by_slug(slug)
        if tenant is None or not tenant.is_active:
            return JSONResponse(
                {"detail": f"Tenant '{slug}' not found"},
                status_code=404,
            )

        request.state.tenant_slug = slug
        request.state.tenant = tenant
        response = await call_next(request)
        # Persist the tenant slug in a cookie so the browser doesn't need to
        # re-specify it via header or query param on subsequent requests.
        if not request.cookies.get("tenant_slug"):
            response.set_cookie("tenant_slug", slug, samesite="lax", max_age=86400)
        return response
