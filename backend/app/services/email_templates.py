"""Branded AIOS email templates - the ONE place email bodies are rendered.

Every outbound email in the all-way comms flow (admin -> team, team -> admin,
admin -> client, client -> admin) is rendered here into an :class:`EmailContent`
(subject + minimal branded HTML + a plain-text alternative), so the look, the escaping,
and the footer stay identical no matter which provider (Resend / SMTP) actually sends.

The HTML is INTENTIONALLY minimal + inline-styled (email clients strip ``<style>`` and
external CSS): a header band, a heading, body lines, an optional CTA button, and a
footer. Every dynamic value is HTML-escaped - the bodies are server-generated, but the
escape keeps them injection-safe regardless. ``render_notification`` is the generic
wrapper the in-app delivery layer reuses; the four ``*_*`` renderers carry the
event-specific who/what/link for each direction and are what the test CLI sends.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape as _esc
from typing import Literal

# The four comms directions the CLI can render + send end-to-end.
EmailKind = Literal["admin_to_team", "team_to_admin", "admin_to_client", "client_to_admin"]
EMAIL_KINDS: tuple[EmailKind, ...] = (
    "admin_to_team",
    "team_to_admin",
    "admin_to_client",
    "client_to_admin",
)

_BRAND = "AIOS"
_ACCENT = "#6E1423"  # maroon
_INK = "#241015"
_MUTED = "#6b6b6b"
_FOOTER = "AIOS - Xegents AI. You are receiving this because of activity on your account."


@dataclass(frozen=True)
class EmailContent:
    """A rendered email: the subject line plus both body representations."""

    subject: str
    html: str
    text: str


def _button(link: str, label: str) -> str:
    return (
        f'<a href="{_esc(link, quote=True)}" '
        f'style="display:inline-block;margin-top:18px;padding:11px 20px;background:{_ACCENT};'
        f'color:#ffffff;text-decoration:none;border-radius:6px;font-weight:700;'
        f'font-size:14px">{_esc(label)}</a>'
    )


def render_html(
    heading: str, lines: list[str], *, link: str | None = None, link_label: str = "Open in AIOS"
) -> str:
    """A minimal, branded, injection-safe HTML body (all values escaped)."""
    body = "".join(
        f'<p style="margin:0 0 12px;font-size:15px;line-height:1.55;color:{_INK}">'
        f"{_esc(line)}</p>"
        for line in lines
        if line
    )
    cta = _button(link, link_label) if link else ""
    return (
        f'<div style="margin:0;padding:24px;background:#f5f0f1;'
        f'font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif">'
        f'<div style="max-width:560px;margin:0 auto;background:#ffffff;border-radius:10px;'
        f'overflow:hidden;border:1px solid #e8d2d7">'
        f'<div style="background:{_ACCENT};padding:16px 24px">'
        f'<span style="color:#ffffff;font-weight:800;font-size:18px;letter-spacing:-0.02em">'
        f"{_BRAND}</span></div>"
        f'<div style="padding:24px 28px 30px">'
        f'<h1 style="margin:0 0 16px;font-size:21px;font-weight:800;color:{_ACCENT}">'
        f"{_esc(heading)}</h1>"
        f"{body}{cta}</div>"
        f'<div style="padding:14px 28px;border-top:1px solid #e8d2d7;font-size:12px;'
        f'color:{_MUTED}">{_esc(_FOOTER)}</div>'
        f"</div></div>"
    )


def render_text(heading: str, lines: list[str], *, link: str | None = None) -> str:
    """The plain-text alternative body (mirrors the HTML content, unescaped)."""
    parts = [_BRAND, "", heading, ""]
    parts.extend(line for line in lines if line)
    if link:
        parts.extend(["", f"Open: {link}"])
    parts.extend(["", "-- ", _FOOTER])
    return "\n".join(parts)


def _content(
    subject: str, heading: str, lines: list[str], *, link: str | None = None,
    link_label: str = "Open in AIOS",
) -> EmailContent:
    return EmailContent(
        subject=subject,
        html=render_html(heading, lines, link=link, link_label=link_label),
        text=render_text(heading, lines, link=link),
    )


def render_notification(title: str, body: str, *, link: str | None = None) -> EmailContent:
    """The generic per-user notification wrapper the in-app delivery layer reuses.

    ``title`` becomes both the subject and the heading; ``body`` is one paragraph.
    """
    lines = [body] if body else []
    return _content(title, title, lines, link=link)


# --------------------------------------------------------------------------- #
# The four directional templates (who / what / link).
# --------------------------------------------------------------------------- #
def admin_to_team(
    *, member_name: str, task_title: str, client_name: str, assigned_by: str = "",
    link: str | None = None,
) -> EmailContent:
    """admin/staff -> team member: a task was assigned / review requested."""
    who = f"{assigned_by} assigned you" if assigned_by else "You have been assigned"
    lines = [
        f"Hi {member_name},",
        f"{who} a new task: “{task_title}” for {client_name}.",
        "Open your queue in AIOS to get started.",
    ]
    return _content(
        f"New task assigned: {task_title}", "A task was assigned to you", lines,
        link=link, link_label="View task",
    )


def team_to_admin(
    *, member_name: str, task_title: str, client_name: str, action: str = "submitted for review",
    link: str | None = None,
) -> EmailContent:
    """team member -> admin: work submitted for review / a task completed."""
    lines = [
        f"{member_name} {action} the task “{task_title}” for {client_name}.",
        "Review it in the team board when you have a moment.",
    ]
    return _content(
        f"Task {action}: {task_title}", "A task needs your attention", lines,
        link=link, link_label="Open review",
    )


def admin_to_client(
    *, client_name: str, item_title: str, item_kind: str = "deliverable",
    link: str | None = None,
) -> EmailContent:
    """admin -> client: a report is ready / a deliverable was published / a milestone hit."""
    lines = [
        f"Hi {client_name},",
        f"Your {item_kind} “{item_title}” is ready in your portal.",
        "Sign in to view and download it.",
    ]
    return _content(
        f"Your {item_kind} is ready: {item_title}", "Something new in your portal", lines,
        link=link, link_label="Open portal",
    )


def client_to_admin(
    *, client_name: str, request_summary: str, link: str | None = None
) -> EmailContent:
    """client -> admin: a portal request / ticket was raised."""
    lines = [
        f"{client_name} raised a new request via the client portal:",
        request_summary,
        "Open the admin dashboard to respond.",
    ]
    return _content(
        f"New portal request from {client_name}", "New client request", lines,
        link=link, link_label="Open dashboard",
    )


def render_kind(kind: EmailKind, *, link: str | None = None) -> EmailContent:
    """Render a representative email for ``kind`` (used by ``send_test_email``).

    Uses realistic sample context so the operator can verify a real, branded email of
    each direction end-to-end without triggering a live workflow.
    """
    if kind == "admin_to_team":
        return admin_to_team(
            member_name="Alex", task_title="On-page fixes for /pricing",
            client_name="Atlas Legal", assigned_by="Danyal", link=link,
        )
    if kind == "team_to_admin":
        return team_to_admin(
            member_name="Alex", task_title="On-page fixes for /pricing",
            client_name="Atlas Legal", action="submitted for review", link=link,
        )
    if kind == "admin_to_client":
        return admin_to_client(
            client_name="Atlas Legal", item_title="March SEO Report",
            item_kind="report", link=link,
        )
    return client_to_admin(
        client_name="Atlas Legal",
        request_summary="Please add three new landing pages for the spring campaign.",
        link=link,
    )
