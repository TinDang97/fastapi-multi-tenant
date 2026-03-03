class DomainError(Exception): ...


class AuthenticationError(DomainError): ...


class TenantNotFoundError(DomainError):
    def __init__(self, slug: str) -> None:
        super().__init__(f"Tenant '{slug}' not found or inactive")
        self.slug = slug


class PermissionDeniedError(DomainError):
    def __init__(self, required: str) -> None:
        super().__init__(f"Requires role: {required}")
        self.required = required


class UserNotFoundError(DomainError): ...


class DuplicateEmailError(DomainError):
    def __init__(self, email: str) -> None:
        super().__init__(f"Email already registered: {email}")
        self.email = email
