"""Pages router — server-side rendered landing pages.

Routes here return full Jinja2 ``TemplateResponse`` pages (not partials).
No authentication is required; these are public-facing pages.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from src.api.dependencies.auth import get_tenant_slug
from src.api.templates import templates

router = APIRouter(tags=["pages"])


@router.get("/", response_class=HTMLResponse)
def index(request: Request, tenant_slug: str = Depends(get_tenant_slug)) -> HTMLResponse:
    """Render the application landing page.

    Args:
        request: The current HTTP request.
        tenant_slug: Active tenant from request state.

    Returns:
        Rendered ``index.html`` template.
    """
    return templates.TemplateResponse(request, "index.html", {"tenant_slug": tenant_slug})


@router.get("/auth/login", response_class=HTMLResponse)
def login_page(request: Request, tenant_slug: str = Depends(get_tenant_slug)) -> HTMLResponse:
    """Render the login page.

    Args:
        request: The current HTTP request.
        tenant_slug: Active tenant from request state.

    Returns:
        Rendered ``auth/login.html`` template.
    """
    return templates.TemplateResponse(request, "auth/login.html", {"tenant_slug": tenant_slug})


@router.get("/auth/register", response_class=HTMLResponse)
def register_page(request: Request, tenant_slug: str = Depends(get_tenant_slug)) -> HTMLResponse:
    """Render the self-service registration page.

    Args:
        request: The current HTTP request.
        tenant_slug: Active tenant from request state.

    Returns:
        Rendered ``auth/register.html`` template.
    """
    return templates.TemplateResponse(request, "auth/register.html", {"tenant_slug": tenant_slug})
