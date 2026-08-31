"""Scoring the detectability of an automated browser session.

Web 2.0 account creation is browser-only - no platform offers a signup API - so every
signup spec rests on sessions that survive bot detection. This scorer is what makes that
measurable instead of assumed: before it existed, "is our stealth good enough" was a
question answered by reading blog posts.

The scoring is pure, so these run with no browser. The live probe that feeds it is
exercised separately against a real Chromium.

ONE THING THIS FILE MUST KEEP HONEST: a clean report means the FINGERPRINT is clean. TLS
fingerprinting, IP reputation and behavioural scoring are decided by the defender
off-page and are invisible from inside the browser. Letting "no leaks" be read as "signup
will work" would be exactly the overclaim the rest of this module exists to prevent.
"""

from __future__ import annotations

import pytest

from app.services.browser_fingerprint import score_probe

pytestmark = pytest.mark.unit


def _clean() -> dict[str, object]:
    """A probe from a session with nothing obviously wrong."""
    return {
        "webdriver": False,
        "userAgent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/120.0.0.0",
        "pluginCount": 5, "mimeTypeCount": 4,
        "languages": ["en-US", "en"], "hasChromeRuntime": True,
        "hardwareConcurrency": 8, "deviceMemory": 8,
        "notificationPerm": "default", "outerDims": [1440, 900],
        "webglVendor": "Intel Inc.", "webglRenderer": "Intel Iris OpenGL Engine",
    }


def test_a_clean_session_reports_no_leaks() -> None:
    assert score_probe(_clean()).clean


def test_webdriver_true_is_a_high_leak() -> None:
    """The single most-checked flag; on its own it identifies automation."""
    rep = score_probe({**_clean(), "webdriver": True})
    assert not rep.clean
    assert any(x.signal == "navigator.webdriver" for x in rep.high)


def test_headless_chrome_in_the_user_agent_is_a_high_leak() -> None:
    """A JS shim cannot remove this - the string comes from the binary - so it is the
    signal that decides whether a patched browser is actually needed."""
    rep = score_probe({**_clean(), "userAgent": "Mozilla/5.0 HeadlessChrome/120.0.0.0"})
    assert any(x.signal == "userAgent" for x in rep.high)


def test_a_software_rasteriser_is_a_high_leak() -> None:
    """SwiftShader is what a headless container falls back to when there is no GPU. No
    consumer machine reports it, so it marks the session as a datacentre bot by itself.
    This was the LAST remaining leak in the real stack before WebGL masking was added."""
    for renderer in (
        "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device))",
        "llvmpipe (LLVM 15.0.7, 256 bits)",
        "Mesa OffScreen",
    ):
        rep = score_probe({**_clean(), "webglRenderer": renderer})
        assert any(x.signal == "WebGL renderer" for x in rep.high), renderer


def test_a_real_gpu_string_is_not_flagged() -> None:
    """The check must not fire on ordinary hardware, or it would report every genuine
    machine as a bot and the score would carry no information."""
    for renderer in ("Intel Iris OpenGL Engine", "Apple M2", "NVIDIA GeForce RTX 3060"):
        assert score_probe({**_clean(), "webglRenderer": renderer}).clean, renderer


def test_empty_plugin_and_language_lists_are_leaks() -> None:
    assert not score_probe({**_clean(), "pluginCount": 0}).clean
    assert not score_probe({**_clean(), "languages": []}).clean


def test_zero_outer_dimensions_are_a_headless_tell() -> None:
    """Headless reports 0x0; a real window never does."""
    rep = score_probe({**_clean(), "outerDims": [0, 0]})
    assert any("outerWidth" in x.signal for x in rep.high)


def test_the_summary_states_what_it_does_not_cover() -> None:
    """The honesty rule, enforced: a clean score must never read as 'will not be caught'."""
    text = score_probe(_clean()).summary()
    assert "TLS" in text and "behaviour" in text


def test_a_raw_headless_probe_is_scored_as_badly_leaking() -> None:
    """The measured raw-Playwright baseline: 4 high signals. Pinned so a regression in
    the scorer that silently stopped detecting anything would fail here."""
    raw = {
        "webdriver": True, "userAgent": "Mozilla/5.0 HeadlessChrome/120",
        "pluginCount": 0, "mimeTypeCount": 0, "languages": [],
        "hasChromeRuntime": False, "hardwareConcurrency": 8, "deviceMemory": 8,
        "notificationPerm": "denied", "outerDims": [1280, 720],
        "webglVendor": "Google Inc.",
        "webglRenderer": "ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device))",
    }
    rep = score_probe(raw)
    assert len(rep.high) >= 4
