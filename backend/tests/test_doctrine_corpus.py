"""R6-1: the SEO-CONTENT-OS doctrine corpus is present, intact, and actually cited.

Prevented defect: `content_generator.py` and `content_qa.py` both name
`backend/seo-content-os/knowledge/` as "the CANONICAL doctrine" justifying their
numeric constants (word budgets, density ceilings, the 14 QA dimensions, the G0-G13
gate stack) - and that path had NEVER EXISTED in git history. The only copy of the
doctrine was an unopened zip at the repo root, grandfathered by
`test_repo_structure.py` with the note "It must be EXTRACTED, not deleted".

So the code cited a source no reader could open, and no test could tell the difference
between "the constants match the doctrine" and "the doctrine is not here at all".

These tests close both halves:
  * the corpus EXISTS at the path the code names, and
  * it still matches the hashes recorded when the constants were derived from it.

The manifest is the anchor. Regenerating it is a deliberate act (a doctrine change);
a silent edit shows up here as a hash mismatch rather than as prose that quietly
disagrees with the code enforcing it.
"""

from __future__ import annotations

import ast
import hashlib
import json
import pathlib

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
_CORPUS = _BACKEND / "seo-content-os"
_MANIFEST = _CORPUS / "MANIFEST.json"


# The ONLY third-party imports in the corpus, pinned so a new one cannot slip in.
#
# All three read `clients/_template/brand.yaml`. PyYAML is currently present in the
# venv only as a TRANSITIVE dependency - it is NOT declared in pyproject.toml - so
# relying on it would work today and break silently on an unrelated dependency bump.
#
# The P1B decision, recorded here rather than discovered mid-port: the client profile
# moves into Postgres (`brand_kits` / `sme_slots`, migrations 0087/0089), so the ported
# validators should take an already-parsed mapping and never touch YAML. If that
# changes, PyYAML must be added to pyproject.toml EXPLICITLY in the same commit.
_KNOWN_THIRD_PARTY: list[str] = [
    "nap_checker.py: yaml",
    "storage_cluster_seed.py: yaml",
    "storage_lint.py: yaml",
]


def _imported_roots(path: pathlib.Path) -> set[str]:
    """Top-level module names imported by ``path`` (absolute imports only)."""
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            roots.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


@pytest.fixture(scope="module")
def manifest() -> dict:
    assert _MANIFEST.is_file(), (
        f"{_MANIFEST} is missing. The doctrine corpus must be extracted into the repo "
        "(research item R6-1), not left inside SEO-CONTENT-OS.zip."
    )
    return json.loads(_MANIFEST.read_text())


# --------------------------------------------------------------------------- #
# 1 - the corpus is where the code says it is
# --------------------------------------------------------------------------- #
def test_the_path_the_code_cites_actually_exists() -> None:
    """Every `backend/seo-content-os/...` path named in a source comment must resolve.

    This is the assertion that would have failed for the module's entire life.
    """
    import re

    cited: set[str] = set()
    for area in ("app", "workers", "integrations"):
        for path in (_BACKEND / area).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            cited.update(
                re.findall(r"backend/seo-content-os/[A-Za-z0-9_./-]+", path.read_text())
            )

    assert cited, "no source file cites the doctrine corpus any more - did a path change?"
    missing = [c for c in sorted(cited) if not (_BACKEND.parent / c).exists()]
    assert not missing, f"source comments cite non-existent doctrine paths: {missing}"


# --------------------------------------------------------------------------- #
# 2 - the corpus has not drifted from what the constants were derived from
# --------------------------------------------------------------------------- #
def test_every_manifest_file_is_present_and_unmodified(manifest: dict) -> None:
    missing: list[str] = []
    changed: list[str] = []
    for rel, rec in manifest["files"].items():
        path = _CORPUS / rel
        if not path.is_file():
            missing.append(rel)
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != rec["sha256"]:
            changed.append(rel)

    assert not missing, f"doctrine files deleted since extraction: {missing}"
    assert not changed, (
        f"doctrine files edited since extraction: {changed}. If the change is "
        "deliberate, regenerate MANIFEST.json in the SAME commit and say what the "
        "doctrine now says differently - the code's numeric constants cite it."
    )


def test_no_undeclared_file_has_appeared(manifest: dict) -> None:
    """An untracked addition is drift too: it would be indexed at runtime while no
    hash covers it."""
    on_disk = {
        p.relative_to(_CORPUS).as_posix()
        for p in _CORPUS.rglob("*")
        if p.is_file() and p.name != "MANIFEST.json" and "__pycache__" not in p.parts
    }
    extra = sorted(on_disk - set(manifest["files"]))
    assert not extra, f"files present but not in MANIFEST.json: {extra}"


# --------------------------------------------------------------------------- #
# 3 - the load-bearing pieces 1B will route to are actually here
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "rel",
    [
        "CLAUDE.md",                                        # the constitution
        "knowledge/doctrine/seo-system-doctrine.md",        # Laws 1-20
        "knowledge/doctrine/google-compliance-spine.md",    # the 33 rules
        "knowledge/doctrine/penalty-casebook.md",
        "knowledge/quality-gates/gates.md",                 # G0-G13, cited by content_qa
        "knowledge/foundations/keyword-research-method.md",
        "knowledge/foundations/topical-map-protocol.md",
        "knowledge/foundations/eeat-framework.md",
        "knowledge/foundations/experience-signals.md",      # Law 16 / the SME halt
        "knowledge/voice/vocabulary-blocklist.md",
        "knowledge/voice/natural-voice-engineering.md",
        "clients/_template/brand.yaml",                     # the client profile schema
    ],
)
def test_load_bearing_doctrine_files_exist(rel: str) -> None:
    path = _CORPUS / rel
    assert path.is_file(), f"missing doctrine file: {rel}"
    assert path.stat().st_size > 512, f"suspiciously small doctrine file: {rel}"


def test_every_page_type_playbook_is_present() -> None:
    """The pipeline routes a page pack per page type; a missing playbook degrades that
    page type silently to generic prose."""
    playbooks = {p.stem for p in (_CORPUS / "knowledge" / "playbooks").glob("*.md")}
    required = {
        "homepage", "service-page", "service-city-page", "location-page",
        "service-area-page", "about-team-page", "faq-page", "local-asset",
    }
    assert required <= playbooks, f"missing playbooks: {sorted(required - playbooks)}"


def test_the_stage_role_agents_are_present() -> None:
    """Each becomes a stage's system block (Block B) in the P1B prompt assembly."""
    agents = {p.stem for p in (_CORPUS / "agents").glob("*.md")}
    required = {
        "keyword-intent-researcher", "topical-map-architect", "outline-architect",
        "sme-interviewer", "voice-writer", "critical-editor", "conversion-optimizer",
        "compliance-auditor", "link-architect", "schema-linking-finisher",
    }
    assert required == agents, f"agent set drifted: {sorted(agents ^ required)}"


# --------------------------------------------------------------------------- #
# 4 - the 22 offline validators are importable Python
# --------------------------------------------------------------------------- #
def test_the_offline_validators_are_present_and_parse() -> None:
    """These are the build-not-buy win: deterministic checks with NO external API.
    They are ported into app/services/content_lint/ in P1B, so they must at minimum
    be syntactically valid Python here."""
    scripts = sorted((_CORPUS / "scripts").glob("*.py"))
    assert len(scripts) >= 20, f"expected the ~22 validator scripts, found {len(scripts)}"

    for path in scripts:
        try:
            ast.parse(path.read_text(), filename=str(path))
        except SyntaxError as exc:  # pragma: no cover - a corrupt extraction
            pytest.fail(f"{path.name} does not parse: {exc}")


def test_the_validators_depend_only_on_stdlib_and_each_other() -> None:
    """The corpus's stated design is "No external APIs. Offline Python tool-scripts for
    deterministic checks." If a script grew a `requests` / `numpy` / `pandas`
    dependency, porting it in-process (P1B) would drag that into the base install,
    which this repo deliberately keeps light.

    Sibling imports are FINE and are asserted separately below - they are the reason
    the port is a package, not 22 loose functions.
    """
    stdlib_ok = {
        "__future__", "abc", "argparse", "ast", "base64", "collections", "copy", "csv",
        "dataclasses", "datetime", "decimal", "difflib", "enum", "functools", "glob",
        "hashlib", "html", "io", "itertools", "json", "logging", "math", "operator",
        "os", "pathlib", "random", "re", "shutil", "statistics", "string", "subprocess",
        "sys", "tempfile", "textwrap", "time", "tomllib", "typing", "unicodedata",
        "urllib", "uuid", "warnings", "xml", "zipfile",
    }
    siblings = {p.stem for p in (_CORPUS / "scripts").glob("*.py")}

    offenders: list[str] = []
    for path in sorted((_CORPUS / "scripts").glob("*.py")):
        for mod in _imported_roots(path):
            if mod not in stdlib_ok and mod not in siblings:
                offenders.append(f"{path.name}: {mod}")

    assert sorted(set(offenders)) == _KNOWN_THIRD_PARTY, (
        "the validator scripts' third-party imports changed. Anything new here becomes "
        "a RUNTIME dependency of the base install when the script is ported in-process "
        f"(P1B), so it needs a deliberate decision: {sorted(set(offenders))}"
    )


def test_the_validator_dependency_graph_is_recorded() -> None:
    """The scripts are NOT 22 independent files - several import each other, so the
    P1B port must move them as a package with the shared primitives extracted first,
    not one at a time. Pinned here so that shape is discovered before the port, not
    halfway through it.
    """
    siblings = {p.stem for p in (_CORPUS / "scripts").glob("*.py")}
    graph = {
        path.stem: sorted(m for m in _imported_roots(path) if m in siblings)
        for path in sorted((_CORPUS / "scripts").glob("*.py"))
    }
    depended_on = {dep for deps in graph.values() for dep in deps}

    # `readability_scorer` is the shared primitive: port it FIRST.
    assert "readability_scorer" in depended_on
    assert graph["duplication_gate"] == ["readability_scorer"]
    assert "keyword_density" in graph["compliance_lint"]

    # No cycles, so a topological port order exists.
    for mod, deps in graph.items():
        for dep in deps:
            assert mod not in graph.get(dep, []), f"import cycle: {mod} <-> {dep}"


# --------------------------------------------------------------------------- #
# 5 - the corpus actually SHIPS
# --------------------------------------------------------------------------- #
def test_the_corpus_is_packaged_into_the_wheel() -> None:
    """A corpus present in the repo but absent from the wheel is the worst shape of
    this bug: every test passes, and the Celery worker raises FileNotFoundError on a
    real client's job.

    The app runs from the installed venv - backend/Dockerfile COPYies only
    db/migrations and the audit engine into the runtime stage - so `packages` and
    `force-include` are the ONLY routes into production.
    """
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - py<3.11
        pytest.skip("tomllib unavailable")

    cfg = tomllib.loads((_BACKEND / "pyproject.toml").read_text())
    wheel = cfg["tool"]["hatch"]["build"]["targets"]["wheel"]
    included = wheel.get("force-include", {})

    assert "seo-content-os" in included, (
        "seo-content-os is missing from [tool.hatch.build.targets.wheel.force-include]. "
        "It is not a Python package, so `packages` cannot carry it, and without this "
        "the doctrine is absent from every deployed image."
    )
    assert included["seo-content-os"] == "seo-content-os", (
        "the corpus must land beside app/ in site-packages so the same relative lookup "
        "resolves from a source checkout and from the wheel"
    )
