"""WS-1 (Truth) gate: nothing fabricated may re-enter the frontend bundle.

The audit's finding was that dead demo data kept reaching the client because
**nothing enforced its absence** — `ADM-003` (no dead controls) and `ADM-025`
(every number traced to a live source) were conventions, not checks. Deleting the
seed arrays once does not keep them deleted; this file does.

It lives in the BACKEND suite deliberately: the frontend has no test runner yet
(WS-9 adds `tsc`/`next build` CI, which cannot express these rules), and
`test_contract_lock.py` already establishes the precedent of the backend suite
reading frontend sources. Every check is a static read of `frontend/` — no build,
no node, no network.

Each rule states the defect it prevents. If a rule ever blocks legitimate work,
change the rule deliberately with a reason — do not silence it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FRONTEND = _REPO_ROOT / "frontend"
_LIB = _FRONTEND / "lib"

# Only source we author. node_modules/.next are third-party or generated.
_SKIP_DIRS = {"node_modules", ".next", "out", "dist"}


def _source_files() -> list[Path]:
    """Every authored .ts/.tsx file under frontend/."""
    files: list[Path] = []
    for path in _FRONTEND.rglob("*"):
        if path.suffix not in (".ts", ".tsx"):
            continue
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        files.append(path)
    return files


def _rel(path: Path) -> str:
    return str(path.relative_to(_REPO_ROOT))


def test_frontend_sources_are_discoverable() -> None:
    """Guard the guard: a bad root would make every rule below vacuously pass."""
    files = _source_files()
    assert len(files) > 50, f"expected the frontend tree at {_FRONTEND}, found {len(files)} files"


# --------------------------------------------------------------------------- #
# Rule 1 · No unit price may be written in the frontend
# --------------------------------------------------------------------------- #
# Prevented defect: `lib/cost.ts` shipped "$0.30 / search" against a real Serper
# price of $0.001/query (~300x) and "$0.75 / task" against $0.0006/call (~1250x).
# A price in the bundle cannot track a settings change and goes stale silently.
# Unit prices now come from GET /cost/pricing (backend `provider_pricing`).

# A dollar-amount literal inside a string: "$0.30", "~$1.50 / run", "$1,490".
_MONEY_IN_STRING = re.compile(r"""["'`][^"'`\n]*?(\$\s*[\d,]+(?:\.\d+)?[kKmM]?)[^"'`\n]*?["'`]""")

# `$0` is a zero DISPLAY, not a quoted price (e.g. a free tier rendered as "$0").
_ZERO_DISPLAY = re.compile(r"^\$\s*0(?:\.0+)?$")

# A JS regex literal on the line means `$1`/`$2` are capture-group backreferences
# in a String.replace, not money.
_REGEX_LITERAL = re.compile(r"(?<![\w)\]])/(?![/*])(?:\\.|\[[^\]]*\]|[^/\n\\])+/[gimsuy]*")

_COMMENT_LINE = re.compile(r"^\s*(//|\*|/\*)")


def _price_offenders(path: Path) -> list[str]:
    hits: list[str] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if _COMMENT_LINE.match(line):
            continue
        if _REGEX_LITERAL.search(line):
            continue
        # `${...}` is interpolation of a computed value, not a literal price.
        stripped = re.sub(r"\$\{[^}]*\}", "", line)
        for match in _MONEY_IN_STRING.finditer(stripped):
            amount = match.group(1).strip()
            if _ZERO_DISPLAY.match(amount):
                continue
            hits.append(f"{_rel(path)}:{lineno}: {line.strip()[:140]}")
            break
    return hits


def test_no_hardcoded_unit_price_anywhere_in_the_frontend() -> None:
    offenders = [hit for path in _source_files() for hit in _price_offenders(path)]
    assert not offenders, (
        "A price literal was written into the frontend. Unit prices come from "
        "GET /cost/pricing (see useProviderPricing), which reads the same Settings "
        "the cost gate bills at.\n  " + "\n  ".join(offenders)
    )


# --------------------------------------------------------------------------- #
# Rule 2 · No credential-shaped literal may ship in the bundle
# --------------------------------------------------------------------------- #
# Prevented defect: `lib/vault.ts` shipped a `vaultKeys` array of realistic fake
# secrets (`sk-ant-api03-…`, `AIzaSy…`, WordPress application passwords) and
# `lib/data.ts` shipped plaintext client-portal passwords (`"Np!Dental#2026"`).
# Fake or not, everything in this tree is served to every browser that loads the
# app, and a realistic fake is indistinguishable from a leak during triage.

_SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Anthropic API key", re.compile(r"sk-ant-[A-Za-z0-9_-]{4,}")),
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_-]{10,}")),
    ("Google OAuth token", re.compile(r"ya29\.[0-9A-Za-z_-]{10,}")),
    ("OpenAI API key", re.compile(r"\bsk-[A-Za-z0-9]{20,}")),
    ("AWS access key id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # A literal password assigned to a password-ish key: `pass: "Np!Dental#2026"`.
    (
        "literal password",
        re.compile(r"\b(?:pass|password|passwd|secret|apiKey|api_key|token)\s*:\s*[\"'][^\"'\s]{6,}[\"']"),
    ),
)

# Narrow, justified exemptions. Each must name why it is not a secret.
_SECRET_EXEMPT: tuple[tuple[str, str], ...] = (
    # A form's controlled input declares its own type, not a value.
    ("type: \"password\"", "an <input type> discriminator, not a credential"),
    ("type: 'password'", "an <input type> discriminator, not a credential"),
)


def _secret_offenders(path: Path) -> list[str]:
    hits: list[str] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if any(token in line for token, _ in _SECRET_EXEMPT):
            continue
        for label, pattern in _SECRET_PATTERNS:
            if pattern.search(line):
                hits.append(f"{_rel(path)}:{lineno}: [{label}] {line.strip()[:120]}")
    return hits


def test_no_credential_shaped_literal_ships_to_the_browser() -> None:
    offenders = [hit for path in _source_files() for hit in _secret_offenders(path)]
    assert not offenders, (
        "A credential-shaped literal is in the frontend bundle. Secrets are sealed "
        "server-side in the vault and revealed only through an owner-authorised "
        "POST /vault/{id}/reveal — never seeded into a source file, even as a fake.\n  "
        + "\n  ".join(offenders)
    )


# --------------------------------------------------------------------------- #
# Rule 3 · The client-side demo store stays deleted
# --------------------------------------------------------------------------- #
# Prevented defect: `lib/store.tsx` was a localStorage-backed parallel source of
# truth seeded from the demo arrays and mounted around every portal. While it was
# mounted, a screen could render convincing data with the API completely down.


def test_the_demo_store_is_not_reintroduced() -> None:
    assert not (_LIB / "store.tsx").exists(), (
        "lib/store.tsx is back. The portals read the API through lib/hooks/*; a "
        "second client-side source of truth lets a screen look healthy while the "
        "backend is failing."
    )
    offenders = [
        f"{_rel(p)}"
        for p in _source_files()
        if re.search(r"""from\s+["']@/lib/store["']""", p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"still importing the deleted demo store: {offenders}"


# --------------------------------------------------------------------------- #
# Rule 4 · Urgency is measured against the real clock
# --------------------------------------------------------------------------- #
# Prevented defect: `dueInfo()` compared every task due date to a hardcoded
# `PORTAL_TODAY = { m: 6, d: 10 }` (10 Jul 2026), so every "Due today" and
# "Nd overdue" label in the team portal was computed against a frozen fake date.


def test_due_urgency_is_not_computed_against_a_frozen_clock() -> None:
    data_ts = (_LIB / "data.ts").read_text(encoding="utf-8")
    assert "PORTAL_TODAY" not in data_ts, (
        "PORTAL_TODAY is back: a hardcoded 'today' makes every overdue label fiction."
    )
    assert "new Date()" in data_ts, (
        "dueInfo() must measure from the real current date."
    )


# --------------------------------------------------------------------------- #
# Rule 5 · Demo seed arrays stay deleted
# --------------------------------------------------------------------------- #
# Prevented defect: `lib/data.ts` carried a full fake agency — eight clients with
# portal passwords, eight staff with fabricated performance percentages, a task
# board and an activity feed. Anything left importable can be rendered by mistake.

_DELETED_SEEDS = (
    "clientDirectory",
    "teamMembers",
    "tasks_seed",
    "activity_seed",
    "teamCredentials",
    "operatorProfile",
    "clientReportGrants",
    "memberGrants",
    "vaultKeys",
)


@pytest.mark.parametrize("symbol", _DELETED_SEEDS)
def test_demo_seed_arrays_are_not_reintroduced(symbol: str) -> None:
    for module in ("data.ts", "vault.ts"):
        src = (_LIB / module).read_text(encoding="utf-8")
        assert not re.search(rf"^export const {symbol}\b", src, re.MULTILINE), (
            f"{module} re-exports the demo seed `{symbol}`. Business data comes from "
            f"the API through lib/hooks/*."
        )


# --------------------------------------------------------------------------- #
# Rule 6 · No unreferenced seed array may sit in `lib/`
# --------------------------------------------------------------------------- #
# The four modules named in the recovery plan were not the whole problem. A
# sweep of `lib/` found fifteen more exported arrays that NOTHING imports —
# fabricated audit rows, backup snapshots, content jobs with client names and
# costs, project milestones, policy change-events with invented `lastChecked`
# timestamps, report workbooks, per-client tier assignments, and upsells with a
# fabricated `clicks30d: 412`. None of it rendered; all of it shipped in the
# browser bundle, and any of it could be rendered by one careless import.
#
# The rule is deliberately structural rather than a denylist of names: an
# exported array of object literals that no page or component imports is dead
# weight at best and a fabrication waiting to be wired at worst. Product
# CATALOGUE data (role templates, feature lists, report definitions) stays —
# and stays because something imports it.

_MIN_SEED_ENTRIES = 3  # below this it is a small constant, not a seeded dataset


def _imported_symbols() -> set[tuple[str, str]]:
    """Every `(module, symbol)` imported from `@/lib/*` anywhere in the app."""
    found: set[tuple[str, str]] = set()
    pattern = re.compile(
        r"""import\s+(?:type\s+)?\{([^}]*)\}\s+from\s+["']@/lib/([\w/]+)["']""", re.S
    )
    for path in _source_files():
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            module = match.group(2)
            for raw in match.group(1).split(","):
                symbol = raw.strip().removeprefix("type ").split(" as ")[0].strip()
                if symbol:
                    found.add((module, symbol))
    return found


def _exported_arrays(path: Path) -> list[tuple[str, int]]:
    """`(name, entry_count)` for each `export const X: T[] = [...]` in a module."""
    src = path.read_text(encoding="utf-8")
    out: list[tuple[str, int]] = []
    for match in re.finditer(r"^export const (\w+)\s*:\s*[^=\n]*=\s*\[", src, re.M):
        # Count from the ASSIGNMENT's bracket, not the `T[]` annotation's.
        open_idx = src.index("[", src.index("=", match.start()))
        depth, i, entries = 0, open_idx, 0
        while i < len(src):
            ch = src[i]
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    break
            elif ch == "{" and depth == 1:
                entries += 1
            i += 1
        out.append((match.group(1), entries))
    return out


def test_no_unreferenced_seed_array_remains_in_lib() -> None:
    imported = _imported_symbols()
    offenders: list[str] = []
    for path in sorted(_LIB.glob("*.ts")):
        module = f"lib/{path.stem}"
        for name, entries in _exported_arrays(path):
            if entries < _MIN_SEED_ENTRIES:
                continue
            if (path.stem, name) in imported or (module, name) in imported:
                continue
            offenders.append(f"{_rel(path)} :: {name} ({entries} entries)")
    assert not offenders, (
        "Unreferenced seed arrays are back in lib/. Nothing imports them, so they "
        "render nowhere — they only ship fabricated data to every browser that "
        "loads the app. Business data comes from the API via lib/hooks/*.\n  "
        + "\n  ".join(offenders)
    )
