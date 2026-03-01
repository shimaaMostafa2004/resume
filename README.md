# SMTP Email Sender (Python 3)

Production-ready Python module for sending email with your own SMTP credentials using secure transport, environment variables, logging, and proper exception handling.

## Features

- Python 3 project structure
- Uses `smtplib` and `email` standard libraries
- Works with Gmail, Outlook, Zoho, custom domain SMTP, and other SMTP providers
- Environment variables via `.env`
- Class-based API: `EmailSender`
- Reusable function: `send_email(to_email, subject, body, attachment_path=None)`
- Plain text and HTML support
- Attachments (single or multiple files)
- Multiple recipients support
- Timeout handling
- Structured logging instead of `print`
- Clear success/failure return messages
- Web form to submit job applications with CV attachment
- CLI tool to send CV applications to multiple companies from CSV

## Project Structure

```text
.
├── email_sender/
│   ├── __init__.py
│   └── sender.py
├── .env.example
├── application_form_app.py
├── send_company_applications.py
├── companies.example.csv
├── application_body.txt
├── main.py
├── README.md
├── requirements.txt
└── templates/
    └── application_form.html
```

## Setup

1. Create and activate a virtual environment (recommended).
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create a `.env` file in the project root by copying `.env.example`:

```bash
cp .env.example .env
```

4. Update `.env` values:

```env
SENDER_EMAIL=your_email@yourdomain.com
SMTP_SERVER=smtp.yourprovider.com
SMTP_PORT=587
SMTP_USERNAME=your_email@yourdomain.com
SMTP_PASSWORD=your_mail_password_or_app_password
SMTP_USE_TLS=true
SMTP_USE_SSL=false
SMTP_TIMEOUT=30
APPLICATION_RECEIVER_EMAIL=hr@yourdomain.com
FLASK_HOST=127.0.0.1
FLASK_PORT=5000
FLASK_DEBUG=false
APPLICATION_MAX_UPLOAD_MB=5
APPLICATION_MAX_COMPANY_ROWS=500
APPLICANT_NAME=Your Name
APPLICANT_EMAIL=your_email@yourdomain.com
APPLICANT_PHONE=+971000000000
APPLICANT_PORTFOLIO=https://yourportfolio.com
APPLICANT_LINKEDIN=https://www.linkedin.com/in/your-profile
```

## Provider Notes

- Use the SMTP details from your mail provider (host, port, username, password).
- For most providers, use `SMTP_PORT=587` with `SMTP_USE_TLS=true`.
- If your provider requires implicit SSL, use `SMTP_PORT=465` and `SMTP_USE_SSL=true`.
- Keep only one of `SMTP_USE_TLS` or `SMTP_USE_SSL` set to `true`.

### Gmail App Password (optional, only if you use Gmail)

1. Go to your Google Account: `https://myaccount.google.com/`
2. Open **Security** and enable **2-Step Verification**.
3. Open **App passwords** and generate a password for Mail.
4. Use that value as `SMTP_PASSWORD` (or `APP_PASSWORD` legacy fallback).

## Usage

### Reusable function (plain text)

```python
from email_sender import send_email

success, message = send_email(
    to_email="recipient@example.com",
    subject="Test Email",
    body="Hello from Python!",
    attachment_path=None,
)
print(success, message)
```

### Class-based usage (plain + HTML + attachments + multiple recipients)

```python
from email_sender import EmailSender

sender = EmailSender(timeout=30)

success, message = sender.send_email(
    to_email=["user1@example.com", "user2@example.com"],
    subject="Monthly Report",
    body="Plain text fallback body.",
    html_body="<h1>Monthly Report</h1><p>See attached report.</p>",
    attachment_path=["report.pdf", "summary.csv"],
)
print(success, message)
```

### Example SMTP values by provider

- Gmail: `SMTP_SERVER=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_USE_TLS=true`
- Outlook/Office365: `SMTP_SERVER=smtp.office365.com`, `SMTP_PORT=587`, `SMTP_USE_TLS=true`
- Yahoo: `SMTP_SERVER=smtp.mail.yahoo.com`, `SMTP_PORT=587`, `SMTP_USE_TLS=true`

## Run example script

```bash
python main.py
```

## Run CV application form

1. Ensure `APPLICATION_RECEIVER_EMAIL` is set in `.env`.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Run the Flask app:

```bash
python application_form_app.py
```

4. Open in browser:

```text
http://127.0.0.1:5000
```

The web app now provides a Bootstrap-styled **bulk upload form**:

- Upload `companies.csv` + CV file
- Write email content in a rich text editor (Quill)
- Send personalized emails to each company row

For bulk upload form, required CSV columns are:

- `company`
- `email`

## Upload to Server (Deploy)

### Option A: Direct Python deploy (Ubuntu VPS)

1. Upload project files to server (SCP/SFTP/Git clone).
2. Create virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

3. Create `.env` on server with production values.
4. Run with Gunicorn:

```bash
gunicorn --bind 0.0.0.0:5000 --workers 2 --threads 4 --timeout 120 wsgi:application
```

### Option B: Docker deploy (recommended)

1. Build image:

```bash
docker build -t application-sender:latest .
```

2. Run container with env file:

```bash
docker run -d --name application-sender -p 5000:5000 --env-file .env application-sender:latest
```

3. Open app in browser:

```text
http://<server-ip>:5000
```

### Optional: Nginx reverse proxy

Use Nginx in front of Gunicorn for HTTPS, domain routing, and better production hardening.

## Developer tool: send applications to companies (CSV)

1. Copy example CSV and update it with real companies:

```bash
copy companies.example.csv companies.csv
```

2. Put your CV file in project root (for example `cv.pdf`) and update `application_body.txt`.

3. Dry run first (no emails sent):

```bash
python send_company_applications.py --csv companies.csv --attachment cv.pdf --dry-run
```

4. Send for real:

```bash
python send_company_applications.py --csv companies.csv --attachment cv.pdf --delay-seconds 3
```

5. Check output report in `send_results.csv`.

Supported CSV columns:

- Required: `company`, `email`
- Optional placeholders: `contact_name`, `position`, `city`, and any custom column

Template placeholders supported in subject/body:

- From `.env`: `{your_name}`, `{your_email}`, `{your_phone}`, `{portfolio}`, `{linkedin}`
- From CSV row: `{company}`, `{email}`, `{contact_name}`, `{position}`, etc.

## Security Best Practices

- Never hardcode credentials.
- Keep `.env` out of source control.
- Use provider-approved SMTP credentials (app passwords where required).
- Rotate passwords/app passwords when needed.
- Use TLS (`STARTTLS`) or SSL for SMTP connections.
