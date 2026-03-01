"""Flask web app to send professional bulk job applications via SMTP."""

from __future__ import annotations

import csv
import html
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import Flask, render_template, request
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from email_sender import EmailSender


load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)


def _read_bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _read_int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value and value.isdigit():
        return int(value)
    return default


ALLOWED_CV_EXTENSIONS = {
    "pdf",
    "doc",
    "docx",
    "rtf",
    "txt",
}
ALLOWED_CSV_EXTENSIONS = {"csv"}

MAX_UPLOAD_MB = _read_int_env("APPLICATION_MAX_UPLOAD_MB", 5)
MAX_CONTENT_LENGTH = MAX_UPLOAD_MB * 1024 * 1024
MAX_COMPANY_ROWS = _read_int_env("APPLICATION_MAX_COMPANY_ROWS", 500)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-change-this-secret")


def _is_allowed_file(filename: str, allowed_extensions: set[str]) -> bool:
    if "." not in filename:
        return False
    extension = filename.rsplit(".", 1)[1].lower()
    return extension in allowed_extensions


def _split_recipients(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[;,]", value) if part.strip()]


class SafeFormatDict(dict[str, Any]):
    """Dictionary returning unresolved placeholders for missing keys."""

    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _load_rows_from_csv(csv_path: Path) -> list[dict[str, str]]:
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


def _default_bulk_body_template() -> str:
    default_path = Path("application_body.txt")
    if default_path.is_file():
        return default_path.read_text(encoding="utf-8")
    return (
        "Dear {contact_name},\n\n"
        "I hope you are doing well. I am applying for the {position} role at {company}. "
        "Please find my CV attached.\n\n"
        "Best regards,\n"
        "{your_name}\n"
        "{your_email}\n"
        "{your_phone}\n"
    )


def _default_bulk_html_template() -> str:
    default_html_path = Path("application_body.html")
    if default_html_path.is_file():
        return default_html_path.read_text(encoding="utf-8")

    return (
        "<p>Dear {contact_name},</p>"
        "<p>I hope you are doing well. I am writing to express interest in the <strong>{position}</strong> role at <strong>{company}</strong>.</p>"
        "<p>I have attached my CV for your review. My profile includes experience in Python backend development, API design, and production-ready delivery.</p>"
        "<p>I would value the opportunity to discuss how I can contribute to your team.</p>"
        "<p>Best regards,<br>"
        "{your_name}<br>"
        "{your_email}<br>"
        "{your_phone}<br>"
        "Portfolio: {portfolio}<br>"
        "LinkedIn: {linkedin}</p>"
    )


def _html_to_text(content: str) -> str:
    normalized = re.sub(r"(?i)<br\s*/?>", "\n", content)
    normalized = re.sub(r"(?i)</(p|div|li|h1|h2|h3|h4|h5|h6)>", "\n", normalized)
    normalized = re.sub(r"<[^>]+>", "", normalized)
    normalized = html.unescape(normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def _normalize_subject(subject: str, fallback: str) -> str:
    normalized = re.sub(r"\s+", " ", subject).strip()
    if not normalized:
        normalized = fallback
    return normalized[:180]


def _is_meaningful_html(content: str) -> bool:
    text = _html_to_text(content)
    return bool(text.strip())


def _default_form_state() -> dict[str, Any]:
    return {
        "subject_template": "Application | {position} | {your_name}",
        "body_template_html": _default_bulk_html_template(),
        "delay_seconds": "2",
        "dry_run": False,
    }


def _extract_form_state() -> dict[str, Any]:
    state = _default_form_state()
    state["subject_template"] = request.form.get("subject_template", state["subject_template"]).strip()
    state["body_template_html"] = request.form.get("body_template_html", "").strip() or state["body_template_html"]
    state["delay_seconds"] = request.form.get("delay_seconds", state["delay_seconds"]).strip()
    state["dry_run"] = request.form.get("dry_run") == "on"
    return state


def _render_form(
    bulk_status_message: str | None = None,
    bulk_status_type: str | None = None,
    bulk_results: list[dict[str, str]] | None = None,
    form_state: dict[str, Any] | None = None,
    summary: dict[str, Any] | None = None,
) -> str:
    merged_form_state = _default_form_state()
    if form_state:
        merged_form_state.update(form_state)

    return render_template(
        "application_form.html",
        bulk_status_message=bulk_status_message,
        bulk_status_type=bulk_status_type,
        bulk_results=bulk_results,
        form_state=merged_form_state,
        professional_template_html=_default_bulk_html_template(),
        summary=summary,
        max_upload_mb=MAX_UPLOAD_MB,
        max_company_rows=MAX_COMPANY_ROWS,
    )


@app.route("/", methods=["GET"])
def index():
    return _render_form()


@app.errorhandler(413)
def file_too_large(_: Any):
    return _render_form(
        bulk_status_message=f"Uploaded file is too large. Maximum allowed size is {MAX_UPLOAD_MB} MB.",
        bulk_status_type="danger",
    ), 413


@app.route("/bulk-send", methods=["POST"])
def bulk_send_applications():
    csv_file: FileStorage | None = request.files.get("companies_csv")
    cv_file: FileStorage | None = request.files.get("bulk_cv")

    form_state = _extract_form_state()
    subject_template = str(form_state["subject_template"])
    body_template_html = str(form_state["body_template_html"])
    delay_seconds_text = str(form_state["delay_seconds"])
    dry_run = bool(form_state["dry_run"])

    if not _is_meaningful_html(body_template_html):
        return _render_form(
            bulk_status_message="Email body cannot be empty.",
            bulk_status_type="danger",
            form_state=form_state,
        ), 400

    try:
        delay_seconds = float(delay_seconds_text)
        if delay_seconds < 0:
            raise ValueError
    except ValueError:
        return _render_form(
            bulk_status_message="Delay must be a non-negative number.",
            bulk_status_type="danger",
            form_state=form_state,
        ), 400

    if csv_file is None or not csv_file.filename:
        return _render_form(
            bulk_status_message="Please upload a companies CSV file.",
            bulk_status_type="danger",
            form_state=form_state,
        ), 400

    if cv_file is None or not cv_file.filename:
        return _render_form(
            bulk_status_message="Please upload a CV file.",
            bulk_status_type="danger",
            form_state=form_state,
        ), 400

    if not _is_allowed_file(csv_file.filename, ALLOWED_CSV_EXTENSIONS):
        return _render_form(
            bulk_status_message="Invalid companies file type. Upload a .csv file.",
            bulk_status_type="danger",
            form_state=form_state,
        ), 400

    if not _is_allowed_file(cv_file.filename, ALLOWED_CV_EXTENSIONS):
        allowed = ", ".join(sorted(ALLOWED_CV_EXTENSIONS))
        return _render_form(
            bulk_status_message=f"Invalid CV file type. Allowed: {allowed}",
            bulk_status_type="danger",
            form_state=form_state,
        ), 400

    env_context = {
        "your_name": os.getenv("APPLICANT_NAME", "Your Name"),
        "your_email": os.getenv("APPLICANT_EMAIL", os.getenv("SENDER_EMAIL", "")),
        "your_phone": os.getenv("APPLICANT_PHONE", ""),
        "portfolio": os.getenv("APPLICANT_PORTFOLIO", ""),
        "linkedin": os.getenv("APPLICANT_LINKEDIN", ""),
    }

    bulk_results: list[dict[str, str]] = []
    started_at = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="bulk_application_") as temp_dir:
        temp_path = Path(temp_dir)
        csv_path = temp_path / secure_filename(csv_file.filename)
        cv_path = temp_path / secure_filename(cv_file.filename)
        csv_file.save(csv_path)
        cv_file.save(cv_path)

        try:
            rows = _load_rows_from_csv(csv_path)
        except ValueError as exc:
            return _render_form(
                bulk_status_message=str(exc),
                bulk_status_type="danger",
                form_state=form_state,
            ), 400

        if len(rows) > MAX_COMPANY_ROWS:
            return _render_form(
                bulk_status_message=f"Too many rows. Maximum allowed rows: {MAX_COMPANY_ROWS}.",
                bulk_status_type="danger",
                form_state=form_state,
            ), 400

        try:
            sender = EmailSender()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to initialize email sender")
            return _render_form(
                bulk_status_message=f"SMTP configuration error: {exc}",
                bulk_status_type="danger",
                form_state=form_state,
            ), 500

        for index, row in enumerate(rows, start=1):
            company = row.get("company", "")
            email_field = row.get("email", "")
            recipients = _split_recipients(email_field)

            if not recipients:
                bulk_results.append(
                    {
                        "company": company,
                        "email": email_field,
                        "status": "failed",
                        "detail": "No valid recipient emails found in row.",
                    }
                )
                logger.warning("[Bulk %s/%s] %s -> invalid recipients", index, len(rows), company)
                continue

            context = SafeFormatDict(
                {
                    **env_context,
                    "company": company or "Company",
                    "email": email_field,
                    "contact_name": row.get("contact_name", "Hiring Team"),
                    "position": row.get("position", "Software Developer"),
                    **row,
                }
            )
            try:
                raw_subject = subject_template.format_map(context)
                subject = _normalize_subject(raw_subject, fallback=f"Application - {context['company']}")
                html_body = body_template_html.format_map(context)
                body = _html_to_text(html_body)

                if not body:
                    status = "failed"
                    detail = "Body template rendered empty for this row."
                    bulk_results.append(
                        {
                            "company": company,
                            "email": email_field,
                            "status": status,
                            "detail": detail,
                        }
                    )
                    logger.warning("[Bulk %s/%s] %s -> %s", index, len(rows), company, detail)
                    continue

                if dry_run:
                    status = "dry-run"
                    detail = "Rendered successfully (not sent)"
                else:
                    success, detail = sender.send_email(
                        to_email=recipients,
                        subject=subject,
                        body=body,
                        html_body=html_body,
                        attachment_path=str(cv_path),
                    )
                    status = "sent" if success else "failed"
            except Exception as exc:  # noqa: BLE001
                logger.exception("Unhandled error for company row: %s", company)
                status = "failed"
                detail = f"Unexpected error: {exc}"

            bulk_results.append(
                {
                    "company": company,
                    "email": email_field,
                    "status": status,
                    "detail": detail,
                }
            )

            logger.info("[Bulk %s/%s] %s -> %s | %s", index, len(rows), company, email_field, status)

            if not dry_run and delay_seconds > 0 and index < len(rows):
                time.sleep(delay_seconds)

    sent_count = sum(1 for item in bulk_results if item["status"] == "sent")
    failed_count = sum(1 for item in bulk_results if item["status"] == "failed")
    dry_count = sum(1 for item in bulk_results if item["status"] == "dry-run")
    elapsed_seconds = round(time.perf_counter() - started_at, 2)

    if not dry_run and failed_count:
        bulk_status_message = f"Completed with errors. Sent: {sent_count}, Failed: {failed_count}."
        bulk_status_type = "warning"
    elif dry_run:
        bulk_status_message = f"Dry run completed. Rows processed: {dry_count}."
        bulk_status_type = "info"
    else:
        bulk_status_message = f"Bulk sending completed successfully. Sent: {sent_count}."
        bulk_status_type = "success"

    return _render_form(
        bulk_status_message=bulk_status_message,
        bulk_status_type=bulk_status_type,
        bulk_results=bulk_results,
        form_state=form_state,
        summary={
            "total": len(bulk_results),
            "sent": sent_count,
            "failed": failed_count,
            "dry": dry_count,
            "elapsed": elapsed_seconds,
            "dry_run": dry_run,
        },
    )


if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = _read_int_env("FLASK_PORT", 5000)
    debug = _read_bool_env("FLASK_DEBUG", False)
    app.run(host=host, port=port, debug=debug)
