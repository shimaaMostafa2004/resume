"""Public API for the email_sender package."""

from .sender import ConfigurationError, EmailSendError, EmailSender, EmailSenderError, send_email

__all__ = [
    "EmailSender",
    "EmailSenderError",
    "ConfigurationError",
    "EmailSendError",
    "send_email",
]
