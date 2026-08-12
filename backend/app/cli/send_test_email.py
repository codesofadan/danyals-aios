"""Send ONE real, branded test email through the configured provider.

Lets an operator verify the email path end-to-end (especially Gmail SMTP) WITHOUT
triggering a full workflow: it renders the SAME template the four comms directions use
and sends it via ``email_sender_from_settings`` (Resend / SMTP / none, per
``EMAIL_PROVIDER``). It reads settings from the environment, so it works unchanged via
``docker exec``/``systemd`` in the worker or API host. No database is touched.

    python -m app.cli.send_test_email --to you@example.com
    python -m app.cli.send_test_email --to you@example.com --kind admin_to_client
    python -m app.cli.send_test_email --to you@example.com --kind client_to_admin --link https://app.qanry.com

Output is one line:
    OK: sent <kind> to <addr> via <provider> (id=<message-id>)
    DEGRADED: no email provider configured (EMAIL_PROVIDER=<...>); nothing sent
    DEGRADED: send failed via <provider> (<ErrorType>)      # exit 1

Exit code is 0 for a successful send OR an expected keyless degrade, 1 for a send that
was attempted and failed (so a CI/health probe can tell a real SMTP fault from an
intentionally-unconfigured host). No secret is ever printed.
"""

from __future__ import annotations

import argparse
import sys

from app.config import get_settings
from app.services.email_templates import EMAIL_KINDS, EmailKind, render_kind
from integrations.resend import email_sender_from_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Send one branded test email via the configured provider (Resend/SMTP)."
    )
    parser.add_argument("--to", required=True, help="recipient email address")
    parser.add_argument(
        "--kind", default="admin_to_team", choices=list(EMAIL_KINDS),
        help="which comms direction to render (default: admin_to_team)",
    )
    parser.add_argument("--link", default=None, help="optional CTA link to embed")
    args = parser.parse_args(argv)

    settings = get_settings()
    kind: EmailKind = args.kind
    content = render_kind(kind, link=args.link)

    sender = email_sender_from_settings(settings)
    if sender is None:
        print(
            f"DEGRADED: no email provider configured (EMAIL_PROVIDER={settings.email_provider}); "
            "nothing sent"
        )
        return 0

    provider = getattr(sender, "provider", "unknown")
    try:
        message_id = sender.send(
            to=args.to, subject=content.subject, html=content.html, text=content.text
        )
    except Exception as exc:
        # Operator diagnostic: report the error TYPE only, never a secret or a body.
        print(f"DEGRADED: send failed via {provider} ({type(exc).__name__})", file=sys.stderr)
        return 1

    print(f"OK: sent {kind} to {args.to} via {provider} (id={message_id or 'n/a'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
