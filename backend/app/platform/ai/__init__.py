"""``app.platform.ai`` - the model router, the graph runtime, tracing and prompts.

``06-AI-STACK.md`` in one package. The shape it enforces::

    job (durable, app/jobs)
      └── graph (LangGraph, checkpointed to Postgres)          graph.py
            └── node
                  └── ModelRouter.complete(...)                router.py
                        ├── tier -> model                      tiers.py
                        ├── versioned, hashed prompt           prompts.py
                        └── LangSmith span + cost commit       tracing.py

Import from the submodules rather than from here: the names below are re-exported for
convenience, but every one of them is lazy-import-sensitive in at least one direction
(``graph`` needs the optional ``[graph]`` extra, ``router`` pulls the config + cost
gate), and a caller that imports precisely says what it depends on.
"""

from __future__ import annotations

from app.platform.ai.tiers import TIERS, TaskTier, TierSpec, judge_is_independent, spec_for

__all__ = [
    "TIERS",
    "TaskTier",
    "TierSpec",
    "judge_is_independent",
    "spec_for",
]
