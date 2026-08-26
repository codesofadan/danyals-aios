"""The load-bearing claims in the docs are held to the code.

WHY THIS FILE EXISTS. Every plan in this repo is made by reading CLAUDE.md and the
module docs, so a wrong sentence there costs more than a wrong line of code: it is
believed, propagated, and planned from. The measured history is not flattering:

  * the RBAC feature count was wrong in BOTH directions - it read 17 while the code
    held 11, was corrected to 11, and then Part 8's tool modules grew the code to 17
    while the doc kept saying 11;
  * `CONTENT-DOCTRINE.md` asserted a QA publish gate that has never existed, and
    contradicted `CONTENT-MODULE.md` in the same directory;
  * `CLAUDE.md` contradicted ITSELF 93 lines apart on the same gate;
  * `KNOWN_LIMITATIONS.md` listed a finished fix as "Not started".

None of that was caught by a test, because prose is not executable. These tests make
the small, checkable subset executable: a count, and the absence of a claim that a
`grep` can refute. Everything else in the docs still relies on care.

DELIBERATELY NOT LINE NUMBERS. Docs here cite `file.py:412` constantly and those go
stale the moment anyone edits above them - two such citations rotted during the very
session that wrote them. These tests assert FACTS, never locations.
"""

from __future__ import annotations

import pathlib
import re

import pytest

from app.rbac.matrix import FEATURES, PERMISSIONS, ROLE_META, TEMPLATES

pytestmark = pytest.mark.unit

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
_CLAUDE_MD = _BACKEND / "CLAUDE.md"


def _claude_md() -> str:
    return _CLAUDE_MD.read_text(encoding="utf-8")


class TestTheRbacCountsInTheDocs:
    """`CLAUDE.md` states the matrix's shape in prose. It must match the module."""

    def test_the_feature_count_is_the_real_one(self) -> None:
        text = _claude_md()
        m = re.search(r"\*\*(\d+)-feature matrix", text)
        assert m, "CLAUDE.md no longer states the feature count in the expected shape"
        assert int(m.group(1)) == len(FEATURES), (
            f"CLAUDE.md claims {m.group(1)} features; app/rbac/matrix.py holds "
            f"{len(FEATURES)}. Measure with len(FEATURES) - this number has been "
            "wrong in both directions before."
        )

    def test_the_other_three_counts_in_the_same_sentence(self) -> None:
        text = _claude_md()
        m = re.search(
            r"(\d+) permissions \+ (\d+) roles \+ (\d+) templates", text
        )
        assert m, "CLAUDE.md no longer states permissions/roles/templates"
        perms, roles, templates = (int(g) for g in m.groups())
        assert perms == len(PERMISSIONS), f"doc says {perms} permissions, code has {len(PERMISSIONS)}"
        assert roles == len(ROLE_META), f"doc says {roles} roles, code has {len(ROLE_META)}"
        assert templates == len(TEMPLATES), (
            f"doc says {templates} templates, code has {len(TEMPLATES)}"
        )


class TestNoDocClaimsAQaPublishGate:
    """The QA score is ADVISORY (decision D-4). The only enforced quality boundary
    is the human review gate.

    A doc asserting otherwise is worse than silence: it describes a safety property
    the platform does not have, and someone will rely on it. `CONTENT-DOCTRINE.md`
    did exactly that while `CONTENT-MODULE.md` next to it said the opposite.
    """

    #: Docs whose subject is the content pipeline, so a gate claim would be read as
    #: authoritative. Paths are relative to `backend/`.
    _DOCS = ("CLAUDE.md", "docs/CONTENT-MODULE.md", "docs/CONTENT-DOCTRINE.md")

    #: Phrases that ASSERT enforcement. Deliberately narrow: these files must stay
    #: free to DISCUSS the absent gate (they all do, at length), so only wording
    #: that claims the block happens is refused.
    _CLAIMS = (
        r"hard QA (?:§?11 )?publish gate",
        r"blocks any draft",
        r"the publish gate is load-bearing",
    )

    def test_the_gate_is_still_absent_from_the_code(self) -> None:
        """Guard-for-the-guard: if someone BUILDS the gate, the assertions below
        become wrong and must be revisited rather than silently kept."""
        hits: list[str] = []
        for path in (_BACKEND / "app", _BACKEND / "workers", _BACKEND / "integrations"):
            for py in path.rglob("*.py"):
                if "raise PublishBlocked" in py.read_text(encoding="utf-8"):
                    hits.append(str(py.relative_to(_BACKEND)))
        assert hits == [], (
            "PublishBlocked is now RAISED, so an automated QA publish gate exists. "
            "That is a real product change (P0-4): update decision D-4, invariant "
            "#12 and this test together - do not just delete the assertion."
        )

    @pytest.mark.parametrize("doc", _DOCS)
    def test_no_doc_asserts_the_gate_exists(self, doc: str) -> None:
        path = _BACKEND / doc
        if not path.exists():
            pytest.skip(f"{doc} is not present")
        text = path.read_text(encoding="utf-8")
        offenders = []
        for line_no, line in enumerate(text.splitlines(), start=1):
            # A BLOCKQUOTE is quoted material, not an assertion. The honest pattern
            # in this repo is to quote the wrong old wording inside `>` while
            # correcting it, and that correction often runs across several lines -
            # so exempting only the line carrying the word "corrected" flagged the
            # continuation lines of the very fix being made.
            if line.lstrip().startswith(">"):
                continue
            # ...and an inline correction on a single line is fine too.
            if re.search(r"corrected|previously read|this line said|no longer", line, re.I):
                continue
            for claim in self._CLAIMS:
                if re.search(claim, line, re.I):
                    offenders.append(f"{doc}:{line_no}: {line.strip()[:110]}")
        assert offenders == [], (
            "these lines assert a QA publish gate that does not exist:\n"
            + "\n".join(offenders)
        )
