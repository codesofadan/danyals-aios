"""SSRF guard for audit targets.

The auditor crawls URLs supplied by the operator and follows redirects,
sitemaps, and link-graph discoveries to additional URLs. Without an input-
validation gate it will dutifully probe whatever address it resolves to,
including loopback (127.0.0.1, ::1), link-local (169.254.0.0/16 -> cloud
metadata at 169.254.169.254), RFC1918 private space, and reserved ranges.
That is an SSRF-class defect.

`validate_public_host(host)` is the single source of truth. It:
  1. Normalises the input to a hostname (strips scheme + port + brackets),
  2. Rejects an explicit denylist of well-known internal hostnames,
  3. Resolves every A/AAAA via `socket.getaddrinfo`,
  4. For each resolved address, rejects if `ipaddress.ip_address(addr)`
     reports any of: is_private, is_loopback, is_link_local, is_reserved,
     is_multicast, is_unspecified.

A failure raises `PrivateAddressError` carrying a typer-friendly message.
The CLI converts this into `typer.BadParameter` (exit code 2) BEFORE
creating a Run UUID, artifact dir, or DB row. The crawler's URL-enqueue
layer applies the same check again so that sitemap-discovered or
redirect-target URLs pointing at internal hosts are dropped (defence in
depth against DNS rebinding and 30x redirects to 169.254.169.254).
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
    """
    host = extract_host(value)

    if host in _HOSTNAME_DENYLIST:
        raise PrivateAddressError(f"private/local address not allowed: {host}")

    # If the host *is* an IP literal, check it directly without DNS.
    try:
        literal_ip = ipaddress.ip_address(host)
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
            raise PrivateAddressError(
                f"could not resolve host {host!r}: {e}"
            ) from e
        for info in infos:
            sockaddr = info[4]
            addr = sockaddr[0] if sockaddr else ""
            if addr and _is_private_ip(addr):
                raise PrivateAddressError(
                    f"private/local address not allowed: {host} -> {addr}"
                )

    return host


def is_public_url(url: str) -> bool:
    """Best-effort check used inside the crawler URL-enqueue path. Returns
    False if the URL targets an internal host, True otherwise. Never
    raises - the caller logs and drops the URL silently."""
    try:
        validate_public_host(url)
    except PrivateAddressError:
        return False
    except Exception:  # noqa: BLE001
        return False
    return True
