"""Chunk 4 gate: the ported SSRF guard.

``socket.getaddrinfo`` is mocked so these tests need no network and are
deterministic across machines.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator

import pytest

from app.core.security import (
    PrivateAddressError,
    extract_host,
    is_public_url,
    validate_public_host,
)


def _addrinfo(*addrs: str) -> list[tuple[int, int, int, str, tuple[str, int]]]:
    """Build a fake ``getaddrinfo`` return value resolving to ``addrs``."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (addr, 0)) for addr in addrs]


@pytest.fixture
def resolve_to(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """No test may hit real DNS: fail loudly if getaddrinfo isn't stubbed."""

    def _guard(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("socket.getaddrinfo called without a stub")

    monkeypatch.setattr(socket, "getaddrinfo", _guard)
    yield


def _stub_resolution(monkeypatch: pytest.MonkeyPatch, *addrs: str) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: _addrinfo(*addrs))


@pytest.mark.unit
def test_rejects_localhost_by_name() -> None:
    # denylisted by name, before any DNS
    with pytest.raises(PrivateAddressError):
        validate_public_host("http://localhost:8000/")


@pytest.mark.unit
def test_rejects_loopback_ipv4_literal() -> None:
    with pytest.raises(PrivateAddressError):
        validate_public_host("127.0.0.1")


@pytest.mark.unit
def test_rejects_loopback_ipv6_literal() -> None:
    with pytest.raises(PrivateAddressError):
        validate_public_host("[::1]")


@pytest.mark.unit
def test_rejects_private_ipv4_literal() -> None:
    with pytest.raises(PrivateAddressError):
        validate_public_host("10.0.0.5")


@pytest.mark.unit
def test_rejects_metadata_ip_by_name() -> None:
    # 169.254.169.254 is both denylisted and link-local
    with pytest.raises(PrivateAddressError):
        validate_public_host("169.254.169.254")


@pytest.mark.unit
def test_rejects_ipv4_mapped_ipv6_metadata_literal() -> None:
    # ::ffff:169.254.169.254 is a link-local mapped address
    with pytest.raises(PrivateAddressError):
        validate_public_host("[::ffff:a9fe:a9fe]")


@pytest.mark.unit
def test_rejects_symbolic_host_resolving_private(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resolution(monkeypatch, "10.0.0.5")
    with pytest.raises(PrivateAddressError):
        validate_public_host("https://sneaky.internal.example/")


@pytest.mark.unit
def test_rejects_symbolic_host_resolving_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resolution(monkeypatch, "169.254.169.254")
    with pytest.raises(PrivateAddressError):
        validate_public_host("https://rebind.example/")


@pytest.mark.unit
def test_accepts_symbolic_host_resolving_public(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resolution(monkeypatch, "93.184.216.34")  # example.com's public IP
    assert validate_public_host("https://example.com/path") == "example.com"


@pytest.mark.unit
def test_rejects_when_any_resolved_address_is_private(monkeypatch: pytest.MonkeyPatch) -> None:
    # one public + one private -> must reject (checks EVERY resolved address)
    _stub_resolution(monkeypatch, "93.184.216.34", "10.0.0.5")
    with pytest.raises(PrivateAddressError):
        validate_public_host("https://mixed.example/")


@pytest.mark.unit
def test_unresolvable_host_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(*_a: object, **_k: object) -> object:
        raise socket.gaierror("name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", _fail)
    with pytest.raises(PrivateAddressError):
        validate_public_host("https://does-not-exist.example/")


@pytest.mark.unit
def test_is_public_url_never_raises_on_garbage() -> None:
    assert is_public_url("not a url") is False
    assert is_public_url("") is False


@pytest.mark.unit
def test_is_public_url_false_for_private(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resolution(monkeypatch, "10.0.0.5")
    assert is_public_url("https://sneaky.example/") is False


@pytest.mark.unit
def test_is_public_url_true_for_public(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_resolution(monkeypatch, "93.184.216.34")
    assert is_public_url("https://example.com/") is True


@pytest.mark.unit
def test_extract_host_variants() -> None:
    assert extract_host("example.com") == "example.com"
    assert extract_host("https://Example.com:8443/path?q=1") == "example.com"
    assert extract_host("example.com:8080") == "example.com"
    assert extract_host("http://[::1]:8000") == "::1"
