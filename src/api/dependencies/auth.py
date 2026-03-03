"""FastAPI dependency factories for JWT authentication and RBAC.

Each function in this module is a FastAPI dependency.  Dependencies are
resolved per-request via ``Depends()``.  The chain is:

    get_tenant_slug
        └─ get_tenant_engine
               ├─ get_user_repo
               └─ get_membership_repo

    get_jwt_service (singleton from DI container)

    get_current_user   ← composes get_tenant_slug + get_jwt_service
                                + get_user_repo + get_membership_repo

    require_role(...)  ← wraps get_current_user with a role check

Layer contract
--------------
This file is part of ``api/``.  It may import from ``application/`` ports
and ``domain/`` entities.  Direct infrastructure imports are permitted here
*only* because these are the concrete dependency factories — the wiring
point between layers.  Route modules must import only the dependency
functions, not the infrastructure classes directly.
"""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import Engine

from src.config import get_settings
from src.container import get_container
from src.domain.entities import ROLE_LEVEL, Role, User
from src.domain.exceptions import AuthenticationError
from src.infrastructure.database import create_tenant_engine
from src.infrastructure.repositories.membership_repository import SQLiteMembershipRepository
from src.infrastructure.repositories.user_repository import SQLiteUserRepository
from src.infrastructure.services.jwt_service import JWTService


def get_tenant_slug(request: Request) -> str:
    """Extract the tenant slug from ``request.state``.

    ``TenantMiddleware`` sets this value before any route handler runs.

    Args:
        request: The current HTTP request.

    Returns:
        The tenant slug string attached by the middleware.
    """
    return cast(str, request.state.tenant_slug)


def get_tenant_engine(tenant_slug: str = Depends(get_tenant_slug)) -> Engine:
    """Create a per-request SQLite engine for the active tenant's database.

    Each call produces a new ``Engine`` pointing at
    ``{tenant_db_dir}/{tenant_slug}.db``.  Engine creation is cheap for
    SQLite; the underlying connection pool is per-engine and scoped to the
    request.

    Args:
        tenant_slug: Slug resolved from the request state.

    Returns:
        A synchronous :class:`sqlalchemy.Engine` for the tenant database.
    """
    settings = get_settings()
    return create_tenant_engine(settings.tenant_db_dir, tenant_slug)


def get_user_repo(engine: Engine = Depends(get_tenant_engine)) -> SQLiteUserRepository:  # noqa: B008
    """Instantiate a user repository bound to the tenant engine.

    Args:
        engine: Per-request tenant engine produced by :func:`get_tenant_engine`.

    Returns:
        A :class:`~src.infrastructure.repositories.user_repository.SQLiteUserRepository`.
    """
    return SQLiteUserRepository(engine)


def get_membership_repo(
    engine: Engine = Depends(get_tenant_engine),  # noqa: B008
) -> SQLiteMembershipRepository:
    """Instantiate a membership repository bound to the tenant engine.

    Args:
        engine: Per-request tenant engine produced by :func:`get_tenant_engine`.

    Returns:
        A ``SQLiteMembershipRepository`` instance for the active tenant.
    """
    return SQLiteMembershipRepository(engine)


def get_jwt_service() -> JWTService:
    """Retrieve the process-wide ``JWTService`` singleton from the DI container.

    Returns:
        The singleton :class:`~src.infrastructure.services.jwt_service.JWTService`.
    """
    return get_container().jwt_service()


async def get_current_user(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    tenant_slug: str = Depends(get_tenant_slug),
    jwt_svc: JWTService = Depends(get_jwt_service),  # noqa: B008
    user_repo: SQLiteUserRepository = Depends(get_user_repo),  # noqa: B008
    membership_repo: SQLiteMembershipRepository = Depends(get_membership_repo),  # noqa: B008
) -> tuple[User, Role]:
    """Decode the JWT, verify the user is active, and confirm tenant membership.

    Checks the ``Authorization: Bearer <token>`` header first, then falls back
    to the ``access_token`` cookie set by the HTMX login flow.

    Validation steps performed in order:

    1. Token is present (header or cookie).
    2. Token signature and expiry are valid (``JWTService.decode_token``).
    3. Token's ``tenant_slug`` claim matches the request's active tenant.
    4. User identified by ``sub`` claim exists and is active.
    5. Role is extracted from the ``role`` claim.

    Args:
        request: The current HTTP request (for cookie fallback).
        authorization: Value of the ``Authorization`` HTTP header.
        tenant_slug: Active tenant slug from request state.
        jwt_svc: JWT verification service.
        user_repo: User repository scoped to the tenant database.
        membership_repo: Membership repository scoped to the tenant database.

    Returns:
        A ``(User, Role)`` tuple for the authenticated principal.

    Raises:
        HTTPException 401: For any authentication failure.
    """
    token: str | None = None
    if authorization is not None:
        token = authorization.removeprefix("Bearer ").strip()
    else:
        token = request.cookies.get("access_token")

    if token is None:
        raise HTTPException(status_code=401, detail="Authorization header required")

    try:
        claims = jwt_svc.decode_token(token)
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    if claims.get("tenant_slug") != tenant_slug:
        raise HTTPException(status_code=401, detail="Token not valid for this tenant")

    user = user_repo.get_by_id(claims["sub"])
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")

    role = Role(claims["role"])
    return user, role


def require_role(*minimum_roles: Role) -> Any:
    """Return a ``Depends`` that enforces a minimum role requirement.

    Computes the minimum role level from the supplied roles and raises
    ``HTTP 403`` if the authenticated user's role falls below that level.
    The full ``(User, Role)`` tuple is returned on success so callers can
    destructure the current principal without a second dependency.

    Uses the role hierarchy defined in ``ROLE_LEVEL``:
        OWNER (3) > ADMIN (2) > MEMBER (1) > VIEWER (0)

    An OWNER always passes an ADMIN check.  A VIEWER never passes a MEMBER
    check.

    Args:
        *minimum_roles: One or more :class:`~src.domain.entities.Role` values.
            The dependency passes if the user satisfies the *lowest* of the
            supplied levels — useful for ``require_role(Role.ADMIN, Role.OWNER)``
            patterns (though ``require_role(Role.ADMIN)`` is equivalent in
            that case).

    Returns:
        A ``fastapi.Depends`` wrapping the inner ``checker`` coroutine.

    Example::

        # As a route dependency (no return value needed):
        @router.delete("/resource", dependencies=[require_role(Role.ADMIN)])
        async def delete_resource() -> ...: ...

        # As an injected parameter (user/role available in handler):
        @router.get("/resource")
        async def get_resource(
            current: tuple[User, Role] = require_role(Role.VIEWER),
        ) -> ...:
            user, role = current
    """
    min_level = min(ROLE_LEVEL[r] for r in minimum_roles)

    async def checker(
        current: tuple[User, Role] = Depends(get_current_user),
    ) -> tuple[User, Role]:
        user, role = current
        if ROLE_LEVEL[role] < min_level:
            # Find the Role name that matches the computed minimum level for a
            # descriptive error message.
            required_name = next(r.value for r in Role if ROLE_LEVEL[r] == min_level)
            raise HTTPException(status_code=403, detail=f"Requires role: {required_name}")
        return user, role

    return Depends(checker)
