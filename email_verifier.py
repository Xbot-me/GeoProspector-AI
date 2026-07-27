"""
Pre-send email verification.

Validates recipient addresses before the outreach pipeline hands them to
the email sender.  Checks run in order:

  1. Syntax   – RFC-ish regex sanity check
  2. Domain   – extracted and tested against a blocklist of known
                 disposable / throwaway providers
  3. MX lookup – DNS query for mail-exchange records via dnspython

The verifier is intentionally *fail-open* on DNS timeouts so that
transient resolver hiccups never silently drop real leads.
"""
import re
from typing import Optional

import dns.exception
import dns.resolver

# ---------------------------------------------------------------------------
# Regex: intentionally permissive – we only want to catch obvious junk
# (missing @, spaces, double dots, etc.), not enforce RFC 5321 to the letter.
# ---------------------------------------------------------------------------
_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*"
    r"\.[a-zA-Z]{2,}$"
)

# ---------------------------------------------------------------------------
# Common disposable / throwaway email domains.
# Kept as a frozenset for O(1) lookups.
# ---------------------------------------------------------------------------
DISPOSABLE_DOMAINS: frozenset[str] = frozenset({
    "mailinator.com",
    "guerrillamail.com",
    "guerrillamail.de",
    "guerrillamail.net",
    "guerrillamail.org",
    "tempmail.com",
    "temp-mail.org",
    "throwaway.email",
    "yopmail.com",
    "yopmail.fr",
    "sharklasers.com",
    "grr.la",
    "guerrillamailblock.com",
    "maildrop.cc",
    "dispostable.com",
    "trashmail.com",
    "trashmail.me",
    "trashmail.net",
    "mailnesia.com",
    "mintemail.com",
    "tempail.com",
    "mohmal.com",
    "burpcollaborator.net",
    "mailcatch.com",
    "mytemp.email",
    "fakeinbox.com",
    "getairmail.com",
    "mailexpire.com",
    "safetymail.info",
    "filzmail.com",
    "getnada.com",
    "mailnull.com",
    "e4ward.com",
    "spamgourmet.com",
    "jetable.org",
    "trash-mail.com",
    "10minutemail.com",
    "10minutemail.net",
    "tempinbox.com",
    "discard.email",
    "discardmail.com",
    "spamfree24.org",
    "mailforspam.com",
    "tempr.email",
    "armyspy.com",
    "cuvox.de",
    "dayrep.com",
    "einrot.com",
    "fleckens.hu",
    "gustr.com",
    "jourrapide.com",
    "rhyta.com",
    "superrito.com",
    "teleworm.us",
})


def verify_email(email: str) -> dict[str, Optional[bool | str]]:
    """
    Validate an email address before sending outreach.

    Checks (in order): syntax → disposable domain → MX records.

    Returns a dict with three keys:
        valid    – True when the address looks deliverable
        reason   – human-readable explanation of the verdict
        mx_found – True / False / None (None on DNS timeout)
    """
    # 1. Syntax ----------------------------------------------------------
    if not _EMAIL_RE.match(email.strip()):
        return {"valid": False, "reason": "Invalid email format", "mx_found": False}

    # 2. Domain extraction -----------------------------------------------
    domain = email.strip().rsplit("@", 1)[1].lower()

    # 3. Disposable domain check -----------------------------------------
    if domain in DISPOSABLE_DOMAINS:
        return {"valid": False, "reason": "Disposable email domain", "mx_found": False}

    # 4. MX record lookup ------------------------------------------------
    try:
        answers = dns.resolver.resolve(domain, "MX")
        if answers:
            return {"valid": True, "reason": "MX records found", "mx_found": True}
        return {"valid": False, "reason": "No MX records for domain", "mx_found": False}
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
        return {"valid": False, "reason": "No MX records for domain", "mx_found": False}
    except (dns.exception.Timeout, dns.resolver.NoResolverConfiguration):
        # Fail-open: don't discard a lead just because DNS was slow or
        # the resolver config is unavailable (e.g. sandboxed environments).
        return {
            "valid": True,
            "reason": "MX lookup timed out (treating as valid)",
            "mx_found": None,
        }
