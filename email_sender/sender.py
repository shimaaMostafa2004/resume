"""Production-ready SMTP email sender module."""

from __future__ import annotations

import logging
import mimetypes
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable, Sequence

from dotenv import load_dotenv


class EmailSenderError(Exception):
    """Base exception for email sender errors."""


class ConfigurationError(EmailSenderError):
    """Raised when required configuration is missing or invalid."""


class EmailSendError(EmailSenderError):
    """Raised when sending an email fails."""


class EmailSender:
    """Send emails using SMTP with secure transport.

    Environment variables used by default:
    - SMTP_SERVER
    - SMTP_PORT (optional, default: 587)
    - SMTP_USERNAME (optional, fallback: SENDER_EMAIL)
    - SMTP_PASSWORD (optional, fallback: APP_PASSWORD)
    - SENDER_EMAIL
    - APP_PASSWORD (legacy fallback)
    - SMTP_USE_TLS (optional, default: true)
    - SMTP_USE_SSL (optional, default: false)
    - SMTP_TIMEOUT (optional, default: 30)

    Args:
        sender_email: Email address used as the sender.
        app_password: SMTP password. Kept for backward compatibility.
        smtp_server: SMTP host.
        smtp_port: SMTP port.
        smtp_username: SMTP username for authentication.
        smtp_password: SMTP password for authentication.
        use_tls: Whether to use STARTTLS.
        use_ssl: Whether to connect with implicit SSL.
        timeout: Socket timeout in seconds.
        logger: Optional custom logger instance.
    """

    def __init__(
        self,
        sender_email: str | None = None,
        app_password: str | None = None,
        smtp_server: str | None = None,
        smtp_port: int | None = None,
        smtp_username: str | None = None,
        smtp_password: str | None = None,
        use_tls: bool | None = None,
        use_ssl: bool | None = None,
        timeout: int = 30,
        logger: logging.Logger | None = None,
    ) -> None:
        load_dotenv()

        env_timeout = os.getenv("SMTP_TIMEOUT")
        resolved_timeout = timeout
        if env_timeout and env_timeout.isdigit():
            resolved_timeout = int(env_timeout)

        env_port = os.getenv("SMTP_PORT")
        resolved_port = smtp_port
        if resolved_port is None:
            if env_port and env_port.isdigit():
                resolved_port = int(env_port)
            else:
                resolved_port = 587

        env_use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower()
        env_use_ssl = os.getenv("SMTP_USE_SSL", "false").strip().lower()

        resolved_use_tls = use_tls if use_tls is not None else env_use_tls in {"1", "true", "yes", "on"}
        resolved_use_ssl = use_ssl if use_ssl is not None else env_use_ssl in {"1", "true", "yes", "on"}

        self.sender_email = sender_email or os.getenv("SENDER_EMAIL")
        self.smtp_server = smtp_server or os.getenv("SMTP_SERVER")
        self.smtp_port = resolved_port
        self.smtp_username = smtp_username or os.getenv("SMTP_USERNAME") or self.sender_email
        self.smtp_password = smtp_password or app_password or os.getenv("SMTP_PASSWORD") or os.getenv("APP_PASSWORD")
        self.use_tls = resolved_use_tls
        self.use_ssl = resolved_use_ssl
        self.timeout = resolved_timeout
        self.logger = logger or logging.getLogger(__name__)

        self._validate_configuration()

    def _validate_configuration(self) -> None:
        """Validate required configuration values."""
        if not self.sender_email:
            raise ConfigurationError("Missing required environment variable: SENDER_EMAIL")
        if not self.smtp_server:
            raise ConfigurationError("Missing SMTP server configuration")
        if not self.smtp_username:
            raise ConfigurationError("Missing SMTP username configuration")
        if not self.smtp_password:
            raise ConfigurationError("Missing SMTP password configuration")
        if self.smtp_port <= 0:
            raise ConfigurationError("SMTP port must be a positive integer")
        if self.timeout <= 0:
            raise ConfigurationError("Timeout must be a positive integer")
        if self.use_tls and self.use_ssl:
            raise ConfigurationError("Enable only one of SMTP_USE_TLS or SMTP_USE_SSL")

    @staticmethod
    def _normalize_recipients(to_email: str | Sequence[str]) -> list[str]:
        """Normalize recipient input to a non-empty list of addresses."""
        if isinstance(to_email, str):
            recipients = [to_email.strip()]
        elif isinstance(to_email, Sequence):
            recipients = [email.strip() for email in to_email if str(email).strip()]
        else:
            raise ConfigurationError("to_email must be a string or a sequence of strings")

        recipients = [email for email in recipients if email]
        if not recipients:
            raise ConfigurationError("At least one recipient email is required")
        return recipients

    @staticmethod
    def _normalize_attachments(
        attachment_path: str | Path | Iterable[str | Path] | None,
    ) -> list[Path]:
        """Normalize attachment input to a list of existing files."""
        if attachment_path is None:
            return []

        if isinstance(attachment_path, (str, Path)):
            attachments = [Path(attachment_path)]
        else:
            attachments = [Path(path) for path in attachment_path]

        missing = [str(path) for path in attachments if not path.is_file()]
        if missing:
            raise ConfigurationError(f"Attachment file not found: {', '.join(missing)}")

        return attachments

    def _build_message(
        self,
        to_email: str | Sequence[str],
        subject: str,
        body: str,
        html_body: str | None = None,
        attachment_path: str | Path | Iterable[str | Path] | None = None,
    ) -> EmailMessage:
        """Create an ``EmailMessage`` for plain text, optional HTML, and attachments."""
        recipients = self._normalize_recipients(to_email)
        attachments = self._normalize_attachments(attachment_path)

        message = EmailMessage()
        message["From"] = self.sender_email
        message["To"] = ", ".join(recipients)
        message["Subject"] = subject
        message.set_content(body)

        if html_body:
            message.add_alternative(html_body, subtype="html")

        for file_path in attachments:
            mime_type, _ = mimetypes.guess_type(str(file_path))
            if mime_type:
                maintype, subtype = mime_type.split("/", 1)
            else:
                maintype, subtype = "application", "octet-stream"

            with file_path.open("rb") as file_handle:
                file_data = file_handle.read()

            message.add_attachment(
                file_data,
                maintype=maintype,
                subtype=subtype,
                filename=file_path.name,
            )

        return message

    def send_email(
        self,
        to_email: str | Sequence[str],
        subject: str,
        body: str,
        attachment_path: str | Path | Iterable[str | Path] | None = None,
        html_body: str | None = None,
    ) -> tuple[bool, str]:
        """Send an email using SMTP with optional STARTTLS or SSL.

        Args:
            to_email: One recipient email or multiple recipients.
            subject: Email subject.
            body: Plain text message body.
            attachment_path: Optional single file path or iterable of file paths.
            html_body: Optional HTML body. When provided, email is sent as multipart
                with both plain text and HTML alternatives.

        Returns:
            A tuple ``(success, message)`` describing the outcome.
        """
        try:
            email_message = self._build_message(
                to_email=to_email,
                subject=subject,
                body=body,
                html_body=html_body,
                attachment_path=attachment_path,
            )

            tls_context = ssl.create_default_context()
            if self.use_ssl:
                with smtplib.SMTP_SSL(
                    host=self.smtp_server,
                    port=self.smtp_port,
                    timeout=self.timeout,
                    context=tls_context,
                ) as server:
                    server.ehlo()
                    server.login(self.smtp_username, self.smtp_password)
                    server.send_message(email_message)
            else:
                with smtplib.SMTP(
                    host=self.smtp_server,
                    port=self.smtp_port,
                    timeout=self.timeout,
                ) as server:
                    server.ehlo()
                    if self.use_tls:
                        server.starttls(context=tls_context)
                        server.ehlo()
                    server.login(self.smtp_username, self.smtp_password)
                    server.send_message(email_message)

            recipient_count = len(self._normalize_recipients(to_email))
            success_message = f"Email sent successfully to {recipient_count} recipient(s)."
            self.logger.info(success_message)
            return True, success_message

        except (ConfigurationError, smtplib.SMTPException, OSError, ValueError) as exc:
            error_message = f"Email sending failed: {exc}"
            self.logger.exception(error_message)
            return False, error_message


# Reusable function requested by specification.
def send_email(
    to_email: str | Sequence[str],
    subject: str,
    body: str,
    attachment_path: str | Path | Iterable[str | Path] | None = None,
) -> tuple[bool, str]:
    """Convenience function that sends plain text email using env configuration."""
    sender = EmailSender()
    return sender.send_email(
        to_email=to_email,
        subject=subject,
        body=body,
        attachment_path=attachment_path,
    )
