"""One decorator binds one check id to one function.

Before this module a check ran if and only if its id appeared as a hardcoded
string literal inside one of ten ``iter_*`` generators. The ``analyzer:`` field
in the checklist looked like a dispatch table but nothing read it, which is how
238 declarations drifted from reality without anything failing.

Registration is validated at IMPORT time against the checklist, so four classes
of defect become impossible to merge rather than merely tested for:

* an id no checklist row defines
* the same id registered twice (six ids used to emit twice per run)
* Python computing a check the checklist marks ``ai-assisted`` - the Wave A
  defect, where an agent and a heuristic each scored the same check
* a scope that does not match the data the check declares it needs

The taxonomy - name, pillar, subcategory, owner, default severity - is NEVER
passed to the decorator. It comes from the checklist, so an analyzer cannot
contradict its own definition. That is the whole point.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from audit_engine.checklist import CheckSpec, load_registry

Scope = Literal["page", "page_http", "site_parsed", "site_crawled", "psi", "rollup"]

SCOPES: frozenset[str] = frozenset(
    {"page", "page_http", "site_parsed", "site_crawled", "psi", "rollup"}
)

#: What each scope receives, for error messages and documentation.
SCOPE_INPUT: dict[str, str] = {
    "page": "ParsedHTML - one parsed page",
    "page_http": "CrawledPage - one page with its HTTP response",
    "site_parsed": "list[ParsedHTML] - every parsed page",
    "site_crawled": "CrawlContext - the crawl graph",
    "psi": "PsiResult - one PageSpeed Insights response",
    "rollup": "RollupContext - findings from other checks",
}


class RegistrationError(RuntimeError):
    """Raised at import time. A bad registration must never reach a run."""


@dataclass(frozen=True)
class Registration:
    """One check, bound to one callable."""

    check_id: str
    scope: str
    func: Callable[..., Any]
    is_async: bool
    #: Real dotted path of the implementation. A test asserts this equals the
    #: checklist's ``analyzer:`` field, which makes that field true at last.
    dotted_path: str
    #: For rollups: the check ids this one aggregates, and how many must have
    #: run before its output means anything. See the ``inputs_ran`` gate.
    inputs: tuple[str, ...] = ()
    min_inputs_ran: int = 0

    @property
    def spec(self) -> CheckSpec:
        return load_registry()[self.check_id]


_REGISTRY: dict[str, Registration] = {}


def _dotted_path(func: Callable[..., Any]) -> str:
    return f"{func.__module__}.{func.__qualname__}"


def check(
    check_id: str,
    *,
    scope: Scope,
    inputs: tuple[str, ...] = (),
    min_inputs_ran: int = 0,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Bind ``check_id`` to the decorated function.

    Everything except the id and the scope comes from the checklist.
    """

    def decorate(func: Callable[..., Any]) -> Callable[..., Any]:
        specs = load_registry()
        where = _dotted_path(func)

        if scope not in SCOPES:
            raise RegistrationError(
                f"{where} declares scope {scope!r}; valid scopes are {sorted(SCOPES)}"
            )
        spec = specs.get(check_id)
        if spec is None:
            raise RegistrationError(
                f"{where} registers {check_id!r}, which no checklist row defines"
            )
        if spec.automation != "full":
            raise RegistrationError(
                f"{where} registers {check_id!r}, but the checklist marks it "
                f"{spec.automation!r}. An agent already scores it; two verdicts "
                f"for one check is the Wave A defect. Demote the checklist row "
                f"to 'full' or delete this analyzer."
            )
        existing = _REGISTRY.get(check_id)
        if existing is not None:
            raise RegistrationError(
                f"{check_id} is already registered by {existing.dotted_path}; "
                f"{where} would emit it a second time in the same run"
            )
        if scope == "rollup" and not inputs:
            raise RegistrationError(
                f"{where} registers rollup {check_id!r} with no declared inputs. "
                f"A rollup with no provenance can publish a score over no data."
            )
        if inputs and scope != "rollup":
            raise RegistrationError(
                f"{where} declares inputs but scope is {scope!r}, not 'rollup'"
            )
        unknown = [i for i in inputs if i not in specs]
        if unknown:
            raise RegistrationError(f"{where} declares unknown inputs {unknown}")
        if min_inputs_ran > len(inputs):
            raise RegistrationError(
                f"{where} needs {min_inputs_ran} inputs but declares only {len(inputs)}"
            )

        _REGISTRY[check_id] = Registration(
            check_id=check_id,
            scope=scope,
            func=func,
            is_async=inspect.iscoroutinefunction(func),
            dotted_path=where,
            inputs=tuple(inputs),
            min_inputs_ran=min_inputs_ran,
        )
        return func

    return decorate


def rollup(
    check_id: str, *, inputs: tuple[str, ...], min_inputs_ran: int = 1
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """A check computed over other checks. Always declares its provenance."""
    return check(check_id, scope="rollup", inputs=inputs, min_inputs_ran=min_inputs_ran)


def registered() -> dict[str, Registration]:
    """Every registration, by check id. The dispatcher's only input."""
    return dict(_REGISTRY)


def for_scope(scope: str) -> list[Registration]:
    return [r for r in _REGISTRY.values() if r.scope == scope]


def clear_registry_for_tests() -> None:
    """Only tests may empty the registry."""
    _REGISTRY.clear()


def restore_registry_for_tests(snapshot: dict[str, Registration]) -> None:
    """Put back a snapshot taken with :func:`registered`.

    A test that clears the registry and does not restore it silently empties it
    for every test that runs afterwards, so real registrations appear to have
    vanished. Always pair this with clear_registry_for_tests.
    """
    _REGISTRY.clear()
    _REGISTRY.update(snapshot)
