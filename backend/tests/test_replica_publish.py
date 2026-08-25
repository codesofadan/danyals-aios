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


class TestThePageGround:
    def test_the_measured_body_tint_reaches_the_design_css(self) -> None:
        from app.services.design_system import DesignSystem
        from app.services.layout_infer import InferredPage
        from app.services.replica_css import generate
        css = generate(InferredPage(sections=(), container_px=1200), DesignSystem(),
                       body_bg="rgb(243, 245, 248)")
        assert "body{background-color:rgb(243, 245, 248) !important}" in css

    def test_no_tint_no_rule(self) -> None:
        from app.services.design_system import DesignSystem
        from app.services.layout_infer import InferredPage
        from app.services.replica_css import generate
        css = generate(InferredPage(sections=(), container_px=1200), DesignSystem())
        assert "body{background-color" not in css


def _n(t: str, box: list[int], s: dict[str, Any] | None = None,
       kids: list[dict[str, Any]] | None = None, txt: str = "",
       **extra: Any) -> dict[str, Any]:
    return {"t": t, "box": box, "s": s or {}, "cls": [], "txt": txt,
            "kids": kids or [], **extra}


def _node(d: dict[str, Any]) -> Any:
    from integrations.replica_capture import ReplicaNode
    b = d.get("box") or [0, 0, 0, 0]
    return ReplicaNode(
        tag=d.get("t", ""), box=(b[0], b[1], b[2], b[3]), style=d.get("s") or {},
        classes=tuple(d.get("cls") or ()), text=d.get("txt") or "",
        href=d.get("href") or "", src=d.get("src") or "", alt=d.get("alt") or "",
        children=[_node(k) for k in (d.get("kids") or [])],
    )


def _chrome_capture() -> Any:
    """A tiny synthetic capture WITH a header, a footer and head metadata."""
    from integrations.replica_capture import ReplicaCapture, ReplicaViewport
    content = _n("div", [0, 0, 1440, 900], kids=[
        _n("section", [0, 0, 1440, 500], kids=[
            _n("h1", [200, 100, 500, 60], txt="Welcome"),
            _n("p", [200, 200, 500, 60], txt="Some copy that renders."),
        ]),
        _n("section", [0, 500, 1440, 400], kids=[
            _n("h2", [200, 560, 500, 40], txt="Second band"),
            _n("p", [200, 620, 500, 40], txt="More copy here."),
        ]),
    ])
    header = _n("header", [0, 0, 1440, 80], kids=[
        _n("a", [40, 20, 160, 40], href="/", kids=[
            _n("img", [40, 20, 150, 40], src="https://client.example/logo.png")]),
        _n("a", [500, 30, 90, 20], txt="Services", href="https://client.example/services/"),
        _n("a", [620, 30, 80, 20], txt="Pricing", href="https://client.example/pricing/"),
        _n("a", [730, 30, 70, 20], txt="About", href="https://client.example/about/"),
        _n("a", [1280, 20, 120, 40], txt="Contact",
           s={"backgroundColor": "rgb(242, 183, 47)", "paddingLeft": "24px"},
           href="https://client.example/contact/"),
    ])
    footer = _n("footer", [0, 900, 1440, 300], kids=[
        _n("div", [0, 900, 1440, 300],
           s={"backgroundImage": 'url("https://client.example/leafy.jpg")'},
           kids=[
               _n("h3", [200, 940, 300, 40], txt="Client Co"),
               _n("p", [200, 1000, 400, 40], txt="All rights reserved."),
           ]),
    ])
    cap = ReplicaCapture(url="https://client.example/", title="Client Co")
    cap.head = {"title": "Client Co | The Best Widgets",
                "description": "Widgets made well since 1990.",
                "canonical": "https://client.example/"}
    cap.viewports.append(ReplicaViewport(
        viewport="desktop", width=1440, height=900,
        root=_node(content), header=_node(header), footer=_node(footer)))
    return cap


class TestTheChrome:
    """Navbar + footer + head fundamentals - the owner's mandate: a replica
    without the site's chrome is a torso."""

    def test_the_navbar_is_recognised_and_leads_the_tree(self) -> None:
        pub = _Publisher()
        res = replicate("https://client.example/", publisher=pub,
                        owner_confirmed_source=True, capture=_chrome_capture())
        assert res.ok, res.notes
        assert any("navbar recognised: logo-left menu-center cta-right" in n
                   for n in res.notes), res.notes
        tree = json.loads(pub.payloads[0]["elementor_data"])
        first = tree[0]
        assert first["settings"].get("css_classes") == "aios-replica-nav"
        blob = json.dumps(first)
        assert '"view": "inline"' in blob, "the menu is an inline icon-list"
        assert "Services" in blob and "Contact" in blob

    def test_the_footer_rides_the_standard_inference_with_its_ground(self) -> None:
        pub = _Publisher()
        res = replicate("https://client.example/", publisher=pub,
                        owner_confirmed_source=True, capture=_chrome_capture())
        assert any("footer replicated" in n for n in res.notes), res.notes
        tree = json.loads(pub.payloads[0]["elementor_data"])
        last = tree[-1]
        blob = json.dumps(last)
        assert "Client Co" in blob
        assert "leafy.jpg" in json.dumps(tree), "the footer's own backdrop image ships"

    def test_head_fundamentals_travel_and_canonical_is_never_copied(self) -> None:
        pub = _Publisher()
        replicate("https://client.example/", publisher=pub,
                  owner_confirmed_source=True, capture=_chrome_capture())
        p = pub.payloads[0]
        assert p["meta_title"] == "Client Co | The Best Widgets"
        assert p["meta_description"] == "Widgets made well since 1990."
        assert "canonical" not in p, ("the source's canonical names the SOURCE's "
                                      "domain; WordPress self-canonicalises")

    def test_chrome_pages_publish_on_the_canvas_template(self) -> None:
        pub = _Publisher()
        replicate("https://client.example/", publisher=pub,
                  owner_confirmed_source=True, capture=_chrome_capture())
        assert pub.payloads[0]["template"] == "elementor_canvas", (
            "the theme's own header/footer must not double up around the replica's")

    def test_internal_links_are_localised_cross_domain_left_alone(self) -> None:
        pub = _Publisher()
        replicate("https://client.example/", publisher=pub,
                  owner_confirmed_source=True, capture=_chrome_capture())
        data = pub.payloads[0]["elementor_data"]
        assert '"url":"/services/"' in data, "same-host links become path-relative"
        assert "https://client.example/services/" not in data
        assert "https://client.example/logo.png" in data, (
            "image SOURCES stay absolute - the media still lives on the source")

    def test_a_capture_without_chrome_still_publishes_and_says_so(self) -> None:
        cap = _chrome_capture()
        cap.viewports[0].header = None
        cap.viewports[0].footer = None
        pub = _Publisher()
        res = replicate("https://client.example/", publisher=pub,
                        owner_confirmed_source=True, capture=cap)
        assert res.ok, res.notes
        assert any("no header element" in n for n in res.notes)
        assert any("no footer element" in n for n in res.notes)
        assert "template" not in pub.payloads[0], (
            "without replicated chrome the theme's template stays")
