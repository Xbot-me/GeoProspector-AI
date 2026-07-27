"""
Email delivery client supporting both Resend API and Direct SMTP.
Wraps plain text pitches in a professional letterhead-style HTML layout
(header, optional rating/review stat card, single CTA, slim signature,
CAN-SPAM footer) with an embedded 1x1 tracking pixel for open reporting.
"""
import re
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
WEBSITE_URL = "https://www.mustafizur.info"


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


def _build_header_html() -> str:
    """Dark letterhead bar with monogram badge — establishes who's emailing up front."""
    return """<tr>
    <td style="background-color:#0f172a; padding:22px 32px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td style="vertical-align:middle;">
            <table role="presentation" cellpadding="0" cellspacing="0">
              <tr>
                <td style="width:36px; height:36px; background:linear-gradient(135deg,#2563eb,#06b6d4); border-radius:9px; text-align:center; vertical-align:middle; font-weight:700; font-size:14px; color:#ffffff; font-family:Arial, sans-serif;">MR</td>
                <td style="padding-left:12px;">
                  <div style="color:#ffffff; font-weight:700; font-size:14px; letter-spacing:-0.01em;">Mustafizur Rahman</div>
                  <div style="color:#94a3b8; font-size:11px; font-weight:500; text-transform:uppercase; letter-spacing:0.06em;">Web Developer &nbsp;&middot;&nbsp; Local Business Sites</div>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </td>
  </tr>
  <tr><td style="height:3px; background:linear-gradient(90deg,#2563eb,#06b6d4); font-size:0; line-height:0;">&nbsp;</td></tr>"""


def _build_stat_card_html(rating: float | None, review_count: int | None) -> str:
    """Highlight the lead's own Google rating/review count as a visual badge.
    Returns an empty string when we don't have both data points to show."""
    if rating is None or review_count is None:
        return ""
    return f"""<tr>
    <td style="padding:0 32px 20px 32px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f8fafc; border:1px solid #e2e8f0; border-radius:12px;">
        <tr>
          <td style="padding:18px 22px;">
            <table role="presentation" cellpadding="0" cellspacing="0">
              <tr>
                <td style="padding-right:28px; vertical-align:top;">
                  <div style="font-size:26px; font-weight:800; color:#0f172a; line-height:1;">{rating:g}<span style="color:#f59e0b; font-size:16px;">&#9733;</span></div>
                  <div style="font-size:11px; color:#94a3b8; font-weight:600; text-transform:uppercase; letter-spacing:0.05em; margin-top:4px;">Average rating</div>
                </td>
                <td style="border-left:1px solid #e2e8f0; padding-left:28px; vertical-align:top;">
                  <div style="font-size:26px; font-weight:800; color:#0f172a; line-height:1;">{review_count}</div>
                  <div style="font-size:11px; color:#94a3b8; font-weight:600; text-transform:uppercase; letter-spacing:0.05em; margin-top:4px;">Customer reviews</div>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </td>
  </tr>"""


def _build_cta_html() -> str:
    """Single CTA linking to the main portfolio site."""
    return f"""<tr>
    <td style="padding:0 32px 36px 32px;" align="center">
      <table role="presentation" cellpadding="0" cellspacing="0">
        <tr>
          <td style="background:linear-gradient(90deg,#2563eb,#0ea5e9); border-radius:10px;">
            <a href="{WEBSITE_URL}" style="display:inline-block; padding:13px 30px; font-size:14px; font-weight:600; color:#ffffff; text-decoration:none; letter-spacing:0.01em;">Visit mustafizur.info &nbsp;&rarr;</a>
          </td>
        </tr>
      </table>
    </td>
  </tr>"""


def _build_signature_html() -> str:
    """Slim one-line signature — 100% domain aligned with sending domain (hello@mustafizur.info)."""
    return """<tr>
    <td style="padding:0 32px 30px 32px; border-top:1px solid #f1f5f9;">
      <table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:24px;">
        <tr>
          <td style="font-size:13px; color:#334155; line-height:1.9;">
            <a href="mailto:hello@mustafizur.info" style="color:#2563eb; text-decoration:none; font-weight:500;">hello@mustafizur.info</a>
            &nbsp;&middot;&nbsp;
            <a href="tel:+8801886769509" style="color:#475569; text-decoration:none;">+880 1886-769509</a>
          </td>
        </tr>
      </table>
    </td>
  </tr>"""


def _build_canspam_footer_html(place_id: str) -> str:
    """CAN-SPAM compliant footer block."""
    unsub_url = f"{UNSUBSCRIBE_BASE_URL}/api/unsubscribe/{place_id}"
    address = SENDER_PHYSICAL_ADDRESS or "Dhaka, Bangladesh"
    return f"""<tr>
    <td style="background-color:#f8fafc; padding:18px 32px; font-size:11px; color:#94a3b8; line-height:1.6;">
      <p style="margin:0 0 4px 0;">{address}</p>
      <p style="margin:0;">Not interested in website upgrades? <a href="{unsub_url}" style="color:#94a3b8; text-decoration:underline;">Unsubscribe here</a> to opt out.</p>
    </td>
  </tr>"""


def format_html_email(
    body_text: str,
    place_id: str,
    rating: float | None = None,
    review_count: int | None = None,
) -> str:
    """Wrap plain text in the letterhead-style responsive HTML email:
    header, optional rating/review stat card, body copy, CTA button,
    slim signature, CAN-SPAM footer, tracking pixel."""
    # Strip the plain-text signature block from the copy — the header/signature
    # blocks already cover that, so we don't want it duplicated in the body.
    if "Mustafizur Rahman" in body_text:
        main_copy = body_text.split("Mustafizur Rahman")[0].strip()
    else:
        main_copy = body_text.strip()

    paragraphs = main_copy.split("\n\n")
    formatted_p = []
    for p in paragraphs:
        if not p.strip():
            continue
        p_br = p.replace("\n", "<br>")
        p_br = re.sub(
            r'(https?://[^\s<]+)',
            r'<a href="\1" style="color: #2563eb; font-weight: 500; text-decoration: none;">\1</a>',
            p_br,
        )
        formatted_p.append(f"<p style='margin: 0 0 16px 0; line-height: 1.65; color: #334155;'>{p_br}</p>")
    html_paragraphs = "".join(formatted_p)

    header_html = _build_header_html()
    stat_card_html = _build_stat_card_html(rating, review_count)
    cta_html = _build_cta_html()
    signature_html = _build_signature_html()
    footer_html = _build_canspam_footer_html(place_id)

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
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin:0; padding:32px 16px; background-color:#eef1f5;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px; margin:0 auto; background-color:#ffffff; border-radius:14px; overflow:hidden; box-shadow:0 6px 24px rgba(15,23,42,0.08);">
        {header_html}
        <tr>
            <td style="padding:34px 32px 8px 32px;">
                {html_paragraphs}
            </td>
        </tr>
        {stat_card_html}
        {cta_html}
        {signature_html}
        {footer_html}
    </table>
    {tracking_pixel}
</body>
</html>"""


def send_email(
    place_id: str,
    to_email: str,
    subject: str,
    body_text: str,
    rating: float | None = None,
    review_count: int | None = None,
) -> tuple[bool, str | None]:
    """
    Dispatch email using configured provider (resend or smtp).
    Returns (success, error_message).
    Checks suppression list before sending.
    rating/review_count are optional — when both are provided, the email
    includes a stat-highlight card; otherwise that section is omitted.
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
    html_body = format_html_email(body_text, place_id, rating=rating, review_count=review_count)

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
