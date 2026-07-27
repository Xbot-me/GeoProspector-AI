"""
Email delivery client supporting both Resend API and Direct SMTP.
Automatically wraps plain text pitches in a responsive HTML layout with
an embedded 1x1 tracking pixel for real-time open reporting and a
CAN-SPAM compliant footer with one-click unsubscribe.
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
    SENDER_SIGNATURE,
    SENDER_PHYSICAL_ADDRESS,
    UNSUBSCRIBE_BASE_URL,
)
from db import record_email_sent, is_suppressed

TRACKING_BASE_URL = "https://b2b.mustafizur.info"


def _clean_body_text(body_text: str) -> str:
    """Safety guarantee: ensure existing db leads or manual sends have the full signature."""
    if "mustafizur.info" in body_text:
        return body_text
    for placeholder in ("[Your Name]", "[Your name]", "[your name]", "[YOUR NAME]"):
        if placeholder in body_text:
            return body_text.replace(placeholder, SENDER_SIGNATURE).strip()
    if "Mustafizur Rahman" in body_text:
        return body_text.replace("Mustafizur Rahman", SENDER_SIGNATURE).strip()
    return f"{body_text.strip()}\n\n{SENDER_SIGNATURE}"


def _build_signature_html() -> str:
    """Build modern Executive Digital Business Card signature with text labels."""
    return """<div style="margin-top: 36px; padding-top: 24px; border-top: 1px solid #f1f5f9;">
    <div style="border-left: 3px solid #2563eb; padding-left: 18px;">
        <div style="font-weight: 700; font-size: 16px; color: #0f172a; letter-spacing: -0.01em; margin-bottom: 2px;">Mustafizur Rahman</div>
        <div style="font-size: 13px; color: #64748b; font-weight: 500; margin-bottom: 16px;">Full-Stack Web Developer</div>
        
        <table role="presentation" border="0" cellpadding="0" cellspacing="0" style="font-size: 13px; color: #334155; line-height: 1.9;">
            <tr>
                <td style="padding-right: 14px; color: #94a3b8; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; vertical-align: baseline;">Website</td>
                <td><a href="https://www.mustafizur.info" style="color: #2563eb; text-decoration: none; font-weight: 500;">www.mustafizur.info</a></td>
            </tr>
            <tr>
                <td style="padding-right: 14px; color: #94a3b8; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; vertical-align: baseline;">Portfolio</td>
                <td><a href="https://www.fiverr.com/users/mustafizur_dev/portfolio" style="color: #2563eb; text-decoration: none; font-weight: 500;">Fiverr Selected Works</a></td>
            </tr>
            <tr>
                <td style="padding-right: 14px; color: #94a3b8; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; vertical-align: baseline;">Email</td>
                <td><a href="mailto:mustafizur.dev101@gmail.com" style="color: #2563eb; text-decoration: none;">mustafizur.dev101@gmail.com</a></td>
            </tr>
            <tr>
                <td style="padding-right: 14px; color: #94a3b8; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; vertical-align: baseline;">Phone</td>
                <td><a href="tel:+8801886769509" style="color: #475569; text-decoration: none;">+880 1886-769509</a></td>
            </tr>
        </table>
    </div>
</div>"""


def _build_canspam_footer(place_id: str) -> str:
    """Build the CAN-SPAM compliant footer HTML block."""
    unsub_url = f"{UNSUBSCRIBE_BASE_URL}/api/unsubscribe/{place_id}"
    address = SENDER_PHYSICAL_ADDRESS or "Dhaka, Bangladesh"
    return f"""
    <div style="margin-top: 36px; padding-top: 20px; border-top: 1px solid #f1f5f9; font-size: 11px; color: #94a3b8; line-height: 1.6;">
        <p style="margin: 0 0 4px 0;">{address}</p>
        <p style="margin: 0;">
            Not interested in website upgrades? <a href="{unsub_url}" style="color: #94a3b8; text-decoration: underline;">Unsubscribe here</a> to opt out.
        </p>
    </div>"""


def format_html_email(body_text: str, place_id: str) -> str:
    """Wrap plain text in an executive responsive HTML card with business signature, CAN-SPAM footer, and tracking pixel."""
    import re
    # Separate signature if present at the end of body_text to render as styled card
    if "Mustafizur Rahman" in body_text:
        main_copy = body_text.split("Mustafizur Rahman")[0].strip()
    else:
        main_copy = body_text.strip()

    paragraphs = main_copy.split("\n\n")
    formatted_p = []
    for p in paragraphs:
        p_br = p.replace("\n", "<br>")
        # Auto-link standalone URLs
        p_br = re.sub(
            r'(https?://[^\s<]+)',
            r'<a href="\1" style="color: #2563eb; font-weight: 500; text-decoration: none;">\1</a>',
            p_br
        )
        formatted_p.append(f"<p style='margin: 0 0 16px 0; line-height: 1.65; color: #334155;'>{p_br}</p>")
    html_paragraphs = "".join(formatted_p)

    signature_html = _build_signature_html()
    canspam_footer = _build_canspam_footer(place_id)

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
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; font-size: 15px; color: #334155; background-color: #f8fafc; margin: 0; padding: 32px 16px;">
    <div style="max-width: 580px; margin: 0 auto; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);">
        <!-- Top Accent Gradient Bar -->
        <div style="height: 4px; background: linear-gradient(90deg, #2563eb 0%, #06b6d4 100%); font-size: 0; line-height: 0;">&nbsp;</div>
        
        <!-- Inner Padding Container -->
        <div style="padding: 32px 28px;">
            {html_paragraphs}
            {signature_html}
            {canspam_footer}
        </div>
    </div>
    {tracking_pixel}
</body>
</html>"""


def send_email(place_id: str, to_email: str, subject: str, body_text: str) -> tuple[bool, str | None]:
    """
    Dispatch email using configured provider (resend or smtp).
    Returns (success, error_message).
    Checks suppression list before sending.
    """
    if not to_email or "@" not in to_email:
        err = f"Invalid recipient email: '{to_email}'"
        record_email_sent(place_id, status="failed", error=err)
        return False, err

    # Check suppression list (bounced, complained, unsubscribed)
    if is_suppressed(to_email):
        err = f"Suppressed: '{to_email}' is on the suppression list (bounce/complaint/unsubscribe)"
        record_email_sent(place_id, status="failed", error=err)
        return False, err

    body_text = _clean_body_text(body_text)
    html_body = format_html_email(body_text, place_id)

    # Build plain-text footer for the text/plain MIME part
    unsub_url = f"{UNSUBSCRIBE_BASE_URL}/api/unsubscribe/{place_id}"
    address = SENDER_PHYSICAL_ADDRESS or "Dhaka, Bangladesh"
    plain_footer = f"\n\n---\n{address}\nUnsubscribe: {unsub_url}"
    body_text_with_footer = body_text + plain_footer

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
                    "text": body_text_with_footer,
                    "headers": {
                        "List-Unsubscribe": f"<{unsub_url}>",
                        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                    },
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
        msg["List-Unsubscribe"] = f"<{unsub_url}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

        msg.attach(MIMEText(body_text_with_footer, "plain", "utf-8"))
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
