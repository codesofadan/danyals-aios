"""HTML to PDF, and every way it is allowed to fail.

The whole point of this module is that it never costs an audit anything. A
missing browser, a crashed render, or a browser that exits 0 having written
nothing must each degrade to "no PDF this run" while the workbook, the CSVs and
the HTML that were already written survive. So the failure paths get more tests
than the success path.
"""

from __future__ import annotations

import subprocess

import pytest

from app.services import report_pdf as P


@pytest.fixture
def html(tmp_path):
    p = tmp_path / "audit-report.html"
    p.write_text("<!doctype html><html><body><h1>hi</h1></body></html>", encoding="utf-8")
    return p


def test_no_browser_returns_none_rather_than_raising(html, tmp_path, monkeypatch):
    monkeypatch.setattr(P, "find_browser", lambda: None)
    assert P.render(html, tmp_path / "out.pdf") is None


def test_a_missing_source_is_not_rendered(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "find_browser", lambda: "/bin/true")
    assert P.render(tmp_path / "nope.html", tmp_path / "out.pdf") is None


def test_a_browser_that_crashes_returns_none(html, tmp_path, monkeypatch):
    monkeypatch.setattr(P, "find_browser", lambda: "/bin/true")

    def boom(*a, **k):
        raise OSError("no such binary")

    monkeypatch.setattr(P.subprocess, "run", boom)
    assert P.render(html, tmp_path / "out.pdf") is None


def test_a_hung_browser_is_killed_and_reported_as_a_failure(html, tmp_path, monkeypatch):
    monkeypatch.setattr(P, "find_browser", lambda: "/bin/true")

    def hang(*a, **k):
        raise subprocess.TimeoutExpired(cmd="chrome", timeout=1)

    monkeypatch.setattr(P.subprocess, "run", hang)
    assert P.render(html, tmp_path / "out.pdf") is None


def test_exit_zero_with_no_file_is_a_failure_not_a_success(html, tmp_path, monkeypatch):
    # Chrome does this. The exit code is not evidence that a PDF exists; the file
    # is. Trusting the return code is how a zero-byte "report" gets served.
    monkeypatch.setattr(P, "find_browser", lambda: "/bin/true")
    monkeypatch.setattr(
        P.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0] if a else [], 0, b"", b""),
    )
    assert P.render(html, tmp_path / "out.pdf") is None


def test_an_empty_file_is_a_failure_too(html, tmp_path, monkeypatch):
    out = tmp_path / "out.pdf"
    monkeypatch.setattr(P, "find_browser", lambda: "/bin/true")

    def touch(*a, **k):
        out.write_bytes(b"")
        return subprocess.CompletedProcess([], 0, b"", b"")

    monkeypatch.setattr(P.subprocess, "run", touch)
    assert P.render(html, out) is None


def test_a_written_pdf_comes_back(html, tmp_path, monkeypatch):
    out = tmp_path / "out.pdf"
    monkeypatch.setattr(P, "find_browser", lambda: "/bin/true")

    def write(*a, **k):
        out.write_bytes(b"%PDF-1.4\n")
        return subprocess.CompletedProcess([], 0, b"", b"")

    monkeypatch.setattr(P.subprocess, "run", write)
    assert P.render(html, out) == out


def test_the_source_is_passed_as_a_file_uri_not_a_bare_path(html, tmp_path, monkeypatch):
    # A bare path is treated as a search term by some builds, which renders a blank
    # page and writes a valid, empty PDF - a silent wrong answer.
    seen: dict = {}
    monkeypatch.setattr(P, "find_browser", lambda: "/bin/true")

    def capture(cmd, *a, **k):
        seen["cmd"] = cmd
        (tmp_path / "out.pdf").write_bytes(b"%PDF-1.4\n")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(P.subprocess, "run", capture)
    P.render(html, tmp_path / "out.pdf")
    assert seen["cmd"][-1].startswith("file://")
    # And no --user-data-dir: a profile dir makes headless --print-to-pdf hang.
    assert not any(str(x).startswith("--user-data-dir") for x in seen["cmd"])


def test_an_env_override_wins_over_the_search_path(tmp_path, monkeypatch):
    fake = tmp_path / "chrome"
    fake.write_text("#!/bin/sh\n")
    monkeypatch.setenv("AIOS_CHROME", str(fake))
    assert P.find_browser() == str(fake)


def test_an_env_override_pointing_at_nothing_falls_back(monkeypatch):
    monkeypatch.setenv("AIOS_CHROME", "/does/not/exist")
    # Falls through to the normal search rather than returning a broken path.
    assert P.find_browser() != "/does/not/exist"


def test_the_images_own_browser_variable_is_honoured(tmp_path, monkeypatch):
    # The backend image sets SEO_AUDIT_CHROME to a wrapper that prepends
    # --disable-dev-shm-usage. Ignoring it and finding /usr/bin/chromium instead
    # is how headless rendering crashes on a container's small /dev/shm.
    wrapper = tmp_path / "chromium-wrap"
    wrapper.write_text("#!/bin/sh\n")
    monkeypatch.delenv("AIOS_CHROME", raising=False)
    monkeypatch.setenv("SEO_AUDIT_CHROME", str(wrapper))
    assert P.find_browser() == str(wrapper)


def test_the_explicit_override_still_wins(tmp_path, monkeypatch):
    mine, theirs = tmp_path / "mine", tmp_path / "theirs"
    mine.write_text("")
    theirs.write_text("")
    monkeypatch.setenv("AIOS_CHROME", str(mine))
    monkeypatch.setenv("SEO_AUDIT_CHROME", str(theirs))
    assert P.find_browser() == str(mine)
