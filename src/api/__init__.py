"""FastAPI routers, request/response schemas, middleware, and dependency factories.

This package is the outermost layer of the clean architecture.  It may import
from ``src.application`` (use cases, commands, queries) but must never import
directly from ``src.domain`` or ``src.infrastructure``.

Sub-packages
------------
``routers/``
    FastAPI ``APIRouter`` instances, one module per resource area.
``schemas/``
    Pydantic request and response models scoped to the API surface.
``middleware/``
    ASGI middleware classes (tenant resolution, request ID, etc.).
``dependencies/``
    FastAPI ``Depends`` factories — especially per-request tenant engine
    and repository injection that sits outside the DI container.
"""
