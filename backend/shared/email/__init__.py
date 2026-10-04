"""Email service module with provider abstraction."""

from shared.email.provider import (
    EmailProvider,
    ConsoleEmailProvider,
    FileEmailProvider,
    MockEmailProvider,
    SESEmailProvider,
    get_email_provider,
)

__all__ = [
    "EmailProvider",
    "ConsoleEmailProvider",
    "FileEmailProvider",
    "MockEmailProvider",
    "SESEmailProvider",
    "get_email_provider",
]
