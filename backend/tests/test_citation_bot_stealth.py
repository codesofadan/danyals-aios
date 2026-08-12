"""Anti-detection + availability-gate tests for the Playwright citation bot.

No real browser is launched: a fake ``playwright.sync_api`` module is injected so the
submit path runs against recorders. Proves the Phase-3 stealth measures are actually
applied (randomized fingerprint, webdriver mask, human-cadence typing) and that the
engine-status gate honestly reflects whether Playwright+Chromium are present.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

import integrations.citation_status as cs
from integrations.citation_bot import PlaywrightCitationSubmitter
from integrations.citation_submitters import CitationJob


# --------------------------------------------------------------------------- #
# playwright_bot_available() — the honest engine gate
# --------------------------------------------------------------------------- #
def test_available_false_when_package_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cs.importlib.util, "find_spec", lambda name: None)
    assert cs.playwright_bot_available() is False


def test_available_true_when_browser_present(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cs.importlib.util, "find_spec", lambda name: object())
    (tmp_path / "chromium-1234").mkdir()  # a Chromium build present
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))
    assert cs.playwright_bot_available() is True


def test_available_false_when_browser_dir_empty(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cs.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))  # no chromium-* inside
    monkeypatch.setattr(cs.Path, "home", classmethod(lambda cls: tmp_path / "nohome"))
    assert cs.playwright_bot_available() is False


# --------------------------------------------------------------------------- #
# Fake Playwright — records what the bot does to the browser/context/page
# --------------------------------------------------------------------------- #
class _Page:
    def __init__(self) -> None:
        self.typed: list[tuple[str, str]] = []
        self.filled: list[tuple[str, str]] = []
        self.clicked: list[str] = []
        self.waits: list[int] = []

    def goto(self, url: str, **_: object) -> None: ...
    def click(self, selector: str, **_: object) -> None:
        self.clicked.append(selector)

    def type(self, selector: str, value: str, **_: object) -> None:
        self.typed.append((selector, value))

    def fill(self, selector: str, value: str, **_: object) -> None:
        self.filled.append((selector, value))

    def wait_for_timeout(self, ms: int) -> None:
        self.waits.append(ms)

    def screenshot(self, **_: object) -> None: ...
    def content(self) -> str:
        return "Thank you, your listing was received"

    def locator(self, _: str) -> object:  # pragma: no cover - success uses text= path
        raise AssertionError("text= success path should be used")


class _Context:
    def __init__(self, page: _Page) -> None:
        self._page = page
        self.init_scripts: list[str] = []
        self.kwargs: dict[str, object] = {}

    def add_init_script(self, js: str) -> None:
        self.init_scripts.append(js)

    def new_page(self) -> _Page:
        return self._page

    def close(self) -> None: ...


class _Browser:
    def __init__(self, ctx: _Context) -> None:
        self._ctx = ctx
        self.context_kwargs: dict[str, object] = {}

    def new_context(self, **kwargs: object) -> _Context:
        self._ctx.kwargs = kwargs
        return self._ctx

    def close(self) -> None: ...


class _Chromium:
    def __init__(self, browser: _Browser) -> None:
        self._browser = browser
        self.launch_kwargs: dict[str, object] = {}

    def launch(self, **kwargs: object) -> _Browser:
        self.launch_kwargs = kwargs
        return self._browser


class _PW:
    def __init__(self, chromium: _Chromium) -> None:
        self.chromium = chromium

    def __enter__(self) -> _PW:
        return self

    def __exit__(self, *_: object) -> None: ...


@pytest.fixture
def fake_pw(monkeypatch: pytest.MonkeyPatch) -> tuple[_Chromium, _Context, _Page]:
    page = _Page()
    ctx = _Context(page)
    browser = _Browser(ctx)
    chromium = _Chromium(browser)
    mod = types.ModuleType("playwright.sync_api")
    mod.sync_playwright = lambda: _PW(chromium)  # type: ignore[attr-defined]
    pkg = types.ModuleType("playwright")
    monkeypatch.setitem(sys.modules, "playwright", pkg)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", mod)
    return chromium, ctx, page


def _spec_single():
    from integrations.citation_bot import FormField, FormSpec

    return {
        "TestDir": FormSpec(
            directory_name="TestDir",
            url="https://dir.example/add",
            fields=(FormField(selector="#name", value_key="business_name"),),
            submit_selector="#go",
            success_indicator="text=your listing was received",
        )
    }


def _job() -> CitationJob:
    return CitationJob(
        directory_name="TestDir",
        directory_url="https://dir.example",
        market="global",
        submit_method="bot:playwright",
        business_name="Acme Co",
        address_line1="1 St",
        address_line2="",
        city="Lahore",
        region="Punjab",
        postal_code="54000",
        phone="+920000000",
        website_url="https://acme.example",
    )


def test_stealth_fingerprint_and_human_typing(fake_pw: tuple[_Chromium, _Context, _Page]) -> None:
    chromium, ctx, page = fake_pw
    bot = PlaywrightCitationSubmitter(specs=_spec_single(), rng_seed=7)
    result = bot.submit(_job())

    assert result.status == "submitted"
    # 1) stealth launch args present
    assert "--disable-blink-features=AutomationControlled" in chromium.launch_kwargs["args"]
    # 2) randomized fingerprint applied on the context
    for k in ("user_agent", "viewport", "locale", "timezone_id"):
        assert k in ctx.kwargs
    assert ctx.kwargs["user_agent"] in cs_user_agents()
    # 3) webdriver mask injected before page scripts
    assert any("navigator" in js and "webdriver" in js for js in ctx.init_scripts)
    # 4) human typing used (page.type), NOT the instant fill()
    assert page.typed == [("#name", "Acme Co")]
    assert page.filled == []
    # 5) submit clicked + a post-submit settle wait happened
    assert "#go" in page.clicked
    assert page.waits  # randomized pauses/settle recorded


def cs_user_agents() -> tuple[str, ...]:
    from integrations.citation_bot import _USER_AGENTS

    return _USER_AGENTS
