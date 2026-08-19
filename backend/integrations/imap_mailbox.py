"""Catch-all IMAP mailbox seam (citation ACCOUNT-CREATION, 7B-5): the read-only
door the signup flow uses to CONFIRM a freshly-created directory account.

Most real citation directories require a SIGNUP (create an account, then click a
link -- or type a code -- from a confirmation email) BEFORE a listing can be added.
The platform owns a single **catch-all** mailbox (every address at
``CITATION_MAIL_DOMAIN`` lands in one INBOX), so each signup uses its OWN unique
alias -- ``alias_for(...)`` below -- which is what avoids the "one email -> many
accounts" ban pattern. This module reads that INBOX over IMAP-SSL, waits for the
confirmation email addressed to a given alias, and extracts the verification LINK
and/or CODE from it.

DEGRADE-SAFE BY CONSTRUCTION: every IMAP error is swallowed (``wait_for_message``
returns ``None`` on timeout/failure, never raises), so a mail outage HOLDS a signup
as ``blocked`` rather than crashing the worker. SECRET-SAFE: the password is never
logged and full email bodies are never logged (only the extracted, non-sensitive
link/code presence). ``imaplib`` is stdlib but lazy-imported inside the poll loop so
importing this module (and the rest of the citations package) costs nothing until a
signup job actually runs -- mirroring the Playwright/optional-SDK gating elsewhere.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.logging_setup import get_logger

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime
    from email.message import EmailMessage

    from app.config import Settings

logger = get_logger("integrations.imap_mailbox")

# Local part of a catch-all alias is capped so it stays a legal address (RFC 5321
# limits the local part to 64 chars; the slug + hash + hyphen sits well under that).
_MAX_SLUG = 40
# A confirmation URL "looks like" a verify link when it carries one of these hints -
# the reference flow's own "click to confirm your account" convention.
_LINK_HINTS = ("verify", "confirm", "activate", "validate", "confirmation", "token", "signup", "register")
_URL_RE = re.compile(r"https?://[^\s\"'<>)\]}]+")
_HREF_RE = re.compile(r"href=[\"']?(https?://[^\"'\s>]+)", re.IGNORECASE)
# A numeric verification code: prefer one sitting next to a "code/OTP/verification"
# cue, else fall back to any 4-8 digit run in the body.
_CODE_CTX_RE = re.compile(r"(?:code|verification|verify|otp|pin|passcode|confirm)\D{0,24}(\d{4,8})", re.IGNORECASE)
_CODE_RE = re.compile(r"\b(\d{4,8})\b")
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class VerifyInfo:
    """What a confirmation email yields: the click-to-confirm LINK and/or a numeric
    CODE. Either may be empty (a link-only or code-only email) -- the signup runner
    picks the one its ``SignupSpec.verify_kind`` calls for."""

    link: str = ""
    code: str = ""


def _slug(value: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (out or "dir")[:_MAX_SLUG].strip("-") or "dir"


def _short(client_id: str) -> str:
    """A short, deterministic, collision-resistant tag for a client id (a UUID or an
    opaque string), so the alias is stable per client without leaking the raw id."""
    return hashlib.sha1(client_id.encode("utf-8")).hexdigest()[:10]


def alias_for(*, directory: str, client_id: str, domain: str) -> str:
    """A DISTINCT catch-all address per (directory, client): ``<dir-slug>-<hash>@domain``.

    Deterministic (the same directory+client always maps to the same alias, so a
    retry reuses -- not duplicates -- the account) and unique across both axes (a
    different directory OR a different client yields a different local part), which is
    exactly what stops one shared email fanning out into many directory accounts."""
    return f"{_slug(directory)}-{_short(client_id)}@{domain}"


def _decode_part(part: EmailMessage) -> str:
    try:
        payload = part.get_payload(decode=True)
        if payload is None:
            raw = part.get_payload()
            return raw if isinstance(raw, str) else ""
        if isinstance(payload, bytes):
            charset = part.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
        return ""
    except Exception:  # a malformed part must never break extraction
        return ""


def _bodies(msg: EmailMessage) -> tuple[str, str]:
    """Return ``(text, html)`` -- the concatenated text/plain and text/html bodies."""
    text_parts: list[str] = []
    html_parts: list[str] = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_maintype() == "multipart":
                continue
            ctype = part.get_content_type()
            if ctype == "text/plain":
                text_parts.append(_decode_part(part))
            elif ctype == "text/html":
                html_parts.append(_decode_part(part))
    else:
        body = _decode_part(msg)
        if msg.get_content_type() == "text/html":
            html_parts.append(body)
        else:
            text_parts.append(body)
    return "\n".join(text_parts), "\n".join(html_parts)


def _clean_url(url: str) -> str:
    url = url.replace("&amp;", "&")
    return url.rstrip(".,)]}>\"'")


def _find_link(text: str, html: str) -> str:
    candidates: list[str] = []
    candidates.extend(_HREF_RE.findall(html))
    candidates.extend(_URL_RE.findall(html))
    candidates.extend(_URL_RE.findall(text))
    for url in candidates:
        if any(hint in url.lower() for hint in _LINK_HINTS):
            return _clean_url(url)
    return ""


def _find_code(text: str, html: str) -> str:
    body = f"{text}\n{_TAG_RE.sub(' ', html)}"
    ctx = _CODE_CTX_RE.search(body)
    if ctx:
        return ctx.group(1)
    bare = _CODE_RE.search(body)
    return bare.group(1) if bare else ""


def extract_verification(msg: EmailMessage) -> VerifyInfo:
    """Pull the confirmation LINK (first https URL that looks like a verify/activate/
    confirm link, from the html hrefs first then any plain URL) AND/OR a numeric CODE
    (a 4-8 digit run, preferring one next to a "code/verification" cue) from the
    email's html + text parts. Never raises -- a body it cannot parse yields empty
    fields, which the caller treats as "no verification found"."""
    text, html = _bodies(msg)
    return VerifyInfo(link=_find_link(text, html), code=_find_code(text, html))


class ImapMailbox:
    """Read-only client over the catch-all INBOX (IMAP4 over SSL).

    Built from settings via :func:`imap_mailbox_from_settings`. The password is held
    only to authenticate and is NEVER logged. Every method is degrade-safe: an IMAP
    error logs (exception TYPE only, never the message/body/credential) and yields a
    ``None``/empty result instead of raising out into the worker."""

    def __init__(self, *, host: str, port: int, user: str, password: str) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password  # never logged

    def wait_for_message(
        self,
        *,
        to_alias: str,
        since: datetime,
        subject_contains: Sequence[str] = (),
        timeout_s: int = 180,
        poll_s: int = 5,
    ) -> EmailMessage | None:
        """Poll the INBOX until a message addressed to ``to_alias`` and arriving at/
        after ``since`` (optionally whose Subject contains one of ``subject_contains``)
        appears, or ``timeout_s`` elapses. Returns the parsed message, or ``None`` on
        timeout / any IMAP failure (degrade-safe -- the signup then HOLDS as blocked)."""
        deadline = time.monotonic() + max(timeout_s, 0)
        alias_l = to_alias.strip().lower()
        while True:
            found = self._poll_once(alias_l, since, subject_contains)
            if found is not None:
                return found
            if time.monotonic() >= deadline:
                return None
            time.sleep(max(poll_s, 1))

    def _poll_once(
        self, alias_l: str, since: datetime, subject_contains: Sequence[str]
    ) -> EmailMessage | None:
        import email
        import imaplib
        from email import policy as email_policy

        since_date = since.strftime("%d-%b-%Y")
        imap: imaplib.IMAP4_SSL | None = None
        try:
            imap = imaplib.IMAP4_SSL(self._host, self._port)
            imap.login(self._user, self._password)
            imap.select("INBOX")
            typ, data = imap.search(None, "SINCE", since_date)
            if typ != "OK" or not data or not data[0]:
                return None
            # Newest first: the confirmation we just triggered is the most recent.
            for mid in reversed(data[0].split()):
                ftyp, fdata = imap.fetch(mid, "(RFC822)")
                if ftyp != "OK" or not fdata or not isinstance(fdata[0], tuple):
                    continue
                raw = fdata[0][1]
                if not isinstance(raw, (bytes, bytearray)):
                    continue
                msg = email.message_from_bytes(bytes(raw), policy=email_policy.default)
                if self._matches(msg, alias_l, since, subject_contains):
                    return msg
            return None
        except Exception as exc:  # never raise out - a mail outage HOLDS the signup
            logger.warning("imap_poll_failed", host=self._host, error=type(exc).__name__)
            return None
        finally:
            if imap is not None:
                try:
                    imap.logout()
                except Exception:
                    logger.debug("imap_logout_failed", host=self._host)

    @staticmethod
    def _matches(
        msg: EmailMessage, alias_l: str, since: datetime, subject_contains: Sequence[str]
    ) -> bool:
        from datetime import timedelta
        from email.utils import parsedate_to_datetime

        # Arrival time: allow a small clock-skew tolerance so a message that landed a
        # moment before our recorded start is not wrongly rejected.
        raw_date = msg.get("Date")
        if raw_date:
            try:
                dt = parsedate_to_datetime(raw_date)
                if dt is not None:
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=since.tzinfo)
                    if since.tzinfo is not None and dt < since - timedelta(seconds=90):
                        return False
            except Exception:
                pass  # an unparseable Date never disqualifies a recipient/subject match
        # Recipient: a catch-all lands the alias in To/Cc or an envelope header.
        recipients: list[str] = []
        for hdr in ("To", "Cc", "Delivered-To", "X-Original-To", "Envelope-To", "X-Delivered-To"):
            values = msg.get_all(hdr)
            if values:
                recipients.extend(str(v) for v in values)
        if alias_l not in " ".join(recipients).lower():
            return False
        if subject_contains:
            subject = (msg.get("Subject") or "").lower()
            if not any(token.lower() in subject for token in subject_contains):
                return False
        return True


def imap_mailbox_from_settings(settings: Settings) -> ImapMailbox | None:
    """The catch-all mailbox client, or ``None`` when unconfigured (host/user/password
    missing) -- the signup flow then DEGRADES (a signup HOLDS as blocked), it never
    crashes. Mirrors ``captcha_solver_from_settings`` / ``citation_bot_from_settings``."""
    host = settings.citation_imap_host
    user = settings.citation_imap_user
    password = settings.citation_imap_password
    if not host or not user or not password:
        logger.info("imap_mailbox_degraded", reason="unconfigured")
        return None
    return ImapMailbox(
        host=host,
        port=settings.citation_imap_port,
        user=user,
        password=password.get_secret_value(),
    )
