from __future__ import annotations

from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt

from src.domain.entities import Role
from src.domain.exceptions import AuthenticationError


class JWTService:
    """Stateless HS256 JWT issuance and verification.

    Secrets and expiry are injected at construction time — never hardcoded.
    The algorithm defaults to HS256 but is configurable so callers can
    enforce RS256 or ES256 if key-rotation requirements change.

    Args:
        secret: HMAC signing secret (or PEM key for asymmetric algorithms).
        expire_minutes: Token lifetime in minutes from issuance.
        algorithm: jose algorithm identifier. Defaults to ``"HS256"``.
    """

    def __init__(
        self,
        secret: str,
        expire_minutes: int,
        algorithm: str = "HS256",
    ) -> None:
        self._secret = secret
        self._expire_minutes = expire_minutes
        self._algorithm = algorithm

    def create_token(self, user_id: str, tenant_slug: str, role: Role) -> str:
        """Issue a signed JWT carrying identity and tenant context.

        Claims:
            - ``sub``: *user_id* — standard JWT subject.
            - ``tenant_slug``: identifies the tenant schema for routing.
            - ``role``: the user's role string within that tenant.
            - ``exp``: absolute expiry timestamp (UTC).

        Args:
            user_id: Unique identifier of the authenticated user.
            tenant_slug: Slug of the tenant the token is scoped to.
            role: The user's :class:`~src.domain.entities.Role` within the tenant.

        Returns:
            A compact, URL-safe JWT string.
        """
        payload: dict[str, str | datetime] = {
            "sub": user_id,
            "tenant_slug": tenant_slug,
            "role": str(role),
            "exp": datetime.now(UTC) + timedelta(minutes=self._expire_minutes),
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def decode_token(self, token: str) -> dict[str, str]:
        """Decode and verify a JWT, returning its raw claims.

        Validates signature, expiry, and algorithm. All ``JWTError`` variants
        (expired, tampered, wrong algorithm) are translated into
        :class:`~src.domain.exceptions.AuthenticationError` so callers never
        depend on the ``jose`` library's exception hierarchy.

        Args:
            token: Compact JWT string to verify.

        Returns:
            The decoded claims dictionary (str keys, str values for
            ``sub``, ``tenant_slug``, and ``role``).

        Raises:
            AuthenticationError: When the token is invalid, expired, or
                cannot be verified with the configured secret/algorithm.
        """
        try:
            return jwt.decode(token, self._secret, algorithms=[self._algorithm])
        except JWTError as exc:
            raise AuthenticationError("Invalid or expired token") from exc
