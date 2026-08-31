"""Drift gate for ``infra/deploy/aios.env.example`` against ``app/config.py``.

The template is the file an operator actually fills in before a deploy, and the
settings it omits fail in the quietest way this codebase has: a missing key does
not crash anything, it leaves a provider seam degraded, a gate un-enforced or a
sweep pointed at a default nobody chose. The operator finds out when a feature
they believed in turns out to have been doing nothing.

WHAT THIS GATE ENFORCES, and why each rule is DERIVED rather than listed:

* CREDENTIALS. Every ``SecretStr`` field on ``Settings`` must appear. ``SecretStr``
  is the annotation this codebase already uses to mean "this is a secret", so a
  credential added to config.py is caught with nobody remembering to update a list
  here. A credential absent from the template is a CAPABILITY absent from it -
  nothing tells the operator the platform can do that thing at all.
* THE NON-SECRET HALF OF A CREDENTIAL PAIR. Taken from the live integrations
  catalogue (``app.services.integrations_status``), which names its env vars in the
  text the API-Management screen shows the operator. Anything the product tells
  someone to set must have a documented place to set it. This is what catches
  DATAFORSEO_LOGIN, B2_KEY_ID, B2_BUCKET and PINECONE_INDEX - none of which are
  secrets, and each of which silently disables its pair when left out.
* WHAT PRODUCTION CANNOT BOOT WITHOUT. ``config._REQUIRED_IN_PROD``, config.py's
  own declaration.
* NO DEAD LINES, in either direction: a template key that is not a settings field
  (and not one of the few keys consumed outside ``Settings``) sets nothing at all,
  which is how a renamed setting leaves working-looking documentation behind.
* NO KEY ASSIGNED TWICE. systemd keeps the LAST assignment in an EnvironmentFile,
  so a duplicate makes the file document one value and the process boot with another.
* THE TEMPLATE MUST PARSE. Shipped values are fed to ``Settings`` verbatim, because
  the file is loaded as a systemd EnvironmentFile and a blank value for an int or
  bool field is a boot failure that the template itself caused.

WHAT THIS GATE CANNOT CATCH - read this before trusting a green run:

* Whether a comment is TRUE. Every entry here is judged on its name, never on the
  sentence above it. A key documented with a wrong explanation passes.
* Whether a shipped VALUE is right. The parse rule proves the file loads, not that
  ``IMAGE_GEN_MODEL=gpt-image-1`` is the model the code wants - and because
  EnvironmentFile values beat code defaults, a stale template value wins silently.
  That exact defect has happened here before.
* The entire "degrades silently" class, which is the reason the template exists.
  CONTENT_ENGINE, WEB2_SIMILARITY_ENFORCE, INDEXNOW_ENABLED, the audit depth
  ceilings and REPORT_AUDIT_REFRESH_TIER are in the template on JUDGEMENT about
  what a wrong value does, and no property of config.py distinguishes them from the
  ~85 tuning knobs deliberately left out. Deleting any of them is invisible here.
* Anything outside ``Settings``: install.sh reads this file directly, the systemd
  units load it as an EnvironmentFile, and install.sh exports part of it into the
  frontend build - but only the five keys named in ``_NON_SETTINGS_KEYS`` are known
  to this test, and nothing here checks the Caddyfile, which duplicates the web port
  as a literal rather than reading it from anywhere.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from pydantic import SecretStr
from pydantic_settings import BaseSettings

from app.config import _REQUIRED_IN_PROD, Settings
from app.services.integrations_status import integration_statuses

# backend/tests/ -> backend/ -> repo root.
_TEMPLATE = Path(__file__).resolve().parents[2] / "infra" / "deploy" / "aios.env.example"

# Keys the template carries that are NOT ``Settings`` fields, each with the consumer
# that does read it. The list is short and explicit so that adding a sixth is a
# deliberate act rather than an unnoticed typo passing as a new integration.
_NON_SETTINGS_KEYS = {
    "AIOS_WEB_PORT",  # the aios-web systemd unit; the Caddyfile repeats the number
    "BACKEND_ORIGIN",  # frontend/next.config.mjs, at BUILD time
    "NEXT_PUBLIC_API_BASE_URL",  # inlined into the JS bundle at build time
    "NEXT_PUBLIC_FILE_BASE_URL",  # inlined into the JS bundle at build time
    "PLAYWRIGHT_BROWSERS_PATH",  # exported by install.sh + the worker unit for Chromium
}

_ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")
_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]{3,}")


def _template_assignments() -> dict[str, str]:
    """Every ``KEY=value`` line in the template, in file order.

    Comments are whole lines by the template's own rule (a systemd EnvironmentFile
    does not strip a trailing ``# note`` from a value), so no comment stripping is
    done here - doing it would hide a value that really does contain a '#'.
    """
    found: dict[str, str] = {}
    for line in _TEMPLATE.read_text().splitlines():
        match = _ASSIGNMENT.match(line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def _template_key_order() -> list[str]:
    """Every assigned key in file order, DUPLICATES KEPT.

    ``_template_assignments`` is a dict, so a key written twice collapses to the last
    one and every rule above goes on passing. systemd resolves an EnvironmentFile the
    same way - last assignment wins - which is why a duplicate is the quiet kind of
    wrong: the file documents one value and the process boots with another.
    """
    return [
        match.group(1)
        for line in _TEMPLATE.read_text().splitlines()
        if (match := _ASSIGNMENT.match(line))
    ]


def _secret_field_names(model: type[BaseSettings]) -> set[str]:
    """The env names of every ``SecretStr`` field on ``model``.

    Matches on the annotation string so that ``SecretStr``, ``SecretStr | None`` and
    any future wrapping all read as a credential; a field has to stop being a secret
    in the type system before it stops being required here.
    """
    return {
        name.upper()
        for name, field in model.model_fields.items()
        if "SecretStr" in str(field.annotation)
    }


def _catalogue_env_names() -> set[str]:
    """Env names the integrations catalogue shows the operator for env-backed seams.

    ``model_construct`` applies the declared defaults without reading the process
    environment, so this is the catalogue as the code defines it rather than as this
    machine happens to be configured. The names are pulled out of the human-facing
    ``detail`` text, which is what an operator is actually told to go and set.
    """
    names: set[str] = set()
    for status in integration_statuses(Settings.model_construct()):
        if status.source == "config":
            names |= set(_ENV_NAME.findall(status.detail))
    return names


@pytest.mark.unit
def test_every_credential_in_config_is_documented_in_the_template() -> None:
    """A credential the code can use must have a documented place to put it.

    Absent, the operator is never told the capability exists, and "we do not offer
    that" is indistinguishable from "nobody pasted the key".
    """
    required = (
        _secret_field_names(Settings)
        | _catalogue_env_names()
        | {name.upper() for name in _REQUIRED_IN_PROD}
    )
    missing = sorted(required - _template_assignments().keys())
    assert not missing, (
        "app/config.py defines credentials that infra/deploy/aios.env.example never "
        f"mentions, so a deploy cannot configure them: {missing}. Add each one with a "
        "comment saying what stops working while it is blank."
    )


@pytest.mark.unit
def test_secret_field_detection_reads_the_annotation() -> None:
    """Pin the derivation itself, since every other rule here rests on it.

    Without this, ``_secret_field_names`` could quietly stop matching (an import
    change, an annotation style change) and the gate above would pass by finding
    nothing to require.
    """

    class _Sample(BaseSettings):
        plain_setting: str = ""
        optional_key: SecretStr | None = None
        mandatory_key: SecretStr = SecretStr("")

    assert _secret_field_names(_Sample) == {"OPTIONAL_KEY", "MANDATORY_KEY"}


@pytest.mark.unit
def test_template_has_no_keys_that_configure_nothing() -> None:
    """A line that maps to no setting is documentation for behaviour that is gone.

    It reads exactly like a working one, so a renamed or deleted setting leaves the
    operator confidently configuring a value the app never looks at.
    """
    unknown = sorted(
        key
        for key in _template_assignments()
        if key.lower() not in Settings.model_fields and key not in _NON_SETTINGS_KEYS
    )
    assert not unknown, (
        "infra/deploy/aios.env.example sets keys that are neither Settings fields nor "
        f"listed in _NON_SETTINGS_KEYS: {unknown}. Either the setting was renamed, or "
        "this test needs to learn about a new non-Settings consumer."
    )


@pytest.mark.unit
def test_no_key_is_assigned_twice() -> None:
    """One key, one place to set it.

    A hand-maintained file of ~140 keys grows a second copy of one by ordinary editing
    - a block moved, a credential documented next to its module as well as with its
    pair. systemd then takes the LAST assignment, so the operator edits the copy they
    found and the process keeps the value they never saw.
    """
    order = _template_key_order()
    duplicated = sorted({key for key in order if order.count(key) > 1})
    assert not duplicated, (
        "infra/deploy/aios.env.example assigns these keys more than once, and systemd "
        f"silently keeps the LAST one: {duplicated}. Delete all but one."
    )


@pytest.mark.unit
def test_template_values_load_as_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """The file as shipped must produce a valid ``Settings``.

    Loaded through the PROCESS ENVIRONMENT rather than as constructor kwargs,
    because that is the only door production uses: systemd reads this file as an
    EnvironmentFile and every value reaches pydantic as a string. A blank line under
    an int or bool field is therefore not a harmless placeholder - it is a
    validation error at import time that takes the API down on first boot, caused by
    the template rather than by anything the operator did.

    Every settings name is cleared first, and ``backend/.env`` is pinned off for the
    duration, so what is measured is the TEMPLATE and not whatever the developer's
    shell or local dotenv happens to hold.
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)
    for key, value in _template_assignments().items():
        monkeypatch.setenv(key, value)
    Settings()
