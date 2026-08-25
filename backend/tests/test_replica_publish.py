"""Stage 6: the pipeline as one callable - URL in, editable Elementor page out."""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from app.services.replica_publish import ReplicaResult, replicate
from integrations.replica_capture import ReplicaCapture, ReplicaViewport

pytestmark = pytest.mark.unit

_FIX = pathlib.Path(__file__).parent / "fixtures" / "replica"


def _capture() -> ReplicaCapture:
    """A real capture rebuilt from the frozen fixtures - no browser."""
    cap = ReplicaCapture(url="https://spotino.org/hy/", title="hy - SPOTiNO")
    cap.css_vars = json.loads((_FIX / "spotino_cssvars.json").read_text())
    for dev, w, h in (("desktop", 1440, 900), ("tablet", 834, 1194), ("mobile", 390, 844)):
        f = _FIX / f"spotino_{dev}.json"
        if not f.exists():
            continue
        raw = json.loads(f.read_text())
        from integrations.replica_capture import ReplicaNode

        def build(n: dict[str, Any]) -> ReplicaNode:
            b = n.get("box") or [0, 0, 0, 0]
            return ReplicaNode(
                tag=n.get("t", ""), box=(b[0], b[1], b[2], b[3]), style=n.get("s") or {},
                classes=tuple(n.get("cls") or ()), text=n.get("txt") or "",
                element_id=n.get("eid") or "", href=n.get("href") or "",
                src=n.get("src") or "", alt=n.get("alt") or "",
                scrim=n.get("scrim") or "",
                children=[build(k) for k in (n.get("kids") or [])],
            )

        cap.viewports.append(ReplicaViewport(
            viewport=dev, width=w, height=h, root=build(raw)))
    return cap


class _Publisher:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.payloads: list[dict[str, Any]] = []

    def publish(self, payload: dict[str, Any]) -> Any:
        if self.fail:
            raise RuntimeError("site unreachable")
        self.payloads.append(payload)

        class R:
            post_id = 77
            preview_url = "https://site.test/?page_id=77&preview=true"
        return R()


class TestTheGate:
    def test_without_owner_confirmation_nothing_is_even_captured(self) -> None:
        """A rebuild carries the source's own words and imagery. The caller asserts
        ownership, or the pipeline refuses before touching the network."""
        pub = _Publisher()
        result = replicate("https://someone-elses-site.test/", publisher=pub)
        assert result.ok is False
        assert pub.payloads == []
        assert any("owner_confirmed_source" in n for n in result.notes)


class TestTheHappyPath:
    def test_the_fixture_page_replicates_end_to_end(self) -> None:
        pub = _Publisher()
        result = replicate(
            "https://spotino.org/hy/", publisher=pub,
            owner_confirmed_source=True, capture=_capture(),
        )
        assert result.ok is True, result.notes
        assert result.post_id == 77
        assert result.sections >= 10
        assert result.widgets >= 100

    def test_the_payload_is_a_full_width_editable_page(self) -> None:
        pub = _Publisher()
        replicate("https://spotino.org/hy/", publisher=pub,
                  owner_confirmed_source=True, capture=_capture())
        p = pub.payloads[0]
        assert p["post_type"] == "page", "a POST renders in the theme's narrow blog column"
        assert p["elementor_edit_mode"] == "builder"
        assert "stretch_section" in p["elementor_data"]
        assert p["design_css"], "the component stylesheet rides along"

    def test_responsive_facts_reach_the_tree(self) -> None:
        pub = _Publisher()
        replicate("https://spotino.org/hy/", publisher=pub,
                  owner_confirmed_source=True, capture=_capture())
        data = pub.payloads[0]["elementor_data"]
        assert "_inline_size_mobile" in data, "the stats trio stays inline at 390px"


class TestDegradesNamedNotRaised:
    def test_an_empty_capture_reports_itself(self) -> None:
        cap = ReplicaCapture(url="https://x.test/", notes=("browser died",))
        result = replicate("https://x.test/", publisher=_Publisher(),
                           owner_confirmed_source=True, capture=cap)
        assert result.ok is False
        assert any("no desktop viewport" in n for n in result.notes)

    def test_a_publish_failure_is_a_note_not_a_stack_trace(self) -> None:
        result = replicate("https://spotino.org/hy/", publisher=_Publisher(fail=True),
                           owner_confirmed_source=True, capture=_capture())
        assert result.ok is False
        assert any("publish failed" in n for n in result.notes)

    def test_the_result_shape_is_stable(self) -> None:
        r = ReplicaResult()
        assert r.ok is False and r.notes == []
