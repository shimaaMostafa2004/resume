"""CLI tool to send CV applications to multiple companies from a CSV file."""

from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from email_sender import EmailSender


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("company_mailer")


@dataclass
class SendResult:
    company: str
    email: str
    status: str
    detail: str


class SafeFormatDict(dict[str, Any]):
    """Dictionary returning unresolved placeholders for missing keys."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _split_recipients(value: str) -> list[str]:
    recipients = [part.strip() for part in re.split(r"[;,]", value) if part.strip()]
    return recipients


def _load_template(template_file: Path | None, fallback: str) -> str:
    if template_file is None:
        return fallback
    return template_file.read_text(encoding="utf-8")


def _load_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.is_file():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("CSV must include headers")

        required = {"company", "email"}
        missing = required - {field.strip().lower() for field in reader.fieldnames}
        if missing:
            raise ValueError(f"CSV missing required columns: {', '.join(sorted(missing))}")

        normalized_rows: list[dict[str, str]] = []
        for row in reader:
            normalized = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
            if not normalized.get("company") or not normalized.get("email"):
                continue
            normalized_rows.append(normalized)

    if not normalized_rows:
        raise ValueError("No valid rows found in CSV (need company and email values)")

    return normalized_rows


def _write_results(output_path: Path, results: list[SendResult]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["company", "email", "status", "detail"])
        for result in results:
            writer.writerow([result.company, result.email, result.status, result.detail])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send personalized job application emails to companies from a CSV file.",
    )
    parser.add_argument(
        "--csv",
        dest="csv_path",
        default="companies.csv",
        help="Path to CSV file containing company and email columns.",
    )
    parser.add_argument(
        "--attachment",
        default="cv.pdf",
        help="Path to CV file to attach.",
    )
    parser.add_argument(
        "--subject-template",
        default="Application for {position} - {your_name}",
        help="Subject template. Supports placeholders from CSV columns and env values.",
    )
    parser.add_argument(
        "--body-template-file",
        default="application_body.txt",
        help="Text body template file.",
    )
    parser.add_argument(
        "--html-template-file",
        default="application_body.html",
        help="Optional HTML body template file.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=2.0,
        help="Delay between sends to reduce SMTP throttling.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview rendered emails without sending.",
    )
    parser.add_argument(
        "--output",
        default="send_results.csv",
        help="CSV output path for send results.",
    )
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = parse_args()

    csv_path = Path(args.csv_path)
    attachment_path = Path(args.attachment)
    body_template_file = Path(args.body_template_file)
    html_template_file = Path(args.html_template_file)
    output_path = Path(args.output)

    if not attachment_path.is_file():
        logger.error("Attachment file not found: %s", attachment_path)
        return 1

    try:
        rows = _load_rows(csv_path)
    except (FileNotFoundError, ValueError) as exc:
        logger.error(str(exc))
        return 1

    fallback_body = (
        "Dear {contact_name},\n\n"
        "I hope you are doing well. I am interested in opportunities at {company}. "
        "Please find my CV attached for your review.\n\n"
        "Best regards,\n"
        "{your_name}\n"
        "{your_email}\n"
        "{your_phone}\n"
    )

    try:
        text_template = _load_template(body_template_file, fallback_body)
    except OSError as exc:
        logger.error("Failed to read body template: %s", exc)
        return 1

    html_template: str | None = None
    if html_template_file.is_file():
        try:
            html_template = _load_template(html_template_file, "")
        except OSError as exc:
            logger.error("Failed to read HTML template: %s", exc)
            return 1

    env_context = {
        "your_name": os.getenv("APPLICANT_NAME", "Your Name"),
        "your_email": os.getenv("APPLICANT_EMAIL", os.getenv("SENDER_EMAIL", "")),
        "your_phone": os.getenv("APPLICANT_PHONE", ""),
        "portfolio": os.getenv("APPLICANT_PORTFOLIO", ""),
        "linkedin": os.getenv("APPLICANT_LINKEDIN", ""),
    }

    sender = EmailSender()
    results: list[SendResult] = []

    for index, row in enumerate(rows, start=1):
        company = row.get("company", "")
        email_field = row.get("email", "")
        recipients = _split_recipients(email_field)

        context = SafeFormatDict({**env_context, **row})
        subject = args.subject_template.format_map(context)
        body = text_template.format_map(context)
        html_body = html_template.format_map(context) if html_template else None

        if args.dry_run:
            logger.info("[DRY-RUN] %s -> %s | %s", company, ", ".join(recipients), subject)
            results.append(
                SendResult(
                    company=company,
                    email=email_field,
                    status="dry-run",
                    detail="Rendered successfully (not sent)",
                )
            )
            continue

        success, detail = sender.send_email(
            to_email=recipients,
            subject=subject,
            body=body,
            html_body=html_body,
            attachment_path=str(attachment_path),
        )

        status = "sent" if success else "failed"
        logger.info("[%s/%s] %s -> %s | %s", index, len(rows), company, ", ".join(recipients), status)
        results.append(SendResult(company=company, email=email_field, status=status, detail=detail))

        if index < len(rows) and args.delay_seconds > 0:
            time.sleep(args.delay_seconds)

    _write_results(output_path=output_path, results=results)

    sent_count = sum(1 for result in results if result.status == "sent")
    failed_count = sum(1 for result in results if result.status == "failed")
    dry_count = sum(1 for result in results if result.status == "dry-run")

    logger.info(
        "Completed. sent=%s failed=%s dry_run=%s output=%s",
        sent_count,
        failed_count,
        dry_count,
        output_path,
    )

    if failed_count > 0 and not args.dry_run:
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        raise SystemExit(130)
