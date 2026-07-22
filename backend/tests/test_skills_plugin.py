"""P9-6: the skill quality / parity harness - validates the WHOLE aios-skills plugin
at build time, so a skill can never silently drift from the backend it drives.

Four properties, all enforced against the real files + the real FastAPI app:

* **frontmatter hygiene** - every ``skills/*/SKILL.md`` opens with a YAML frontmatter
  whose ``name`` equals its folder, a present third-person ``description`` < 1024
  chars, a least-privilege ``allowed-tools`` (no bare ``Bash(*)`` / unscoped
  ``Bash``), and a body < 500 lines.
* **human-gate** - every skill that WRITES / PUBLISHES / SPENDS sets
  ``disable-model-invocation: true`` so a human, not an autonomous model turn, runs it.
* **parity / coverage** - every ``/api/v1`` path a SKILL.md references in its body is a
  REAL route on ``app.main:app`` (modulo ``{param}``). This is the skill<->dashboard
  parity the plan requires: a documented skill call maps to an actual backend call.
* **manifest** - ``plugin.json`` is valid JSON and the 30 expected skills are all present.

Pure + offline: it reads the plugin files and builds the app's OpenAPI schema (no DB,
no network, no broker), so it runs in the ``unit`` gate.
"""

from __future__ import annotations

import json
import re
from itertools import product
from pathlib import Path

import pytest

from app.main import create_app

pytestmark = pytest.mark.unit

# backend/tests/test_skills_plugin.py -> parents[2] is the repo root; aios-skills is a
# sibling of backend/.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PLUGIN_DIR = _REPO_ROOT / "aios-skills"
_SKILLS_DIR = _PLUGIN_DIR / "skills"

# The 31 skills the plugin ships. Kept explicit so a dropped/renamed skill fails loudly.
EXPECTED_SKILLS = frozenset({
    "assign-task", "audit", "backlink-audit", "blog-post", "citation-builder",
    "citation-submit",
    "client-snapshot", "content", "geo-audit", "local-audit", "local-service-page",
    "milestones", "monthly-report", "offpage", "policy-brief", "policy-radar",
    "report", "sheets-sync", "team-status", "technical-audit", "titles-meta",
    "upsells", "web2-build",
    # Part 8 - one skill per Part-8 tool module.
    "billing", "competitor-intel", "data-import", "keyword-research", "local-seo",
    "on-page-fix", "onboard-client", "rank-report",
})

# Skills that WRITE / PUBLISH / SPEND must never be auto-invoked by a model turn - a
# human runs them. The plan's ``content/*`` and ``report*`` globs are resolved to the
# concrete folder names here.
WRITE_SKILLS = frozenset({
    "content", "blog-post", "local-service-page", "titles-meta",  # content/*
    "report", "monthly-report",                                   # report*
    "web2-build", "citation-builder", "citation-submit", "backlink-audit", "policy-brief",
    "sheets-sync", "upsells", "assign-task", "audit",
    # Part 8. Every one of these spends, mutates a live site, seals a secret, or moves
    # money: rank-report re-prices a standing per-client commitment when it adds a
    # keyword; keyword-research / competitor-intel spend provider budget; on-page-fix
    # writes to the client's live WordPress; local-seo's refresh spends; onboard-client
    # seals credentials into the vault; data-import commits rows; billing moves the
    # invoice ledger.
    "billing", "competitor-intel", "data-import", "keyword-research", "local-seo",
    "on-page-fix", "onboard-client", "rank-report",
})

_MAX_DESC = 1024
_MAX_BODY_LINES = 500
# A third-person description never opens with a first-/second-person pronoun.
_NON_THIRD_PERSON = frozenset({
    "i", "i'm", "i'll", "we", "our", "us", "my", "me", "you", "your", "yours",
})

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)
_KV_RE = re.compile(r"^([A-Za-z0-9_-]+):\s*(.*)$")
# An HTTP-verb-prefixed API path as the SKILL.md bodies document backend calls. The
# char class keeps dotted suffixes (findings.json / report.pdf) and pipe shorthands
# (backlinks|citations|web2, {acknowledge|dismiss}); trailing punctuation is trimmed.
# Case-insensitive so it verifies BOTH the uppercase prose form (``POST /api/v1/audits``)
# AND the client's real lowercase invocation (``aios_client.py get /audits``) - a
# documented call and an actual call must both map to a real backend route.
_PATH_RE = re.compile(r"\b(?:GET|POST|PATCH|PUT|DELETE)\s+(/[A-Za-z0-9_{}|.\-/]+)", re.IGNORECASE)

# AUTHORING-STANDARD §6: every skill reaches the ONE shared backend client through the
# plugin root, with a single canonical allowed-tools form - so all 30 skills read as if
# one operator wrote them and no per-call permission prompt fires at runtime.
_CANON_ALLOWED_TOOLS = "Bash(python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py:*), Read"
# The shared client, when referenced by PATH, must resolve through the plugin root.
# (A bare "aios_client.py <cmd>" shorthand in a later step is fine - only the pathed
# form is constrained, which is what a ${CLAUDE_SKILL_DIR}/../../ traversal would hit.)
_CANON_CLIENT_PREFIX = "${CLAUDE_PLUGIN_ROOT}/"
_CLIENT_SCRIPT_RE = re.compile(r"scripts/aios_client\.py")


def _skill_dirs() -> list[Path]:
    return sorted(p for p in _SKILLS_DIR.iterdir() if p.is_dir())


def _parse(text: str) -> tuple[dict[str, str], str]:
    """Split a SKILL.md into (frontmatter dict, body). Frontmatter keys are the simple
    single-line ``key: value`` pairs these skills use (no external YAML dependency)."""
    m = _FM_RE.match(text)
    assert m is not None, "SKILL.md must open with a '---' YAML frontmatter block '---'"
    fm: dict[str, str] = {}
    for line in m.group(1).splitlines():
        kv = _KV_RE.match(line)
        if kv:  # skip blank lines / block continuations we do not assert on
            fm[kv.group(1)] = kv.group(2).strip()
    return fm, m.group(2)


@pytest.fixture(scope="module")
def api_routes() -> list[list[str]]:
    """Every real ``/api/v1`` route as a list of path segments (from the OpenAPI schema,
    which is stable across FastAPI's internal route representation)."""
    spec = create_app().openapi()
    return [
        [s for s in path.split("/") if s]
        for path in spec.get("paths", {})
        if path.startswith("/api/v1")
    ]


# --------------------------------------------------------------------------- #
# Frontmatter hygiene (one test id per skill)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("skill", sorted(EXPECTED_SKILLS))
def test_frontmatter_is_valid(skill: str) -> None:
    fm, body = _parse((_SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8"))

    assert fm.get("name") == skill, f"frontmatter 'name' must equal the folder {skill!r}"

    desc = fm.get("description", "")
    assert desc, f"{skill}: a description is required"
    assert len(desc) < _MAX_DESC, f"{skill}: description must be < {_MAX_DESC} chars (is {len(desc)})"
    first_word = desc.split()[0].strip(".,").lower()
    assert first_word not in _NON_THIRD_PERSON, (
        f"{skill}: description must be third-person, not open with {first_word!r}"
    )

    tools = fm.get("allowed-tools", "")
    assert tools, f"{skill}: allowed-tools is required (least-privilege)"
    assert not re.search(r"Bash\(\s*\*\s*\)", tools), f"{skill}: allowed-tools must not grant bare Bash(*)"
    assert not re.search(r"\bBash\b(?!\s*\()", tools), (
        f"{skill}: every Bash tool must be scoped Bash(...), never unscoped Bash"
    )

    body_lines = body.count("\n") + 1
    assert body_lines < _MAX_BODY_LINES, f"{skill}: body must be < {_MAX_BODY_LINES} lines (is {body_lines})"


# --------------------------------------------------------------------------- #
# Wiring: the shared client is reached one canonical way (AUTHORING-STANDARD §6)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("skill", sorted(EXPECTED_SKILLS))
def test_backend_call_wiring_is_canonical(skill: str) -> None:
    text = (_SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8")
    fm, _ = _parse(text)

    # No relative traversal anywhere: every plugin asset (scripts/, reference/) is
    # addressed from ${CLAUDE_PLUGIN_ROOT}, so a call resolves regardless of cwd.
    assert "../.." not in text, (
        f"{skill}: no '../..' traversal - address plugin assets via ${{CLAUDE_PLUGIN_ROOT}}"
    )
    # Every PATHED reference to the shared client resolves through the plugin root -
    # never a ${CLAUDE_SKILL_DIR}/../../ traversal (${CLAUDE_SKILL_DIR} is only for a
    # skill's own reference/ files, §0/§2). Bare 'aios_client.py <cmd>' shorthand is fine.
    for m in _CLIENT_SCRIPT_RE.finditer(text):
        prefix = text[max(0, m.start() - len(_CANON_CLIENT_PREFIX)):m.start()]
        assert prefix.endswith(_CANON_CLIENT_PREFIX), (
            f"{skill}: 'scripts/aios_client.py' must be reached via "
            f"${{CLAUDE_PLUGIN_ROOT}}/, not {text[max(0, m.start() - 24):m.start()]!r} "
            f"(AUTHORING-STANDARD §6)"
        )
    # allowed-tools is exactly the standard's single canonical form (§6 line 194).
    assert fm.get("allowed-tools") == _CANON_ALLOWED_TOOLS, (
        f"{skill}: allowed-tools must be the canonical form {_CANON_ALLOWED_TOOLS!r}, "
        f"got {fm.get('allowed-tools')!r}"
    )


# --------------------------------------------------------------------------- #
# Human-gate: writers/spenders are never model-auto-invoked
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("skill", sorted(WRITE_SKILLS))
def test_write_skill_disables_model_invocation(skill: str) -> None:
    fm, _ = _parse((_SKILLS_DIR / skill / "SKILL.md").read_text(encoding="utf-8"))
    assert fm.get("disable-model-invocation", "").lower() == "true", (
        f"{skill} writes/publishes/spends -> must set 'disable-model-invocation: true'"
    )


# --------------------------------------------------------------------------- #
# Manifest + roster
# --------------------------------------------------------------------------- #
def test_plugin_manifest_valid_and_roster_complete() -> None:
    manifest = json.loads((_PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest.get("name"), "plugin.json must declare a name"

    present = {p.name for p in _skill_dirs() if (p / "SKILL.md").exists()}
    assert present == EXPECTED_SKILLS, (
        f"skill roster drift: missing={sorted(EXPECTED_SKILLS - present)} "
        f"extra={sorted(present - EXPECTED_SKILLS)}"
    )


# --------------------------------------------------------------------------- #
# Parity: every skill-referenced /api/v1 path is a real backend route
# --------------------------------------------------------------------------- #
def _normalize(path: str) -> list[str]:
    """Query-strip, trailing-punctuation-strip, /api/v1-prefix, and segment a raw path."""
    path = path.split("?")[0].strip().rstrip(".,/")
    if not path.startswith("/api/v1"):
        path = "/api/v1" + path
    return [s for s in path.split("/") if s]


def _candidates(segments: list[str]) -> list[list[str]]:
    """Expand a bare pipe-alternation shorthand (``backlinks|citations|web2``) into one
    candidate per alternative; a braced ``{acknowledge|dismiss}`` stays a param wildcard."""
    per_segment = [
        (seg.split("|") if ("|" in seg and not seg.startswith("{")) else [seg])
        for seg in segments
    ]
    return [list(combo) for combo in product(*per_segment)]


def _segment_matches(ref: str, route: str) -> bool:
    """A ref segment matches a route segment when either side is a ``{param}`` or they are equal."""
    return ref.startswith("{") or route.startswith("{") or ref == route


def _resolves(candidate: list[str], api_routes: list[list[str]]) -> bool:
    return any(
        len(candidate) == len(route)
        and all(_segment_matches(a, b) for a, b in zip(candidate, route, strict=True))
        for route in api_routes
    )


def test_every_referenced_api_path_is_a_real_route(api_routes: list[list[str]]) -> None:
    verified = 0
    for skill_dir in _skill_dirs():
        text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
        for raw in sorted(set(_PATH_RE.findall(text))):
            for candidate in _candidates(_normalize(raw)):
                verified += 1
                assert _resolves(candidate, api_routes), (
                    f"{skill_dir.name}: references {raw!r} -> /{'/'.join(candidate)}, "
                    f"which is not a real /api/v1 route (skill<->backend parity broken)"
                )
    # Anti-false-negative: a broken extractor that verifies nothing must not pass green.
    assert verified >= 60, f"expected many skill->route references verified, only saw {verified}"
