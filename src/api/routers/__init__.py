"""FastAPI ``APIRouter`` instances, one module per resource area.

Routers are included on the ``FastAPI`` application in ``src/main.py``.
Each router module imports only from ``src.application`` (use cases) and
``src.api.dependencies`` (``Depends`` factories).  Direct imports from
``src.domain`` or ``src.infrastructure`` are prohibited.

Planned routers
---------------
``auth.py``
    ``POST /auth/register``, ``POST /auth/login`` — tenant-scoped
    registration and JWT issuance.
``users.py``
    ``GET /users/me``, ``PATCH /users/me`` — authenticated user profile.
``health.py``
    ``GET /health`` — liveness probe used by load balancers and uptime
    monitors.
"""
