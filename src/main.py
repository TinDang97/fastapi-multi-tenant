"""FastAPI application entry point.

Startup sequence (via ``lifespan``)
------------------------------------
1. :func:`~src.container.init_container` builds the DI container and populates
   all ``Singleton`` providers (registry engine, auth services).
2. The container is wired to ``src.api`` so ``@inject``-decorated route
   functions receive their dependencies automatically.
3. On shutdown the container is unwired to release any resources held by
   providers.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src.api.middleware.tenant_middleware import TenantMiddleware
from src.api.routers import auth, health, pages, users
from src.api.templates import templates
from src.container import init_container
from src.domain.exceptions import (
    AuthenticationError,
    DomainError,
    DuplicateEmailError,
    PermissionDeniedError,
    TenantNotFoundError,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage the application lifecycle."""
    container = init_container()
    container.wire(packages=["src.api"])
    yield
    container.unwire()


app = FastAPI(
    title="FastAPI Multi-Tenant",
    version="0.1.0",
    description="Multi-tenant boilerplate: SQLite-per-tenant, clean architecture, HTMX.",
    lifespan=lifespan,
)

# ── Static assets ──────────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")

# ── Middleware (outermost first) ───────────────────────────────────────────────
# TenantMiddleware runs before every route handler to populate request.state.tenant_slug.
app.add_middleware(TenantMiddleware)


# ── Exception handlers ─────────────────────────────────────────────────────────
def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse | HTMLResponse:
    if _is_htmx(request):
        if exc.status_code == 403:
            return templates.TemplateResponse(  # type: ignore[return-value]
                "errors/403.html",
                {"request": request, "required_role": None},
                status_code=403,
            )
        # All other 4xx/5xx: render inline feedback div instead of raw JSON.
        html = f'<div class="feedback feedback--error">{exc.detail}</div>'
        return HTMLResponse(html, status_code=exc.status_code)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(AuthenticationError)
async def authentication_error_handler(request: Request, exc: AuthenticationError) -> JSONResponse | HTMLResponse:
    if _is_htmx(request):
        html = f'<div class="feedback feedback--error">{exc}</div>'
        return HTMLResponse(html, status_code=401)
    return JSONResponse({"detail": str(exc)}, status_code=401)


@app.exception_handler(TenantNotFoundError)
async def tenant_not_found_handler(request: Request, exc: TenantNotFoundError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=404)


@app.exception_handler(PermissionDeniedError)
async def permission_denied_handler(request: Request, exc: PermissionDeniedError) -> HTMLResponse | JSONResponse:
    if _is_htmx(request):
        html = templates.TemplateResponse(
            "errors/403.html",
            {"request": request, "required_role": exc.required},
            status_code=403,
        )
        return html  # type: ignore[return-value]
    return JSONResponse({"detail": str(exc)}, status_code=403)


@app.exception_handler(DuplicateEmailError)
async def duplicate_email_handler(request: Request, exc: DuplicateEmailError) -> JSONResponse | HTMLResponse:
    if _is_htmx(request):
        html = f'<div class="feedback feedback--error">{exc}</div>'
        return HTMLResponse(html, status_code=409)
    return JSONResponse({"detail": str(exc)}, status_code=409)


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=400)


# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(pages.router)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)


