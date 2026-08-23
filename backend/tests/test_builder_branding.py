"""P0-9 gate: the builder's name never appears in the shipped product.

`docs/architecture/PRODUCT-OVERHAUL-BACKLOG.md` states it as a hard rule, and the master
plan's platform-wide Definition of Done repeats it: *the builder's name appears
nowhere in the running software, its configuration, its tests, or its output.*

It had reached end clients twice over — in the WordPress plugin header, which is
listed in every client's wp-admin Plugins screen, and in the footer of every
outbound email the platform sends. A one-time find-and-replace does not keep it
out; this does.

**Scope, stated precisely.** This sweeps what SHIPS or RUNS: backend source and
tests, the frontend bundle, the WordPress plugin, packaging metadata, infra
config, and the operator scripts. It deliberately does NOT sweep `docs/` — that is
the project's own historical record (including the backlog entry that states this
rule), and rewriting history to satisfy a lint is dishonest, not compliant.
(`context/` was folded into `docs/architecture/` on 2026-08-23, so one exclusion
now covers what used to need two.)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Split so this file does not itself contain the literal it forbids — otherwise
# the sweep would have to special-case its own path, which is how such a guard
# quietly stops covering the tree it lives in.
_BUILDER = "xe" + "gents"
_PATTERN = re.compile(_BUILDER, re.IGNORECASE)

# Directories that ship or run. Everything a client, a browser, a server or CI
# can reach.
_SHIPPED_ROOTS = (
    "backend/app",
    "backend/workers",
    "backend/integrations",
    "backend/tests",
    "frontend/app",
    "frontend/components",
    "frontend/lib",
    "wordpress-plugin",
    "infra",
    "tools",
    "db",
    ".github",
)

_SHIPPED_FILES = (
    "backend/pyproject.toml",
    "frontend/package.json",
    "docker-compose.yml",
)

_EXTENSIONS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".php", ".txt", ".toml", ".json",
    ".yml", ".yaml", ".sql", ".sh", ".css", ".html",
}

_SKIP_DIRS = {"node_modules", ".next", "__pycache__", ".venv", "out", "dist", ".git"}


def _candidate_files() -> list[Path]:
    files: list[Path] = []
    for rel in _SHIPPED_ROOTS:
        root = _REPO_ROOT / rel
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in _EXTENSIONS:
                continue
            if any(part in _SKIP_DIRS for part in path.parts):
                continue
            files.append(path)
    for rel in _SHIPPED_FILES:
        path = _REPO_ROOT / rel
        if path.is_file():
            files.append(path)
    return files


def test_the_sweep_actually_covers_the_shipped_tree() -> None:
    """Guard the guard: a bad root would make the rule below vacuously pass."""
    files = _candidate_files()
    assert len(files) > 200, f"expected the shipped tree, found only {len(files)} files"
    # The two surfaces that reached end clients must be in scope by construction.
    covered = {str(p.relative_to(_REPO_ROOT)) for p in files}
    assert "wordpress-plugin/aios-publisher/aios-publisher.php" in covered
    assert "backend/app/services/email_templates.py" in covered


def test_the_builders_name_is_absent_from_everything_that_ships() -> None:
    offenders: list[str] = []
    for path in _candidate_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # a binary or unreadable file carries no reviewable string
        for lineno, line in enumerate(text.splitlines(), 1):
            if _PATTERN.search(line):
                rel = path.relative_to(_REPO_ROOT)
                offenders.append(f"{rel}:{lineno}: {line.strip()[:120]}")
    assert not offenders, (
        "The builder's name is back in the shipped product. It is visible to end "
        "clients wherever it lands — the WordPress plugin header shows in every "
        "client's wp-admin, and the email footer goes out on every notification.\n  "
        + "\n  ".join(offenders)
    )


def test_the_wordpress_plugin_header_names_the_product_not_the_builder() -> None:
    """The plugin header is the single most client-visible string in the system."""
    header = (_REPO_ROOT / "wordpress-plugin" / "aios-publisher" / "aios-publisher.php").read_text(
        encoding="utf-8"
    )[:2000]
    author = re.search(r"^\s*\*\s*Author:\s*(.+?)\s*$", header, re.MULTILINE)
    assert author, "the plugin header must declare an Author"
    assert not _PATTERN.search(author.group(1)), f"Author is the builder: {author.group(1)}"
    assert author.group(1).strip(), "Author must not be blank"


def test_the_outbound_email_footer_names_the_product_not_the_builder() -> None:
    from app.services.email_templates import _FOOTER

    assert _FOOTER.strip(), "emails must still carry a footer"
    assert not _PATTERN.search(_FOOTER), f"email footer names the builder: {_FOOTER}"


# --------------------------------------------------------------------------- #
# P0-10 · no real client contact data may live in the tree
# --------------------------------------------------------------------------- #
# `tools/finish_citation.py` hardcoded one client's full NAP — a real street
# address and a real phone number — in version control. It was also a per-client
# hardcode in a script meant for every client: reused as-is it would stamp the
# WRONG business onto another client's directory listings, which is precisely the
# NAP inconsistency a citation campaign exists to remove.


def test_the_citation_handoff_script_carries_no_hardcoded_client_nap() -> None:
    src = (_REPO_ROOT / "tools" / "finish_citation.py").read_text(encoding="utf-8")

    # A bare digit run long enough to be a phone number, inside a string literal.
    phone_like = re.findall(r"[\"'](\+?\d[\d\s().-]{8,}\d)[\"']", src)
    assert not phone_like, f"a phone-number-shaped literal is in the script: {phone_like}"

    assert "NAP = {" not in src, "the NAP is hardcoded again; it must come from the export"
    assert "_nap(" in src, "the script must resolve the NAP from the handoff export"


def test_the_citation_handoff_export_is_not_committed() -> None:
    """The export carries live directory logins and a shared password."""
    assert not (_REPO_ROOT / "tools" / "citation_handoffs.json").exists(), (
        "tools/citation_handoffs.json is in the working tree. It holds real "
        "directory account credentials; it must never be committed."
    )
