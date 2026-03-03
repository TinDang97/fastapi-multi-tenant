from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class Role(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"


ROLE_LEVEL: dict[Role, int] = {
    Role.OWNER: 3,
    Role.ADMIN: 2,
    Role.MEMBER: 1,
    Role.VIEWER: 0,
}


def role_satisfies(user_role: Role, required_role: Role) -> bool:
    """Return True if user_role meets or exceeds required_role in hierarchy."""
    return ROLE_LEVEL[user_role] >= ROLE_LEVEL[required_role]


@dataclass
class Tenant:
    slug: str
    name: str
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class User:
    id: str
    email: str
    hashed_password: str
    is_active: bool = True

    @staticmethod
    def generate_id() -> str:
        return str(uuid.uuid4())


@dataclass
class TenantMembership:
    user_id: str
    tenant_slug: str
    role: Role
