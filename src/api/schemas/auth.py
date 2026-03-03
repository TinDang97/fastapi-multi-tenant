"""Pydantic request and response schemas for authentication endpoints.

These schemas define the JSON contract between clients and ``/auth`` routes.
They are deliberately decoupled from domain entities and infrastructure
models — conversion happens in the router layer.

Schemas never import from ``src.domain`` or ``src.infrastructure``.
"""

from __future__ import annotations

from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    """Payload for ``POST /auth/register``.

    Attributes:
        email: Valid RFC-5322 email address for the new account.
        password: Plain-text password (hashed server-side; never stored raw).
    """

    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    """Payload for ``POST /auth/login``.

    Attributes:
        email: Email address of the account to authenticate.
        password: Plain-text password to verify against the stored hash.
    """

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Response body for successful authentication.

    Attributes:
        access_token: Signed JWT for subsequent authenticated requests.
        token_type: OAuth2 token type — always ``"bearer"``.
        user_id: UUID string identifying the authenticated user.
        email: Email address of the authenticated user.
        role: Role name string (``OWNER``, ``ADMIN``, ``MEMBER``, or ``VIEWER``).
    """

    access_token: str
    token_type: str = "bearer"  # noqa: S105
    user_id: str
    email: str
    role: str
