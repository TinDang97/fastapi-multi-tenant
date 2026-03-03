"""Unit tests for infrastructure JWT and password services.

Each test is hermetic — no database, no network, no global state.
"""

from __future__ import annotations

import time

import pytest
from jose import jwt

from src.domain.entities import Role
from src.domain.exceptions import AuthenticationError
from src.infrastructure.services.jwt_service import JWTService
from src.infrastructure.services.password_service import PasswordService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_SECRET = "test-secret-not-for-production"
_ALGORITHM = "HS256"


@pytest.fixture()
def password_service() -> PasswordService:
    return PasswordService()


@pytest.fixture()
def jwt_service() -> JWTService:
    return JWTService(secret=_SECRET, expire_minutes=30, algorithm=_ALGORITHM)


@pytest.fixture()
def jwt_service_short_lived() -> JWTService:
    """JWTService whose tokens expire in 0 minutes (immediately in tests)."""
    return JWTService(secret=_SECRET, expire_minutes=0, algorithm=_ALGORITHM)


# ---------------------------------------------------------------------------
# PasswordService
# ---------------------------------------------------------------------------


class TestPasswordServiceHash:
    def test_hash_returns_string(self, password_service: PasswordService) -> None:
        result = password_service.hash("password123")
        assert isinstance(result, str)

    def test_hash_is_not_plaintext(self, password_service: PasswordService) -> None:
        plain = "password123"
        hashed = password_service.hash(plain)
        assert hashed != plain

    def test_same_password_produces_different_hashes(
        self, password_service: PasswordService
    ) -> None:
        """bcrypt generates a unique salt per call — hashes must differ."""
        plain = "password123"
        assert password_service.hash(plain) != password_service.hash(plain)

    def test_hash_starts_with_bcrypt_prefix(self, password_service: PasswordService) -> None:
        hashed = password_service.hash("password123")
        assert hashed.startswith("$2b$") or hashed.startswith("$2a$")


class TestPasswordServiceVerify:
    def test_correct_password_returns_true(self, password_service: PasswordService) -> None:
        plain = "correct-horse-battery-staple"
        hashed = password_service.hash(plain)
        assert password_service.verify(plain, hashed) is True

    def test_wrong_password_returns_false(self, password_service: PasswordService) -> None:
        hashed = password_service.hash("real-password")
        assert password_service.verify("wrong-password", hashed) is False

    def test_empty_password_against_non_empty_hash_returns_false(
        self, password_service: PasswordService
    ) -> None:
        hashed = password_service.hash("non-empty")
        assert password_service.verify("", hashed) is False


# ---------------------------------------------------------------------------
# JWTService — create_token
# ---------------------------------------------------------------------------


class TestJWTServiceCreateToken:
    def test_returns_string(self, jwt_service: JWTService) -> None:
        token = jwt_service.create_token("user-1", "acme", Role.MEMBER)
        assert isinstance(token, str)

    def test_token_contains_expected_claims(self, jwt_service: JWTService) -> None:
        token = jwt_service.create_token("user-42", "acme", Role.ADMIN)
        claims = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
        assert claims["sub"] == "user-42"
        assert claims["tenant_slug"] == "acme"
        assert claims["role"] == str(Role.ADMIN)

    def test_token_has_exp_claim(self, jwt_service: JWTService) -> None:
        token = jwt_service.create_token("user-1", "acme", Role.OWNER)
        claims = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
        assert "exp" in claims

    def test_exp_is_in_the_future(self, jwt_service: JWTService) -> None:
        token = jwt_service.create_token("user-1", "acme", Role.VIEWER)
        claims = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
        assert claims["exp"] > int(time.time())

    def test_all_role_variants_encode_correctly(self, jwt_service: JWTService) -> None:
        for role in Role:
            token = jwt_service.create_token("uid", "slug", role)
            claims = jwt.decode(token, _SECRET, algorithms=[_ALGORITHM])
            assert claims["role"] == str(role)

    def test_different_users_produce_different_tokens(self, jwt_service: JWTService) -> None:
        t1 = jwt_service.create_token("user-1", "acme", Role.MEMBER)
        t2 = jwt_service.create_token("user-2", "acme", Role.MEMBER)
        assert t1 != t2

    def test_different_tenants_produce_different_tokens(self, jwt_service: JWTService) -> None:
        t1 = jwt_service.create_token("user-1", "acme", Role.MEMBER)
        t2 = jwt_service.create_token("user-1", "globex", Role.MEMBER)
        assert t1 != t2


# ---------------------------------------------------------------------------
# JWTService — decode_token
# ---------------------------------------------------------------------------


class TestJWTServiceDecodeToken:
    def test_decode_returns_dict(self, jwt_service: JWTService) -> None:
        token = jwt_service.create_token("user-1", "acme", Role.MEMBER)
        claims = jwt_service.decode_token(token)
        assert isinstance(claims, dict)

    def test_decode_returns_correct_sub(self, jwt_service: JWTService) -> None:
        token = jwt_service.create_token("user-99", "acme", Role.OWNER)
        claims = jwt_service.decode_token(token)
        assert claims["sub"] == "user-99"

    def test_decode_returns_correct_tenant_slug(self, jwt_service: JWTService) -> None:
        token = jwt_service.create_token("user-1", "globex", Role.ADMIN)
        claims = jwt_service.decode_token(token)
        assert claims["tenant_slug"] == "globex"

    def test_decode_returns_correct_role(self, jwt_service: JWTService) -> None:
        token = jwt_service.create_token("user-1", "acme", Role.VIEWER)
        claims = jwt_service.decode_token(token)
        assert claims["role"] == str(Role.VIEWER)

    def test_tampered_token_raises_authentication_error(
        self, jwt_service: JWTService
    ) -> None:
        token = jwt_service.create_token("user-1", "acme", Role.MEMBER)
        # Flip the last character to corrupt the signature.
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        with pytest.raises(AuthenticationError):
            jwt_service.decode_token(tampered)

    def test_wrong_secret_raises_authentication_error(
        self, jwt_service: JWTService
    ) -> None:
        other_service = JWTService(secret="completely-different", expire_minutes=30)
        token = other_service.create_token("user-1", "acme", Role.MEMBER)
        with pytest.raises(AuthenticationError):
            jwt_service.decode_token(token)

    def test_garbage_string_raises_authentication_error(
        self, jwt_service: JWTService
    ) -> None:
        with pytest.raises(AuthenticationError):
            jwt_service.decode_token("not.a.jwt")

    def test_empty_string_raises_authentication_error(
        self, jwt_service: JWTService
    ) -> None:
        with pytest.raises(AuthenticationError):
            jwt_service.decode_token("")

    def test_expired_token_raises_authentication_error(
        self, jwt_service_short_lived: JWTService
    ) -> None:
        """Token with 0-minute expiry is expired as soon as it is created."""
        token = jwt_service_short_lived.create_token("user-1", "acme", Role.MEMBER)
        # Sleep 1 second to ensure exp is strictly in the past.
        time.sleep(1)
        with pytest.raises(AuthenticationError):
            jwt_service_short_lived.decode_token(token)

    def test_raised_exception_is_domain_error_not_jwt_error(
        self, jwt_service: JWTService
    ) -> None:
        """Callers must never depend on jose internals leaking through."""
        from jose import JWTError

        with pytest.raises(AuthenticationError) as exc_info:
            jwt_service.decode_token("bad.token.here")

        assert not isinstance(exc_info.value, JWTError)
