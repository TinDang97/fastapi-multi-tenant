"""Unit tests for CreateUserUseCase.

All dependencies are replaced with in-memory fakes.
No database, no network, no infrastructure imports.
"""

from __future__ import annotations

import pytest

from src.application.use_cases.create_user import CreateUserCommand, CreateUserResult, CreateUserUseCase
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


def _make_use_case(seed_email: str | None = None) -> CreateUserUseCase:
    """Build a CreateUserUseCase, optionally pre-seeding one existing user."""
    user_repo = FakeUserRepo()
    if seed_email is not None:
        existing = User(
            id=User.generate_id(),
            email=seed_email,
            hashed_password="hashed:existing",
        )
        user_repo._users[existing.id] = existing  # noqa: SLF001
    return CreateUserUseCase(
        user_repo=user_repo,
        membership_repo=FakeMembershipRepo(),
        password_service=FakePasswordService(),
    )


def _cmd(
    email: str = "new@example.com",
    plain_password: str = "s3cret",
    role: Role = Role.MEMBER,
    tenant_slug: str = "acme",
) -> CreateUserCommand:
    return CreateUserCommand(
        email=email,
        plain_password=plain_password,
        role=role,
        tenant_slug=tenant_slug,
    )


# ---------------------------------------------------------------------------
# Tests — success: ADMIN role
# ---------------------------------------------------------------------------


class TestCreateUserSuccess:
    """Happy-path creation returns a populated CreateUserResult."""

    def test_create_user_success_returns_result_type(self) -> None:
        # Arrange
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd(role=Role.ADMIN))

        # Assert
        assert isinstance(result, CreateUserResult)

    def test_create_user_success_result_contains_user(self) -> None:
        # Arrange
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd(email="admin@acme.com", role=Role.ADMIN))

        # Assert: user field must be populated with the persisted entity
        assert result.user is not None
        assert result.user.email == "admin@acme.com"

    def test_create_user_success_result_contains_membership(self) -> None:
        # Arrange
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd(role=Role.ADMIN))

        # Assert: membership field must be populated
        assert result.membership is not None

    def test_create_user_success_user_is_active_by_default(self) -> None:
        # Arrange
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd(role=Role.ADMIN))

        # Assert: admin-created users must be immediately active
        assert result.user.is_active is True

    def test_create_user_success_membership_links_to_user(self) -> None:
        # Arrange
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd(role=Role.ADMIN))

        # Assert: membership.user_id must reference the newly created user
        assert result.membership.user_id == result.user.id

    def test_create_user_success_membership_carries_tenant_slug(self) -> None:
        # Arrange
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd(role=Role.ADMIN, tenant_slug="enterprise"))

        # Assert
        assert result.membership.tenant_slug == "enterprise"


# ---------------------------------------------------------------------------
# Tests — duplicate email
# ---------------------------------------------------------------------------


class TestCreateUserDuplicateEmail:
    """Creating a user with a taken email must raise DuplicateEmailError."""

    def test_create_user_duplicate_email_raises(self) -> None:
        # Arrange: seed an existing user that occupies the email
        uc = _make_use_case(seed_email="taken@acme.com")
        cmd = _cmd(email="taken@acme.com", role=Role.ADMIN)

        # Act + Assert
        with pytest.raises(DuplicateEmailError):
            uc.execute(cmd)

    def test_create_user_duplicate_email_error_carries_offending_email(self) -> None:
        # Arrange
        uc = _make_use_case(seed_email="dup@acme.com")
        cmd = _cmd(email="dup@acme.com", role=Role.MEMBER)

        # Act + Assert: error must expose the email for logging/response construction
        with pytest.raises(DuplicateEmailError) as exc_info:
            uc.execute(cmd)
        assert exc_info.value.email == "dup@acme.com"

    def test_create_user_duplicate_email_error_message_contains_email(self) -> None:
        # Arrange
        uc = _make_use_case(seed_email="clash@acme.com")
        cmd = _cmd(email="clash@acme.com")

        # Act + Assert
        with pytest.raises(DuplicateEmailError) as exc_info:
            uc.execute(cmd)
        assert "clash@acme.com" in str(exc_info.value)

    def test_create_user_duplicate_email_is_not_swallowed(self) -> None:
        """DuplicateEmailError must propagate; the use case must not catch it silently."""
        uc = _make_use_case(seed_email="silent@acme.com")
        cmd = _cmd(email="silent@acme.com")

        with pytest.raises(DuplicateEmailError):
            uc.execute(cmd)


# ---------------------------------------------------------------------------
# Tests — correct role assignment
# ---------------------------------------------------------------------------


class TestCreateUserAssignsCorrectRole:
    """The role provided in the command must be the role stored in the membership."""

    def test_create_user_assigns_viewer_role(self) -> None:
        # Arrange
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd(role=Role.VIEWER))

        # Assert: VIEWER role must be preserved exactly — use case must not override it
        assert result.membership.role == Role.VIEWER

    def test_create_user_assigns_member_role(self) -> None:
        # Arrange
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd(role=Role.MEMBER))

        # Assert
        assert result.membership.role == Role.MEMBER

    def test_create_user_assigns_admin_role(self) -> None:
        # Arrange
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd(role=Role.ADMIN))

        # Assert
        assert result.membership.role == Role.ADMIN

    def test_create_user_assigns_owner_role(self) -> None:
        # Arrange
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd(role=Role.OWNER))

        # Assert
        assert result.membership.role == Role.OWNER

    def test_create_user_assigns_correct_role_for_all_roles(self) -> None:
        # Arrange + Act + Assert: parametrised across every Role member
        for i, role in enumerate(Role):
            uc = _make_use_case()
            result = uc.execute(_cmd(email=f"user{i}@acme.com", role=role))
            assert result.membership.role == role, f"Expected {role}, got {result.membership.role}"

    def test_create_user_role_not_silently_overridden_to_member(self) -> None:
        """Ensure CreateUserUseCase does not fall back to MEMBER the way RegisterUserUseCase does."""
        # Arrange
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd(role=Role.OWNER))

        # Assert: must NOT be MEMBER (which is the RegisterUserUseCase default)
        assert result.membership.role != Role.MEMBER
        assert result.membership.role == Role.OWNER


# ---------------------------------------------------------------------------
# Tests — user ID generation
# ---------------------------------------------------------------------------


class TestCreateUserGeneratesId:
    """Each created user must receive a unique, non-empty identifier."""

    def test_create_user_generates_id(self) -> None:
        # Arrange
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd())

        # Assert: ID must be a non-empty string
        assert result.user.id != ""
        assert result.user.id is not None

    def test_create_user_id_is_a_string(self) -> None:
        # Arrange
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd())

        # Assert
        assert isinstance(result.user.id, str)

    def test_create_user_generates_unique_id_per_creation(self) -> None:
        # Arrange: shared repos so all creations hit the same store
        user_repo = FakeUserRepo()
        membership_repo = FakeMembershipRepo()
        password_service = FakePasswordService()
        uc = CreateUserUseCase(
            user_repo=user_repo,
            membership_repo=membership_repo,
            password_service=password_service,
        )
        ids: set[str] = set()

        # Act: create 10 distinct users
        for i in range(10):
            cmd = CreateUserCommand(
                email=f"user{i}@acme.com",
                plain_password="pass",
                role=Role.MEMBER,
                tenant_slug="acme",
            )
            result = uc.execute(cmd)
            ids.add(result.user.id)

        # Assert: all IDs must be distinct — no collisions
        assert len(ids) == 10


# ---------------------------------------------------------------------------
# Tests — password hashing
# ---------------------------------------------------------------------------


class TestCreateUserPasswordHashing:
    """Passwords must be hashed before storage — never stored in plain text."""

    def test_create_user_password_is_hashed(self) -> None:
        # Arrange
        plain = "my-plain-password"
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd(plain_password=plain))

        # Assert: stored value must differ from the plain text supplied
        assert result.user.hashed_password != plain

    def test_create_user_hashed_password_matches_fake_hash_convention(self) -> None:
        # Arrange: FakePasswordService produces "hashed:<plain>"
        plain = "supersecret"
        uc = _make_use_case()

        # Act
        result = uc.execute(_cmd(plain_password=plain))

        # Assert
        assert result.user.hashed_password == f"hashed:{plain}"
