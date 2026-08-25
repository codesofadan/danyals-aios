"""Guard: a synthetic (``Fake*``) provider must never be reachable on a production path.

WHY THIS FILE EXISTS
--------------------
The single most damaging defect found in the 2026-08-23 recovery audit was not missing
code - it was code that *fabricated* data and presented it as measured:

* ``content_providers_from_settings`` substituted ``FakeSerpResearcher`` when
  ``SERPER_API_KEY`` was absent. That fake synthesises "competitors" from a SHA-256 of
  the keyword (``https://example.test/<hex>``, template snippets). The pipeline drafted
  a "SERP-grounded" article from that invented research and PUBLISHED IT TO A CLIENT'S
  LIVE WORDPRESS SITE. Nothing downstream could tell it from real research, because the
  ``SerpResearcher`` protocol carries no liveness signal.
* ``rank_provider_from_settings`` / ``local_pack_provider_from_settings`` degraded to
  fakes whose positions were then WRITTEN to the ranking ledgers, where they are
  indistinguishable from a measured check and get charted to the client as real
  performance.
* ``keyword_data_provider_from_settings`` degraded to a fake that hashes a seed into
  plausible volume/difficulty/intent, which an operator would then use to build a
  content strategy grounded in demand that does not exist.
* ``discover_competitors`` computed a liveness flag and then DISCARDED it (``_live``).

The fakes themselves are legitimate and must stay: they keep the modules unit-testable
with no network and no keys. What must never happen again is a PRODUCTION factory or
worker silently substituting one and persisting or publishing its output.

THE RULE
--------
Every ``Fake*`` construction in ``app/``, ``integrations/`` and ``workers/`` must be
declared below with the reason it is safe. A new, undeclared one fails this test. If you
are adding one, the question to answer is not "does this keep the module running?" but
"can this output ever be written, published, charted or billed as if it were real?" If
yes, the caller must refuse (degrade) instead - see ``keyword_data_is_live``,
``local_pack_provider_is_live`` and ``rank_pricing_from_settings(...).live``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_BACKEND = Path(__file__).resolve().parent.parent
_PRODUCTION_DIRS = ("app", "integrations", "workers")

# (module path, enclosing function) -> (allowed Fake class names, why it is safe here).
#
# The class names are pinned deliberately. An earlier version keyed only on location,
# which meant a NEW fake added inside an already-declared function slipped through --
# proven by reintroducing the original FakeSerpResearcher defect and watching the scan
# stay green. Pinning the names closes that hole.
_DECLARED_SAFE: dict[tuple[str, str], tuple[frozenset[str], str]] = {
    # Explicit test-only bundles. Named *_for_tests; never called by app code.
    ("integrations/content_providers.py", "content_providers_for_tests"): (
        frozenset({"FakeSerpResearcher", "FakeSummarizer", "FakeImageGenerator",
                   "FakeWordPressPublisher", "FakeKeywordDataProvider"}),
        "explicit all-fakes bundle for the pipeline suites; not reachable from the app. "
        "The PRODUCTION factory deliberately leaves keyword_data None rather than "
        "substituting this fake - it synthesises volume from a hash, and nothing "
        "downstream could tell a hashed 880 from a bought one"
    ),
    ("integrations/context_providers.py", "providers_for_tests"): (
        frozenset({"FakeSummarizer", "FakeEmbedder"}),
        "explicit all-fakes bundle for the context suites; not reachable from the app"
    ),
    # Images are an enrichment, not evidence. The content worker injects only a REAL
    # hosted image and skips a fake/empty one, so a missing key is a visible absence
    # rather than fabricated evidence.
    ("integrations/content_providers.py", "content_providers_from_settings"): (
        frozenset({"FakeImageGenerator", "FakeWordPressPublisher"}),
        "FakeImageGenerator only; a fake image is skipped by the worker, never published. "
        "The WordPress default is also a fake because per-site credentials live in the "
        "vault and the service layer builds the real publisher per publish"
    ),
    # These factories still return a fake so the modules stay unit-testable offline, but
    # every WRITING caller now gates on an explicit liveness helper first.
    ("app/modules/rank_tracker/provider.py", "_build_fake"): (
        frozenset({"FakeRankProvider"}),
        "registry entry for the explicitly-configured 'fake' vendor; the worker gates on "
        "rank_pricing_from_settings(...).live before it can persist"
    ),
    ("app/modules/rank_tracker/provider.py", "rank_provider_from_settings"): (
        frozenset({"FakeRankProvider"}),
        "keeps the module unit-testable; check_keyword_rank + dispatch_rank_checks gate "
        "on rank_pricing_from_settings(...).live before any write"
    ),
    ("app/modules/local_seo/provider.py", "local_pack_provider_from_settings"): (
        frozenset({"FakeLocalPackProvider"}),
        "keeps the module unit-testable; refresh_local_ranks gates on "
        "local_pack_provider_is_live before any write"
    ),
    ("integrations/keyword_data.py", "keyword_data_provider_from_settings"): (
        frozenset({"FakeKeywordDataProvider"}),
        "keeps the module unit-testable; research_keywords gates on keyword_data_is_live "
        "before any write"
    ),
    ("app/modules/competitor_intel/provider.py", "serp_source_from_settings"): (
        frozenset({"FakeSerpResearcher"}),
        "returns (provider, live) so the caller cannot ignore liveness; "
        "discover_competitors now refuses when live is False"
    ),
}


def _enclosing_function(tree: ast.Module, lineno: int) -> str:
    """The innermost function containing ``lineno``, or '<module>'."""
    best: tuple[int, str] = (-1, "<module>")
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            end = getattr(node, "end_lineno", node.lineno)
            if node.lineno <= lineno <= end and node.lineno > best[0]:
                best = (node.lineno, node.name)
    return best[1]


def _synthetic_constructions() -> dict[tuple[str, str], list[str]]:
    """Every ``Fake*(...)`` construction on a production path, by (module, function)."""
    found: dict[tuple[str, str], list[str]] = {}
    for directory in _PRODUCTION_DIRS:
        for path in sorted((_BACKEND / directory).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                if not name.startswith("Fake"):
                    continue
                rel = path.relative_to(_BACKEND).as_posix()
                key = (rel, _enclosing_function(tree, node.lineno))
                found.setdefault(key, []).append(name)
    return found


def test_every_synthetic_provider_on_a_production_path_is_declared_safe() -> None:
    """A NEW undeclared ``Fake*`` on a production path fails the build.

    This is deliberately auto-discovering: a future module gets the guard for free,
    with no registration step to forget.
    """
    undeclared: dict[tuple[str, str], list[str]] = {}
    for key, names in _synthetic_constructions().items():
        declared = _DECLARED_SAFE.get(key)
        allowed = declared[0] if declared else frozenset()
        unexpected = sorted(set(names) - allowed)
        if unexpected:
            undeclared[key] = unexpected
    assert not undeclared, (
        "Synthetic provider(s) constructed on a production path without a declared "
        "justification:\n"
        + "\n".join(
            f"  {mod}::{fn} -> {', '.join(sorted(set(names)))}"
            for (mod, fn), names in sorted(undeclared.items())
        )
        + "\n\nIf this output can ever be persisted, published, charted or billed as if "
        "it were measured, the caller must DEGRADE instead (see the module docstring). "
        "If it genuinely cannot, add it to _DECLARED_SAFE with the reason."
    )


def test_the_declarations_have_not_gone_stale() -> None:
    """A declaration whose call site is gone must be removed, not left to rot."""
    actual = set(_synthetic_constructions())
    stale = sorted(key for key in _DECLARED_SAFE if key not in actual)
    assert not stale, (
        "These entries in _DECLARED_SAFE no longer match any call site and should be "
        f"deleted: {stale}"
    )


def test_the_content_bundle_degrades_without_a_research_key() -> None:
    """The specific regression that put invented research on client sites.

    Kept as an explicit, named test in addition to the static scan, because this is the
    one the static scan cannot express: the danger was not that a fake existed, but that
    it was substituted for the RESEARCH seam specifically.
    """
    from app.config import Settings
    from integrations.content_providers import content_providers_from_settings

    settings = Settings(anthropic_api_key="ak", serper_api_key=None)  # type: ignore[call-arg]
    assert content_providers_from_settings(settings) is None
