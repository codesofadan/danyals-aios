"""The prompt registry and the task-tier table.

The registry's whole value is that any output can be traced back to the exact bytes that
produced it - so the tests that matter are about the HASH (stable, over the text only,
present on every prompt) and about failing loudly where a prompt is missing or malformed.
A registry that silently yields "" is worse than no registry: an empty system prompt does
not fail, it produces confident nonsense under whatever default the SDK applies, which is
precisely the incident ``integrations/llm.py`` records.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.platform.ai import prompts
from app.platform.ai.tiers import TIERS, TaskTier, judge_is_independent, spec_for

pytestmark = pytest.mark.unit


def _write(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


_VALID = """---
id: test/example
version: 3
task_tier: drafting
inputs: topic, tone
outputs: a paragraph
changelog: v3 - tightened the refusal clause
---
Write about {topic} in a {tone} register.
"""


# --------------------------------------------------------------------------- #
# The registry
# --------------------------------------------------------------------------- #
def test_a_prompt_carries_its_identity_and_a_hash_over_the_text_only(tmp_path: Path) -> None:
    """The hash must change when the INSTRUCTION changes and not when the metadata does.

    That asymmetry is what keeps a trace's ``prompt_sha`` a useful link months later: a
    changelog correction or a typo in ``outputs:`` should not break the connection
    between an article and the words that produced it.
    """
    _write(tmp_path, "example.v3.md", _VALID)
    registry = prompts.load(tmp_path, force=True)
    original = registry["test/example"]

    assert original.version == 3
    assert original.task_tier == "drafting"
    assert original.inputs == ("topic", "tone")
    assert original.trace_fields == {
        "prompt_id": "test/example", "prompt_version": 3, "prompt_sha": original.sha,
    }

    _write(tmp_path, "example.v3.md", _VALID.replace("v3 - tightened", "v3 - reworded"))
    assert prompts.load(tmp_path, force=True)["test/example"].sha == original.sha

    _write(tmp_path, "example.v3.md", _VALID.replace("{tone} register", "{tone} VOICE"))
    assert prompts.load(tmp_path, force=True)["test/example"].sha != original.sha


def test_render_fills_placeholders_and_names_the_prompt_when_one_is_missing(
    tmp_path: Path,
) -> None:
    """A missing value must be a KeyError at the call site, never a literal ``{topic}``
    shipped to the model and from there into a client's published article."""
    _write(tmp_path, "example.v3.md", _VALID)
    prompt = prompts.load(tmp_path, force=True)["test/example"]

    assert prompt.render(topic="drains", tone="plain") == "Write about drains in a plain register."

    with pytest.raises(KeyError) as caught:
        prompt.render(topic="drains")
    assert "test/example" in str(caught.value)
    assert "tone" in str(caught.value)


def test_an_unknown_prompt_id_raises_and_lists_what_does_exist(tmp_path: Path) -> None:
    _write(tmp_path, "example.v3.md", _VALID)
    prompts.load(tmp_path, force=True)

    with pytest.raises(prompts.PromptNotFoundError) as caught:
        prompts.get("test/does-not-exist")
    assert "test/example" in str(caught.value)


@pytest.mark.parametrize(
    ("body", "because"),
    [
        ("no frontmatter at all\n", "missing opening"),
        ("---\nid: x\nversion: 1\n", "never closed"),
        ("---\nid: x\nversion: 1\ntask_tier: bulk\n---\n\n", "body is empty"),
        ("---\nid: x\nversion: 1\n---\nbody\n", "missing"),
        ("---\nnot a key value line\n---\nbody\n", "not 'key: value'"),
    ],
)
def test_a_malformed_prompt_fails_the_load_rather_than_being_skipped(
    tmp_path: Path, body: str, because: str
) -> None:
    """A registry that quietly drops the one file that failed to parse hands a
    ``PromptNotFoundError`` to a worker at 3am for a file sitting right there in git."""
    _write(tmp_path, "broken.md", body)
    with pytest.raises(ValueError, match=because):
        prompts.load(tmp_path, force=True)


def test_two_files_claiming_one_id_fail_the_load(tmp_path: Path) -> None:
    _write(tmp_path, "a.md", _VALID)
    _write(tmp_path, "nested/b.md", _VALID)
    with pytest.raises(ValueError, match="duplicate prompt id"):
        prompts.load(tmp_path, force=True)


def test_the_shipped_prompts_all_parse_and_declare_a_real_tier() -> None:
    """The registry in the repo must be loadable and internally consistent.

    A prompt whose ``task_tier`` is not a real tier would fail only when something tried
    to route it, which is a deploy-time problem discovered at run time.
    """
    registry = prompts.load(force=True)
    assert registry, "the shipped prompt registry must not be empty"
    for prompt_id, prompt in registry.items():
        assert prompt.id == prompt_id
        assert TaskTier(prompt.task_tier) in TIERS
        assert prompt.sha and prompt.text.strip()


# --------------------------------------------------------------------------- #
# The tier table
# --------------------------------------------------------------------------- #
def test_every_tier_has_a_spec_and_an_unknown_one_raises() -> None:
    """An unknown tier must not default. A cheap default silently downgrades work that
    asked for reasoning; an expensive one silently multiplies a bulk job's bill."""
    for tier in TaskTier:
        assert spec_for(tier).model
    with pytest.raises(KeyError):
        spec_for("cheap-please")


def test_the_judge_tier_is_never_configured_like_the_generator_it_grades() -> None:
    """§8's judge-independence rule, asserted rather than left as a comment."""
    assert judge_is_independent(TaskTier.DRAFTING, TaskTier.JUDGE)
    assert judge_is_independent(TaskTier.BULK, TaskTier.JUDGE)
    assert not judge_is_independent(TaskTier.JUDGE, TaskTier.JUDGE)


def test_model_ids_carry_no_date_suffix_and_the_thinking_tiers_are_the_deep_ones() -> None:
    """06-AI-STACK.md §3 writes the ids undated and reserves adaptive thinking for the
    two tiers whose depth is the point."""
    for spec in TIERS.values():
        assert not any(part.isdigit() and len(part) == 8 for part in spec.model.split("-"))
    assert TIERS[TaskTier.REASONING].adaptive_thinking
    assert TIERS[TaskTier.JUDGE].adaptive_thinking
    assert not TIERS[TaskTier.BULK].adaptive_thinking
    assert TIERS[TaskTier.BULK].effort is None
