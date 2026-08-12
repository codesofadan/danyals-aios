"""Unit tests for the branded email templates (the single email-body home).

Proves every directional template renders a subject + minimal HTML + a plain-text
alternative, that dynamic values are HTML-escaped (injection-safe), and that an
optional CTA link is embedded only when supplied.
"""

from __future__ import annotations

import pytest

from app.services.email_templates import (
    EMAIL_KINDS,
    admin_to_client,
    client_to_admin,
    render_kind,
    render_notification,
)

pytestmark = pytest.mark.unit


def test_every_kind_renders_full_content() -> None:
    for kind in EMAIL_KINDS:
        c = render_kind(kind)
        assert c.subject and c.html and c.text
        assert "AIOS" in c.html  # branded
        assert c.html.count("<div") >= 3  # header + card + footer structure


def test_dynamic_values_are_escaped() -> None:
    c = client_to_admin(client_name="<script>x</script>", request_summary="a & b")
    assert "<script>" not in c.html  # escaped
    assert "&lt;script&gt;" in c.html
    assert "a &amp; b" in c.html


def test_link_embedded_only_when_supplied() -> None:
    with_link = admin_to_client(
        client_name="Atlas", item_title="March Report", link="https://app.qanry.com/portal"
    )
    without = admin_to_client(client_name="Atlas", item_title="March Report")
    assert "https://app.qanry.com/portal" in with_link.html
    assert "href=" not in without.html  # no CTA button when no link


def test_notification_wrapper_uses_title_as_subject() -> None:
    c = render_notification("Audit done", "The report is ready")
    assert c.subject == "Audit done"
    assert "The report is ready" in c.html
    assert "The report is ready" in c.text
