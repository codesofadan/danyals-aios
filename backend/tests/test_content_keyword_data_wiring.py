"""P5: the real keyword-data provider reaches the content bundle - or nothing does.

The rule this file defends: an absent provider is ABSENT, never a fake. v1 already
shipped `difficulty = log10(totalResults) * 8` looking exactly like vendor data;
substituting `FakeKeywordDataProvider` on the production path would be the same lie
with a better provenance story, and nothing downstream could tell a hashed 880 from a
bought one.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.services.content_pipeline.context import PipelineContext
from app.services.content_pipeline.research import run_research
from app.services.content_research import TeardownFetch
from integrations.content_providers import (
    content_providers_for_tests,
    content_providers_from_settings,
)
from integrations.content_research import FakeSerpResearcher
from integrations.keyword_data import KeywordDataProvider

pytestmark = pytest.mark.unit


def _settings(**kw: Any) -> Settings:
    base: dict[str, Any] = {
        "anthropic_api_key": "sk-test", "serper_api_key": "serper-test",
        "_env_file": None,
    }
    return Settings(**{**base, **kw})  # type: ignore[arg-type]


class TestTheProductionFactory:
    def test_without_dataforseo_credentials_the_provider_is_none_not_a_fake(self) -> None:
        """A hashed volume presented as demand is the exact defect this rebuild
        exists to remove."""
        bundle = content_providers_from_settings(_settings())
        assert bundle is not None
        assert bundle.keyword_data is None

    def test_a_missing_keyword_provider_does_not_degrade_the_whole_bundle(self) -> None:
        """Unlike the writer and SERP keys. A missing keyword provider costs FIDELITY -
        estimated metrics, honestly labelled. A missing writer means there is nothing
        to write at all. Degrading the bundle for the first would stop work that can
        legitimately proceed."""
        bundle = content_providers_from_settings(_settings())
        assert bundle is not None and bundle.writer is not None and bundle.serp is not None

    def test_a_missing_writer_key_still_degrades_everything(self) -> None:
        assert content_providers_from_settings(_settings(anthropic_api_key=None)) is None

    def test_a_password_without_a_login_is_not_enough_to_construct_one(self) -> None:
        bundle = content_providers_from_settings(_settings(dataforseo_password="pw"))
        assert bundle is not None and bundle.keyword_data is None


class TestTheTestBundle:
    def test_the_all_fakes_bundle_does_carry_the_fake(self) -> None:
        """The rule is about the PRODUCTION factory. A deterministic fake is exactly
        what the offline suites need."""
        bundle = content_providers_for_tests()
        assert isinstance(bundle.keyword_data, KeywordDataProvider)


class _Port:
    def __init__(self) -> None:
        self._inner = FakeSerpResearcher()

    def serp(self, keyword: str, geo: str | None = None) -> Any:
        return self._inner.serp(keyword, geo)

    def keyword_metrics(self, keyword: str) -> Any:
        return self._inner.keyword_metrics(keyword)

    def teardown(self, urls: list[str], keyword: str, geo: str | None) -> TeardownFetch:
        return TeardownFetch(pages=[], refused=[])


class TestTheLookupNeverLaundersAnEstimate:
    """`metrics_for` returning a row marked `estimated` would turn "we guessed this"
    into "read from the engagement's keyword plan" in the stage notes - which is the
    fabrication wearing the audit trail's clothes."""

    def _ctx(self) -> PipelineContext:
        return PipelineContext(
            primary_keyword="slab leak repair san jose", geo="San Jose",
            engagement_id="e1", vertical="plumbing",
        )

    def test_a_bought_row_is_used_and_reported_as_measured(self) -> None:
        class Plan:
            def metrics_for(self, engagement_id: str | None, keyword: str) -> dict[str, Any]:
                return {"volume": 880, "difficulty": 34, "estimated": False}

        result = run_research(self._ctx(), researcher=_Port(), plan=Plan())
        assert result.data["metrics_estimated"] is False
        assert any("keyword plan" in n for n in result.notes)

    def test_no_row_falls_back_to_estimated_and_says_so(self) -> None:
        class Empty:
            def metrics_for(self, engagement_id: str | None, keyword: str) -> None:
                return None

        result = run_research(self._ctx(), researcher=_Port(), plan=Empty())
        assert result.data["metrics_estimated"] is True
        assert any("ESTIMATED" in n for n in result.notes)

    def test_no_plan_at_all_is_the_same_honest_fallback(self) -> None:
        result = run_research(self._ctx(), researcher=_Port(), plan=None)
        assert result.data["metrics_estimated"] is True
