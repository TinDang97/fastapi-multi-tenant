from __future__ import annotations

from passlib.context import CryptContext


class PasswordService:
    """Bcrypt-backed password hashing and verification.

    Instantiated once and shared across the application lifetime via the DI
    container — CryptContext construction is moderately expensive so it must
    not be rebuilt per-request.
    """

    def __init__(self) -> None:
        self._ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

    def hash(self, plain_password: str) -> str:
        """Return a bcrypt hash of *plain_password*.

        Args:
            plain_password: The raw password string to hash.

        Returns:
            A bcrypt-hashed password string suitable for storage.
        """
        return self._ctx.hash(plain_password)

    def verify(self, plain_password: str, hashed_password: str) -> bool:
        """Verify *plain_password* against a stored *hashed_password*.

        Args:
            plain_password: The raw password string supplied by the user.
            hashed_password: The stored bcrypt hash to verify against.

        Returns:
            True if the password matches the hash, False otherwise.
        """
        return self._ctx.verify(plain_password, hashed_password)
