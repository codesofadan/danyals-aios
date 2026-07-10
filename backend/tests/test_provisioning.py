"""P2-3 gate: provision_user creates auth user + users row + template grants."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.services.provisioning import provision_user


class _Exec:
    def __init__(self, data: Any) -> None:
        self.data = data


class _Table:
    def __init__(self, store: dict[str, list[dict[str, Any]]], name: str) -> None:
        self._store = store
        self._name = name
        self._select = False
        self._filter: tuple[str, str] | None = None

    def insert(self, rows: Any) -> _Table:
        items = rows if isinstance(rows, list) else [rows]
        self._store.setdefault(self._name, []).extend(items)
        return self

    def select(self, *_cols: str) -> _Table:
        self._select = True
        return self

    def eq(self, key: str, value: str) -> _Table:
        self._filter = (key, str(value))
        return self

    def limit(self, _n: int) -> _Table:
        return self

    def order(self, _key: str) -> _Table:
        return self

    def execute(self) -> _Exec:
        if not self._select:
            return _Exec(None)
        data = self._store.get(self._name, [])
        if self._filter:
            key, value = self._filter
            data = [r for r in data if str(r.get(key)) == value]
        return _Exec(list(data))


class _AuthAdmin:
    def create_user(self, params: dict[str, Any]) -> SimpleNamespace:
        return SimpleNamespace(user=SimpleNamespace(id="uid-123", email=params["email"]))


class _FakeAdmin:
    def __init__(self) -> None:
        self.store: dict[str, list[dict[str, Any]]] = {}
        self.auth = SimpleNamespace(admin=_AuthAdmin())

    def table(self, name: str) -> _Table:
        return _Table(self.store, name)


@pytest.mark.unit
def test_provision_creates_row_and_template_grants() -> None:
    admin = _FakeAdmin()
    row = provision_user(
        admin,  # type: ignore[arg-type]
        email="jane@x.com",
        password="secret12",
        name="Jane Doe",
        role="specialist",
        template_key="seo",
    )
    assert row["id"] == "uid-123"
    assert row["role"] == "specialist"
    assert row["status"] == "invited"
    grants = admin.store["user_feature_grants"]
    assert len(grants) == 13  # SEO Specialist template grant count
    assert all(g["level"] == "full" and g["user_id"] == "uid-123" for g in grants)


@pytest.mark.unit
def test_provision_without_template_seeds_no_grants() -> None:
    admin = _FakeAdmin()
    provision_user(
        admin,  # type: ignore[arg-type]
        email="v@x.com",
        password="secret12",
        name="Vic",
        role="viewer",
        template_key=None,
    )
    assert "user_feature_grants" not in admin.store


@pytest.mark.unit
def test_provision_super_template_grants_all_features() -> None:
    admin = _FakeAdmin()
    provision_user(
        admin,  # type: ignore[arg-type]
        email="boss@x.com",
        password="secret12",
        name="The Boss",
        role="owner",
        template_key="super",
    )
    assert len(admin.store["user_feature_grants"]) == 17
