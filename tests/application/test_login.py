"""Unit tests for LoginUseCase.

All dependencies are replaced with in-memory fakes.
No database, no network, no infrastructure imports.
Token claim assertions decode the structured fake token instead of a real JWT
so that these tests remain infrastructure-free.  A dedicated sub-test class
uses the real JWTService to verify actual JWT claims.
"""

from __future__ import annotations

import pytest
from jose import jwt

from src.application.use_cases.login import LoginCommand, LoginResult, LoginUseCase
from src.domain.entities import Role, TenantMembership, User
from src.domain.exceptions import AuthenticationError
from src.infrastructure.services.jwt_service import JWTService

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

_JWT_SECRET = "test-only-secret"
_JWT_ALGORITHM = "HS256"


class FakeUserRepo:
    """In-memory UserRepository that satisfies the UserRepository Protocol."""

    def __init__(self, users: list[User] | None = None) -> None:
        self._users: dict[str, User] = {u.id: u for u in (users or [])}
        self._by_email: dict[str, User] = {u.email: u for u in (users or [])}

    def get_by_id(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    def get_by_email(self, email: str) -> User | None:
        return self._by_email.get(email)

    def create(self, user: User) -> User:
        self._users[user.id] = user
        self._by_email[user.email] = user
        return user

    def delete_by_id(self, user_id: str) -> bool:
        return bool(self._users.pop(user_id, None))


class FakeMembershipRepo:
    """In-memory MembershipRepository that satisfies the MembershipRepository Protocol."""

    def __init__(self, memberships: list[TenantMembership] | None = None) -> None:
        self._memberships: list[TenantMembership] = list(memberships or [])

    def get_membership(self, user_id: str, tenant_slug: str) -> TenantMembership | None:
        return next(
            (m for m in self._memberships if m.user_id == user_id and m.tenant_slug == tenant_slug),
            None,
        )

    def assign_role(self, membership: TenantMembership) -> TenantMembership:
        self._memberships.append(membership)
        return membership

    def list_members(self, tenant_slug: str) -> list[TenantMembership]:
        return [m for m in self._memberships if m.tenant_slug == tenant_slug]


class FakePasswordService:
    """Deterministic password service: hash prefixes plain with 'hashed:'."""

    def hash(self, plain_password: str) -> str:
        return f"hashed:{plain_password}"

    def verify(self, plain_password: str, hashed_password: str) -> bool:
        return hashed_password == f"hashed:{plain_password}"


class FakeJWTService:
    """Structured fake that embeds all claims in the token string for easy assertion."""

    def create_token(self, user_id: str, tenant_slug: str, role: Role) -> str:
        return f"token:{user_id}:{tenant_slug}:{role}"

    def decode_token(self, token: str) -> dict[str, str]:
        parts = token.split(":", 3)
        return {"sub": parts[1], "tenant_slug": parts[2], "role": parts[3]}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_user(
    email: str = "user@example.com",
    plain_password: str = "correct",
    is_active: bool = True,
) -> User:
    return User(
        id=User.generate_id(),
        email=email,
        hashed_password=f"hashed:{plain_password}",
        is_active=is_active,
    )


def _make_membership(
    user_id: str,
    tenant_slug: str = "acme",
    role: Role = Role.MEMBER,
) -> TenantMembership:
    return TenantMembership(user_id=user_id, tenant_slug=tenant_slug, role=role)


def _make_use_case(
    users: list[User] | None = None,
    memberships: list[TenantMembership] | None = None,
) -> LoginUseCase:
    return LoginUseCase(
        user_repo=FakeUserRepo(users),
        membership_repo=FakeMembershipRepo(memberships),
        password_service=FakePasswordService(),
        jwt_service=FakeJWTService(),
    )


def _cmd(
    email: str = "user@example.com",
    plain_password: str = "correct",
    tenant_slug: str = "acme",
) -> LoginCommand:
    return LoginCommand(email=email, plain_password=plain_password, tenant_slug=tenant_slug)


# ---------------------------------------------------------------------------
# Tests — happy path
# ---------------------------------------------------------------------------


class TestLoginValidCredentials:
    """Successful login returns a populated LoginResult."""

    def test_login_valid_credentials_returns_token(self) -> None:
        # Arrange
        user = _make_user()
        membership = _make_membership(user.id)
        uc = _make_use_case([user], [membership])

        # Act
        result = uc.execute(_cmd())

        # Assert: token must be a non-empty string
        assert isinstance(result.token, str)
        assert result.token != ""

    def test_login_valid_credentials_returns_user(self) -> None:
        # Arrange
        user = _make_user(email="alice@example.com")
        membership = _make_membership(user.id)
        uc = _make_use_case([user], [membership])

        # Act
        result = uc.execute(_cmd(email="alice@example.com"))

        # Assert: the returned user identity must match what was looked up
        assert result.user.id == user.id
        assert result.user.email == user.email

    def test_login_valid_credentials_returns_correct_role(self) -> None:
        # Arrange
        user = _make_user()
        membership = _make_membership(user.id, role=Role.ADMIN)
        uc = _make_use_case([user], [membership])

        # Act
        result = uc.execute(_cmd())

        # Assert: the role carried in the result must come from the membership record
        assert result.role == Role.ADMIN

    def test_login_result_type_is_login_result(self) -> None:
        # Arrange
        user = _make_user()
        membership = _make_membership(user.id)
        uc = _make_use_case([user], [membership])

        # Act
        result = uc.execute(_cmd())

        # Assert
        assert isinstance(result, LoginResult)

    def test_login_role_from_membership_is_returned_for_all_roles(self) -> None:
        # Arrange + Act + Assert for each defined Role value
        for role in Role:
            user = _make_user(email=f"{role.lower()}@example.com")
            membership = _make_membership(user.id, role=role)
            uc = _make_use_case([user], [membership])
            result = uc.execute(_cmd(email=user.email))
            assert result.role == role


# ---------------------------------------------------------------------------
# Tests — wrong password
# ---------------------------------------------------------------------------


class TestLoginWrongPassword:
    """Submitting an incorrect password must raise AuthenticationError."""

    def test_login_wrong_password_raises(self) -> None:
        # Arrange
        user = _make_user(plain_password="correct")
        membership = _make_membership(user.id)
        uc = _make_use_case([user], [membership])

        # Act + Assert
        with pytest.raises(AuthenticationError):
            uc.execute(_cmd(plain_password="wrong"))

    def test_login_wrong_password_raises_authentication_error_not_subtype(self) -> None:
        # Arrange: ensure the exception type is exactly AuthenticationError (no leak)
        user = _make_user(plain_password="correct")
        membership = _make_membership(user.id)
        uc = _make_use_case([user], [membership])

        # Act + Assert
        with pytest.raises(AuthenticationError) as exc_info:
            uc.execute(_cmd(plain_password="bad"))
        assert type(exc_info.value) is AuthenticationError

    def test_login_empty_password_raises(self) -> None:
        # Arrange
        user = _make_user(plain_password="correct")
        membership = _make_membership(user.id)
        uc = _make_use_case([user], [membership])

        # Act + Assert: empty string must not accidentally match any hash
        with pytest.raises(AuthenticationError):
            uc.execute(_cmd(plain_password=""))


# ---------------------------------------------------------------------------
# Tests — unknown email
# ---------------------------------------------------------------------------


class TestLoginUnknownEmail:
    """Looking up a non-existent email must raise AuthenticationError."""

    def test_login_unknown_email_raises(self) -> None:
        # Arrange: empty repo — no users at all
        uc = _make_use_case(users=[], memberships=[])

        # Act + Assert
        with pytest.raises(AuthenticationError):
            uc.execute(_cmd(email="ghost@example.com"))

    def test_login_unknown_email_raises_authentication_error_not_subtype(self) -> None:
        # Arrange
        uc = _make_use_case(users=[], memberships=[])

        # Act + Assert: must be AuthenticationError, not a more specific exception
        with pytest.raises(AuthenticationError) as exc_info:
            uc.execute(_cmd(email="nobody@example.com"))
        assert type(exc_info.value) is AuthenticationError

    def test_login_unknown_email_does_not_leak_absence(self) -> None:
        """Error type must be identical to wrong-password error to prevent user enumeration."""
        # Arrange
        user = _make_user(plain_password="correct")
        membership = _make_membership(user.id)
        uc_no_user = _make_use_case(users=[], memberships=[])
        uc_wrong_pw = _make_use_case([user], [membership])

        # Act
        with pytest.raises(AuthenticationError) as exc_no_user:
            uc_no_user.execute(_cmd(email="ghost@example.com"))
        with pytest.raises(AuthenticationError) as exc_wrong_pw:
            uc_wrong_pw.execute(_cmd(plain_password="wrong"))

        # Assert: both must surface the exact same exception class
        assert type(exc_no_user.value) is type(exc_wrong_pw.value)


# ---------------------------------------------------------------------------
# Tests — inactive user
# ---------------------------------------------------------------------------


class TestLoginInactiveUser:
    """An inactive user must not be able to authenticate."""

    def test_login_inactive_user_raises(self) -> None:
        # Arrange
        user = _make_user(is_active=False)
        membership = _make_membership(user.id)
        uc = _make_use_case([user], [membership])

        # Act + Assert
        with pytest.raises(AuthenticationError):
            uc.execute(_cmd())

    def test_login_inactive_user_raises_authentication_error_not_subtype(self) -> None:
        # Arrange
        user = _make_user(is_active=False)
        membership = _make_membership(user.id)
        uc = _make_use_case([user], [membership])

        # Act + Assert
        with pytest.raises(AuthenticationError) as exc_info:
            uc.execute(_cmd())
        assert type(exc_info.value) is AuthenticationError

    def test_login_inactive_user_with_correct_password_still_raises(self) -> None:
        # Arrange: correct password but inactive — must still fail
        user = _make_user(plain_password="correct", is_active=False)
        membership = _make_membership(user.id)
        uc = _make_use_case([user], [membership])

        # Act + Assert: is_active check must run before password check (or alongside)
        with pytest.raises(AuthenticationError):
            uc.execute(_cmd(plain_password="correct"))


# ---------------------------------------------------------------------------
# Tests — missing membership
# ---------------------------------------------------------------------------


class TestLoginNoMembership:
    """A user with valid credentials but no membership in the tenant must be rejected."""

    def test_login_no_membership_raises(self) -> None:
        # Arrange: user exists with correct password but has no membership record
        user = _make_user()
        uc = _make_use_case([user], memberships=[])

        # Act + Assert
        with pytest.raises(AuthenticationError):
            uc.execute(_cmd())

    def test_login_membership_in_different_tenant_raises(self) -> None:
        # Arrange: user has membership in "other", not in "acme"
        user = _make_user()
        membership_other = _make_membership(user.id, tenant_slug="other")
        uc = _make_use_case([user], [membership_other])

        # Act + Assert: must not accept membership from a different tenant
        with pytest.raises(AuthenticationError):
            uc.execute(_cmd(tenant_slug="acme"))

    def test_login_no_membership_raises_authentication_error_not_subtype(self) -> None:
        # Arrange
        user = _make_user()
        uc = _make_use_case([user], memberships=[])

        # Act + Assert
        with pytest.raises(AuthenticationError) as exc_info:
            uc.execute(_cmd())
        assert type(exc_info.value) is AuthenticationError


# ---------------------------------------------------------------------------
# Tests — token claims (using real JWTService to decode a real JWT)
# ---------------------------------------------------------------------------


class TestLoginTokenContainsClaims:
    """The issued JWT must carry the expected sub, tenant_slug, and role claims."""

    def _make_uc_with_real_jwt(
        self,
        users: list[User] | None = None,
        memberships: list[TenantMembership] | None = None,
    ) -> LoginUseCase:
        """Build a LoginUseCase backed by the real JWTService."""
        return LoginUseCase(
            user_repo=FakeUserRepo(users),
            membership_repo=FakeMembershipRepo(memberships),
            password_service=FakePasswordService(),
            jwt_service=JWTService(
                secret=_JWT_SECRET,
                expire_minutes=60,
                algorithm=_JWT_ALGORITHM,
            ),
        )

    def test_login_token_contains_sub_claim(self) -> None:
        # Arrange
        user = _make_user()
        membership = _make_membership(user.id)
        uc = self._make_uc_with_real_jwt([user], [membership])

        # Act
        result = uc.execute(_cmd())
        claims = jwt.decode(result.token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])

        # Assert: sub must be the user's ID
        assert claims["sub"] == user.id

    def test_login_token_contains_tenant_slug_claim(self) -> None:
        # Arrange
        user = _make_user()
        membership = _make_membership(user.id, tenant_slug="gamma-corp")
        uc = self._make_uc_with_real_jwt([user], [membership])

        # Act
        result = uc.execute(_cmd(tenant_slug="gamma-corp"))
        claims = jwt.decode(result.token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])

        # Assert
        assert claims["tenant_slug"] == "gamma-corp"

    def test_login_token_contains_role_claim(self) -> None:
        # Arrange
        user = _make_user()
        membership = _make_membership(user.id, role=Role.ADMIN)
        uc = self._make_uc_with_real_jwt([user], [membership])

        # Act
        result = uc.execute(_cmd())
        claims = jwt.decode(result.token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])

        # Assert: role claim must match the membership role string
        assert claims["role"] == str(Role.ADMIN)

    def test_login_token_contains_exp_claim(self) -> None:
        # Arrange
        user = _make_user()
        membership = _make_membership(user.id)
        uc = self._make_uc_with_real_jwt([user], [membership])

        # Act
        result = uc.execute(_cmd())
        claims = jwt.decode(result.token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])

        # Assert: every JWT must include an expiry to prevent tokens from lasting forever
        assert "exp" in claims

    def test_login_token_is_verifiable_with_correct_secret(self) -> None:
        # Arrange
        user = _make_user()
        membership = _make_membership(user.id)
        uc = self._make_uc_with_real_jwt([user], [membership])

        # Act + Assert: decode must not raise
        result = uc.execute(_cmd())
        claims = jwt.decode(result.token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
        assert claims is not None

    def test_login_token_all_required_claims_present(self) -> None:
        # Arrange
        user = _make_user()
        membership = _make_membership(user.id, tenant_slug="delta", role=Role.OWNER)
        uc = self._make_uc_with_real_jwt([user], [membership])

        # Act
        result = uc.execute(_cmd(tenant_slug="delta"))
        claims = jwt.decode(result.token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])

        # Assert all three business-logic claims exist simultaneously
        assert claims["sub"] == user.id
        assert claims["tenant_slug"] == "delta"
        assert claims["role"] == str(Role.OWNER)
