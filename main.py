"""Example usage script for the SMTP EmailSender module."""

from __future__ import annotations

import logging

from email_sender import EmailSender, send_email


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


def run_examples() -> None:
    """Run plain text and HTML email examples with SMTP credentials from .env."""

    sender = EmailSender(timeout=30)

    plain_success, plain_message = sender.send_email(
        to_email=["recipient1@example.com", "recipient2@example.com"],
        subject="Plain Text Email Example",
        body="Hello,\n\nThis is a plain text email sent via Gmail SMTP.\n",
        attachment_path=None,
    )
    logging.info("Plain email status: %s | %s", plain_success, plain_message)

    html_success, html_message = sender.send_email(
        to_email="recipient@example.com",
        subject="HTML Email Example",
        body="This is the plain text fallback version.",
        html_body="""
        <html>
          <body>
            <h2>Hello from Python</h2>
                        <p>This is an <strong>HTML</strong> email sent using SMTP.</p>
          </body>
        </html>
        """,
        attachment_path="sample_attachment.txt",  # Optional: replace with a real file path.
    )
    logging.info("HTML email status: %s | %s", html_success, html_message)

    # Example of the reusable convenience function requested in the spec.
    quick_success, quick_message = send_email(
        to_email="recipient@example.com",
        subject="Quick Send Function",
        body="This message is sent with the reusable send_email() function.",
        attachment_path=None,
    )
    logging.info("Quick send status: %s | %s", quick_success, quick_message)


if __name__ == "__main__":
    run_examples()
