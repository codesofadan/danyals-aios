"""Argon2id password hashing for the local login path (P6A-7 auth cutover).

The cutover replaces Supabase GoTrue with local username/password auth. Every
credential lives ONLY in ``auth.users.password_hash`` as an argon2id hash, sealed
with the library defaults (a per-hash random salt is embedded in the encoded
string). Verification is constant-time inside argon2-cffi and never raises out of
:func:`verify_password` - a mismatch, a malformed hash, or a hashing failure all
return ``False`` so the caller can answer a uniform, non-enumerating 401.

Future path (NOT implemented): a migration importing Supabase/bcrypt hashes would
detect a ``$2b$`` prefix here, verify with ``bcrypt``, and transparently re-hash
to argon2id on the next successful login. This is a fresh local start, so only
argon2id is produced/accepted today.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

# One process-wide hasher; the defaults are the argon2-cffi RFC 9106 recommended
# parameters. It is stateless and thread-safe, so sharing it is safe.
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Return an argon2id encoded hash (salt + parameters embedded) for ``password``."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Whether ``password`` matches ``password_hash``. Never raises (bad hash -> False).

    Returns ``False`` for a wrong password AND for a malformed/empty stored hash,
    so the login endpoint can return one generic 401 with no user enumeration.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
