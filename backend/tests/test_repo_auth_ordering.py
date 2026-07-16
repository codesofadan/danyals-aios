"""Regression guard: every RLS repo factory must depend on ``get_current_user``.

Each repo factory reads the caller's token from ``request.state.access_token``,
which is populated ONLY as a side effect of ``get_current_user``. If a factory
does not itself depend on auth, FastAPI is free to resolve it BEFORE the auth
dependency (sibling deps resolve in signature order), so the token is still the
empty string -> ``client_for_user("")`` -> PostgREST ``PGRST301 "Empty JWT"`` ->
a masked HTTP 500. That was a real production bug on ~34 routes.

This test inspects each factory's dependency graph directly (independent of any
route's parameter order) and asserts ``get_current_user`` is a transitive
sub-dependency. It fails on the pre-fix code and passes on the fixed code.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.dependencies.models import Dependant
from fastapi.dependencies.utils import get_dependant

from app.core.auth import get_current_user
from app.db.activity_repo import get_activity_repo
from app.db.audits_repo import get_audits_repo
from app.db.clients_repo import get_clients_repo
from app.db.cost_repo import get_cost_repo
from app.db.portal_repo import get_portal_repo
from app.db.tasks_repo import get_tasks_repo
from app.db.tiers_repo import get_tiers_repo
from app.db.vault_repo import get_vault_repo

pytestmark = pytest.mark.unit

_FACTORIES = [
    get_clients_repo,
    get_tasks_repo,
    get_cost_repo,
    get_audits_repo,
    get_vault_repo,
    get_tiers_repo,
    get_activity_repo,
    get_portal_repo,
]


def _iter_deps(dependant: Dependant) -> Iterator[Dependant]:
    """Yield ``dependant`` and every transitive sub-dependency."""
    yield dependant
    for sub in dependant.dependencies:
        yield from _iter_deps(sub)


@pytest.mark.parametrize("factory", _FACTORIES, ids=lambda f: f.__name__)
def test_repo_factory_depends_on_auth(factory: object) -> None:
    dependant = get_dependant(path="/", call=factory)
    calls = [d.call for d in _iter_deps(dependant)]
    assert get_current_user in calls, (
        f"{factory.__name__} must depend (transitively) on get_current_user so "
        "request.state.access_token is set before the factory reads it"
    )
