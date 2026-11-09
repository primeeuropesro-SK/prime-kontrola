"""Optional e-mail delivery of the weekly report (any SMTP server, e.g. Gmail with an app password).

Environment: SMTP_HOST, SMTP_PORT (587), SMTP_USER, SMTP_PASSWORD,
             REPORT_EMAIL_TO (comma separated), REPORT_EMAIL_FROM (default SMTP_USER),
             REPORT_SEND_HOUR (default 7, Bratislava time, Mondays).
"""
import os
import smtplib
import ssl
from email.message import EmailMessage

SEND_HOUR = int(os.environ.get("REPORT_SEND_HOUR", "7"))


def configured():
    return all(os.environ.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "REPORT_EMAIL_TO"))


def send(subject, html_body):
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = os.environ.get("REPORT_EMAIL_FROM") or os.environ["SMTP_USER"]
    msg["To"] = os.environ["REPORT_EMAIL_TO"]
    msg.set_content("Report vyhľadávania je v HTML verzii tohto e-mailu.")
    msg.add_alternative(html_body, subtype="html")
    host, port = os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.starttls(context=ctx)
            s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            s.send_message(msg)
