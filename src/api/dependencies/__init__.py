"""FastAPI dependency factories for per-request resources.

Unlike the DI container (which manages singletons and request-agnostic
factories), the functions here use ``FastAPI.Depends`` to produce objects
whose lifetime and configuration are tied to individual HTTP requests.

Key responsibilities
--------------------
* Resolve ``tenant_slug`` from ``request.state`` (set by ``TenantMiddleware``).
* Create or retrieve a cached per-tenant ``Engine`` for the active tenant.
* Instantiate per-tenant repositories (``SQLiteUserRepository``,
  ``SQLiteMembershipRepository``) backed by the tenant engine.
* Extract and validate the current user from the ``Authorization`` header
  using the ``JWTService`` singleton from the DI container.

These factories are imported directly in router modules via::

    from fastapi import Depends
    from src.api.dependencies import get_tenant_engine, get_current_user
"""
