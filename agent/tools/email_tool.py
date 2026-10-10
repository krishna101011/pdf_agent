"""Email: drafting is free and safe; sending needs your approval."""
from __future__ import annotations

import re
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage

from ..config import Settings
from ..errors import ToolError
from ..safety import find_secrets
from .base import Tool, params

EMAIL_RE = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")


def _check(to: str, subject: str, body: str, secrets: list[str]) -> list[str]:
    recipients = [a.strip() for a in re.split(r"[,;]", str(to)) if a.strip()]
    if not recipients:
        raise ToolError("Who should the email go to?")
    if len(recipients) > 5:
        raise ToolError("I only send to up to 5 people at once.")
    for a in recipients:
        if not EMAIL_RE.match(a):
            raise ToolError(f"'{a}' isn't a valid email address.")
    if "\n" in subject or "\r" in subject:
        raise ToolError("The subject must be one line.")
    if not str(subject).strip() or not str(body).strip():
        raise ToolError("The email needs a subject and a message.")
    if find_secrets(f"{subject}\n{body}", secrets):
        raise ToolError("The email text looks like it contains a password or key, so I won't use it.")
    return recipients


def make_email_tools(settings: Settings) -> list[Tool]:
    drafts = settings.workspace / "emails"

    def draft_email(to: str, subject: str, body: str) -> str:
        _check(to, subject, body, settings.secrets())
        drafts.mkdir(parents=True, exist_ok=True)
        name = datetime.now().strftime("%Y%m%d-%H%M%S") + ".txt"
        (drafts / name).write_text(f"To: {to}\nSubject: {subject}\n\n{body}\n", encoding="utf-8")
        return f"Draft saved as workspace/emails/{name}. Nothing was sent."

    def preview(args: dict) -> str:
        return (f"Send this email from {settings.smtp_user or '(no sender set)'}:\n"
                f"To: {args.get('to')}\nSubject: {args.get('subject')}\n\n{args.get('body')}")

    def send_email(to: str, subject: str, body: str) -> str:
        if not (settings.smtp_user and settings.smtp_password):
            raise ToolError("Email isn't set up. Fill in SMTP_USER and SMTP_PASSWORD in .env "
                            "(for Gmail use an App Password).")
        recipients = _check(to, subject, body, settings.secrets())
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = settings.smtp_user, ", ".join(recipients), subject
        msg.set_content(body)
        try:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port,
                                  context=ssl.create_default_context(), timeout=30) as server:
                server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
        except smtplib.SMTPAuthenticationError:
            raise ToolError("The email server rejected the login. For Gmail you need an App Password, "
                            "not your normal password.")
        except (smtplib.SMTPException, OSError) as e:
            raise ToolError(f"Couldn't send the email ({e}).")
        return f"Email sent to {', '.join(recipients)}."

    fields = {"to": {"type": "string", "description": "One or more addresses separated by commas"},
              "subject": {"type": "string"}, "body": {"type": "string"}}
    return [
        Tool("draft_email", "Write an email and save it as a draft file. Sends nothing.",
             params(fields, ["to", "subject", "body"]), draft_email),
        Tool("send_email", "Send an email. The user must approve first. Only send after the user asked.",
             params(fields, ["to", "subject", "body"]), send_email, needs_approval=True, preview=preview),
    ]
