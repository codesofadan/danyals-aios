"""Turn a created account into a REGISTERED one: sealed credential + account row.

WHY THIS IS ONE FUNCTION AND NOT THREE COPIES. Three paths now bring an account into
existence - the CLI, the operator's "add the token" step, and the auto-lane worker that
mints its own. Each needs the identical hygiene: the handle must carry no platform slug
or client hash (R2-08 - the footprint no content check can see), the registration domain
must not be shared across clients, the credential must be sealed under the ACCOUNT id
rather than the client id, and the account row must exist before anything reports live.

Copies of that drift, and the drift is invisible: nothing fails a test, an account simply
gets created a slightly different way, and months later one suspension enumerates a
client base. So the rules live here once and every path calls in.
"""

from __future__ import annotations

import json
from typing import Any


class AccountRegistrationError(ValueError):
    """The account may not be registered as asked, with the reason for an operator."""


def register_account(
    *,
    platform: str,
    client_id: str,
    handle: str,
    registration_email: str,
    credential: dict[str, str],
    property_url: str = "",
    ownership: str = "per_client",
    max_properties: int = 1,
) -> str:
    """Seal the credential and create the account row. Returns the new account id.

    Refuses an empty credential outright: an account row with nothing sealed behind it
    shows green on the board and cannot publish, which is the exact failure the usable
    -account SQL was written after measuring.
    """
    from app.cli.web2_accounts import (
        HandleRejectedError,
        _shared_domains,
        build_spec,
        insert_account,
    )
    from app.services.vault import add_key
    from integrations.web2_credentials import VAULT_KIND_CLIENT_ACCESS, vault_provider_for

    cleaned = {k: str(v) for k, v in credential.items() if str(v).strip()}
    if not cleaned:
        raise AccountRegistrationError(
            "Going live needs the platform credential. An account that reports live with "
            "nothing sealed shows green on the board and cannot publish."
        )
    try:
        spec = build_spec(
            platform=platform,
            ownership=ownership,
            handle=handle,
            client_id=client_id,
            registration_email=registration_email,
            property_url=property_url,
            max_properties=max_properties,
            credential=cleaned,
            shared_domains=_shared_domains(),
        )
    except (HandleRejectedError, ValueError) as refused:
        raise AccountRegistrationError(str(refused)) from refused

    account_id = insert_account(spec)
    # Sealed under the ACCOUNT id, never the client id: one credential per account is
    # what makes a per-client account genuinely separate rather than a naming
    # convention over one shared login.
    add_key(
        provider=vault_provider_for(spec.platform),
        label=account_id,
        secret=json.dumps(spec.credential),
        kind=VAULT_KIND_CLIENT_ACCESS,
    )
    return account_id


def credential_is_complete(platform: str, credential: dict[str, Any]) -> bool:
    """Whether this credential has every field the platform's publisher requires."""
    from integrations.web2_publishers import PLATFORM_CREDENTIAL_FIELDS

    required = PLATFORM_CREDENTIAL_FIELDS.get(platform, ())
    return all(str(credential.get(field, "")).strip() for field in required)
