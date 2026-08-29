"""The import CLI: turning 50 guesses into a verification work queue.

It writes every in-code spec in as INACTIVE, so it changes nothing about what the bot
will submit to and everything about what an operator can see.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.cli.citation_specs_import import ImportPlan, _report, _spec_payload, build_plan
from integrations.citation_bot import FORM_SPECS

pytestmark = pytest.mark.unit


class _Cur:
    def __init__(self, catalogue: list[dict[str, Any]], have: list[dict[str, Any]]) -> None:
        self._catalogue, self._have, self._rows = catalogue, have, []
        self._one: dict[str, Any] | None = None

    def execute(self, sql: str, params: Any = None) -> None:
        low = sql.lower()
        if "from public.directories" in low and "directory_specs" not in low:
            self._rows = self._catalogue
        elif "directory_specs" in low and "join" in low:
            self._rows = self._have
        elif "_spec_host_of" in low:
            url, dir_url = params
            host = lambda u: (u or "").replace("https://", "").replace("http://", "").split("/")[0].removeprefix("www.")  # noqa: E731
            self._one = {"spec_host": host(url), "dir_host": host(dir_url)}

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows

    def fetchone(self) -> dict[str, Any] | None:
        return self._one


class _Conn:
    def __init__(self, cur: _Cur) -> None:
        self._cur = cur

    def __enter__(self) -> _Cur:
        return self._cur

    def __exit__(self, *a: Any) -> None:
        return None


def test_every_in_code_spec_serialises_to_the_stored_shape() -> None:
    """The stored jsonb must satisfy 0111's shape CHECK for every one of the 50, or the
    import fails halfway and leaves a partial queue."""
    for name in FORM_SPECS:
        payload = _spec_payload(name)
        assert payload["url"] and payload["submit_selector"]
        assert isinstance(payload["fields"], list)
        for f in payload["fields"]:
            assert set(f) == {"selector", "value_key"}


def test_a_spec_pointing_off_its_directorys_host_is_reported_not_imported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """0111 binds a spec's URL to its own directory's host, because that URL is a browser
    navigation target. A mismatch is not a schema problem - it means the spec points
    somewhere the directory does not live, which is exactly the rot the 2026-08-23 probe
    found (three of the fifty had been acquired, renamed or absorbed)."""
    import app.cli.citation_specs_import as mod

    name = next(iter(FORM_SPECS))
    cur = _Cur(
        catalogue=[{"id": "d1", "name": name, "url": "https://somewhere-else.example/"}],
        have=[],
    )
    monkeypatch.setattr(mod, "privileged_connection", lambda: _Conn(cur))
    monkeypatch.setattr(mod, "FORM_SPECS", {name: FORM_SPECS[name]})

    plan = build_plan()
    assert plan.insertable == []
    assert plan.host_mismatch and plan.host_mismatch[0][0] == name


def test_a_spec_whose_directory_is_not_in_the_catalogue_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reported, never created. A spec naming a directory we do not track is the useful
    output - inventing the directory to make the import succeed would be fabrication."""
    import app.cli.citation_specs_import as mod

    name = next(iter(FORM_SPECS))
    monkeypatch.setattr(mod, "privileged_connection", lambda: _Conn(_Cur([], [])))
    monkeypatch.setattr(mod, "FORM_SPECS", {name: FORM_SPECS[name]})
    plan = build_plan()
    assert plan.no_such_directory == [name]
    assert plan.insertable == []


def test_an_already_present_spec_is_not_duplicated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Specs are immutable - a revision is a NEW row - so re-running the import must not
    silently pile up duplicates of the same guess."""
    import app.cli.citation_specs_import as mod

    name = next(iter(FORM_SPECS))
    cur = _Cur(
        catalogue=[{"id": "d1", "name": name, "url": FORM_SPECS[name].url}],
        have=[{"name": name}],
    )
    monkeypatch.setattr(mod, "privileged_connection", lambda: _Conn(cur))
    monkeypatch.setattr(mod, "FORM_SPECS", {name: FORM_SPECS[name]})
    plan = build_plan()
    assert plan.already_present == [name]
    assert plan.insertable == []


def test_the_dry_run_report_states_that_nothing_becomes_submittable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The single most important sentence in the CLI's output. An operator reading
    "imported 50 specs" could reasonably conclude coverage just went from 0 to 50."""
    _report(ImportPlan(insertable=[("X", "https://x.example/add")]), applied=None)
    out = capsys.readouterr().out
    assert "DRY RUN - nothing was written" in out
    assert "Nothing becomes submittable" in out
    assert "dated human DOM check" in out


def test_the_applied_report_says_none_is_active(capsys: pytest.CaptureFixture[str]) -> None:
    _report(ImportPlan(), applied=50)
    assert "None is active; none can submit yet" in capsys.readouterr().out
