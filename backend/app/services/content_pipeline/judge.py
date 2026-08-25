"""ClaudeJudge - the LLM half of the QA gate, which has never once run (P3, stage 11).

`content_qa` was built with a `Judge` seam and five dimensions that use it: originality,
intent_match, eeat_experience, information_gain, cta_ux. In every real run `judge` is
None, so all five silently fall back to conservative deterministic proxies - and the
scorecard reports a number that looks like a judgment and is a heuristic. Three of those
five are HARD GATE dimensions.

ONE CALL, FIVE VERDICTS. The five differ only in their rubric; the draft is identical
across all of them. Asking five times would send the same page five times and bill for
it five times. So the first `assess` scores everything and the remaining four are served
from cache.

FAILING SAFE. If the reply cannot be parsed, this raises rather than returning a score.
That direction is deliberate: `score(judge=None)` degrades to documented proxies and
says so, whereas a judge that invents 85 when its own output was unreadable produces a
page that passed QA because the QA broke. The gate stage catches the raise and re-scores
deterministically, with a note saying the judged dimensions are proxies.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.services.content_pipeline.draft import THINKING_ALLOWANCE
from app.services.content_pipeline.writer import DoctrineWriter, WriteAccounting
from app.services.content_qa import JudgeVerdict

STAGE = "gate"

# The dimensions `content_qa.score` routes through the judge seam. Pinned by a test
# against content_qa itself - if a sixth is added there, the batch must learn about it
# or that dimension silently keeps using its proxy.
JUDGED_DIMENSIONS: tuple[str, ...] = (
    "originality",
    "intent_match",
    "eeat_experience",
    "information_gain",
    "cta_ux",
)

# Mirrors the rubric text at each `content_qa` call site. Duplicated deliberately: the
# batch has to state all five rubrics in one prompt, and it only learns a caller's
# wording for the dimension it is asked about FIRST. A caller's own `criteria` still
# wins for that dimension - see `assess`.
DEFAULT_CRITERIA: dict[str, str] = {
    "originality": (
        "Originality / anti-scaled-content-abuse: is this materially original, worth "
        "publishing even if search did not exist, and not spun boilerplate?"
    ),
    "intent_match": "Does the page's structure and format match the search intent?",
    "eeat_experience": (
        "E-E-A-T with first-hand Experience as the key signal: real projects, results, "
        "credentials, testimonials, and trust signals."
    ),
    "information_gain": (
        "Information gain: does the page add a real, provenance-backed differentiation "
        "angle beyond rehashing the top-10?"
    ),
    "cta_ux": (
        "CTA / UX: is there a clear, well-placed call to action and a scannable, "
        "people-first layout?"
    ),
}

MAX_TOKENS = THINKING_ALLOWANCE + 3_000


class JudgeUnavailableError(RuntimeError):
    """The judge could not produce a usable verdict. Callers degrade to proxies."""


def _prompt(draft: str, criteria: dict[str, str], context: dict[str, str]) -> str:
    lines = [
        "Score this page on each dimension below, 0-100. You are the last reviewer "
        "before it goes on a paying client's live site.",
        "",
        "Score honestly and independently per dimension. A page can be well written and "
        "still score low on Experience: those are different questions. Do not let one "
        "strong dimension lift the others, and do not converge everything on 80.",
        "",
        "Anchors, so the numbers mean the same thing every time:",
        "  90-100  publishable as-is; a specialist would be glad to have written it",
        "  70-89   sound, with specific fixable gaps",
        "  50-69   real problems a reader would notice",
        "  0-49    would embarrass the agency",
        "",
        "Dimensions:",
    ]
    for dim in JUDGED_DIMENSIONS:
        lines.append(f"  - {dim}: {criteria.get(dim) or DEFAULT_CRITERIA[dim]}")
        if context.get(dim):
            lines.append(f"      known context: {context[dim]}")
    lines += [
        "",
        "The rationale is read by a human deciding whether to publish, so quote the "
        "page rather than describing it. 'Generic' is not a rationale; 'the three "
        "H2s all open with the same construction' is.",
        "",
        "Return ONLY JSON, no prose around it:",
        '{"' + JUDGED_DIMENSIONS[0] + '": {"score": 0, "rationale": "..."}, ...}',
        "with one entry for every dimension listed above.",
        "",
        "--- THE PAGE ---",
        draft,
    ]
    return "\n".join(lines)


def _parse(raw: str) -> dict[str, JudgeVerdict]:
    match = re.search(r"\{.*\}", raw, re.S)
    if not match:
        raise JudgeUnavailableError("the judge reply contained no JSON object")
    try:
        obj: Any = json.loads(match.group(0))
    except (ValueError, TypeError) as exc:
        raise JudgeUnavailableError(f"the judge reply was not valid JSON ({exc})") from exc
    if not isinstance(obj, dict):
        raise JudgeUnavailableError("the judge reply was not a JSON object")

    out: dict[str, JudgeVerdict] = {}
    for dim in JUDGED_DIMENSIONS:
        entry = obj.get(dim)
        if isinstance(entry, dict):
            raw_score, rationale = entry.get("score"), entry.get("rationale", "")
        else:
            raw_score, rationale = entry, ""
        if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
            continue
        out[dim] = JudgeVerdict(
            score=max(0, min(100, int(raw_score))),
            rationale=str(rationale or "").strip(),
        )
    if not out:
        raise JudgeUnavailableError("the judge returned no scorable dimension")
    return out


class ClaudeJudge:
    """A `content_qa.Judge` that scores every judged dimension in one call."""

    def __init__(
        self,
        writer: DoctrineWriter,
        *,
        page_type: str = "service",
        vertical: str | None = None,
        framework: str | None = None,
        model: str | None = None,
        accounting: WriteAccounting | None = None,
    ) -> None:
        self._writer = writer
        self._page_type = page_type
        self._vertical = vertical
        self._framework = framework
        self._model = model
        self.accounting = accounting or WriteAccounting()
        self._verdicts: dict[str, JudgeVerdict] = {}
        self._criteria: dict[str, str] = {}
        self._context: dict[str, str] = {}
        self._ran = False

    def assess(
        self, dimension: str, *, draft: str, criteria: str, context: str = ""
    ) -> JudgeVerdict:
        """Score one dimension, running the single batched call on first use."""
        # The caller's own wording wins for whichever dimension it asks about first;
        # the rest fall back to the mirrored rubrics above.
        if criteria:
            self._criteria.setdefault(dimension, criteria)
        if context:
            self._context.setdefault(dimension, context)

        if not self._ran:
            self._ran = True
            self._verdicts = self._run(draft)

        verdict = self._verdicts.get(dimension)
        if verdict is None:
            raise JudgeUnavailableError(f"the judge returned no verdict for {dimension!r}")
        return verdict

    def _run(self, draft: str) -> dict[str, JudgeVerdict]:
        try:
            raw = self._writer.write(
                STAGE, _prompt(draft, self._criteria, self._context),
                page_type=self._page_type, vertical=self._vertical,
                framework=self._framework, max_tokens=MAX_TOKENS,
                expected_calls=1, model=self._model, accounting=self.accounting,
            )
        except JudgeUnavailableError:
            raise
        except Exception as exc:
            raise JudgeUnavailableError(f"the judge call failed ({type(exc).__name__})") from exc
        return _parse(raw)
