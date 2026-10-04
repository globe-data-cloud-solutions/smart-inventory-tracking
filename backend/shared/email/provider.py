"""Email provider abstraction for local development and AWS SES production.

This module enables dependency injection of different email implementations:
- ConsoleEmailProvider: prints emails to console (local dev)
- FileEmailProvider: writes emails to files (local dev)
- MockEmailProvider: stores in memory (testing)
- SESEmailProvider: sends via AWS SES (production - added later)

Usage:
    from shared.email.provider import get_email_provider
    email_provider = get_email_provider()  # Selected via ENVIRONMENT config
    await email_provider.send(to, subject, html)
"""

from abc import ABC, abstractmethod
from typing import List, Optional
import os
from datetime import datetime


class EmailProvider(ABC):
    """Abstract base class for email providers."""

    @abstractmethod
    async def send(
        self,
        to: str,
        subject: str,
        html: str,
        text: Optional[str] = None,
        from_email: Optional[str] = None,
    ) -> bool:
        """Send a single email.

        Args:
            to: recipient email address
            subject: email subject
            html: HTML email body
            text: plain text fallback
            from_email: sender email (uses default if not provided)

        Returns:
            True if sent successfully, False otherwise
        """
        pass

    @abstractmethod
    async def send_bulk(
        self,
        recipients: List[dict],  # [{"email": "...", "name": "..."}, ...]
        subject: str,
        html: str,
        text: Optional[str] = None,
    ) -> int:
        """Send email to multiple recipients.

        Args:
            recipients: list of {"email": "...", "name": "..."} dicts
            subject: email subject
            html: HTML email body
            text: plain text fallback

        Returns:
            number of emails sent successfully
        """
        pass


class ConsoleEmailProvider(EmailProvider):
    """Prints emails to console for local development."""

    async def send(
        self,
        to: str,
        subject: str,
        html: str,
        text: Optional[str] = None,
        from_email: Optional[str] = None,
    ) -> bool:
        """Print email to console."""
        from_addr = from_email or os.environ.get("SES_FROM_EMAIL", "noreply@smart-platform.com")
        print(f"\n{'='*80}")
        print(f"EMAIL SENT (Console Provider)")
        print(f"{'='*80}")
        print(f"From: {from_addr}")
        print(f"To: {to}")
        print(f"Subject: {subject}")
        print(f"{'='*80}")
        print(f"HTML:\n{html}")
        if text:
            print(f"\nPlain Text:\n{text}")
        print(f"{'='*80}\n")
        return True

    async def send_bulk(
        self,
        recipients: List[dict],
        subject: str,
        html: str,
        text: Optional[str] = None,
    ) -> int:
        """Print bulk emails to console."""
        count = 0
        for recipient in recipients:
            success = await self.send(
                to=recipient.get("email", ""),
                subject=subject,
                html=html,
                text=text,
            )
            if success:
                count += 1
        return count


class FileEmailProvider(EmailProvider):
    """Writes emails to files for local development and inspection."""

    def __init__(self, email_dir: str = "/tmp/emails"):
        """Initialize file provider.

        Args:
            email_dir: directory to store email files
        """
        self.email_dir = email_dir
        os.makedirs(email_dir, exist_ok=True)

    async def send(
        self,
        to: str,
        subject: str,
        html: str,
        text: Optional[str] = None,
        from_email: Optional[str] = None,
    ) -> bool:
        """Write email to file."""
        try:
            from_addr = from_email or os.environ.get("SES_FROM_EMAIL", "noreply@smart-platform.com")
            timestamp = datetime.now().isoformat()
            filename = f"{self.email_dir}/{timestamp.replace(':', '-')}_{to.replace('@', '_at_')}.txt"

            content = f"""From: {from_addr}
To: {to}
Subject: {subject}
Timestamp: {timestamp}

HTML:
{html}
"""
            if text:
                content += f"\nPlain Text:\n{text}"

            with open(filename, "w", encoding="utf-8") as f:
                f.write(content)

            print(f"✓ Email written to {filename}")
            return True
        except Exception as e:
            print(f"✗ Failed to write email: {e}")
            return False

    async def send_bulk(
        self,
        recipients: List[dict],
        subject: str,
        html: str,
        text: Optional[str] = None,
    ) -> int:
        """Write bulk emails to files."""
        count = 0
        for recipient in recipients:
            success = await self.send(
                to=recipient.get("email", ""),
                subject=subject,
                html=html,
                text=text,
            )
            if success:
                count += 1
        return count


class MockEmailProvider(EmailProvider):
    """In-memory email provider for testing."""

    def __init__(self):
        """Initialize mock provider."""
        self.sent_emails: List[dict] = []

    async def send(
        self,
        to: str,
        subject: str,
        html: str,
        text: Optional[str] = None,
        from_email: Optional[str] = None,
    ) -> bool:
        """Store email in memory."""
        from_addr = from_email or os.environ.get("SES_FROM_EMAIL", "noreply@smart-platform.com")
        self.sent_emails.append({
            "from": from_addr,
            "to": to,
            "subject": subject,
            "html": html,
            "text": text,
            "timestamp": datetime.now().isoformat(),
        })
        return True

    async def send_bulk(
        self,
        recipients: List[dict],
        subject: str,
        html: str,
        text: Optional[str] = None,
    ) -> int:
        """Store bulk emails in memory."""
        count = 0
        for recipient in recipients:
            success = await self.send(
                to=recipient.get("email", ""),
                subject=subject,
                html=html,
                text=text,
            )
            if success:
                count += 1
        return count

    def get_sent(self) -> List[dict]:
        """Return all sent emails (for testing)."""
        return self.sent_emails

    def clear(self) -> None:
        """Clear sent emails (for test cleanup)."""
        self.sent_emails = []


class SESEmailProvider(EmailProvider):
    """AWS SES email provider for production."""

    def __init__(self):
        """Initialize SES provider."""
        try:
            import boto3
            self.client = boto3.client(
                "ses",
                region_name=os.environ.get("AWS_SES_REGION", "us-east-1"),
            )
        except ImportError:
            raise RuntimeError(
                "boto3 is required for SESEmailProvider. "
                "Install it with: pip install boto3"
            )

    async def send(
        self,
        to: str,
        subject: str,
        html: str,
        text: Optional[str] = None,
        from_email: Optional[str] = None,
    ) -> bool:
        """Send email via AWS SES."""
        try:
            from_addr = from_email or os.environ.get("SES_FROM_EMAIL", "noreply@smart-platform.com")
            self.client.send_email(
                Source=from_addr,
                Destination={"ToAddresses": [to]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Html": {"Data": html, "Charset": "UTF-8"},
                        **({"Text": {"Data": text, "Charset": "UTF-8"}} if text else {}),
                    },
                },
            )
            return True
        except Exception as e:
            print(f"Failed to send email via SES: {e}")
            return False

    async def send_bulk(
        self,
        recipients: List[dict],
        subject: str,
        html: str,
        text: Optional[str] = None,
    ) -> int:
        """Send bulk emails via AWS SES.

        Note: SES sendBulkEmail is not used here. Instead, we send individual
        emails in sequence. For true bulk sending, use SES templated emails
        or implement sendBulkEmail with proper handling of per-recipient customization.
        """
        count = 0
        for recipient in recipients:
            success = await self.send(
                to=recipient.get("email", ""),
                subject=subject,
                html=html,
                text=text,
            )
            if success:
                count += 1
        return count


def get_email_provider() -> EmailProvider:
    """Factory function to get the configured email provider.

    Provider is selected based on ENVIRONMENT variable:
    - 'local' or 'console': ConsoleEmailProvider (prints to console)
    - 'file': FileEmailProvider (writes to /tmp/emails/)
    - 'mock': MockEmailProvider (stores in memory for testing)
    - 'aws' or 'prod': SESEmailProvider (sends via AWS SES)
    - default: ConsoleEmailProvider

    Returns:
        An instance of the configured EmailProvider
    """
    env = os.environ.get("ENVIRONMENT", "local").lower()
    email_provider_override = os.environ.get("EMAIL_PROVIDER", "").lower()

    # Explicit EMAIL_PROVIDER config takes precedence
    if email_provider_override:
        if email_provider_override == "console":
            return ConsoleEmailProvider()
        elif email_provider_override == "file":
            return FileEmailProvider()
        elif email_provider_override == "mock":
            return MockEmailProvider()
        elif email_provider_override == "ses":
            return SESEmailProvider()

    # Fall back to ENVIRONMENT-based selection
    if env in ("prod", "aws", "production"):
        return SESEmailProvider()
    elif env == "file":
        return FileEmailProvider()
    elif env == "mock":
        return MockEmailProvider()
    else:  # local, dev, default
        return ConsoleEmailProvider()
