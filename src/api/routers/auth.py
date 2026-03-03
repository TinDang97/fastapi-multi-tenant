"""Authentication router — registration and login endpoints.

Both endpoints are public (no ``Authorization`` header required).  The active
tenant is resolved from ``request.state.tenant_slug`` via middleware before
any route handler runs.

Routes
------
POST /auth/register
    Self-service registration.  Creates a user with the ``MEMBER`` role.
POST /auth/login
    Credential verification.  Returns a signed JWT on success.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from src.api.dependencies.auth import (
    get_jwt_service,
    get_membership_repo,
    get_tenant_slug,
    get_user_repo,
)
from src.api.schemas.auth import LoginRequest, RegisterRequest, TokenResponse
from src.application.use_cases.login import LoginCommand, LoginUseCase
from src.application.use_cases.register_user import RegisterUserCommand, RegisterUserUseCase
from src.container import get_container
from src.domain.exceptions import AuthenticationError, DuplicateEmailError
from src.infrastructure.repositories.membership_repository import SQLiteMembershipRepository
from src.infrastructure.repositories.user_repository import SQLiteUserRepository
from src.infrastructure.services.jwt_service import JWTService

router = APIRouter(prefix="/auth", tags=["auth"])


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def _build_htmx_auth_response(token: str) -> Response:
    """Return a 200 Response with JWT cookie + HX-Redirect to /users.

    When FastAPI routes return a ``Response`` object directly, the injected
    ``response`` parameter's headers are NOT merged.  All headers and cookies
    must be set on the returned response instance.
    """
    resp = Response(status_code=200)
    resp.set_cookie(
        "access_token",
        token,
        httponly=True,
        samesite="lax",
        max_age=3600,
    )
    resp.headers["HX-Redirect"] = "/users"
    return resp


@router.post("/register", response_model=TokenResponse, status_code=201)
def register(
    request: Request,
    body: RegisterRequest,
    tenant_slug: str = Depends(get_tenant_slug),
    user_repo: SQLiteUserRepository = Depends(get_user_repo),  # noqa: B008
    membership_repo: SQLiteMembershipRepository = Depends(get_membership_repo),  # noqa: B008
    jwt_svc: JWTService = Depends(get_jwt_service),  # noqa: B008
) -> TokenResponse:
    """Register a new user and return a JWT scoped to the current tenant.

    The user is assigned the ``MEMBER`` role automatically.  A 409 is returned
    if the email address is already registered within this tenant's database.

    Args:
        body: Registration payload with ``email`` and ``password``.
        tenant_slug: Active tenant extracted from request state by middleware.
        user_repo: Per-tenant user repository.
        membership_repo: Per-tenant membership repository.
        jwt_svc: JWT issuance service from the DI container.

    Returns:
        :class:`~src.api.schemas.auth.TokenResponse` containing the JWT and
        the new user's identity.

    Raises:
        HTTPException 409: If the email address is already registered.
    """
    password_svc = get_container().password_service()
    use_case = RegisterUserUseCase(user_repo, membership_repo, password_svc)
    try:
        result = use_case.execute(
            RegisterUserCommand(
                email=body.email,
                plain_password=body.password,
                tenant_slug=tenant_slug,
            )
        )
    except DuplicateEmailError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    token = jwt_svc.create_token(result.user.id, tenant_slug, result.membership.role)
    if _is_htmx(request):
        return _build_htmx_auth_response(token)  # type: ignore[return-value]
    return TokenResponse(
        access_token=token,
        user_id=result.user.id,
        email=result.user.email,
        role=str(result.membership.role),
    )


@router.post("/login", response_model=TokenResponse)
def login(  # noqa: PLR0913
    request: Request,
    body: LoginRequest,
    tenant_slug: str = Depends(get_tenant_slug),
    user_repo: SQLiteUserRepository = Depends(get_user_repo),  # noqa: B008
    membership_repo: SQLiteMembershipRepository = Depends(get_membership_repo),  # noqa: B008
    jwt_svc: JWTService = Depends(get_jwt_service),  # noqa: B008
) -> TokenResponse:
    """Authenticate a user and return a JWT scoped to the current tenant.

    Returns 401 for any of: unknown email, wrong password, inactive account,
    or no membership in the active tenant.  The error detail intentionally
    avoids revealing which specific check failed.

    Args:
        body: Login payload with ``email`` and ``password``.
        tenant_slug: Active tenant extracted from request state by middleware.
        user_repo: Per-tenant user repository.
        membership_repo: Per-tenant membership repository.
        jwt_svc: JWT issuance service from the DI container.

    Returns:
        :class:`~src.api.schemas.auth.TokenResponse` containing the JWT and
        the authenticated user's identity.

    Raises:
        HTTPException 401: If credentials are invalid or account is inactive.
    """
    password_svc = get_container().password_service()
    use_case = LoginUseCase(user_repo, membership_repo, password_svc, jwt_svc)
    try:
        result = use_case.execute(
            LoginCommand(
                email=body.email,
                plain_password=body.password,
                tenant_slug=tenant_slug,
            )
        )
    except AuthenticationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    if _is_htmx(request):
        return _build_htmx_auth_response(result.token)  # type: ignore[return-value]
    return TokenResponse(
        access_token=result.token,
        user_id=result.user.id,
        email=result.user.email,
        role=str(result.role),
    )
