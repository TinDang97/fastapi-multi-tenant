"""Shared Jinja2 template engine for HTMX-driven server-side rendering.

All routers that return HTML responses import ``templates`` from this module
to ensure a single ``Jinja2Templates`` instance is used throughout the
application.  The ``templates/`` directory is resolved relative to the
project root (the working directory when ``uvicorn`` / ``fastapi dev`` starts).

Usage::

    from src.api.templates import templates
    from fastapi import Request
    from fastapi.responses import HTMLResponse

    @router.get("/dashboard", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(request, "dashboard.html", {"key": "value"})
"""

from __future__ import annotations

from fastapi.templating import Jinja2Templates

templates = Jinja2Templates(directory="templates")
