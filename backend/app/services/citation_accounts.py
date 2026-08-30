"""Directory accounts: the passwords the bot used to throw away.

`integrations/citation_signup.py` generates a strong per-account password, types it into
the signup form, and never stores it. Every directory account the bot has created has an
irrecoverable login - so those listings cannot be corrected, cannot be removed, and
cannot be handed to an operator to finish. The only remaining move is to abandon the
account and create a duplicate, which is the exact problem a citation campaign exists to
prevent.

This module is the missing half: create the account row FIRST, then seal the password
into the vault under coordinates the database itself assigned. The ordering is forced by
the schema (0111) - the vault label is the account row's own id, so it cannot be known
until the row exists, and `credential_sealed_at` is nulled on insert precisely so a
caller cannot claim a secret that could not yet have been written.

WHAT THIS MODULE DELIBERATELY DOES NOT DO. It does not reveal. Reading a directory
password back is `vault.reveal_secret`, which is owner-only and enforced in its own
router - and it stays that way. An operator finishing a listing does not need the
password: they sign into the directory once in their own browser, and the queue hands
them everything else. A reveal path built for operator convenience is a reveal path, and
this codebase already has exactly one of those, audited, in one place.
"""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass
from typing import Any

from app.db.database import rls_connection
from app.logging_setup import get_logger
from app.services import vault

logger = get_logger("app.services.citation_accounts")

# Excludes the characters that get mistyped or mangled when a human reads a password off
# a screen (0/O, 1/l/I) and the quoting characters that break naive directory forms.
_ALPHABET = "".join(
    c for c in (string.ascii_letters + string.digits + "!@#$%^&*-_=+")
    if c not in "0O1lI'\"`\\"
)
_PASSWORD_LENGTH = 24


def generate_password() -> str:
    """A fresh per-account password. `secrets`, never `random`: this is a credential."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(_PASSWORD_LENGTH))


@dataclass(frozen=True)
class CitationAccount:
    """An account we hold on a directory, on behalf of one client."""

    id: str
    client_id: str
    directory_id: str
    registration_email: str
    vault_provider: str
    vault_label: str
    health: str
    credential_sealed: bool


def _as_account(row: dict[str, Any]) -> CitationAccount:
    return CitationAccount(
        id=str(row["id"]),
        client_id=str(row["client_id"]),
        directory_id=str(row["directory_id"]),
        registration_email=str(row["registration_email"]),
        vault_provider=str(row["vault_provider"]),
        vault_label=str(row["vault_label"]),
        health=str(row["health"]),
        credential_sealed=row.get("credential_sealed_at") is not None,
    )


def create_account_with_credential(
    *,
    user_id: str,
    client_id: str,
    directory_id: str,
    registration_email: str,
    password: str | None = None,
    created_by: str | None = None,
) -> tuple[CitationAccount, str]:
    """Create the account row and seal its password. Returns the account and the plaintext.

    THE PLAINTEXT IS RETURNED EXACTLY ONCE, to the caller that created the account -
    normally the signup bot, which needs it to type into the form it is standing in front
    of. It is never returned again by any read path, never logged, and never stored
    outside the vault's sealed bytes. This mirrors how `skill_tokens` hands back its raw
    token once at mint and never again.

    THE ORDER IS FORCED BY THE SCHEMA AND IS THE WHOLE DESIGN. The vault label is the
    account row's own id, so the row must exist before the secret can be named - and
    0111's trigger nulls `credential_sealed_at` on insert so no caller can assert a
    credential that could not yet have been written. Sealing is therefore always a second
    step, and `credential_sealed_at` is set only after `vault.add_key` has actually
    returned.

    If sealing fails the row is DELETED rather than left behind. A citation_account with
    no credential is worse than no row at all: it looks like an account we hold, and the
    unique constraint on (client_id, directory_id) would then block the retry that would
    have created a working one.
    """
    plaintext = password or generate_password()

    with rls_connection(user_id) as cur:
        cur.execute(
            "insert into public.citation_accounts "
            "  (client_id, directory_id, registration_email, created_by) "
            "values (%s, %s, %s, %s) returning *",
            (client_id, directory_id, registration_email, created_by),
        )
        row = cur.fetchone()
    if row is None:  # pragma: no cover - RLS refusal surfaces as no returned row
        raise PermissionError("not permitted to create a citation account for this client")

    account = _as_account(dict(row))
    try:
        vault.add_key(
            provider=account.vault_provider,
            label=account.vault_label,
            secret=plaintext,
            created_by=created_by,
            # `client_access`: a login belonging to a CLIENT's presence, not an agency
            # integration key. Same sealing, same owner-only reveal - the distinction
            # only lets the two populations be told apart without opening either.
            kind="client_access",
        )
    except Exception:
        # Never log the exception body: a vault error can echo the value it was handed.
        logger.warning("citation_account_seal_failed", account_id=account.id)
        with rls_connection(user_id) as cur:
            cur.execute("delete from public.citation_accounts where id = %s", (account.id,))
            removed = cur.rowcount or 0
        if removed == 0:
            # MEASURED 2026-08-30: 0111 gave this table SELECT, INSERT and UPDATE policies
            # and no DELETE policy. Under FORCE ROW LEVEL SECURITY a DELETE with no policy
            # is not an error - it matches nothing and reports success - so this rollback
            # deleted nothing and left behind exactly the credential-less row the comment
            # above calls "worse than no row at all", with the unique
            # (client_id, directory_id) constraint then blocking the retry it existed to
            # enable. 0115 adds the policy, scoped to rows that never sealed.
            #
            # The check stays because a policy can be dropped again, and a rollback that
            # silently does nothing is the failure mode that hid this for a week. If the
            # row survives, say which one, so the operator can clear it by hand.
            logger.error(
                "citation_account_rollback_deleted_nothing",
                account_id=account.id,
                client_id=client_id,
                directory_id=directory_id,
            )
        raise

    with rls_connection(user_id) as cur:
        cur.execute(
            "update public.citation_accounts set credential_sealed_at = now() "
            "where id = %s and credential_sealed_at is null",
            (account.id,),
        )

    logger.info(
        "citation_account_created",
        account_id=account.id,
        directory_id=directory_id,
        # The alias is not a secret and is the only way to tie a confirmation email back
        # to an account. The password never appears here in any form.
        registration_email=registration_email,
    )
    return account, plaintext


def account_for(
    *, user_id: str, client_id: str, directory_id: str
) -> CitationAccount | None:
    """The account we hold for this client on this directory, if any. Never the secret."""
    with rls_connection(user_id) as cur:
        cur.execute(
            "select * from public.citation_accounts "
            "where client_id = %s and directory_id = %s limit 1",
            (client_id, directory_id),
        )
        row = cur.fetchone()
    return _as_account(dict(row)) if row else None


def set_health(
    *, user_id: str, account_id: str, health: str, note: str = ""
) -> bool:
    """Record what we now know about an account's standing.

    Health is LEARNED, never assumed: `unverified` is the default because creating an
    account is not the same as confirming it works. It moves on evidence - a
    confirmation email arriving, a login failing, a suspension notice - and
    `health_checked_at` records when that evidence was seen, so a stale belief is
    visibly stale rather than quietly authoritative."""
    with rls_connection(user_id) as cur:
        cur.execute(
            "update public.citation_accounts "
            "set health = %s, health_checked_at = now(), health_note = %s "
            "where id = %s",
            (health, note[:500], account_id),
        )
        return (cur.rowcount or 0) > 0
