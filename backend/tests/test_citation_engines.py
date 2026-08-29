"""7B-4 unit gate: the citation-SUBMISSION engines (direct API, CAPTCHA solver,
and the Playwright bot's degrade path) - no network, no keys, no
browser. Mirrors ``test_content_providers.py``'s ``httpx.MockTransport`` pattern.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.config import get_settings
from app.modules.citations.service import submitter_for
from app.modules.citations.tasks import _api_submitters
from integrations.captcha_solver import (
    CapSolverClient,
    CaptchaChallenge,
    CaptchaSolver,
    FakeCaptchaSolver,
    captcha_solver_from_settings,
)
from integrations.citation_bot import (
    FORM_SPECS,
    CaptchaWidget,
    FormField,
    FormSpec,
    PlaywrightCitationSubmitter,
    _job_value,
    citation_bot_from_settings,
)
from integrations.citation_submitters import (
    CitationJob,
    CitationSubmitter,
    FakeCitationSubmitter,
)
from integrations.errors import ProviderCallError, ProviderNotConfiguredError

pytestmark = pytest.mark.unit

Handler = Callable[[httpx.Request], httpx.Response]


def _with_mock(client: Any, handler: Handler) -> None:
    old = client._client
    client._client = httpx.Client(
        base_url=old.base_url, headers=old.headers, transport=httpx.MockTransport(handler)
    )


def _job(**over: Any) -> CitationJob:
    body: dict[str, Any] = {
        "directory_name": "Brownbook", "directory_url": "brownbook.net", "market": "US",
        "submit_method": "bot:playwright", "business_name": "Acme Dental",
        "address_line1": "123 Main St", "address_line2": "", "city": "Bellevue",
        "region": "WA", "postal_code": "98004", "phone": "555-0100",
        "website_url": "https://acme.example", "categories": ("dentist",),
        "external_ref": None,
    }
    body.update(over)
    return CitationJob(**body)


# --------------------------------------------------------------------------- #
# 1. The shared Protocol + the deterministic fake.
# --------------------------------------------------------------------------- #
def test_fake_citation_submitter_satisfies_the_protocol() -> None:
    assert isinstance(FakeCitationSubmitter(), CitationSubmitter)


def test_fake_citation_submitter_is_deterministic_and_varies() -> None:
    fake = FakeCitationSubmitter()
    a, b = fake.submit(_job()), fake.submit(_job())
    assert a == b
    other = fake.submit(_job(directory_name="Hotfrog"))
    assert other.proof_url != a.proof_url


def test_fake_citation_submitter_echoes_external_ref_on_update() -> None:
    result = FakeCitationSubmitter().submit(_job(external_ref="existing-123"))
    assert result.external_ref == "existing-123"


# --------------------------------------------------------------------------- #
# 2. The direct-API submitters that were DELETED, and the guard that keeps them gone.
# --------------------------------------------------------------------------- #
# `integrations/citation_apis.py` held BingPlacesSubmitter + FoursquareSubmitter and was
# deleted in the 0106 pass. Both wrote to endpoints that do not exist - probed
# unauthenticated 2026-08-23:
#
#     POST https://api.foursquare.com/v3/places                     -> 404
#     POST https://places-api.foursquare.com/places                 -> 404
#     POST https://ssl.bing.com/webmaster/places/api/v1/locations   -> 301 -> 404
#
# with a Foursquare READ endpoint returning 401 as the control, so these were missing
# routes and not auth failures. Foursquare routes place additions to a community-
# moderated Placemaker queue; Bing Places API access is a partner programme. There was
# no endpoint to repair, so the code went rather than being "fixed".
def test_the_dead_direct_api_submitters_stay_deleted() -> None:
    """A guard, not a formality. Both submitters looked entirely plausible - typed,
    key-gated, unit-tested against a mock transport that happily returned 200 for a
    route the vendor does not serve. That is exactly how they survived so long. If
    someone re-adds the module from git history, this fails and points at the probes."""
    with pytest.raises(ModuleNotFoundError):
        import integrations.citation_apis  # noqa: F401


def test_no_api_submitter_is_configured_so_an_api_row_blocks_cleanly() -> None:
    """With the engines gone, an `api:` directory must BLOCK with an honest reason -
    never fall through to the Playwright bot, and never look like a success."""
    submitter, reason = submitter_for(
        "api:bing_places", api_submitters=_api_submitters(get_settings()), bot=object()
    )
    assert submitter is None
    assert "no API submitter configured" in reason


# --------------------------------------------------------------------------- #
# 3. The CAPTCHA solver.
# --------------------------------------------------------------------------- #
def test_fake_captcha_solver_satisfies_the_protocol() -> None:
    assert isinstance(FakeCaptchaSolver(), CaptchaSolver)


def test_capsolver_refuses_a_blank_key() -> None:
    with pytest.raises(ProviderNotConfiguredError):
        CapSolverClient(api_key="")


def test_capsolver_creates_and_polls_until_ready() -> None:
    client = CapSolverClient(api_key="k")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/createTask":
            return httpx.Response(200, json={"taskId": "t1"})
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(200, json={"status": "processing"})
        return httpx.Response(200, json={"status": "ready", "solution": {"gRecaptchaResponse": "tok-123"}})

    _with_mock(client, handler)
    client._poll_interval_patch = None  # documents intent; the sleep below is real but tiny
    CapSolverClient._POLL_INTERVAL_SECONDS = 0.01  # keep the test fast
    solution = client.solve(CaptchaChallenge(kind="recaptcha_v2", site_key="sk", page_url="https://x.example"))
    assert solution.token == "tok-123"


def test_capsolver_surfaces_a_create_task_error() -> None:
    client = CapSolverClient(api_key="k")
    _with_mock(client, lambda req: httpx.Response(200, json={"errorId": 1, "errorDescription": "bad key"}))
    with pytest.raises(ProviderCallError):
        client.solve(CaptchaChallenge(kind="recaptcha_v2", site_key="sk", page_url="https://x.example"))


def test_captcha_solver_from_settings_degrades_without_a_key() -> None:
    from app.config import Settings

    settings = Settings(_env_file=None, app_env="dev")
    assert captcha_solver_from_settings(settings) is None


# --------------------------------------------------------------------------- #
# 4. The Playwright bot: FormSpec plumbing + the degrade path (Playwright is not
# installed in this test environment - exactly the production-without-the-optional-
# extra case).
# --------------------------------------------------------------------------- #
def test_job_value_reads_nap_fields_and_literals() -> None:
    job = _job()
    assert _job_value(job, "business_name") == "Acme Dental"
    assert _job_value(job, "literal:fixed") == "fixed"
    assert _job_value(job, "unknown_key") == ""


def test_form_specs_catalog_is_non_empty_and_every_directory_name_is_unique() -> None:
    assert len(FORM_SPECS) >= 10
    assert len(FORM_SPECS) == len({spec.directory_name for spec in FORM_SPECS.values()})
    for name, spec in FORM_SPECS.items():
        assert spec.directory_name == name
        assert spec.url.startswith("https://")
        assert spec.fields  # every spec fills at least one field


def test_form_specs_catalog_has_at_least_fifty_automation_ready_directories() -> None:
    # The catalog was expanded 36 -> 50 bot_fillable directories (all real rows from
    # db/migrations/0046_directories_seed.sql). This is the structural sanity sweep:
    # every spec must be fully formed (a real https URL + >=1 field + a submit button
    # + a success indicator) so a queued row can actually be driven, never a half-spec.
    assert len(FORM_SPECS) >= 50
    for name, spec in FORM_SPECS.items():
        assert spec.url.startswith("https://"), name  # non-empty, real add-business URL
        assert len(spec.fields) >= 1, name  # fills at least one NAP field
        assert all(f.selector and f.value_key for f in spec.fields), name
        assert spec.submit_selector, name  # a button to submit
        assert spec.success_indicator, name  # a way to know it worked


def test_playwright_bot_degrades_cleanly_without_the_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Playwright's ABSENCE is now simulated rather than assumed of the env: the
    design-capture work installs the automation extra into the backend venv (that is
    the intended deploy state since install.sh gained `.[automation]`), so a test
    that relies on the import genuinely failing broke the day capture started
    working. The production-without-the-extra case is still the case under test."""
    import builtins

    real = builtins.__import__

    def no_playwright(name: str, *a: object, **k: object) -> object:
        if name.startswith("playwright"):
            raise ImportError("no playwright")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_playwright)
    with pytest.raises(ProviderNotConfiguredError):
        PlaywrightCitationSubmitter()


def test_citation_bot_from_settings_degrades_to_none_without_playwright(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    from app.config import Settings

    real = builtins.__import__

    def no_playwright(name: str, *a: object, **k: object) -> object:
        if name.startswith("playwright"):
            raise ImportError("no playwright")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_playwright)
    settings = Settings(_env_file=None, app_env="dev")
    assert citation_bot_from_settings(settings, captcha_solver=None) is None


def test_form_spec_success_indicator_shapes_are_supported() -> None:
    # A `text=` indicator and a bare CSS selector are both valid FormSpec shapes;
    # this just pins the constant so a future refactor can't silently change it.
    spec = FormSpec(
        directory_name="X", url="https://x.example",
        fields=(FormField("input[name='a']", "business_name"),),
        submit_selector="button", success_indicator="text=thanks",
    )
    assert spec.success_indicator.startswith("text=")


def test_captcha_widget_defaults() -> None:
    widget = CaptchaWidget(kind="recaptcha_v2", site_key_selector=".g-recaptcha")
    assert widget.site_key_attr == "data-sitekey"
    assert widget.response_field_name == "g-recaptcha-response"
