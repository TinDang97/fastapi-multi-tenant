"""Users router — HTMX-driven user management endpoints.

All responses are HTML (``TemplateResponse`` or ``Response``).  RBAC is
enforced at the route level via :func:`~src.api.dependencies.auth.require_role`.

Routes
------
GET  /users
    List all users in the tenant.  Requires VIEWER or above.
POST /users
    Admin creates a user with an explicit role.  Requires ADMIN or above.
DELETE /users/{user_id}
    Admin deletes a user from the tenant database.  Requires ADMIN or above.
    Returns 200 with an empty body on success, 404 if the user does not exist.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from src.api.dependencies.auth import (
    get_membership_repo,
    get_tenant_slug,
    get_user_repo,
    require_role,
)
from src.api.templates import templates
from src.application.use_cases.create_user import CreateUserCommand, CreateUserUseCase
from src.application.use_cases.list_users import ListUsersUseCase
from src.container import get_container
from src.domain.entities import Role, User
from src.domain.exceptions import DuplicateEmailError
from src.infrastructure.repositories.membership_repository import SQLiteMembershipRepository
from src.infrastructure.repositories.user_repository import SQLiteUserRepository

router = APIRouter(tags=["users"])


@router.get("/users", response_class=HTMLResponse)
def list_users(
    request: Request,
    current: tuple[User, Role] = require_role(Role.VIEWER),
    user_repo: SQLiteUserRepository = Depends(get_user_repo),  # noqa: B008
    membership_repo: SQLiteMembershipRepository = Depends(get_membership_repo),  # noqa: B008
    tenant_slug: str = Depends(get_tenant_slug),
) -> HTMLResponse:
    """Render the full users list page for the active tenant.

    Requires the authenticated user to hold at minimum the ``VIEWER`` role.

    Args:
        request: Current HTTP request (passed through to template context).
        current: ``(user, role)`` tuple from the RBAC dependency.
        user_repo: Per-tenant user repository.
        membership_repo: Per-tenant membership repository.
        tenant_slug: Active tenant from request state.

    Returns:
        Full ``users/list.html`` page rendered with the current user list.
    """
    user, role = current
    use_case = ListUsersUseCase(user_repo, membership_repo)
    users_with_roles = use_case.execute(tenant_slug)
    # Flatten UserWithRole → plain dict so templates access user.email / user.role directly.
    flat_users = [
        {
            "id": uwr.user.id,
            "email": uwr.user.email,
            "is_active": uwr.user.is_active,
            "role": str(uwr.role),
        }
        for uwr in users_with_roles
    ]
    # Pass raw token so base.html hx-headers sets Authorization for HTMX requests.
    raw_token = (
        request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        or request.cookies.get("access_token", "")
    )
    current_user_ctx = {"email": user.email, "role": str(role), "id": user.id}
    return templates.TemplateResponse(
        request,
        "users/list.html",
        {
            "users": flat_users,
            "current_user": current_user_ctx,
            "tenant_slug": tenant_slug,
            "token": raw_token,
        },
    )


@router.post("/users", response_class=HTMLResponse, status_code=201)
def create_user(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(...),
    current: tuple[User, Role] = require_role(Role.ADMIN),
    user_repo: SQLiteUserRepository = Depends(get_user_repo),  # noqa: B008
    membership_repo: SQLiteMembershipRepository = Depends(get_membership_repo),  # noqa: B008
    tenant_slug: str = Depends(get_tenant_slug),
) -> HTMLResponse:
    """Create a new user with the specified role and return the table row partial.

    Intended for HTMX ``hx-post`` — returns a ``users/_row.html`` partial
    that the client can swap into the existing table.  Requires ADMIN or above.

    Args:
        request: Current HTTP request (passed through to template context).
        email: New user's email address (form field).
        password: New user's plain-text password (form field).
        role: Role to assign — must be a valid :class:`~src.domain.entities.Role` value.
        current: ``(user, role)`` tuple from the RBAC dependency.
        user_repo: Per-tenant user repository.
        membership_repo: Per-tenant membership repository.
        tenant_slug: Active tenant from request state.

    Returns:
        ``users/_row.html`` partial for HTMX swap on success.

    Raises:
        HTTPException 409: If the email address is already registered.
        HTTPException 422: If ``role`` is not a valid :class:`~src.domain.entities.Role`.
    """
    _, _ = current

    try:
        parsed_role = Role(role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid role: {role}") from exc

    password_svc = get_container().password_service()
    use_case = CreateUserUseCase(user_repo, membership_repo, password_svc)
    try:
        result = use_case.execute(
            CreateUserCommand(
                email=email,
                plain_password=password,
                role=parsed_role,
                tenant_slug=tenant_slug,
            )
        )
    except DuplicateEmailError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    actor, actor_role = current
    raw_token = (
        request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        or request.cookies.get("access_token", "")
    )
    return templates.TemplateResponse(
        request,
        "users/_row.html",
        {
            "user": {
                "id": result.user.id,
                "email": result.user.email,
                "is_active": result.user.is_active,
                "role": str(result.membership.role),
            },
            "current_user": {"email": actor.email, "role": str(actor_role), "id": actor.id},
            "token": raw_token,
        },
        status_code=201,
    )


@router.delete("/users/{user_id}")
def delete_user(
    user_id: str,
    current: tuple[User, Role] = require_role(Role.ADMIN),
    user_repo: SQLiteUserRepository = Depends(get_user_repo),  # noqa: B008
) -> Response:
    """Delete a user from the active tenant's database.

    Returns an empty 200 response on success so HTMX can remove the row.
    Requires ADMIN or above.

    Args:
        user_id: UUID string of the user to delete.
        current: ``(user, role)`` tuple from the RBAC dependency.
        user_repo: Per-tenant user repository.

    Returns:
        Empty :class:`fastapi.Response` with status 200.

    Raises:
        HTTPException 404: If no user with ``user_id`` exists.
    """
    _, _ = current

    deleted = user_repo.delete_by_id(user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
    return Response(status_code=200)
