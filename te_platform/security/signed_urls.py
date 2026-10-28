## =============================================================================
## te_platform/security/signed_urls.py — tamper-proof, expiring download links
## =============================================================================
## GUIDE STEP   10.3
## PURPOSE      sign_download(report_id, expires_at) returns a relative link
##                /agent/reports/<report_id>?exp=<unix time>&sig=<signature>
##              and verify_download(report_id, exp, sig) checks such a link.
##              The signature is an HMAC: a keyed hash that only someone holding
##              the server's secret key (Settings.report_signing_key) can
##              compute. Changing the report id or extending the expiry time
##              invalidates the signature, so links cannot be forged, reused for
##              another report, or extended.
## USED BY      tools/report_render_pdf.py (signs the link it returns, in the
##              MCP server process), and the download endpoint
##              GET /agent/reports/{id} in agent/user_reports_api.py, which calls
##              verify_download before sending the file AND checks that the
##              report belongs to the logged-in user (defence in depth: a
##              valid link alone is not enough). The path starts with /agent/
##              because Caddy routes /agent/* to the agent service, which has
##              the login cookie check and read access to the reports volume.
##              Both processes need the same Settings.report_signing_key
##              (compose.yml gives the secret to mcp and agent).
## DEPENDS ON   Python standard library (hmac, hashlib, base64), config.py.
## WHY          Architecture §3.6: reports must be downloadable from the chat
##              without exposing them to anyone who guesses an ID.
## ACTIVATE     Requires Settings.report_signing_key (long random secret, e.g.
##              `python -c "import secrets; print(secrets.token_urlsafe(48))"`,
##              stored as a Docker secret). Uncomment; tests in
##              test_platform_security.py (valid, expired, tampered).
## =============================================================================

## -----------------------------------------------------------------------------
## TO-DO LIST: build this file yourself, step by step
## -----------------------------------------------------------------------------
## Write your code between this list and the SOLUTION marker below. Do the
## steps in order and run the "Check" before moving on. Lines starting with
## "|" are short illustrations, not the full code. Keep the public names
## exactly as written here: tools/report_render_pdf.py and agent/user_reports_api.py
## call them. Needs Settings.report_signing_key (config.py, guide 10.x).
##
## Guide 10.3
## [ ] 1. Imports at the top: `base64`, `hashlib`, `hmac`, `time`,
##        `datetime` (datetime), `quote` (urllib.parse) and `get_settings`
##        (te_platform.config).
## [ ] 2. `_signature(report_id: str, exp: int) -> str`. Every function
##        of this file gets a one-line docstring. Raise
##        RuntimeError when report_signing_key is None (no unsigned links).
##        Sign both values, joined by the "\x1f" separator:
##          | message = f"{report_id}\x1f{exp}".encode()
##        HMAC-SHA256 with the key's secret value, then URL-safe base64 of
##        the digest with the "=" padding stripped.
## [ ] 3. `sign_download(report_id: str, expires_at: datetime) -> str`:
##        exp = the expiry as whole Unix seconds; return the relative link
##        "/agent/reports/<quoted id>?exp=<exp>&sig=<signature>", quoting
##        the id with quote(report_id, safe="") so even "/" is escaped.
## [ ] 4. `verify_download(report_id: str, exp: int, sig: str) -> bool`:
##        False when exp is in the past; otherwise compare the expected
##        signature with `sig` using hmac.compare_digest (never ==: see the
##        SOLUTION's comment on constant time).
## [ ] 5. Check: activate the signed_urls block of
##        tests/platform_tests/test_platform_security.py, then
##          | uv run pytest tests/platform_tests/test_platform_security.py -q
##          | uv run mypy te_platform
##
## Stuck, or want to compare? The SOLUTION below is the complete reference
## code. Uncomment it only if you decide to use it as it is.

## =============================================================================
## SOLUTION: complete reference code (commented out on purpose)
## =============================================================================

import base64
import hashlib
import hmac
import time
from datetime import datetime
from urllib.parse import quote

from te_platform.config import get_settings


def _signature(report_id: str, exp: int) -> str:
    """Return the HMAC-SHA256 of (report_id, exp), URL-safe base64, no padding."""
    key = get_settings().report_signing_key
    if key is None:
        # Fail loudly: unsigned links would be a security hole.
        raise RuntimeError("TE_REPORT_SIGNING_KEY is not configured")
    # The message binds BOTH values, separated by a character that cannot
    # appear in either, so ("ab", 1) and ("a", "b1") can never collide.
    message = f"{report_id}\x1f{exp}".encode()  # str.encode() is UTF-8
    secret = key.get_secret_value().encode("utf-8")
    digest = hmac.new(secret, message, hashlib.sha256).digest()
    # URL-safe base64 without padding: short and safe inside a query string.
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def sign_download(report_id: str, expires_at: datetime) -> str:
    """Return the relative download link for a report, valid until expires_at."""
    exp = int(expires_at.timestamp())
    # safe="": also escape "/" so an id can never change the link's path.
    path = "/agent/reports/" + quote(report_id, safe="")
    return f"{path}?exp={exp}&sig={_signature(report_id, exp)}"


def verify_download(report_id: str, exp: int, sig: str) -> bool:
    """Return True only for an unexpired link whose signature matches."""
    if exp < int(time.time()):
        return False  # expired
    expected = _signature(report_id, exp)
    # Constant-time comparison: the time taken does not reveal how many
    # leading characters of a guessed signature were right.
    return hmac.compare_digest(expected, sig)
