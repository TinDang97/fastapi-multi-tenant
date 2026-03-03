"""Parametrized exhaustive coverage of role_satisfies() across all 4x4 combinations.

The complementary class-based tests in ``tests/test_domain.py`` cover the same
function through prose-style methods (owner_satisfies_all, viewer_satisfies_only_viewer,
etc.).  This module adds the full 16-row parametrized matrix so that every
(user_role, required_role) pair is an individually reported test case.
That makes regressions trivial to pinpoint when a single level mapping changes.
"""

from __future__ import annotations

import pytest

from src.domain.entities import Role, role_satisfies


@pytest.mark.parametrize(
    "user_role,required_role,expected",
    [
        # OWNER satisfies every role including itself
        (Role.OWNER, Role.OWNER, True),
        (Role.OWNER, Role.ADMIN, True),
        (Role.OWNER, Role.MEMBER, True),
        (Role.OWNER, Role.VIEWER, True),
        # ADMIN satisfies ADMIN and below, not OWNER
        (Role.ADMIN, Role.OWNER, False),
        (Role.ADMIN, Role.ADMIN, True),
        (Role.ADMIN, Role.MEMBER, True),
        (Role.ADMIN, Role.VIEWER, True),
        # MEMBER satisfies MEMBER and VIEWER only
        (Role.MEMBER, Role.OWNER, False),
        (Role.MEMBER, Role.ADMIN, False),
        (Role.MEMBER, Role.MEMBER, True),
        (Role.MEMBER, Role.VIEWER, True),
        # VIEWER satisfies only itself
        (Role.VIEWER, Role.OWNER, False),
        (Role.VIEWER, Role.ADMIN, False),
        (Role.VIEWER, Role.MEMBER, False),
        (Role.VIEWER, Role.VIEWER, True),
    ],
)
def test_role_satisfies(user_role: Role, required_role: Role, expected: bool) -> None:
    """role_satisfies returns the correct boolean for all 16 (user, required) pairs."""
    assert role_satisfies(user_role, required_role) == expected
