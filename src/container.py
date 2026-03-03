"""Application-level dependency injection container.

Architecture decisions
----------------------
* **Registry engine** — ``Singleton``: one SQLAlchemy ``Engine`` is created
  once at startup and reused for the full process lifetime.  Creating engines
  is expensive (thread-pool setup, connection-pool warmup) and the registry
  database is global state — there is no reason to create more than one.

* **Registry repos** — ``Factory``: a new repository instance is produced for
  each injection point.  Repositories are thin wrappers around a session that
  open and close per-operation; the cost of constructing them is negligible and
  keeping them scoped avoids shared mutable state between requests.

* **Auth services** — ``Singleton``: both ``PasswordService``
  and ``JWTService`` are
  stateless after construction.  ``PasswordService`` builds a ``CryptContext``
  once (moderately expensive); ``JWTService`` stores only immutable config.
  Sharing one instance per process is correct and efficient.

* **Tenant engines** — *not* managed here.  Each request carries a
  ``tenant_slug`` that determines which ``{slug}.db`` file to open.  Tenant
  engines are created and cached by FastAPI ``Depends`` factories defined in
  ``src/api/dependencies/``, keeping per-request lifecycle concerns out of the
  container.

Re-exports
----------
``Provide`` and ``inject`` are re-exported so that route modules can import
them from a single location::

    from src.container import inject, Provide, get_container
"""

from __future__ import annotations

from dependency_injector import containers, providers
from dependency_injector.wiring import Provide, inject  # noqa: F401 — re-exported for api/

from src.config import get_settings
from src.infrastructure.database import (  # noqa: F401 — re-exported callable
    create_registry_engine,
    create_tenant_engine,
)
from src.infrastructure.repositories.membership_repository import (
    SQLiteMembershipRepository,  # noqa: F401
)
from src.infrastructure.repositories.tenant_repository import SQLiteTenantRepository
from src.infrastructure.repositories.user_repository import SQLiteUserRepository  # noqa: F401
from src.infrastructure.services.jwt_service import JWTService
from src.infrastructure.services.password_service import PasswordService


class ApplicationContainer(containers.DeclarativeContainer):
    """Root IoC container for the FastAPI multi-tenant application.

    All singleton and factory providers are declared here.  The container is
    wired to ``src.api`` on startup so that ``@inject``-decorated route
    functions receive their dependencies automatically.

    Tenant-scoped resources (per-tenant engines and repos) are intentionally
    excluded — they are resolved per-request via ``FastAPI.Depends``.
    """

    wiring_config = containers.WiringConfiguration(
        packages=["src.api"],
    )

    config = providers.Configuration()

    # ── Registry engine (Singleton) ──────────────────────────────────────────
    # One engine for the shared registry.db that stores the tenant catalogue.
    registry_engine = providers.Singleton(
        create_registry_engine,
        db_path=config.registry_db_path,
    )

    # ── Registry repos (Factory) ─────────────────────────────────────────────
    # New repo instance per injection site; all share the singleton engine.
    tenant_repo = providers.Factory(
        SQLiteTenantRepository,
        engine=registry_engine,
    )

    # ── Auth services (Singletons) ───────────────────────────────────────────
    # Stateless after construction — safe and efficient to share across requests.
    password_service = providers.Singleton(PasswordService)

    jwt_service = providers.Singleton(
        JWTService,
        secret=config.jwt_secret,
        expire_minutes=config.jwt_expire_minutes,
    )


def create_container() -> ApplicationContainer:
    """Build and configure a fresh :class:`ApplicationContainer` from settings.

    Reads the current :class:`~src.config.Settings` singleton and populates the
    container's ``config`` provider so that all downstream providers receive
    the correct runtime values.

    Returns:
        A fully configured :class:`ApplicationContainer` instance ready to
        be used or wired.
    """
    settings = get_settings()
    container = ApplicationContainer()
    container.config.from_dict(
        {
            "registry_db_path": settings.registry_db_path,
            "tenant_db_dir": settings.tenant_db_dir,
            "jwt_secret": settings.jwt_secret,
            "jwt_expire_minutes": settings.jwt_expire_minutes,
        }
    )
    return container


# Module-level container instance — populated by init_container() at startup.
_container: ApplicationContainer | None = None


def get_container() -> ApplicationContainer:
    """Return the process-wide :class:`ApplicationContainer` singleton.

    Raises:
        RuntimeError: If :func:`init_container` has not been called yet.
            This guard prevents silent mis-use when the lifespan event has not
            fired (e.g. in a misconfigured test harness).

    Returns:
        The initialised :class:`ApplicationContainer`.
    """
    if _container is None:
        raise RuntimeError(
            "DI container is not initialised. "
            "Ensure init_container() is called inside the FastAPI lifespan handler "
            "before any route is invoked."
        )
    return _container


def init_container() -> ApplicationContainer:
    """Create, configure, and register the global :class:`ApplicationContainer`.

    Must be called exactly once, typically inside the FastAPI ``lifespan``
    async context manager.  Idempotent in the sense that calling it a second
    time replaces the existing container (useful in tests that need a fresh
    container with different config).

    Returns:
        The newly created and registered :class:`ApplicationContainer`.
    """
    global _container
    _container = create_container()
    return _container
