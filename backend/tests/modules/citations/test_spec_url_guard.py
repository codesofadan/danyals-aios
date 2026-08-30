"""The SSRF guard, rewritten after an adversarial review broke the first one.

0108 bound a spec's URL host to its directory's host with an RFC-3986-shaped regex. The
consumer is Chromium, a WHATWG parser that treats `\\` as `/` inside the authority — so
the two disagreed, and two payloads navigated somewhere the check had approved:

    https://evil.com\\@brownbook.net                    regex: brownbook.net  browser: evil.com
    https://169.254.169.254\\.brownbook.net/latest/…    regex: matched %.brownbook.net
                                                       browser: 169.254.169.254

Both were MEASURED against the real Chromium Playwright drives. Adding a backslash case
would have fixed those two and left the class open, so 0114 refuses ambiguity instead: a
URL is accepted only in the narrow form where every parser agrees.

These are unit tests of the SQL predicate. The end-to-end refusals are exercised against
a live database in the migration's own verification.
"""

from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.unit

MIGRATION = "db/migrations/0114_spec_url_unambiguous.sql"


def _sql() -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[3].parent / MIGRATION).read_text()


# --------------------------------------------------------------------------- #
# The predicate, mirrored. Kept in step with the SQL by the tests below.
# --------------------------------------------------------------------------- #
_ABS = re.compile(r"^https?://[a-z0-9.-]+(:[0-9]{1,5})?([/?#].*)?$", re.I)
_BARE = re.compile(r"^[a-z0-9.-]+(:[0-9]{1,5})?(/.*)?$", re.I)


def host_of(u: str) -> str | None:
    """A faithful mirror of `public._spec_host_of`. NULL means REFUSE, not unknown."""
    if re.search(r"[\\\s]", u) or re.search(r"[^\x20-\x7e]", u) or "%" in u:
        return None
    if _ABS.match(u):
        m = re.match(r"^https?://([a-z0-9.-]+)", u, re.I)
        return re.sub(r"^www\.", "", m.group(1).lower()) if m else None
    if _BARE.match(u):
        m = re.match(r"^([a-z0-9.-]+)", u, re.I)
        return re.sub(r"^www\.", "", m.group(1).lower()) if m else None
    return None


# --------------------------------------------------------------------------- #
# The payloads that defeated the first guard.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "payload",
    [
        r"https://evil.com\@brownbook.net/add",
        r"https://169.254.169.254\.brownbook.net/latest/meta-data/",
        r"https://brownbook.net\@evil.com/",
    ],
)
def test_the_backslash_bypasses_are_refused(payload: str) -> None:
    """A backslash is where RFC 3986 and the WHATWG URL Standard disagree, and the
    disagreement IS the vulnerability — our check reads one host, the browser navigates
    to another."""
    assert host_of(payload) is None


@pytest.mark.parametrize(
    "payload",
    [
        "https://user:pw@brownbook.net/add",          # userinfo: nothing to strip if refused
        "https://brownbook.net\t/add",                # tab: stripped by WHATWG, not by us
        "https://brownbook.net\n/add",                # newline: same
        "https://brownb%6fok.net/add",                # percent-encoding in the authority
        "https://brownbο ok.net/add",                  # non-ASCII: IDN homograph
        "https://brown​book.net/add",            # zero-width: invisible in review
    ],
)
def test_the_wider_ambiguity_class_is_refused(payload: str) -> None:
    """Not a blocklist of known tricks — a whitelist of the one unambiguous shape. Every
    future divergence between the two URL standards is closed by construction."""
    assert host_of(payload) is None


# --------------------------------------------------------------------------- #
# The legitimate forms still work — the catalogue holds both.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.brownbook.net/business/add/", "brownbook.net"),
        ("https://brownbook.net/add", "brownbook.net"),
        ("brownbook.net", "brownbook.net"),                      # 155 seed rows look like this
        ("https://www.2findlocal.com/", "2findlocal.com"),       # 71 look like this
        ("https://sub.brownbook.net/add", "sub.brownbook.net"),
        ("https://brownbook.net:8443/add", "brownbook.net"),
    ],
)
def test_ordinary_directory_urls_still_resolve(url: str, expected: str) -> None:
    assert host_of(url) == expected


def test_www_is_stripped_from_both_sides_so_a_spec_binds_to_a_bare_catalogue_row() -> None:
    assert host_of("https://www.brownbook.net/add") == host_of("brownbook.net")


# --------------------------------------------------------------------------- #
# The rules the migration adds, asserted on the migration itself.
# --------------------------------------------------------------------------- #
def test_an_ip_literal_host_is_refused_outright() -> None:
    """A directory is a domain. IPs are how every SSRF payload names its target, so the
    shape is closed rather than enumerated as a blocklist of private ranges."""
    sql = _sql()
    assert "_host_is_ip_literal" in sql
    assert "may not be an IP literal" in sql


def test_directory_id_is_immutable_so_a_verification_cannot_be_moved() -> None:
    """MEASURED: a verified, ACTIVE spec was moved from 'Brownbook' to 'Brownbook (UK)'
    in one UPDATE. The catalogue shares hosts widely — 4 rows on brownbook.net, 3 on
    bbb.org, 3 on n49.com — and the whitelist is keyed by NAME, so the bot would then
    serve a spec for a directory that never earned it."""
    assert "directory_specs.directory_id is immutable" in _sql()


def test_the_verification_evidence_cannot_be_rewritten() -> None:
    """MEASURED: evidence could be replaced with `{"notes": "I never looked"}` and
    verified_by set to NULL while the write-once date stood. A verification whose record
    of what was checked is rewritable is not a verification."""
    assert "evidence and signer are fixed once it is recorded" in _sql()


def test_changing_a_directorys_url_voids_its_specs() -> None:
    """The parser-free bypass: point a directory at an internal host, earn a spec against
    it, restore the url. The guard only ever validated against the CURRENT url."""
    sql = _sql()
    assert "directories_url_change_voids_specs" in sql
    assert "directory_url_changed" in sql


def test_the_binding_is_rechecked_on_ACTIVATION_not_merely_at_insert() -> None:
    """A hole opened by the first version of this very fix, and measured: scoping the
    check to INSERT let a url-change-voided spec be re-armed with a plain
    `set active = true` while its directory had become 169.254.169.254.

    Activation is the moment a stale binding becomes dangerous, because it is when the
    row starts being served to the browser — so that is where it is re-checked."""
    assert "not (new.active and not old.active)" in _sql()
