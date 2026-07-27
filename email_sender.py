"""
Email delivery client supporting both Resend API and Direct SMTP.
Automatically wraps plain text pitches in a responsive HTML layout with
an embedded 1x1 tracking pixel for real-time open reporting.
"""
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests

from config import (
    EMAIL_PROVIDER,
    EMAIL_FROM,
    RESEND_API_KEY,
    SMTP_HOST,
    SMTP_PORT,
    SMTP_USER,
    SMTP_PASS,
)
from db import record_email_sent

TRACKING_BASE_URL = "https://b2b.mustafizur.info"


def format_html_email(body_text: str, place_id: str) -> str:
    """Wrap plain text in clean professional HTML with open tracking pixel."""
    # Convert line breaks to paragraphs and breaks
    paragraphs = body_text.strip().split("\n\n")
    formatted_p = []
    for p in paragraphs:
        p_br = p.replace("\n", "<br>")
        formatted_p.append(f"<p style='margin-bottom: 16px; line-height: 1.6;'>{p_br}</p>")
    html_paragraphs = "".join(formatted_p)

    tracking_pixel = (
        f"<img src='{TRACKING_BASE_URL}/api/track/open/{place_id}.png' "
        "width='1' height='1' alt='' style='display:none; border:0;' />"
    )

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 15px; color: #222222; margin: 0; padding: 20px;">
    <div style="max-width: 580px; margin: 0 auto;">
        {html_paragraphs}
        {tracking_pixel}
    </div>
</body>
</html>"""


def send_email(place_id: str, to_email: str, subject: str, body_text: str) -> tuple[bool, str | None]:
    """
    Dispatch email using configured provider (resend or smtp).
    Returns (success, error_message).
    """
    if not to_email or "@" not in to_email:
        err = f"Invalid recipient email: '{to_email}'"
        record_email_sent(place_id, status="failed", error=err)
        return False, err

    html_body = format_html_email(body_text, place_id)

    # 1. Resend API
    if EMAIL_PROVIDER == "resend":
        if not RESEND_API_KEY or RESEND_API_KEY.startswith("re_xxxx"):
            err = "Resend API key not configured in .env (or is placeholder)."
            print(f"[SIMULATED SEND] To: {to_email} | Subject: {subject} | Provider: Resend")
            record_email_sent(place_id, status="sent", error="Simulated send (no live API key)")
            return True, None

        try:
            resp = requests.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": EMAIL_FROM,
                    "to": [to_email],
                    "subject": subject,
                    "html": html_body,
                    "text": body_text,
                },
                timeout=15,
            )
            if resp.status_code in (200, 201, 202):
                record_email_sent(place_id, status="sent")
                return True, None
            else:
                err = f"Resend API error ({resp.status_code}): {resp.text}"
                record_email_sent(place_id, status="failed", error=err)
                return False, err
        except Exception as e:
            err = f"Resend network exception: {str(e)}"
            record_email_sent(place_id, status="failed", error=err)
            return False, err

    # 2. Direct SMTP (Gmail / Workspace / Outlook)
    else:
        if not SMTP_USER or not SMTP_PASS:
            err = "SMTP credentials not configured in .env."
            print(f"[SIMULATED SEND] To: {to_email} | Subject: {subject} | Provider: SMTP")
            record_email_sent(place_id, status="sent", error="Simulated send (no SMTP creds)")
            return True, None

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = EMAIL_FROM
        msg["To"] = to_email

        msg.attach(MIMEText(body_text, "plain", "utf-8"))
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
                if SMTP_PORT == 587:
                    server.starttls()
                server.login(SMTP_USER, SMTP_PASS)
                server.sendmail(SMTP_USER, [to_email], msg.as_string())
            record_email_sent(place_id, status="sent")
            return True, None
        except Exception as e:
            err = f"SMTP error: {str(e)}"
            record_email_sent(place_id, status="failed", error=err)
            return False, err
