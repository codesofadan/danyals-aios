"""CAPTCHA-solver seam (7B-4): the ONLY door to clearing a CAPTCHA-gated citation
form. Used exclusively by the Playwright citation bot
(``integrations.citation_bot``) for directories tagged ``captcha_assisted`` - never
called directly by a worker or router.

``CapSolverClient`` is the real client over the CapSolver createTask/getTaskResult
API; CapMonster Cloud implements the SAME request/response shape (both budget
solvers converged on this convention), so pointing ``base_url`` at
``https://api.capmonster.cloud`` (``CAPTCHA_SOLVER_PROVIDER=capmonster``) is a
drop-in swap, not a second client class. Per the reference plan's own cost table, a
solve costs ~$0.0003-0.003 depending on CAPTCHA type - metered through the
``citations`` money-dial alongside the rest of a submission's cost, not tracked
separately.

``FakeCaptchaSolver`` is the deterministic, offline solver: it "solves" instantly
with a stable fake token, so the bot + worker suites run fully live with zero
external accounts.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.config import Settings
from app.logging_setup import get_logger
from integrations.errors import ProviderCallError, ProviderNotConfiguredError
from integrations.http_client import HttpProviderClient

logger = get_logger("integrations.captcha_solver")

_INSTALL_HINT = "set CAPTCHA_SOLVER_API_KEY (CapSolver or CapMonster) to clear CAPTCHA-gated directories"

_CAPSOLVER_BASE = "https://api.capsolver.com"
_CAPMONSTER_BASE = "https://api.capmonster.cloud"


@dataclass(frozen=True)
class CaptchaChallenge:
    """One CAPTCHA to solve: its TYPE + the page context the solver needs."""

    kind: str  # 'recaptcha_v2' | 'recaptcha_v3' | 'hcaptcha' | 'turnstile' | 'image'
    site_key: str
    page_url: str
    image_base64: str = ""  # only for kind='image'


@dataclass(frozen=True)
class CaptchaSolution:
    """The solved token to inject back into the page's response field."""

    token: str


@runtime_checkable
class CaptchaSolver(Protocol):
    def solve(self, challenge: CaptchaChallenge) -> CaptchaSolution: ...


_TASK_TYPE: dict[str, str] = {
    "recaptcha_v2": "ReCaptchaV2TaskProxyless",
    "recaptcha_v3": "ReCaptchaV3TaskProxyless",
    "hcaptcha": "HCaptchaTaskProxyless",
    "turnstile": "AntiTurnstileTaskProxyLess",
}


class CapSolverClient(HttpProviderClient):
    """Real ``CaptchaSolver`` over the CapSolver/CapMonster createTask + polled
    getTaskResult API. Polls until ``status="ready"`` or a bounded timeout, matching
    the provider's own documented flow (a solve is not synchronous)."""

    provider = "capsolver"
    _POLL_INTERVAL_SECONDS = 2.0
    _POLL_TIMEOUT_SECONDS = 90.0

    def __init__(self, *, api_key: str, base_url: str = _CAPSOLVER_BASE, timeout: float = 30.0) -> None:
        if not api_key:
            raise ProviderNotConfiguredError(f"CAPTCHA solver unavailable: {_INSTALL_HINT}")
        super().__init__(base_url=base_url, headers={"Content-Type": "application/json"}, timeout=timeout)
        self._api_key = api_key

    def solve(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        if challenge.kind == "image":
            task_body: dict[str, object] = {"type": "ImageToTextTask", "body": challenge.image_base64}
        else:
            task_type = _TASK_TYPE.get(challenge.kind)
            if task_type is None:
                raise ProviderCallError(f"unsupported CAPTCHA kind: {challenge.kind}")
            task_body = {
                "type": task_type, "websiteURL": challenge.page_url, "websiteKey": challenge.site_key,
            }
        created = self.request_json(
            "POST", "/createTask", json_body={"clientKey": self._api_key, "task": task_body}
        )
        if created.get("errorId"):
            raise ProviderCallError(f"CAPTCHA createTask error: {created.get('errorDescription')}")
        task_id = created.get("taskId")
        if not task_id:
            raise ProviderCallError("CAPTCHA createTask response missing taskId")
        return self._poll(task_id)

    def _poll(self, task_id: str) -> CaptchaSolution:
        deadline = time.monotonic() + self._POLL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            result = self.request_json(
                "POST", "/getTaskResult", json_body={"clientKey": self._api_key, "taskId": task_id}
            )
            if result.get("errorId"):
                raise ProviderCallError(f"CAPTCHA getTaskResult error: {result.get('errorDescription')}")
            if result.get("status") == "ready":
                solution = result.get("solution") or {}
                token = solution.get("gRecaptchaResponse") or solution.get("token") or solution.get("text") or ""
                if not token:
                    raise ProviderCallError("CAPTCHA solver returned a ready task with no usable token")
                return CaptchaSolution(token=str(token))
            time.sleep(self._POLL_INTERVAL_SECONDS)
        raise ProviderCallError(f"CAPTCHA task {task_id} did not complete within {self._POLL_TIMEOUT_SECONDS}s")


class FakeCaptchaSolver:
    """Deterministic, offline ``CaptchaSolver`` - always 'solves' instantly with a
    stable fake token."""

    def solve(self, challenge: CaptchaChallenge) -> CaptchaSolution:
        return CaptchaSolution(token=f"fake-solved-{challenge.kind}")


def captcha_solver_from_settings(settings: Settings) -> CaptchaSolver | None:
    """The real solver when a key is configured, else ``None`` (degraded - a
    ``captcha_assisted`` job HOLDS as ``blocked`` rather than guessing a token)."""
    key = settings.captcha_solver_api_key
    if not key:
        logger.info("captcha_solver_degraded", reason="missing_api_key")
        return None
    base_url = _CAPMONSTER_BASE if settings.captcha_solver_provider == "capmonster" else _CAPSOLVER_BASE
    return CapSolverClient(api_key=key.get_secret_value(), base_url=base_url)
