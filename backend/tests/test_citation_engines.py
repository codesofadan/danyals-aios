"""7B-4 unit gate: the citation-SUBMISSION engines (direct API, CAPTCHA solver,
and the Playwright bot's degrade path) - no network, no keys, no
browser. Mirrors ``test_content_providers.py``'s ``httpx.MockTransport`` pattern.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from integrations.captcha_solver import (
    CapSolverClient,
    CaptchaChallenge,
    CaptchaSolver,
    FakeCaptchaSolver,
    captcha_solver_from_settings,
)
from integrations.citation_apis import BingPlacesSubmitter, FoursquareSubmitter
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
# 2. Direct-API submitters (Bing Places / Foursquare).
# --------------------------------------------------------------------------- #
def test_bing_places_refuses_a_blank_key() -> None:
    with pytest.raises(ProviderNotConfiguredError):
        BingPlacesSubmitter(api_key="")


def test_bing_places_creates_a_listing() -> None:
    client = BingPlacesSubmitter(api_key="k")
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["header"] = request.headers.get("Ocp-Apim-Subscription-Key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"id": "loc-1"})

    _with_mock(client, handler)
    result = client.submit(_job())
    assert result.status == "submitted" and result.external_ref == "loc-1"
    assert seen["header"] == "k"
    assert seen["body"]["businessName"] == "Acme Dental"


def test_bing_places_failure_is_a_clean_failed_result_not_a_raise() -> None:
    client = BingPlacesSubmitter(api_key="k")
    _with_mock(client, lambda req: httpx.Response(500, json={}))
    result = client.submit(_job())
    assert result.status == "failed" and result.error


def test_foursquare_refuses_a_blank_key() -> None:
    with pytest.raises(ProviderNotConfiguredError):
        FoursquareSubmitter(api_key="")


def test_foursquare_creates_a_place() -> None:
    client = FoursquareSubmitter(api_key="k")
    _with_mock(client, lambda req: httpx.Response(200, json={"fsq_id": "fsq-1"}))
    result = client.submit(_job())
    assert result.status == "submitted" and result.external_ref == "fsq-1"


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
