"""The proof-screenshot reader, and the traversal guard that makes a key safe.

`citations.proof_url` holds a relative KEY. It used to hold the absolute server path the
Playwright bot returned, which is why a column named `*_url` carried `/var/lib/...` and
leaked the server's layout to anything that serialised the row. A key needs a reader, and
a reader that accepts a key from the database needs a guard.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.modules.citations.evidence import CitationEvidenceStore, citation_evidence_store

pytestmark = pytest.mark.unit


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "ab12cd34.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "deep.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    return tmp_path


def test_a_real_key_resolves(root: Path) -> None:
    store = CitationEvidenceStore(str(root))
    assert store.resolve("ab12cd34.png") == (root / "ab12cd34.png").resolve()


def test_a_nested_key_resolves(root: Path) -> None:
    store = CitationEvidenceStore(str(root))
    assert store.resolve("nested/deep.png") is not None


def test_an_empty_key_is_none(root: Path) -> None:
    """The honest state when no screenshot was captured - never an error."""
    assert CitationEvidenceStore(str(root)).resolve("") is None


def test_a_missing_file_is_none(root: Path) -> None:
    assert CitationEvidenceStore(str(root)).resolve("nope.png") is None


@pytest.mark.parametrize(
    "key",
    [
        "../../../etc/passwd",
        "nested/../../etc/passwd",
        "/etc/passwd",
        "....//....//etc/passwd",
    ],
)
def test_a_key_that_escapes_the_root_is_refused(root: Path, key: str) -> None:
    """The key comes out of the database, so it is only as trustworthy as everything
    that can write there. Resolution happens on the NORMALISED paths, because `..` is
    only visible after normalisation."""
    assert CitationEvidenceStore(str(root)).resolve(key) is None


def test_a_directory_is_not_a_file(root: Path) -> None:
    assert CitationEvidenceStore(str(root)).resolve("nested") is None


def test_the_store_degrades_to_none_when_no_root_is_configured() -> None:
    """Unconfigured is legitimate: the bot then captures nothing and `proof_url` stays
    honestly empty. It must degrade, never raise."""
    settings = Settings(_env_file=None, app_env="dev")  # type: ignore[call-arg]
    assert settings.citation_artifact_dir is None
    assert citation_evidence_store(settings) is None


def test_the_store_is_built_when_a_root_is_configured(tmp_path: Path) -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None, app_env="dev", citation_artifact_dir=str(tmp_path)
    )
    assert citation_evidence_store(settings) is not None
