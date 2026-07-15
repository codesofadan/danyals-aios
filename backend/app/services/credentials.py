"""One-time credential generation for the Add-Member invite flow (Part 7 / 7F-4).

The Add-Member wizard hands a new teammate a generated username + a strong
temporary password, shown to the admin exactly once. This module is the
SERVER-SIDE, cryptographically-random counterpart of the wizard's client-side
``genUsername`` / ``genPassword`` (``frontend/components/team/AddMemberWizard.tsx``):
usernames follow the same ``first.last`` shape, and passwords keep the readable
``Adjective-Noun####$`` skeleton but draw every choice from :mod:`secrets` and add
a hex tail so the result is high-entropy, not guessable from the two short word
lists. The plaintext is returned to the caller ONCE and never stored - only its
argon2id hash is persisted (see :mod:`app.services.provisioning`).
"""

from __future__ import annotations

import re
import secrets

# Readable word lists (mirrors the wizard). Entropy does NOT rest on these alone -
# the 4-digit block, symbol and hex tail below dominate - so a short, friendly
# list is fine for the human-facing prefix.
_ADJ = (
    "Solar", "Rapid", "Cobalt", "Lunar", "Amber", "Quartz",
    "Nimbus", "Vivid", "Onyx", "Cedar", "Zephyr", "Crimson",
)
_NOUN = (
    "Falcon", "Harbor", "Cipher", "Meadow", "Quasar", "Lynx",
    "Beacon", "Vertex", "Willow", "Ember", "Comet", "Delta",
)
_SYM = "!@#$%&*?"


def generate_password() -> str:
    """Return a strong, readable one-time password (>= ~64 bits from the tail alone).

    Shape ``Adjective-Noun####$xxxxxx``: a friendly prefix plus a 4-digit block, a
    symbol and a 6-hex-char tail, every element chosen with :mod:`secrets`. It
    satisfies typical complexity rules (upper, lower, digit, symbol) and is meant
    to be reset on first login, so readability for hand-off matters.
    """
    adj = secrets.choice(_ADJ)
    noun = secrets.choice(_NOUN)
    digits = secrets.randbelow(9000) + 1000  # 1000..9999
    sym = secrets.choice(_SYM)
    tail = secrets.token_hex(3)  # 6 hex chars of extra entropy
    return f"{adj}-{noun}{digits}{sym}{tail}"


def generate_username(name: str) -> str:
    """Derive a login username from a display name (mirrors the wizard's genUsername).

    ``"Ali Hassan" -> "ali.hassan"``; a single token becomes ``"<token>.aios"``;
    an empty/symbol-only name falls back to ``"new.member"``. Uniqueness is NOT
    guaranteed here - a collision surfaces on the DB's case-insensitive unique
    index and the router maps it to a clean 400.
    """
    parts = [p for p in re.sub(r"[^a-z\s]", "", name.strip().lower()).split() if p]
    if not parts:
        return "new.member"
    if len(parts) == 1:
        return f"{parts[0]}.aios"
    return f"{parts[0]}.{parts[-1]}"
