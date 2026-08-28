"""The credential worksheet: it must be shareable, and it must not flatter the state.

Two properties carry this file.

NO SECRET REACHES THE SHEET. Its whole purpose is to be sent to teammates, so a column
that leaked a token would make it undistributable - and the leak would be invisible,
because a CSV full of credentials looks exactly like a CSV of field NAMES.

A GAP IS NEVER SHOWN AS DONE. "We hold a token" and "this can publish" are different
facts: a credential missing one field builds no publisher. Reporting the first as the
second is how a platform gets marked ready and then quietly fails at publish time.
"""

from __future__ import annotations

import io

import pytest

from app.cli import web2_credentials_sheet as sheet

pytestmark = pytest.mark.unit


def _row(**over: object) -> sheet.Row:
    kw: dict[str, object] = {
        "platform": "WordPress.com", "status": sheet.STATUS_MISSING,
        "ownership_tier": "per_client", "scope": "agnostic", "authority": "high",
        "required": "oauth_token, site", "missing": "oauth_token, site",
        "cost": "Free", "account_needed": "One account per CLIENT",
        "where": "https://developer.wordpress.com/apps/", "steps": "…", "blocker": "",
    }
    kw.update(over)
    return sheet.Row(**kw)  # type: ignore[arg-type]


def test_the_sheet_carries_field_names_never_values() -> None:
    """`Credentials required` names the SHAPE. If a real token ever reached this column
    the sheet could not be shared, and nothing about the file would look wrong."""
    buf = io.StringIO()
    sheet.to_csv([_row()], buf)
    text = buf.getvalue()
    assert "oauth_token" in text          # the field name is expected
    assert "site" in text
    # a value-shaped string must never appear
    for shape in ("ghp_", "glpat-", "sk9", "pat-na2", "Bearer ", "AASS"):
        assert shape not in text


def test_the_three_platforms_that_unlock_a_normal_client_sort_first() -> None:
    """Priority is not decoration. A team picking the top of the sheet must be picking
    the work that unlocks an ordinary local-business client, not a research repository
    that only suits one client in fifty."""
    rows = sheet._prioritise([
        _row(platform="Zenodo", scope="research", authority="high"),
        _row(platform="WordPress.com", scope="agnostic"),
        _row(platform="HackMD", scope="developer", authority="medium"),
        _row(platform="Blogger", scope="agnostic"),
    ])
    assert [r.platform for r in rows][:2] == ["Blogger", "WordPress.com"]
    assert all(r.priority.startswith("P1") for r in rows[:2])


def test_an_incomplete_credential_outranks_an_absent_one() -> None:
    """One missing field is minutes of work; a fresh OAuth run is not. The sheet should
    send someone to the nearly-finished one first."""
    rows = sheet._prioritise([
        _row(platform="Netlify", scope="developer", authority="medium"),
        _row(platform="GitHub Pages", scope="developer", status=sheet.STATUS_INCOMPLETE),
    ])
    assert rows[0].platform == "GitHub Pages"


def test_a_platform_needing_no_human_credential_is_not_an_errand() -> None:
    """Telegra.ph is minted anonymously by a command. Listing it as NOT CONNECTED would
    put a task on a person that has nothing for them to fetch."""
    rows = sheet._prioritise([_row(platform="Telegra.ph", status=sheet.STATUS_AUTO)])
    assert rows[0].priority == "ours - no credential"


def test_every_guide_names_where_to_go_and_what_to_bring_back() -> None:
    """A guide without a URL or without a 'give us X' line is not actionable, and an
    unactionable row is why credential chases stall."""
    for platform, guide in sheet.GUIDES.items():
        assert guide.where, f"{platform}: no location"
        assert guide.steps, f"{platform}: no steps"
        if platform != "Telegra.ph":  # nothing to hand back
            assert "Give us" in guide.steps or "give us" in guide.steps, platform


def test_a_paid_platform_says_so_in_its_cost_column() -> None:
    """Hashnode's API went behind a $5/seat subscription in May 2026. A teammate sent to
    fetch that token on a free account comes back with one the API rejects."""
    assert "PAID" in sheet.GUIDES["Hashnode"].cost
    assert "Pro" in sheet.GUIDES["Hashnode"].blocker


def test_the_blogger_row_warns_about_the_seven_day_token() -> None:
    """Google expires a refresh token after 7 days while the consent screen is in
    Testing. Without that warning the integration looks fine, then dies every week."""
    assert "7 DAYS" in sheet.GUIDES["Blogger"].blocker


def test_the_header_and_the_row_writer_stay_in_step() -> None:
    buf = io.StringIO()
    sheet.to_csv([_row()], buf)
    lines = buf.getvalue().splitlines()
    assert len(lines[0].split(",")) == len(sheet.HEADERS)
