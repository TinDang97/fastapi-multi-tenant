"""ASGI middleware for the FastAPI multi-tenant application.

Middleware is registered on the ``FastAPI`` application instance in
``src/main.py``.  Each middleware module must expose a single class that
accepts ``app: ASGIApp`` as its first constructor argument.

Planned middleware
------------------
``tenant_middleware.py``
    Resolves the current tenant from the request (subdomain, path prefix, or
    ``X-Tenant-Slug`` header) and attaches the ``tenant_slug`` to
    ``request.state`` for downstream use.
"""
