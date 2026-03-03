"""Unit tests for RegisterUserUseCase.

All dependencies are replaced with in-memory fakes.
No database, no network, no infrastructure imports.
"""

from __future__ import annotations

import pytest

from src.application.use_cases.register_user import RegisterUserCommand, RegisterUserUseCase
from src.domain.entities import Role, TenantMembership, User
from src.domain.exceptions import DuplicateEmailError

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeUserRepo:
    """In-memory UserRepository that satisfies the UserRepository Protocol."""

    def __init__(self) -> None:
        self._users: dict[str, User] = {}

    def get_by_id(self, user_id: str) -> User | None:
        return self._users.get(user_id)

    def get_by_email(self, email: str) -> User | None:
        return next((u for u in self._users.values() if u.email == email), None)

    def create(self, user: User) -> User:
        if self.get_by_email(user.email):
            raise DuplicateEmailError(user.email)
        self._users[user.id] = user
        return user

    def delete_by_id(self, user_id: str) -> bool:
        return bool(self._users.pop(user_id, None))


class FakeMembershipRepo:
    """In-memory MembershipRepository that satisfies the MembershipRepository Protocol."""

    def __init__(self) -> None:
        self._memberships: dict[tuple[str, str], TenantMembership] = {}

    def get_membership(self, user_id: str, tenant_slug: str) -> TenantMembership | None:
        return self._memberships.get((user_id, tenant_slug))

    def assign_role(self, membership: TenantMembership) -> TenantMembership:
        self._memberships[(membership.user_id, membership.tenant_slug)] = membership
        return membership

    def list_members(self, tenant_slug: str) -> list[TenantMembership]:
        return [m for m in self._memberships.values() if m.tenant_slug == tenant_slug]


class FakePasswordService:
    """Deterministic password service: hash prefixes plain with 'hashed:'."""

    def hash(self, plain_password: str) -> str:
        return f"hashed:{plain_password}"

    def verify(self, plain_password: str, hashed_password: str) -> bool:
        return hashed_password == f"hashed:{plain_password}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_use_case(seed_email: str | None = None) -> RegisterUserUseCase:
    """Build a RegisterUserUseCase, optionally pre-seeding an existing user."""
    user_repo = FakeUserRepo()
    if seed_email is not None:
        existing = User(
            id=User.generate_id(),
            email=seed_email,
            hashed_password="hashed:existing",
        )
        user_repo._users[existing.id] = existing  # noqa: SLF001
    return RegisterUserUseCase(
        user_repo=user_repo,
        membership_repo=FakeMembershipRepo(),
        password_service=FakePasswordService(),
    )


def _cmd(
    email: str = "new@example.com",
    plain_password: str = "s3cret",
    tenant_slug: str = "acme",
) -> RegisterUserCommand:
    return RegisterUserCommand(
        email=email,
        plain_password=plain_password,
        tenant_slug=tenant_slug,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestRegisterSuccess:
    """Happy-path registration produces the expected user and membership."""

    def test_register_success_returns_user_with_correct_email(self) -> None:
        # Arrange
        uc = _make_use_case()
        cmd = _cmd(email="alice@example.com", tenant_slug="acme")

        # Act
        result = uc.execute(cmd)

        # Assert
        assert result.user.email == "alice@example.com"

    def test_register_success_assigns_member_role(self) -> None:
        # Arrange
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd())

        # Assert: RegisterUserUseCase must always assign MEMBER, never another role
        assert result.membership.role == Role.MEMBER

    def test_register_success_links_membership_to_created_user(self) -> None:
        # Arrange
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd())

        # Assert: the membership must reference the same user that was created
        assert result.membership.user_id == result.user.id

    def test_register_success_membership_carries_correct_tenant_slug(self) -> None:
        # Arrange
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd(tenant_slug="beta-corp"))

        # Assert
        assert result.membership.tenant_slug == "beta-corp"

    def test_register_success_user_is_active_by_default(self) -> None:
        # Arrange
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd())

        # Assert: newly created users must be active so they can immediately log in
        assert result.user.is_active is True

    def test_register_success_result_exposes_both_user_and_membership(self) -> None:
        # Arrange
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd())

        # Assert: both fields must be populated (not None / default-zero values)
        assert result.user is not None
        assert result.membership is not None


class TestRegisterDuplicateEmail:
    """Registering with an already-taken email must raise DuplicateEmailError."""

    def test_register_duplicate_email_raises_error(self) -> None:
        # Arrange: seed the repository with a user that owns the email
        uc = _make_use_case(seed_email="taken@example.com")
        cmd = _cmd(email="taken@example.com")

        # Act + Assert
        with pytest.raises(DuplicateEmailError):
            uc.execute(cmd)

    def test_register_duplicate_email_error_carries_offending_email(self) -> None:
        # Arrange
        uc = _make_use_case(seed_email="dup@example.com")
        cmd = _cmd(email="dup@example.com")

        # Act + Assert: the exception must surface the email for logging / response
        with pytest.raises(DuplicateEmailError) as exc_info:
            uc.execute(cmd)
        assert exc_info.value.email == "dup@example.com"

    def test_register_duplicate_email_error_message_contains_email(self) -> None:
        # Arrange
        uc = _make_use_case(seed_email="clash@example.com")
        cmd = _cmd(email="clash@example.com")

        # Act + Assert
        with pytest.raises(DuplicateEmailError) as exc_info:
            uc.execute(cmd)
        assert "clash@example.com" in str(exc_info.value)

    def test_register_duplicate_email_is_not_swallowed(self) -> None:
        """DuplicateEmailError must propagate; the use case must not catch it silently."""
        uc = _make_use_case(seed_email="silent@example.com")
        cmd = _cmd(email="silent@example.com")

        # Act + Assert: reaching this line means the error was swallowed — test must fail
        with pytest.raises(DuplicateEmailError):
            uc.execute(cmd)


class TestRegisterPasswordHashing:
    """Passwords must be hashed before storage — never stored in plain text."""

    def test_register_password_is_hashed(self) -> None:
        # Arrange
        plain = "my-plain-password"
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd(plain_password=plain))

        # Assert: stored value must differ from plain text
        assert result.user.hashed_password != plain

    def test_register_hashed_password_matches_fake_hash_convention(self) -> None:
        # Arrange: FakePasswordService produces "hashed:<plain>"
        plain = "supersecret"
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd(plain_password=plain))

        # Assert
        assert result.user.hashed_password == f"hashed:{plain}"

    def test_register_different_passwords_produce_different_hashes(self) -> None:
        # Arrange: two separate use case instances with independent repos
        uc1 = _make_use_case()
        uc2 = _make_use_case()

        # Act
        r1 = uc1.execute(_cmd(email="a@example.com", plain_password="alpha"))
        r2 = uc2.execute(_cmd(email="b@example.com", plain_password="beta"))

        # Assert
        assert r1.user.hashed_password != r2.user.hashed_password


class TestRegisterUserIdGeneration:
    """Each registration must produce a unique, non-empty user identifier."""

    def test_register_generates_user_id(self) -> None:
        # Arrange
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd())

        # Assert: ID must be a non-empty string so it can be used as a DB key
        assert result.user.id != ""
        assert result.user.id is not None

    def test_register_user_id_is_a_string(self) -> None:
        # Arrange
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd())

        # Assert
        assert isinstance(result.user.id, str)

    def test_register_multiple_users_receive_unique_ids(self) -> None:
        # Arrange: shared repo so all registrations go to the same store
        user_repo = FakeUserRepo()
        membership_repo = FakeMembershipRepo()
        password_service = FakePasswordService()
        uc = RegisterUserUseCase(
            user_repo=user_repo,
            membership_repo=membership_repo,
            password_service=password_service,
        )
        ids: set[str] = set()

        # Act: register 10 distinct users
        for i in range(10):
            cmd = RegisterUserCommand(
                email=f"user{i}@example.com",
                plain_password="pass",
                tenant_slug="acme",
            )
            result = uc.execute(cmd)
            ids.add(result.user.id)

        # Assert: all IDs must be distinct — no collisions
        assert len(ids) == 10
