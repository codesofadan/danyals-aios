"""The prompt registry: prompts are CODE, versioned in the repo and hashed into traces.

``06-AI-STACK.md`` §7. Two properties do the work:

**Versioned on disk, not inline and not in a table.** An inline prompt cannot be
diffed in a PR, cannot be reviewed by anyone who is not reading that service, and
cannot be pinned to an output after the fact. A prompt in a database row is worse:
it changes under a running system with no review and no history. Both failure modes
are live in this repo today - ``content_generator`` and ``web2_pipeline`` phrase their
contracts in string literals scattered across 1,000-line modules.

**Hashed, and the hash rides in the trace.** This is the whole point. Given any output
that came out wrong, the span carries ``prompt_id``, ``prompt_version`` and
``prompt_sha`` - so the exact bytes that produced it are recoverable from git, even
months later, even after three revisions. Without the hash, "which prompt wrote this?"
is answered by guessing at a date.

FORMAT. A prompt is a Markdown file with a minimal frontmatter block::

    ---
    id: web2/post_body
    version: 1
    task_tier: drafting
    inputs: platform, topic, anchor, target_url, brief
    outputs: markdown article body
    changelog: v1 initial - platform-shaped Web 2.0 post body
    ---
    <the prompt text>

The frontmatter is parsed by the tiny reader below rather than by PyYAML, deliberately:
``pyyaml`` is not a declared dependency of the base image (it arrives only as a
transitive of the optional ``[graph]`` extra), and the registry must load in the core
install where the router still needs it. The format is flat ``key: value`` - no nesting,
no anchors, no tags - so a hand-rolled reader is not a liability here, it is the
narrower contract.

LOADED ONCE, AT FIRST USE, THEN FROZEN. A prompt that could change under a running
process would break the guarantee the hash exists to provide.
"""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from app.logging_setup import get_logger

logger = get_logger("platform.ai.prompts")

#: Where the prompt files live. A package-relative path so it travels with the code
#: into the Docker image without a settings entry to get wrong.
PROMPT_ROOT: Final[Path] = Path(__file__).parent / "prompts"

_FRONTMATTER_FENCE: Final = "---"


class PromptNotFoundError(KeyError):
    """A prompt id was requested that no file declares.

    A hard failure rather than an empty string: a model call with an empty system prompt
    does not fail, it produces confident nonsense under whatever default the SDK applies
    - which is exactly the incident recorded in ``integrations/llm.py``'s
    ``_COMPACTION_SYSTEM_PROMPT`` header, where every article ever drafted was written
    under a summarisation contract because a ``system=`` was silently omitted.
    """


@dataclass(frozen=True)
class Prompt:
    """One versioned prompt: its text, its identity, and its hash.

    ``sha`` is over the TEXT ONLY, not the frontmatter - so a changelog edit does not
    invalidate the link between a trace and the bytes that produced its output, while
    any change to the instruction itself does.
    """

    id: str
    version: int
    task_tier: str
    text: str
    sha: str
    inputs: tuple[str, ...] = ()
    outputs: str = ""
    changelog: str = ""
    path: str = ""

    def render(self, **values: Any) -> str:
        """Fill the prompt's ``{placeholders}`` from ``values``.

        ``str.format_map`` over a dict that raises on a missing key, so a prompt that
        references ``{topic}`` and a caller that forgot to pass one is a KeyError at the
        call site - not a literal ``{topic}`` shipped to the model and then into a
        client's article.
        """
        return self.text.format_map(_StrictMap(values, self.id))

    @property
    def trace_fields(self) -> dict[str, Any]:
        """The identity fields §7 requires on every span that used this prompt."""
        return {"prompt_id": self.id, "prompt_version": self.version, "prompt_sha": self.sha}


class _StrictMap(dict[str, Any]):
    """A format mapping that names the prompt when a placeholder has no value."""

    def __init__(self, values: dict[str, Any], prompt_id: str) -> None:
        super().__init__(values)
        self._prompt_id = prompt_id

    def __missing__(self, key: str) -> Any:
        raise KeyError(
            f"prompt {self._prompt_id!r} references {{{key}}} but no value was supplied"
        )


_registry: dict[str, Prompt] = {}
_loaded = False
_lock = threading.Lock()


def _parse(path: Path) -> Prompt:
    """Read one prompt file into a :class:`Prompt`, or raise ValueError naming the file."""
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_FENCE:
        raise ValueError(f"{path}: missing opening '---' frontmatter fence")
    try:
        close = next(i for i, line in enumerate(lines[1:], start=1)
                     if line.strip() == _FRONTMATTER_FENCE)
    except StopIteration as exc:
        raise ValueError(f"{path}: frontmatter is never closed with '---'") from exc

    meta: dict[str, str] = {}
    for line in lines[1:close]:
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise ValueError(f"{path}: frontmatter line is not 'key: value': {line!r}")
        meta[key.strip()] = value.strip()

    text = "\n".join(lines[close + 1:]).strip()
    if not text:
        raise ValueError(f"{path}: prompt body is empty")
    missing = {"id", "version", "task_tier"} - meta.keys()
    if missing:
        raise ValueError(f"{path}: frontmatter is missing {sorted(missing)}")

    return Prompt(
        id=meta["id"],
        version=int(meta["version"]),
        task_tier=meta["task_tier"],
        text=text,
        sha=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
        inputs=tuple(part.strip() for part in meta.get("inputs", "").split(",") if part.strip()),
        outputs=meta.get("outputs", ""),
        changelog=meta.get("changelog", ""),
        path=str(path.relative_to(PROMPT_ROOT)) if path.is_relative_to(PROMPT_ROOT) else str(path),
    )


def load(root: Path | None = None, *, force: bool = False) -> dict[str, Prompt]:
    """Load every ``*.md`` under the prompt root. Idempotent; thread-safe.

    A malformed prompt file is a STARTUP failure, not a skipped file. A registry that
    quietly drops the one prompt that failed to parse is a registry that hands
    :class:`PromptNotFoundError` to a worker at 3am for a file that is sitting right
    there in the repo.
    """
    global _loaded
    with _lock:
        if _loaded and not force:
            return dict(_registry)
        base = root or PROMPT_ROOT
        found: dict[str, Prompt] = {}
        if base.is_dir():
            for path in sorted(base.rglob("*.md")):
                prompt = _parse(path)
                if prompt.id in found:
                    raise ValueError(
                        f"duplicate prompt id {prompt.id!r}: {found[prompt.id].path} and "
                        f"{prompt.path}"
                    )
                found[prompt.id] = prompt
        _registry.clear()
        _registry.update(found)
        _loaded = True
        logger.info("prompts_loaded", count=len(found), root=str(base))
        return dict(_registry)


def get(prompt_id: str) -> Prompt:
    """The prompt registered under ``prompt_id``, loading the registry on first use."""
    if not _loaded:
        load()
    try:
        return _registry[prompt_id]
    except KeyError as exc:
        known = ", ".join(sorted(_registry)) or "(registry is empty)"
        raise PromptNotFoundError(
            f"no prompt {prompt_id!r} in {PROMPT_ROOT}; known ids: {known}"
        ) from exc


def all_prompts() -> dict[str, Prompt]:
    """Every registered prompt - for the CI check and the eval harness."""
    if not _loaded:
        load()
    return dict(_registry)
