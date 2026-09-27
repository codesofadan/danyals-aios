"""The readiness board: what this deploy will really deliver, before money is spent.

The guarantees under test are the ones an operator acts on, so each is asserted as a
behaviour rather than a shape:

  * A KEY IN THE PLATFORM'S SETTINGS DOES NOT MAKE THE AUDIT ENGINE ABLE TO USE IT. The
    engine reads its own ``.env`` + the inherited process env, so the board must judge
    engine-side providers from THOSE names only. This is the whole reason the module
    exists and it is the first test.
  * ``off`` on a dial BLOCKS; ``byhand`` does not. A chosen setting reported as a defect
    trains people to ignore the board.
  * The spend halt blocks even the FREE audit - it is the cost gate's first check for
    every metered feature, and it surprises people.
  * A missing writer/SERP key is a BLOCK on content (nothing drafts), while a missing
    image or keyword-metrics key only DEGRADES. Collapsing those two into one severity
    is the failure mode this board was built to prevent.
  * Blank assignments in a .env (``SERPER_API_KEY=``) read as ABSENT, and no secret
    value is ever carried into the payload.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.core.auth import CurrentUser, get_current_user
from app.db.cost_repo import get_cost_repo
from app.routers import integrations
from app.services.preflight import engine_env_keys, preflight

pytestmark = pytest.mark.unit

# Every engine-side provider present, so a test can subtract exactly one.
_FULL_ENGINE = (
    "SERPER_API_KEY",
    "GOOGLE_PAGESPEED_API_KEY",
    "GOOGLE_PLACES_API_KEY",
    "ANTHROPIC_API_KEY",
)


def _settings(**over: Any) -> Settings:
    # Keyless means KEYLESS: app.main's import-time apply_provider_env exports the real
    # ANTHROPIC_API_KEY into os.environ on a keyed dev box, and pydantic-settings reads
    # os.environ even with _env_file=None.
    for key in ("anthropic_api_key", "serper_api_key", "image_gen_api_key"):
        over.setdefault(key, None)
    over.setdefault("audit_engine_dir", "/engine")
    over.setdefault("audit_engine_python", "/engine/.venv/bin/python")
    return Settings(_env_file=None, app_env="dev", **over)


def _board(**kw: Any) -> dict[str, Any]:
    settings = kw.pop("settings", None) or _settings()
    kw.setdefault("engine_keys", _FULL_ENGINE)
    out = preflight(settings, **kw)
    return {c.id: c for c in out.capabilities}


# --- the engine reads its own environment, not ours ----------------------------
def test_a_platform_serper_key_does_not_make_the_audit_engine_able_to_use_it() -> None:
    """The defect this board exists to surface: green on the key screen, absent in audits."""
    caps = _board(settings=_settings(serper_api_key="platform-only"), engine_keys=())
    standard = caps["audit_standard"]
    assert standard.verdict == "partial"
    assert any("SERPER_API_KEY" in g.fix for g in standard.gaps)
    assert any("not measured" in g.what for g in standard.gaps)
    # ... and the fix names the ENGINE's env, not the platform's.
    serper_gap = next(g for g in standard.gaps if "SERPER_API_KEY" in g.fix)
    assert "audit engine" in serper_gap.fix


def test_engine_keys_make_the_paid_depths_ready() -> None:
    caps = _board()
    assert caps["audit_standard"].verdict == "ready"
    assert caps["audit_deep"].verdict == "ready"
    assert "SERP" in " ".join(caps["audit_standard"].measures)


def test_one_unrestricted_google_key_satisfies_psi_and_places() -> None:
    """The engine's own fallback chain, honoured - or the fix we print is wrong."""
    caps = _board(engine_keys=("SERPER_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"))
    assert caps["audit_deep"].verdict == "ready"
    assert caps["audit_free"].verdict == "ready"


def test_missing_places_degrades_only_the_deep_depth() -> None:
    keys = tuple(k for k in _FULL_ENGINE if k != "GOOGLE_PLACES_API_KEY")
    caps = _board(engine_keys=keys)
    assert caps["audit_standard"].verdict == "ready"  # standard never runs local checks
    deep = caps["audit_deep"]
    assert deep.verdict == "partial"
    assert all(g.severity == "degrades" for g in deep.gaps)
    assert any("local checks" in g.what for g in deep.gaps)


def test_no_engine_configured_blocks_every_audit_but_not_the_comparison() -> None:
    caps = _board(settings=_settings(audit_engine_dir=None, audit_engine_python=None))
    assert caps["audit_free"].verdict == "blocked"
    assert caps["audit_deep"].verdict == "blocked"
    # The comparison reads stored audits; it needs no engine and must not be tarred.
    assert caps["audit_compare"].verdict == "ready"


# --- dials + the halt ----------------------------------------------------------
def test_a_dial_at_off_blocks_and_names_the_dial() -> None:
    caps = _board(dial_modes={"tech_audit": "off"})
    blocked = caps["audit_standard"]
    assert blocked.verdict == "blocked"
    gap = next(g for g in blocked.gaps if g.severity == "blocks")
    assert "tech_audit" in gap.why and "Cost screen" in gap.fix


def test_byhand_is_a_choice_not_a_gap() -> None:
    assert _board(dial_modes={"tech_audit": "byhand", "content": "byhand"})[
        "audit_standard"
    ].verdict == "ready"


def test_the_spend_halt_stops_even_the_free_audit() -> None:
    caps = _board(spend_halted=True)
    free = caps["audit_free"]
    assert free.verdict == "blocked"
    assert any("spend halt" in g.why for g in free.gaps)
    # and it is reported at the top level, so a header can say so once
    out = preflight(_settings(), spend_halted=True, engine_keys=_FULL_ENGINE)
    assert out.spend_halted is True
    assert out.blocked >= 4


# --- content: a block and a degrade are different sentences --------------------
def test_no_writer_or_serp_key_blocks_drafting_with_the_honest_reason() -> None:
    caps = _board()  # keyless platform settings
    draft = caps["content_draft"]
    assert draft.verdict == "blocked"
    reasons = [g.why for g in draft.gaps if g.severity == "blocks"]
    assert any("no Anthropic key" in r for r in reasons)
    assert any("synthetic research" in r for r in reasons)
    assert all("hold" in g.what or "$0" in g.what for g in draft.gaps if g.severity == "blocks")


def test_keyed_content_is_ready_and_missing_extras_only_degrade() -> None:
    settings = _settings(
        anthropic_api_key="a",
        serper_api_key="s",
        dataforseo_login="u",
        dataforseo_password="p",
    )
    caps = _board(settings=settings)
    assert caps["content_draft"].verdict == "ready"
    images = caps["content_images"]
    assert images.verdict == "partial"
    assert [g.severity for g in images.gaps] == ["degrades"]
    assert "no images" in images.gaps[0].what


def test_estimated_keyword_metrics_degrade_but_never_block() -> None:
    settings = _settings(anthropic_api_key="a", serper_api_key="s")
    draft = _board(settings=settings)["content_draft"]
    assert draft.verdict == "partial"
    assert [g.severity for g in draft.gaps] == ["degrades"]
    assert "estimated" in draft.gaps[0].what


def test_an_image_key_with_nowhere_to_host_is_reported_separately() -> None:
    settings = _settings(
        anthropic_api_key="a",
        serper_api_key="s",
        image_gen_api_key="i",
        content_image_dir=None,
        content_artifact_dir=None,
        audit_artifact_dir=None,
    )
    images = _board(settings=settings)["content_images"]
    assert images.verdict == "partial"
    assert "discarded" in images.gaps[0].what


def test_publishing_blocks_until_a_wordpress_credential_is_sealed() -> None:
    assert _board()["content_publish"].verdict == "blocked"
    assert _board(vault_providers=["wordpress"])["content_publish"].verdict == "ready"


# --- counts + copy discipline --------------------------------------------------
def test_counts_add_up_and_every_gap_carries_a_fix() -> None:
    out = preflight(_settings(), engine_keys=())
    assert out.ready + out.partial + out.blocked == len(out.capabilities)
    for cap in out.capabilities:
        assert cap.summary and cap.measures
        for gap in cap.gaps:
            assert gap.what and gap.why and gap.fix
            assert gap.severity in {"blocks", "degrades"}


def test_no_copy_here_uses_an_em_or_en_dash() -> None:
    """House style, and this copy renders ON the audit screen.

    The dashboard holds the audit surface to the same no-dash rule the rendered report is
    held to (`audit_report.no_dashes`, `components/audit/NoDashes.test.ts`), and this
    board's every sentence is written here rather than in the frontend - so the rule has
    to be enforced here or it is not enforced at all.
    """
    dashes = (chr(0x2014), chr(0x2013))
    out = preflight(_settings(), engine_keys=())
    text = " ".join(
        [c.name + c.summary + " ".join(c.measures) for c in out.capabilities]
        + [g.what + g.why + g.fix for c in out.capabilities for g in c.gaps]
    )
    assert not any(d in text for d in dashes)


# --- reading the engine's env -------------------------------------------------
def test_engine_env_reads_the_file_and_the_process_env_and_skips_blanks(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "# a comment\n"
        'GOOGLE_PLACES_API_KEY="pk"\n'
        "SERPER_API_KEY=\n"  # blank: looks configured, is not
        'MOZ_SECRET_KEY=""\n'
        "export ANTHROPIC_API_KEY = sk-x\n"
        "NOT_AN_ASSIGNMENT\n",
        encoding="utf-8",
    )
    keys = engine_env_keys(str(tmp_path), {"GOOGLE_PAGESPEED_API_KEY": "pp", "EMPTY": ""})
    assert "GOOGLE_PLACES_API_KEY" in keys
    assert "GOOGLE_PAGESPEED_API_KEY" in keys  # inherited, the engine sees it too
    assert "SERPER_API_KEY" not in keys
    assert "MOZ_SECRET_KEY" not in keys
    assert "EMPTY" not in keys
    assert "NOT_AN_ASSIGNMENT" not in keys
    # No VALUE is carried out of this function - only names.
    assert not any("pk" in k or "sk-x" in k for k in keys)


def test_a_missing_engine_dir_still_reports_the_process_env() -> None:
    assert engine_env_keys(None, {"SERPER_API_KEY": "x"}) == {"SERPER_API_KEY"}
    assert engine_env_keys("/nope/does/not/exist", {"SERPER_API_KEY": "x"}) == {"SERPER_API_KEY"}


# --- the endpoint -------------------------------------------------------------
def _user(role: str) -> CurrentUser:
    return CurrentUser(
        id="u-1", email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


class _FakeCostRepo:
    def dial_modes(self) -> dict[str, str]:
        return {"content": "off"}

    def get_settings(self) -> dict[str, Any]:
        return {"halted": False}


@pytest.fixture(autouse=True)
def _mount(app: FastAPI) -> None:
    app.include_router(integrations.router, prefix="/api/v1")
    app.dependency_overrides[get_cost_repo] = lambda: _FakeCostRepo()


async def test_endpoint_is_open_to_any_staff_and_reports_the_dial(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    # A specialist is 403'd from the KEY list and must still be able to ask whether the
    # work they are about to run will produce anything.
    app.dependency_overrides[get_current_user] = lambda: _user("specialist")
    resp = await client.get("/api/v1/integrations/readiness")
    assert resp.status_code == 200
    body = resp.json()
    assert "spendHalted" in body
    draft = next(c for c in body["capabilities"] if c["id"] == "content_draft")
    assert draft["verdict"] == "blocked"
    assert any("content" in g["why"] for g in draft["gaps"])


async def test_endpoint_requires_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/integrations/readiness")).status_code == 401
