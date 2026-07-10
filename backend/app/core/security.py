"""SSRF guard - ported from ``danyals-audit-system/audit_engine/security.py``.

Source: the audit engine crawls operator-supplied URLs and follows redirects,
sitemaps, and link-graph discoveries. Without a validation gate it would probe
whatever address it resolves to, including loopback (127.0.0.1, ::1), link-local
(169.254.0.0/16 -> cloud metadata at 169.254.169.254), RFC1918 private space, and
reserved ranges. ``validate_public_host`` is the single source of truth: it
normalises the input to a hostname, rejects a denylist of internal names, and
rejects any host that resolves (via ``socket.getaddrinfo``) to a private,
loopback, link-local, reserved, multicast, or unspecified address.

CALLER CONTRACT (Part 2 - read before wiring this into a fetch path):

* ``socket.getaddrinfo`` BLOCKS on DNS. Any async route that validates a host
  MUST offload it: ``await asyncio.to_thread(validate_public_host, url)`` (or
  ``anyio.to_thread.run_sync``). Never call it directly on the event loop.

* One-shot validation is INSUFFICIENT. A later ``httpx`` fetch re-resolves DNS
  and follows redirects, so a host that validated as public can be re-pointed at
  an internal address between the check and the fetch (TOCTOU / DNS-rebinding),
  or a 30x can redirect to 169.254.169.254. The fetch path MUST disable
  automatic redirects (``follow_redirects=False``) and re-validate every hop -
  or pin the connection to the already-validated IP.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

# Hostnames that resolve to internal infrastructure on common platforms.
# We reject these by name (before DNS) because some resolvers may rewrite
# them or because they are well-known SSRF pivots.
_HOSTNAME_DENYLIST = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "ip6-localhost",
        "ip6-loopback",
        "metadata.google.internal",
        "metadata",  # AWS / GCP shorthand
        "169.254.169.254",  # AWS / GCP / Azure IMDS
    }
)


class PrivateAddressError(ValueError):
    """Raised when a target host resolves to a private/internal address."""


def _strip_brackets(host: str) -> str:
    """Strip IPv6 URL brackets, e.g. '[::1]' -> '::1'."""
    if host.startswith("[") and host.endswith("]"):
        return host[1:-1]
    return host


def extract_host(value: str) -> str:
    """Extract a bare hostname from either a hostname or a URL.

    Accepts: 'example.com', 'https://example.com/path', 'example.com:8080',
    '[::1]', 'http://[::1]:8000'. Returns the host portion, lower-cased,
    with surrounding IPv6 brackets stripped.
    """
    raw = (value or "").strip()
    if not raw:
        raise PrivateAddressError("empty host")
    # If it parses as a URL with a scheme, use urlparse.hostname (handles
    # port + IPv6 brackets correctly).
    if "://" in raw:
        host = urlparse(raw).hostname or ""
    else:
        # Bare host[:port]; strip a trailing port. IPv6 literals must already
        # be bracketed in this branch (we cannot disambiguate 'a:1' otherwise).
        host = raw
        if host.startswith("["):
            # bracketed IPv6 + optional :port
            close = host.find("]")
            if close >= 0:
                host = host[: close + 1]
        elif host.count(":") == 1:
            host = host.split(":", 1)[0]
    host = _strip_brackets(host).lower()
    if not host:
        raise PrivateAddressError(f"could not parse host from {value!r}")
    return host


def _is_private_ip(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        # Not an IP literal; treated as non-private here. The hostname
        # denylist + DNS resolution path covers symbolic names.
        return False
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_public_host(value: str) -> str:
    """Validate that `value` (host or URL) resolves only to public addresses.

    Returns the extracted hostname on success. Raises `PrivateAddressError`
    with a human-readable message on failure.

    NOTE: ``socket.getaddrinfo`` blocks; on an async route offload this call
    (see the module docstring's caller contract).
    """
    host = extract_host(value)

    if host in _HOSTNAME_DENYLIST:
        raise PrivateAddressError(f"private/local address not allowed: {host}")

    # If the host *is* an IP literal, check it directly without DNS.
    try:
        literal_ip: ipaddress.IPv4Address | ipaddress.IPv6Address | None = ipaddress.ip_address(host)
    except ValueError:
        literal_ip = None
    if literal_ip is not None and _is_private_ip(host):
        raise PrivateAddressError(f"private/local address not allowed: {host}")

    # Resolve symbolic hostnames and check every returned address.
    if literal_ip is None:
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as e:
            # DNS failure - surface as a validation error so we don't try
            # to crawl an unresolvable host either.
            raise PrivateAddressError(f"could not resolve host {host!r}: {e}") from e
        for info in infos:
            sockaddr = info[4]
            addr = str(sockaddr[0]) if sockaddr else ""
            if addr and _is_private_ip(addr):
                raise PrivateAddressError(f"private/local address not allowed: {host} -> {addr}")

    return host


def is_public_url(url: str) -> bool:
    """Best-effort check used inside a URL-enqueue path. Returns False if the URL
    targets an internal host, True otherwise. Never raises - the caller logs and
    drops the URL silently."""
    try:
        validate_public_host(url)
    except PrivateAddressError:
        return False
    except Exception:
        return False
    return True
