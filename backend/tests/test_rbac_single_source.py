"""The gate that makes ``app.rbac.matrix`` the ONLY copy of the access model.

WHY THIS FILE EXISTS
--------------------
On 2026-08-24 a field-by-field comparison of ``app/rbac/matrix.py`` against
``frontend/lib/data.ts`` found **fourteen** differences: nine colours (the backend
still carried the pre-Avant-Garde palette), the ``client_setup`` icon, and four
descriptions where an em dash had become a hyphen. The drift had landed entirely in
presentation - the permission keys, the 8x6 grant matrix, the feature keys and the
template grants all still agreed - so nothing was broken. That is the warning, not
the reassurance.

It survived because **nothing compared the two files**:

* ``test_rbac_matrix.py`` said it "pins the reference data to ``frontend/lib/data.ts``"
  and then re-typed the expected values as Python literals. It tested Python against
  Python and never opened the TS file.
* ``test_contract_lock.py`` does read the TS, but compares field NAMES only - and
  listed none of the four RBAC models anyway.

Three hand-written copies of one access matrix, and no comparison between any two.

WHAT THIS GATE ASSERTS
----------------------
The backend is the single source of truth, served over ``GET /rbac/*``. So:

1. **While** ``data.ts`` still declares a catalogue symbol (during the handover to
   the API-backed frontend), every value it declares must EQUAL the backend's, for
   every field the backend owns.
2. **Once** the frontend consumes ``/rbac/*`` and the declaration is deleted, there
   is nothing left to compare and the check reduces to its structural form: the
   dashboard must not reintroduce a copy that disagrees.

So the gate is green before, during and after the handover, and permits a drifting
copy at no point in between.

3. ``color`` must never come back to the backend. It is a theme token with no Python
   reader, and it was where nine of the fourteen drifts lived.

NON-VACUITY
-----------
A guard that cannot see is worse than no guard, because it reports safety. This file
therefore tests its own parser against a fixture carrying a KNOWN injected drift
(:func:`test_the_comparison_detects_a_drift_it_is_shown`), and hard-fails if a symbol
is present in the TS but unreadable - it never silently skips what it cannot parse.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.rbac import matrix as m
from app.schemas.identity import to_team_role

# backend/tests/ -> backend/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATA_TS = _REPO_ROOT / "frontend" / "lib" / "data.ts"

# The catalogue symbols the backend owns. A symbol the dashboard no longer declares
# is the GOAL state, not a failure.
_CATALOGUE_SYMBOLS = (
    "ROLE_ORDER",
    "ROLE_META",
    "permissions",
    "defaultRolePerms",
    "accessFeatures",
    "roleTemplates",
)

# Declarations the parser must resolve first, because later symbols reference them.
_PARSE_ORDER = ("SERIES", *_CATALOGUE_SYMBOLS[:5], "ALL_KEYS", *_CATALOGUE_SYMBOLS[5:])


class _Unresolved:
    """A TS expression the parser read but could not evaluate (e.g. a theme token).

    Kept as a distinct value rather than ``None`` so a field that is genuinely absent
    can never be confused with one the parser gave up on.
    """

    __slots__ = ("expr",)

    def __init__(self, expr: str) -> None:
        self.expr = expr

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<unresolved {self.expr}>"


class _JsLiteralParser:
    """A small recursive-descent reader for the JS literal subset ``data.ts`` uses.

    Deliberately not a general JS parser, and deliberately not a regex: it raises on
    anything it does not understand rather than returning a partial answer, because a
    parser that degrades quietly is how the drift got here in the first place.

    Understands: strings, numbers, booleans, ``null``, arrays, objects (quoted or bare
    keys), trailing commas, line and block comments, identifiers resolved against
    ``env``, member access (``SERIES.c1``), and the single call form
    ``<ident>.map((x) => x.<prop>)``.
    """

    def __init__(self, src: str, env: dict[str, Any]) -> None:
        self.s = src
        self.i = 0
        self.env = env

    # --- lexing helpers ---------------------------------------------------
    def _skip(self) -> None:
        while self.i < len(self.s):
            c = self.s[self.i]
            if c in " \t\r\n":
                self.i += 1
            elif self.s.startswith("//", self.i):
                nl = self.s.find("\n", self.i)
                self.i = len(self.s) if nl == -1 else nl + 1
            elif self.s.startswith("/*", self.i):
                end = self.s.find("*/", self.i)
                if end == -1:
                    raise ValueError("unterminated block comment")
                self.i = end + 2
            else:
                return

    def _expect(self, ch: str) -> None:
        self._skip()
        if self.i >= len(self.s) or self.s[self.i] != ch:
            raise ValueError(f"expected {ch!r} at offset {self.i}, found {self.s[self.i:self.i + 20]!r}")
        self.i += 1

    # --- values -----------------------------------------------------------
    def value(self) -> Any:
        self._skip()
        if self.i >= len(self.s):
            raise ValueError("unexpected end of input")
        c = self.s[self.i]
        if c in "\"'`":
            return self.string()
        if c == "[":
            return self.array()
        if c == "{":
            return self.obj()
        if c == "-" or c.isdigit():
            return self.number()
        if c.isalpha() or c == "_" or c == "$":
            return self.identifier_expr()
        raise ValueError(f"unparseable value at offset {self.i}: {self.s[self.i:self.i + 30]!r}")

    def string(self) -> str:
        quote = self.s[self.i]
        self.i += 1
        out: list[str] = []
        while True:
            if self.i >= len(self.s):
                raise ValueError("unterminated string")
            c = self.s[self.i]
            if c == "\\":
                nxt = self.s[self.i + 1]
                if nxt == "u":  # \uXXXX - an em dash arrives this way from any JSON emitter
                    out.append(chr(int(self.s[self.i + 2 : self.i + 6], 16)))
                    self.i += 6
                    continue
                out.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
                self.i += 2
                continue
            if c == quote:
                self.i += 1
                return "".join(out)
            out.append(c)
            self.i += 1

    def number(self) -> float | int:
        mt = re.compile(r"-?\d+(\.\d+)?([eE][+-]?\d+)?").match(self.s, self.i)
        if mt is None:
            raise ValueError(f"bad number at offset {self.i}")
        self.i = mt.end()
        txt = mt.group(0)
        return float(txt) if any(ch in txt for ch in ".eE") else int(txt)

    def array(self) -> list[Any]:
        self._expect("[")
        out: list[Any] = []
        while True:
            self._skip()
            if self.s[self.i] == "]":
                self.i += 1
                return out
            out.append(self.value())
            self._skip()
            if self.s[self.i] == ",":
                self.i += 1
            elif self.s[self.i] != "]":
                raise ValueError(f"expected ',' or ']' at offset {self.i}")

    def obj(self) -> dict[str, Any]:
        self._expect("{")
        out: dict[str, Any] = {}
        while True:
            self._skip()
            if self.s[self.i] == "}":
                self.i += 1
                return out
            key = self.string() if self.s[self.i] in "\"'" else self._bare_key()
            self._expect(":")
            out[key] = self.value()
            self._skip()
            if self.s[self.i] == ",":
                self.i += 1
            elif self.s[self.i] != "}":
                raise ValueError(f"expected ',' or '}}' at offset {self.i}")

    def _bare_key(self) -> str:
        mt = re.compile(r"[A-Za-z_$][\w$]*").match(self.s, self.i)
        if mt is None:
            raise ValueError(f"bad object key at offset {self.i}")
        self.i = mt.end()
        return mt.group(0)

    def identifier_expr(self) -> Any:
        mt = re.compile(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*").match(self.s, self.i)
        if mt is None:
            raise ValueError(f"bad identifier at offset {self.i}")
        path = mt.group(0)
        self.i = mt.end()

        if path in ("true", "false"):
            return path == "true"
        if path == "null":
            return None

        self._skip()
        # The one call form we support: `<base>.map((x) => x.<prop>)`
        if self.i < len(self.s) and self.s[self.i] == "(" and path.endswith(".map"):
            depth, start = 0, self.i
            while self.i < len(self.s):
                if self.s[self.i] == "(":
                    depth += 1
                elif self.s[self.i] == ")":
                    depth -= 1
                    if depth == 0:
                        self.i += 1
                        break
                self.i += 1
            inner = self.s[start:self.i]
            pm = re.search(r"=>\s*\w+\.(\w+)", inner)
            base = self.env.get(path[: -len(".map")])
            if pm is None or not isinstance(base, list):
                raise ValueError(f"cannot evaluate {path}{inner}")
            return [item[pm.group(1)] for item in base]

        head, *rest = path.split(".")
        if head not in self.env:
            return _Unresolved(path)
        cur: Any = self.env[head]
        for part in rest:
            if not isinstance(cur, dict) or part not in cur:
                return _Unresolved(path)
            cur = cur[part]
        return cur


def _declared(src: str, name: str) -> bool:
    """Whether ``src`` declares ``const <name>`` at all."""
    return re.search(rf"\bconst\s+{re.escape(name)}\b", src) is not None


def _extract(src: str, names: tuple[str, ...] = _PARSE_ORDER) -> dict[str, Any]:
    """Parse the named ``const`` declarations out of a TS source, in order.

    Raises if a name is declared but cannot be read. Silence is not an option here:
    an unreadable symbol must break the build, not quietly drop out of the comparison.
    """
    env: dict[str, Any] = {}
    for name in names:
        if not _declared(src, name):
            continue
        mt = re.search(rf"\bconst\s+{re.escape(name)}\b", src)
        assert mt is not None
        eq = mt.end()
        while True:
            eq = src.find("=", eq)
            if eq == -1:
                raise ValueError(f"no initializer found for {name}")
            if src[eq + 1] not in "=>" and src[eq - 1] not in "=!<>":
                break
            eq += 1
        env[name] = _JsLiteralParser(src[eq + 1:], env).value()
    return env


# --------------------------------------------------------------------------- #
# The backend's view of the same catalogue, in the dashboard's own casing.
# --------------------------------------------------------------------------- #

def _backend_catalogue() -> dict[str, Any]:
    return {
        "ROLE_ORDER": [to_team_role(r) for r in m.ROLE_ORDER],
        "ROLE_META": {to_team_role(rm.role): {"desc": rm.desc} for rm in m.ROLE_META},
        "permissions": [
            {"key": p.key, "label": p.label, "desc": p.desc, "icon": p.icon} for p in m.PERMISSIONS
        ],
        "defaultRolePerms": {
            to_team_role(role): sorted(perms) for role, perms in m.DEFAULT_ROLE_PERMS.items()
        },
        "accessFeatures": [
            {"key": f.key, "label": f.label, "short": f.short, "icon": f.icon, "group": f.group, "desc": f.desc}
            for f in m.FEATURES
        ],
        "roleTemplates": [
            {
                "key": t.key,
                "label": t.label,
                "tagline": t.tagline,
                "icon": t.icon,
                "role": to_team_role(t.role),
                "grants": sorted(t.grants),
            }
            for t in m.TEMPLATES
        ],
    }


def _normalise(symbol: str, value: Any) -> Any:
    """Reduce a parsed TS value to the fields the backend owns, in a comparable form.

    Fields the backend does NOT own (``c``, ``color``, ``GROUP_COLOR``) are dropped
    rather than compared: colour is the frontend's, by design.
    """
    owned = {
        "ROLE_META": ("desc",),
        "permissions": ("key", "label", "desc", "icon"),
        "accessFeatures": ("key", "label", "short", "icon", "group", "desc"),
        "roleTemplates": ("key", "label", "tagline", "icon", "role", "grants"),
    }
    if symbol == "ROLE_ORDER":
        return list(value)
    if symbol == "defaultRolePerms":
        return {k: sorted(v) for k, v in value.items()}
    if symbol == "ROLE_META":
        return {k: {f: v[f] for f in owned[symbol]} for k, v in value.items()}
    out = []
    for item in value:
        row = {f: item[f] for f in owned[symbol] if f != "grants"}
        if "grants" in owned[symbol]:
            row["grants"] = sorted(item["grants"])
        out.append(row)
    return out


def _drifts(ts_env: dict[str, Any]) -> list[str]:
    """Every field on which a TS-declared catalogue symbol disagrees with the backend."""
    backend = _backend_catalogue()
    found: list[str] = []
    for symbol in _CATALOGUE_SYMBOLS:
        if symbol not in ts_env:
            continue  # deleted from the dashboard - the goal state
        ts_val = _normalise(symbol, ts_env[symbol])
        be_val = backend[symbol]
        if isinstance(be_val, list) and isinstance(ts_val, list):
            ts_by = {r["key"]: r for r in ts_val} if ts_val and "key" in ts_val[0] else None
            if ts_by is not None:
                be_by = {r["key"]: r for r in be_val}
                if set(ts_by) != set(be_by):
                    found.append(
                        f"{symbol}: key sets differ - ts-only={sorted(set(ts_by) - set(be_by))} "
                        f"backend-only={sorted(set(be_by) - set(ts_by))}"
                    )
                for key in sorted(set(ts_by) & set(be_by)):
                    for field, tv in ts_by[key].items():
                        bv = be_by[key][field]
                        if tv != bv:
                            found.append(f"{symbol}[{key}].{field}: ts={tv!r} backend={bv!r}")
                continue
        if isinstance(be_val, dict) and isinstance(ts_val, dict):
            if set(ts_val) != set(be_val):
                found.append(
                    f"{symbol}: key sets differ - ts-only={sorted(set(ts_val) - set(be_val))} "
                    f"backend-only={sorted(set(be_val) - set(ts_val))}"
                )
            for key in sorted(set(ts_val) & set(be_val)):
                if ts_val[key] != be_val[key]:
                    found.append(f"{symbol}[{key}]: ts={ts_val[key]!r} backend={be_val[key]!r}")
            continue
        if ts_val != be_val:
            found.append(f"{symbol}: ts={ts_val!r} backend={be_val!r}")
    return found

# --------------------------------------------------------------------------- #
# Non-vacuity first: prove the comparison can SEE, before trusting it to pass.
#
# These tests are built from a catalogue this file SYNTHESISES, never from the live
# frontend/lib/data.ts. An earlier version anchored its self-test to a literal inside
# the real file (`label: "Technical Audit"`), which had two defects worth recording:
# it went red the moment `accessFeatures` was deleted - the exact state this work
# moves toward - and it went red on an ordinary, correct rename applied to BOTH files,
# which would have trained the next engineer to edit the anchor until it passed, at
# which point the proof becomes decoration. Synthesising removes both.
# --------------------------------------------------------------------------- #


def _synthesise_ts(catalogue: dict[str, Any]) -> str:
    """Emit a data.ts-shaped source for a catalogue, to exercise the reader on itself."""
    def j(v: Any) -> str:
        return json.dumps(v, ensure_ascii=False)


    def rows(items: list[dict[str, Any]]) -> str:
        return ",\n  ".join(
            "{ " + ", ".join(f"{k}: {j(v)}" for k, v in row.items()) + " }" for row in items
        )

    meta = ",\n  ".join(f"{r}: {{ desc: {j(v['desc'])}, c: SERIES.c1 }}"
                         for r, v in catalogue["ROLE_META"].items())
    perms = ",\n  ".join(f"{r}: {j(v)}" for r, v in catalogue["defaultRolePerms"].items())
    return f"""
// synthesised for the gate's own self-test - not the product file
export const SERIES = {{ c1: "#C6FF3C" }};
export const ROLE_ORDER: TeamRole[] = {j(catalogue["ROLE_ORDER"])};
export const ROLE_META: Record<TeamRole, {{ desc: string; c: string }}> = {{
  {meta},
}};
export const permissions: {{ key: PermKey }}[] = [
  {rows(catalogue["permissions"])},
];
export const defaultRolePerms: Record<TeamRole, PermKey[]> = {{
  {perms},
}};
export const accessFeatures: AccessFeature[] = [
  {rows(catalogue["accessFeatures"])},
];
const ALL_KEYS = accessFeatures.map((f) => f.key);
export const roleTemplates: RoleTemplate[] = [
  {rows(catalogue["roleTemplates"])},
];
"""


@pytest.mark.unit
def test_the_reader_round_trips_the_backend_catalogue() -> None:
    """Parse a catalogue this file emitted and get the same catalogue back, with no drift.

    If this fails, every green result from the real gate is meaningless - it would mean
    the reader cannot represent the data it is asked to compare.
    """
    synth = _synthesise_ts(_backend_catalogue())
    env = _extract(synth)
    assert set(env) >= set(_CATALOGUE_SYMBOLS), f"reader lost symbols: {set(_CATALOGUE_SYMBOLS) - set(env)}"
    assert _drifts(env) == []
    # The `.map` projection must EVALUATE, not degrade to a sentinel - defaultRolePerms
    # and ALL_KEYS depend on it, and a sentinel would silently exempt them.
    assert env["ALL_KEYS"] == list(m.FEATURE_KEYS)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("what", "old", "new"),
    [
        ("a feature label", 'label: "Technical Audit"', 'label: "Site Audit"'),
        ("a feature icon", 'icon: "add_business"', 'icon: "language"'),
        ("a role description", '"Read-only access to reports and dashboards."', '"Anything at all."'),
        # The two that would be a privilege escalation rather than a cosmetic slip.
        ("a template's grants", '"content_pipeline", "publishing"', '"content_pipeline", "key_vault"'),
        ("a role's permissions", '"run_audits", "view_reports"', '"run_audits", "manage_vault"'),
    ],
)
def test_the_comparison_detects_every_drift_it_is_shown(what: str, old: str, new: str) -> None:
    """The gate must FAIL on an injected drift, or it is decoration.

    This is the check the previous gate could not have passed: ``test_rbac_matrix.py``
    compared Python to Python, so no drift in the TS file could ever have moved it.
    """
    synth = _synthesise_ts(_backend_catalogue())
    tampered = synth.replace(old, new, 1)
    assert tampered != synth, f"the {what} fixture no longer matches what is synthesised"
    assert _drifts(_extract(tampered)), f"the gate did not see an injected drift in {what}"


@pytest.mark.unit
def test_a_symbol_that_cannot_be_read_is_an_error_not_a_skip() -> None:
    """An unreadable declaration must break the build, never drop out of the set."""
    with pytest.raises(ValueError):
        _extract("export const permissions = <<< not javascript >>>;", ("permissions",))


# --------------------------------------------------------------------------- #
# The structural half: a copy under a different name is still a copy.
# --------------------------------------------------------------------------- #

_QUOTED = re.compile(r"""['"]([A-Za-z_]\w*)['"]""")


def _const_spans(src: str) -> list[tuple[str, str]]:
    """Every ``const <name>`` in the source, paired with the text up to the next one."""
    marks = [(mt.group(1), mt.start()) for mt in re.finditer(r"\bconst\s+(\w+)", src)]
    return [
        (name, src[start : (marks[i + 1][1] if i + 1 < len(marks) else len(src))])
        for i, (name, start) in enumerate(marks)
    ]


def _catalogue_copies_under_other_names(src: str) -> list[str]:
    """Declarations that look like the access matrix but are not the names we compare.

    The value comparison keys on six known identifiers. Renaming one and re-declaring a
    drifting copy would therefore be invisible to it - the same hole the whole file
    exists to close, one rename away. This closes it by content instead of by name.
    """
    known = set(_CATALOGUE_SYMBOLS) | {"ALL_KEYS"}
    features, perms = set(m.FEATURE_KEYS), set(m.PERM_KEYS)
    found: list[str] = []
    for name, span in _const_spans(src):
        if name in known:
            continue
        quoted = set(_QUOTED.findall(span))
        n_feat, n_perm = len(quoted & features), len(quoted & perms)
        if n_feat >= 3 or n_perm >= 3:
            found.append(f"const {name} (contains {n_feat} feature keys, {n_perm} permission keys)")
    return found


@pytest.mark.unit
def test_no_catalogue_copy_hides_under_another_name() -> None:
    """Deleting ``roleTemplates`` and re-adding it as ``ROLE_TEMPLATE_CATALOGUE`` must not work.

    Without this the gate has no structural form at all: once the six known names are
    gone it asserts nothing whatsoever about ``data.ts``, and a re-introduced copy -
    including one that quietly grants a template ``key_vault`` - passes untouched.
    """
    if not _DATA_TS.exists():
        return
    rogue = _catalogue_copies_under_other_names(_DATA_TS.read_text(encoding="utf-8"))
    assert not rogue, (
        "frontend/lib/data.ts declares what looks like a second copy of the access "
        "matrix under a name the value comparison does not check. The dashboard must "
        "read GET /rbac/* rather than redeclare the catalogue:\n  - " + "\n  - ".join(rogue)
    )


@pytest.mark.unit
def test_the_structural_check_catches_a_renamed_copy() -> None:
    """Non-vacuity for the structural half, on a synthesised copy."""
    rogue = _catalogue_copies_under_other_names(
        'const ROLE_TEMPLATE_CATALOGUE = [{ grants: ["content_pipeline", "key_vault", "billing"] }];'
    )
    assert any("ROLE_TEMPLATE_CATALOGUE" in r for r in rogue)
    # ...and does not fire on an ordinary declaration that merely mentions one key.
    assert _catalogue_copies_under_other_names('const HOME = { feature: "billing" };') == []


# --------------------------------------------------------------------------- #
# The gate.
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_the_dashboard_holds_no_catalogue_that_disagrees_with_the_backend() -> None:
    """``app.rbac.matrix`` is the single source of truth for the access model.

    Green in all three states, and that is measured rather than asserted by the two
    tests below: while ``data.ts`` still declares the catalogue (every value must
    agree), while the declarations are deleted one at a time, and afterwards, when the
    dashboard reads ``/rbac/*`` and declares nothing.
    """
    if not _DATA_TS.exists():
        return  # the goal state: no second copy to disagree
    drifts = _drifts(_extract(_DATA_TS.read_text(encoding="utf-8")))
    assert not drifts, (
        "frontend/lib/data.ts disagrees with app/rbac/matrix.py, which is the single "
        "source of truth. Either correct data.ts, or delete its copy and read "
        "GET /rbac/* instead:\n  - " + "\n  - ".join(drifts)
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "deleted",
    [(), ("roleTemplates",), ("ROLE_META",), ("permissions", "defaultRolePerms"),
     ("accessFeatures", "ALL_KEYS", "roleTemplates"), _PARSE_ORDER],
    ids=["none", "templates", "role-meta", "perms", "features", "everything"],
)
def test_the_gate_is_green_through_every_step_of_the_handover(deleted: tuple[str, ...]) -> None:
    """Deleting a catalogue symbol is the GOAL, and must never be what turns the gate red.

    Measured, not claimed. The previous version of this file asserted in its docstring
    that it was "green before, during and after the handover" and was in fact red from
    the moment ``accessFeatures`` was deleted - an unmeasured claim about a guard, in
    the file written to stop unmeasured claims.
    """
    synth = _synthesise_ts(_backend_catalogue())
    for name in deleted:
        synth = re.sub(
            rf"(export )?const {re.escape(name)}\b.*?(?=\n(export )?const |\Z)",
            "",
            synth,
            flags=re.DOTALL,
        )
    env = _extract(synth)
    for name in deleted:
        assert name not in env, f"{name} survived deletion"
    assert _drifts(env) == [], f"deleting {deleted or 'nothing'} turned the gate red"


@pytest.mark.unit
def test_colour_is_not_reintroduced_to_the_backend() -> None:
    """Colour is a theme token. It has no Python reader, and it is where the drift lived.

    Nine of the fourteen fields that had drifted by 2026-08-24 were colours: the
    backend carried the pre-Avant-Garde palette and served it on ``/rbac/roles`` and
    ``/rbac/templates``, where every caller discarded it. The field was removed rather
    than reconciled, so THIS catalogue's drift surface went with it. (The backend is
    not palette-free - see the note in ``app/rbac/matrix.py``.) This keeps it gone.
    """
    from app.schemas.rbac import RoleView, TemplateView

    for model in (m.RoleMetaDef, m.RoleTemplateDef, RoleView, TemplateView):
        assert "color" not in model.model_fields, (
            f"{model.__name__} reintroduced `color`. Accent colour belongs to the "
            "frontend theme (SERIES); the backend owns keys, grants, labels and icons."
        )


@pytest.mark.unit
def test_every_catalogue_symbol_is_either_compared_or_provably_gone() -> None:
    """No symbol may leave the comparison silently - it is deleted, or it is checked."""
    assert set(_backend_catalogue()) == set(_CATALOGUE_SYMBOLS)
    if not _DATA_TS.exists():
        return
    src = _DATA_TS.read_text(encoding="utf-8")
    env = _extract(src)
    for symbol in _CATALOGUE_SYMBOLS:
        assert _declared(src, symbol) == (symbol in env), (
            f"{symbol} is declared in data.ts but the guard could not parse it, so it "
            "was excluded from the comparison. Fix the parser rather than the symbol."
        )


# --------------------------------------------------------------------------- #
# The OTHER copy: what the endpoints actually serve.
#
# The gate above proves matrix.py == data.ts. That is the copy being DELETED. Nothing
# proved matrix.py == what GET /rbac/* emits - the copy about to become load-bearing -
# and the router does an unverified projection on the way out (``to_team_role``,
# ``sorted()``, ``list()``). The existing HTTP tests assert counts and key names only.
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_the_endpoints_serve_exactly_what_the_matrix_holds(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """Every field of all four ``/rbac/*`` responses, compared by VALUE to the source."""
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="u-1", email="op@x.com", role="viewer", status="active",  # type: ignore[arg-type]
        name="Op Erator", title="Analyst", avatar_color="#000000", phone="", two_fa=True,
    )

    async def get(path: str) -> Any:
        resp = await client.get(f"/api/v1/rbac/{path}")
        assert resp.status_code == 200, f"{path} -> {resp.status_code}"
        return resp.json()

    assert await get("features") == [f.model_dump() for f in m.FEATURES]
    assert await get("permissions") == [p.model_dump() for p in m.PERMISSIONS]
    assert await get("roles") == [
        {
            "role": to_team_role(rm.role),
            "desc": rm.desc,
            "permissions": sorted(m.DEFAULT_ROLE_PERMS[rm.role]),
        }
        for rm in m.ROLE_META
    ]
    assert await get("templates") == [
        {
            "key": t.key,
            "label": t.label,
            "tagline": t.tagline,
            "icon": t.icon,
            "role": to_team_role(t.role),
            "grants": list(t.grants),
        }
        for t in m.TEMPLATES
    ]


# --------------------------------------------------------------------------- #
# The one assertion the frontend can no longer make about itself.
#
# `frontend/lib/TEMPLATE_COLOR` supplies the avatar accent the Add-Member wizard
# submits, which `services/provisioning.py` writes to `public.users.avatar_color`.
# A template with no entry there is provisioned with the legacy violet `#7B69EE` -
# the very hex this unit deleted from `TEMPLATES`.
#
# Until `3155bc1` the dashboard could check this itself, by looping over its own
# `roleTemplates` copy. Deleting that copy - the goal - removed the frontend's only
# independent source of template keys, so a frontend version of this check could now
# only iterate `Object.keys(TEMPLATE_COLOR)` and assert that every key it has, it has.
# Vacuous, and green forever. The assertion did not disappear; it moved to the only
# side that can still make it non-vacuously.
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_every_backend_template_has_a_dashboard_colour() -> None:
    """One direction only: every ``TEMPLATES`` key must appear in ``TEMPLATE_COLOR``.

    The reverse - a colour left behind for a template that no longer exists - is
    harmless dead data and is deliberately NOT asserted here, so that a failure says
    unambiguously which of the two happened.

    Unlike the catalogue checks above, this one does **not** pass when its subject is
    missing. A duplicated catalogue disappearing is the goal; the theme map
    disappearing is a regression or a relocation, and either needs a person to look.
    """
    src = _DATA_TS.read_text(encoding="utf-8") if _DATA_TS.exists() else ""
    assert _declared(src, "TEMPLATE_COLOR"), (
        "frontend/lib/data.ts no longer declares TEMPLATE_COLOR, which is where the "
        "Add-Member wizard gets the avatar accent it submits. If the map moved, move "
        "this assertion with it deliberately - do not let it lapse into passing."
    )
    colours = _extract(src, ("SERIES", "TEMPLATE_COLOR"))["TEMPLATE_COLOR"]
    missing = sorted(t.key for t in m.TEMPLATES if t.key not in colours)
    assert not missing, (
        f"template(s) {missing} exist in app/rbac/matrix.py with no entry in "
        "TEMPLATE_COLOR. A member provisioned from one of them is written to "
        "public.users.avatar_color with the legacy violet #7B69EE fallback "
        "(app/services/provisioning.py). Add the accent to frontend/lib/data.ts."
    )


# --------------------------------------------------------------------------- #
# PM-3: "A client can never reach a staff route." Marked CONFIRMED - "enforced +
# tested" - in the recovery specification, and false on 2026-08-24.
#
# Twenty-one routes carried `CurrentUserDep` and nothing else. Where a database was
# involved the line held anyway: `/clients` returns ZERO rows to a client, because
# `clients_select` is `using (public.is_staff())` (0003_clients_sites.sql:67) and
# 0010_client_portal.sql:69 records deliberately that no client select policy exists.
# So the gap was exactly the routes that serve in-process constants and have no RLS
# policy to save them - these four, which handed a portal client the agency's whole
# role/permission matrix, feature catalogue and template grants.
#
# RLS is the guard nobody has to remember. It failed precisely where there was no
# database. These are the negative tests per boundary that SEC-002 asks for.
# --------------------------------------------------------------------------- #

_RBAC_ROUTES = ("features", "permissions", "roles", "templates")


def _as(app: FastAPI, role: str) -> None:
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id="u-1", email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op Erator", title="T", avatar_color="#000000", phone="", two_fa=True,
    )


@pytest.mark.unit
@pytest.mark.parametrize("path", _RBAC_ROUTES)
async def test_a_portal_client_cannot_read_the_agency_access_model(
    app: FastAPI, client: httpx.AsyncClient, path: str
) -> None:
    """The negative half of PM-3, per boundary.

    A 403 and not a 404: the route exists, the caller is authenticated, and the answer
    is that this principal may not have it. Pretending the route is absent would hide
    a real authorization decision behind a fiction.
    """
    _as(app, "client")
    resp = await client.get(f"/api/v1/rbac/{path}")
    assert resp.status_code == 403, (
        f"/rbac/{path} returned {resp.status_code} to a portal client. This endpoint "
        "serves in-process constants - no query runs, so RLS cannot stop it, and the "
        "app layer is the only boundary there is."
    )


@pytest.mark.unit
@pytest.mark.parametrize("role", ["owner", "admin", "manager", "specialist", "analyst", "viewer"])
async def test_every_staff_role_still_reads_the_access_model(
    app: FastAPI, client: httpx.AsyncClient, role: str
) -> None:
    """The positive half - so the guard cannot pass by locking everybody out.

    A boundary test that only checks the deny side is satisfied by a broken route.
    """
    _as(app, role)
    for path in _RBAC_ROUTES:
        resp = await client.get(f"/api/v1/rbac/{path}")
        assert resp.status_code == 200, f"{role} lost access to /rbac/{path}"


@pytest.mark.unit
async def test_the_access_model_still_requires_authentication(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """Staff-only must not have replaced authenticated-only - both gates stand."""
    app.dependency_overrides.pop(get_current_user, None)
    for path in _RBAC_ROUTES:
        resp = await client.get(f"/api/v1/rbac/{path}")
        assert resp.status_code == 401, f"/rbac/{path} stopped requiring auth"


# --------------------------------------------------------------------------- #
# The client vocabulary, held to what actually implements it.
#
# A vocabulary whose only reader is itself is decoration. Each capability below is
# asserted against the mechanism that enforces it, so the names cannot drift away
# from the platform the way the catalogue drifted from the dashboard.
# --------------------------------------------------------------------------- #


@pytest.mark.unit
async def test_a_portal_client_cannot_read_what_the_agency_pays_its_suppliers(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    """``GET /cost/pricing`` is the same shape of hole as ``/rbac/*``, found the same way.

    It returns ``provider_pricing(settings)`` - in-process constants, no query - so RLS
    never gets a chance to act. Unit prices are what the AGENCY pays a supplier, not
    what a client is charged. The AST sweep that measured the guards found it; it is
    not in the same module as the rest of this unit, and it is here because the defect
    is, not because the file is.
    """
    _as(app, "client")
    assert (await client.get("/api/v1/cost/pricing")).status_code == 403
    _as(app, "viewer")
    assert (await client.get("/api/v1/cost/pricing")).status_code == 200


@pytest.mark.unit
def test_the_client_vocabulary_is_exactly_what_the_corpus_confirms() -> None:
    """Three capabilities, each traceable. A fourth needs a requirement ID first."""
    traceable = {
        "view_granted_reports",   # CLIENT-007 / 0031_client_report_grants.sql
        "raise_request",          # CLIENT-006, CLIENT-009 / spec 12.2
        "run_audit_within_tier",  # CLIENT-004, ADM-035 / services/client_audits.py
    }
    assert traceable == m.CLIENT_CAPABILITIES
    for cap in m.CLIENT_CAPABILITIES:
        assert m.client_may(cap)


@pytest.mark.unit
def test_a_client_holds_no_staff_permission_and_no_feature() -> None:
    """The named zero. Unchanged behaviour - stated rather than implied."""
    assert m.perms_for_role("client") == frozenset()
    assert not m.is_staff_role("client")
    for perm in m.PERM_KEYS:
        assert not m.role_has_perm("client", perm)
    for feature in m.FEATURE_KEYS:
        assert m.effective_feature_level("client", {}, feature) == "off"


@pytest.mark.unit
def test_a_client_never_approves_and_the_portal_offers_no_way_to() -> None:
    """Owner decision of 2026-08-24, closing Q-11 / Q-12 / CLIENT-013.

    The specification recorded client approval of content drafts and of publishing to
    their own site as **UNKNOWN** - not as "off". The plan asserted "off by default",
    which would have settled a commercial question by writing code. It is now off
    because someone decided it, and this test is what holds the portal to that: adding
    a client-facing approval route fails here, which is the moment to revisit the
    decision rather than the moment to discover it was never made.
    """
    assert m.CLIENT_MAY_APPROVE is False
    assert "approve" not in m.CLIENT_CAPABILITIES

    from app.routers.portal import router as portal_router

    writes = [
        (method, r.path)
        for r in portal_router.routes
        for method in getattr(r, "methods", set()) or set()
        if method in {"POST", "PUT", "PATCH", "DELETE"}
    ]
    offending = [w for w in writes if "approv" in w[1].lower() or "publish" in w[1].lower()]
    assert not offending, (
        f"the client portal exposes {offending}, but CLIENT_MAY_APPROVE is False. "
        "Either this is the change request that reopens Q-11/Q-12, or the route is a "
        "mistake. It is not something to resolve by editing this test."
    )
