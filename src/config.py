"""Application settings loaded from environment variables.

All secrets and environment-specific values are read from ``os.environ``
at first access.  The module-level singleton is lazily constructed on first
call to :func:`get_settings` and reused for the lifetime of the process.

Override any value by setting the corresponding environment variable before
starting the server, e.g.::

    JWT_SECRET=my-prod-secret REGISTRY_DB_PATH=/var/data/registry.db uvicorn ...

No secrets are hardcoded here — the defaults are development-only fallbacks
that are clearly labelled as unsafe for production.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class Settings:
    """Typed application configuration derived from environment variables.

    Attributes:
        registry_db_path: Filesystem path to the registry SQLite database.
        tenant_db_dir: Directory that holds per-tenant SQLite database files.
        jwt_secret: HMAC secret used to sign and verify JWT tokens.
            Must be replaced with a cryptographically strong value in
            production — the default is intentionally weak.
        jwt_expire_minutes: Token lifetime in minutes from the time of
            issuance.
        env: Deployment environment label (e.g. ``"development"``,
            ``"production"``).  Used for logging and feature flags.
    """

    registry_db_path: str = field(
        default_factory=lambda: os.environ.get("REGISTRY_DB_PATH", "data/registry.db")
    )
    tenant_db_dir: str = field(
        default_factory=lambda: os.environ.get("TENANT_DB_DIR", "data/tenants")
    )
    jwt_secret: str = field(
        default_factory=lambda: os.environ.get(
            "JWT_SECRET", "dev-secret-change-in-production"
        )
    )
    jwt_expire_minutes: int = field(
        default_factory=lambda: int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))
    )
    env: str = field(
        default_factory=lambda: os.environ.get("ENV", "development")
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton.

    The instance is created once on first call using values present in
    ``os.environ`` at that point.  Subsequent calls return the same object
    without re-reading the environment.

    Returns:
        The application :class:`Settings` instance.
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
