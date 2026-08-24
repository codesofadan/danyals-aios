"""Locate the SEO-CONTENT-OS doctrine corpus at runtime.

One resolver, used by every module that reads the corpus - the vocabulary blocklist
today, the doctrine chunk index in P1B.

The path must work in BOTH shapes and they differ:

  * source checkout - ``backend/app/services/...`` next to ``backend/seo-content-os/``
  * installed wheel - ``site-packages/app/services/...`` next to
    ``site-packages/seo-content-os/``, because ``pyproject.toml`` force-includes the
    corpus beside the ``app`` package.

``Path(app.__file__).parents[1]`` lands on ``backend/`` and on ``site-packages/``
respectively, so the same expression resolves in both. That is the whole reason the
force-include target is a sibling of ``app`` rather than nested inside it.

This matters more than it looks: the app runs from the installed venv (the Dockerfile
COPYies only db/migrations and the audit engine into the runtime stage), so a corpus
that resolves only in a checkout would pass every test and raise FileNotFoundError
inside the Celery worker on a real client's job.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

import app

_CORPUS_DIRNAME = "seo-content-os"


class DoctrineCorpusMissingError(RuntimeError):
    """The corpus is not on disk. Names the likely cause rather than just the path."""


@cache
def corpus_root() -> Path:
    """Absolute path to the doctrine corpus. Raises if it is not there.

    Cached: this resolves once per process and the answer cannot change at runtime.
    """
    root = Path(app.__file__).resolve().parents[1] / _CORPUS_DIRNAME
    if not root.is_dir():
        raise DoctrineCorpusMissingError(
            f"doctrine corpus not found at {root}. In a source checkout it lives at "
            "backend/seo-content-os/; in a built image it is force-included beside the "
            "`app` package by [tool.hatch.build.targets.wheel.force-include]. A missing "
            "corpus here means the build dropped it."
        )
    return root


def corpus_file(*parts: str) -> Path:
    """Resolve one file inside the corpus, e.g. ``corpus_file("knowledge", "x.md")``."""
    target = corpus_root().joinpath(*parts)
    if not target.is_file():
        raise DoctrineCorpusMissingError(f"doctrine file not found: {target}")
    return target
