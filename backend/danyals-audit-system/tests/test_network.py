"""Probes that open their own socket.

These are the only checks that connect to a host of their own accord rather
than following the crawler, so the SSRF guard matters more here than anywhere
else: a redirect or sitemap entry pointing at 169.254.169.254 would otherwise
become a way to reach cloud metadata from inside the audit.

No test here touches the network. Any that did would be slow, flaky, and would
fail in CI for reasons unrelated to the code.
"""
from __future__ import annotations

import socket
import ssl
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from audit_engine.analyzers import network as nw
from audit_engine.analyzers.context import CrawlContext

ALL = [nw.check_ssl_certificate, nw.check_cdn, nw.check_hosting_performance]


def ctx_for(site="https://example.com/", headers=None, response_ms=200, crawled=True):
    c = CrawlContext(site_url=site)
    if crawled:
        cp = SimpleNamespace(url=site, final_url=site, response_ms=response_ms,
                             parsed=None, headers=headers or {})
        c.by_url[c.home] = cp
        c.crawled_urls.add(c.home)
    return c


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Fail loudly if a test reaches the network by accident."""
    def boom(*a, **k):
        raise AssertionError("a test tried to open a real socket")
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket, "gethostbyname_ex", boom)
    monkeypatch.setattr(socket, "gethostbyaddr", boom)


# --- the SSRF guard ---------------------------------------------------------

@pytest.mark.parametrize("host", [
    "localhost", "127.0.0.1", "169.254.169.254", "10.0.0.1",
    "192.168.1.1", "172.16.0.1", "[::1]",
])
@pytest.mark.parametrize("fn", ALL, ids=lambda f: f.__name__)
def test_a_private_address_is_never_probed(fn, host):
    """This is the check that stops the audit becoming an SSRF primitive."""
    v = fn(ctx_for(site=f"https://{host}/"))
    assert v.status == "n_a", f"{fn.__name__} probed {host}"
    assert not v.remediation


def test_a_public_host_passes_the_guard():
    assert nw._host_of(ctx_for()) == "example.com"


def test_a_missing_host_is_refused():
    assert nw._host_of(ctx_for(site="")) is None


# --- contracts --------------------------------------------------------------

@pytest.mark.parametrize("fn", ALL, ids=lambda f: f.__name__)
def test_every_verdict_is_well_formed(fn):
    v = fn(ctx_for(site="https://127.0.0.1/"))
    assert v.status in {"pass", "warn", "fail", "n_a"}
    assert 0.0 <= v.score <= 10.0 and 0.0 <= v.confidence <= 1.0
    assert isinstance(v.evidence, dict)


def test_ssl_is_n_a_on_a_plain_http_site():
    v = nw.check_ssl_certificate(ctx_for(site="http://example.com/"))
    assert v.status == "n_a"
    assert "not served over HTTPS" in v.evidence["reason"]


# --- certificate ------------------------------------------------------------

def _fake_tls(monkeypatch, *, days, protocol="TLSv1.3", sans=("example.com",)):
    expires = datetime.now(UTC) + timedelta(days=days)
    cert = {
        "notAfter": expires.strftime("%b %d %H:%M:%S %Y GMT"),
        "issuer": ((("organizationName", "Test CA"),),),
        "subjectAltName": tuple(("DNS", s) for s in sans),
    }

    class Tls:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def getpeercert(self): return cert
        def version(self): return protocol
        def cipher(self): return ("TLS_AES_256_GCM_SHA384", protocol, 256)

    class Sock:
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: Sock())
    monkeypatch.setattr(
        ssl.SSLContext, "wrap_socket", lambda self, sock, server_hostname=None: Tls())


def test_a_healthy_certificate_passes(monkeypatch):
    _fake_tls(monkeypatch, days=200)
    v = nw.check_ssl_certificate(ctx_for())
    assert v.status == "pass"
    assert v.evidence["issuer"] == "Test CA"
    assert v.evidence["covers_host"] is True


def test_an_expired_certificate_is_critical(monkeypatch):
    _fake_tls(monkeypatch, days=-3)
    v = nw.check_ssl_certificate(ctx_for())
    assert v.status == "fail" and v.severity == "critical" and v.score == 0.0
    assert "interstitial" in v.remediation


def test_an_imminent_expiry_is_critical(monkeypatch):
    """If renewal is automated it has already failed."""
    _fake_tls(monkeypatch, days=5)
    v = nw.check_ssl_certificate(ctx_for())
    assert v.status == "fail" and v.severity == "critical"
    assert "already failed" in v.remediation


def test_expiry_within_a_month_warns(monkeypatch):
    _fake_tls(monkeypatch, days=25)
    assert nw.check_ssl_certificate(ctx_for()).status == "warn"


@pytest.mark.parametrize("protocol", ["TLSv1", "TLSv1.1"])
def test_a_deprecated_tls_version_is_critical(monkeypatch, protocol):
    """RFC 8996 deprecated both in 2021."""
    _fake_tls(monkeypatch, days=200, protocol=protocol)
    v = nw.check_ssl_certificate(ctx_for())
    assert v.status == "fail" and v.severity == "critical"
    assert "RFC 8996" in v.remediation


def test_a_certificate_that_does_not_cover_the_host_is_critical(monkeypatch):
    _fake_tls(monkeypatch, days=200, sans=("other.com",))
    v = nw.check_ssl_certificate(ctx_for())
    assert v.status == "fail"
    assert v.evidence["covers_host"] is False


def test_a_wildcard_certificate_covers_a_subdomain(monkeypatch):
    """validate_public_host resolves DNS, which the no-network fixture blocks,
    so the guard is stubbed here to keep the test about certificate logic."""
    _fake_tls(monkeypatch, days=200, sans=("*.example.com",))
    monkeypatch.setattr(nw, "validate_public_host", lambda h: h)
    c = ctx_for(site="https://shop.example.com/")
    assert nw.check_ssl_certificate(c).evidence["covers_host"] is True


def test_a_verification_failure_is_critical(monkeypatch):
    def boom(*a, **k):
        raise ssl.SSLCertVerificationError("self signed certificate")
    monkeypatch.setattr(socket, "create_connection", boom)
    v = nw.check_ssl_certificate(ctx_for())
    assert v.status == "fail" and v.severity == "critical"


def test_an_unreachable_host_is_n_a_not_a_failure(monkeypatch):
    """We could not measure it. That is not the same as it being broken."""
    def boom(*a, **k):
        raise TimeoutError("timed out")
    monkeypatch.setattr(socket, "create_connection", boom)
    v = nw.check_ssl_certificate(ctx_for())
    assert v.status == "n_a"
    assert not v.remediation


# --- CDN --------------------------------------------------------------------

@pytest.mark.parametrize("header,name", [
    ("cf-ray", "Cloudflare"), ("x-amz-cf-id", "Amazon CloudFront"),
    ("x-served-by", "Fastly"), ("x-vercel-id", "Vercel"),
    ("x-sucuri-id", "Sucuri"),
])
def test_a_cdn_is_detected_from_its_header(monkeypatch, header, name):
    monkeypatch.setattr(socket, "gethostbyname_ex", lambda h: (h, [], ["1.2.3.4"]))
    v = nw.check_cdn(ctx_for(headers={header: "x"}))
    assert v.status == "pass"
    assert name in v.evidence["cdn_detected"]


def test_a_cdn_is_detected_from_the_server_header(monkeypatch):
    monkeypatch.setattr(socket, "gethostbyname_ex", lambda h: (h, [], ["1.2.3.4"]))
    v = nw.check_cdn(ctx_for(headers={"server": "cloudflare"}))
    assert "Cloudflare" in v.evidence["cdn_detected"]


def test_a_cdn_is_detected_from_a_dns_alias(monkeypatch):
    monkeypatch.setattr(
        socket, "gethostbyname_ex",
        lambda h: (h, ["d123.cloudfront.net"], ["1.2.3.4"]))
    v = nw.check_cdn(ctx_for(headers={"server": "nginx"}))
    assert "Amazon CloudFront" in v.evidence["cdn_detected"]


def test_no_cdn_is_a_minor_warning_not_a_failure(monkeypatch):
    """A small business served fast from one region does not need a CDN."""
    monkeypatch.setattr(socket, "gethostbyname_ex", lambda h: (h, [], ["1.2.3.4"]))
    v = nw.check_cdn(ctx_for(headers={"server": "nginx"}))
    assert v.status == "warn" and v.severity == "minor"
    assert "not required" in v.remediation


def test_a_dns_failure_does_not_break_cdn_detection(monkeypatch):
    def boom(h):
        raise OSError("no such host")
    monkeypatch.setattr(socket, "gethostbyname_ex", boom)
    v = nw.check_cdn(ctx_for(headers={"cf-ray": "x"}))
    assert v.status == "pass"


def test_cdn_is_n_a_without_a_captured_homepage(monkeypatch):
    monkeypatch.setattr(socket, "gethostbyname_ex", lambda h: (h, [], []))
    assert nw.check_cdn(ctx_for(crawled=False)).status == "n_a"


# --- hosting ----------------------------------------------------------------

def _dns(monkeypatch, ip="203.0.113.9", rdns="host.example-hosting.net"):
    monkeypatch.setattr(socket, "gethostbyname_ex", lambda h: (h, [], [ip]))
    monkeypatch.setattr(socket, "gethostbyaddr", lambda a: (rdns, [], [a]))


def test_a_fast_origin_passes(monkeypatch):
    _dns(monkeypatch)
    v = nw.check_hosting_performance(ctx_for(response_ms=300))
    assert v.status == "pass"
    assert v.evidence["reverse_dns"] == "host.example-hosting.net"


def test_a_slow_origin_names_who_is_answering(monkeypatch):
    _dns(monkeypatch)
    v = nw.check_hosting_performance(ctx_for(response_ms=1200))
    assert v.status == "warn"
    assert "host.example-hosting.net" in v.remediation


def test_a_very_slow_origin_is_critical(monkeypatch):
    _dns(monkeypatch)
    v = nw.check_hosting_performance(ctx_for(response_ms=5638))
    assert v.status == "fail" and v.severity == "critical"
    assert "before the first byte" in v.remediation


def test_hosting_is_n_a_without_a_crawled_homepage():
    assert nw.check_hosting_performance(ctx_for(crawled=False)).status == "n_a"


def test_hosting_is_n_a_without_timing(monkeypatch):
    _dns(monkeypatch)
    assert nw.check_hosting_performance(ctx_for(response_ms=0)).status == "n_a"


def test_reverse_dns_failure_still_produces_a_verdict(monkeypatch):
    monkeypatch.setattr(socket, "gethostbyname_ex", lambda h: (h, [], ["203.0.113.9"]))
    def boom(a):
        raise OSError("no PTR")
    monkeypatch.setattr(socket, "gethostbyaddr", boom)
    v = nw.check_hosting_performance(ctx_for(response_ms=5000))
    assert v.status == "fail"
    assert "203.0.113.9" in v.remediation


def test_the_network_probe_reason_is_retired():
    from audit_engine.analyzers.ledger import Reason
    assert not hasattr(Reason, "NEEDS_NETWORK_PROBE")
