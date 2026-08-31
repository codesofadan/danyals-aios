"""Measure how detectable an automated browser session is.

WHY THIS EXISTS BEFORE ANY PLATFORM WORK. Web 2.0 account creation is browser-only -
no platform offers a signup API - so the whole engine rests on sessions that survive
bot detection. Writing signup selectors before knowing whether the browser itself is
detectable is building the roof first: every spec would fail for a reason that has
nothing to do with the spec.

So this probes a live session and reports which signals leak. It is a MEASUREMENT, not
a bypass: it tells us where we stand against the checks anti-bot vendors actually run,
so a decision to change browser driver is made on evidence rather than on a blog post.

WHAT IT CHECKS. The signals that are cheap for a defender to read and that classically
give automation away:

* ``navigator.webdriver`` - the single most-checked flag.
* ``HeadlessChrome`` in the user agent - a giveaway a JS shim cannot remove, because the
  string is baked into the binary.
* an empty plugin/mimeType list, and an empty ``languages`` array - real browsers have both.
* a missing ``window.chrome`` runtime object.
* WebGL vendor/renderer reporting SwiftShader/llvmpipe - the software renderer a
  headless container uses, which no consumer machine reports.
* ``Notification.permission === 'denied'`` while permissions query says ``prompt`` - a
  classic headless inconsistency.

WHAT IT DOES NOT CHECK, and this matters. TLS fingerprinting, IP reputation and
behavioural scoring are decided off-page by the defender; nothing measurable inside the
browser reveals them. A clean score here means the FINGERPRINT is clean, not that a
session will pass Cloudflare. Treating this as a pass/fail for "will signup work" would
be exactly the overclaim the rest of this module is built to avoid.

Pure: :func:`score_probe` is a plain function over the probe dict, so the scoring is
unit-tested with no browser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: The JS run inside the page to collect raw signals. Returns a flat dict; every value
#: is defensive because a hardened context can make any of these throw.
PROBE_JS = """() => {
  const out = {};
  const safe = (fn, dflt) => { try { return fn(); } catch (e) { return dflt; } };
  out.webdriver          = safe(() => navigator.webdriver, null);
  out.userAgent          = safe(() => navigator.userAgent, "");
  out.pluginCount        = safe(() => navigator.plugins.length, 0);
  out.mimeTypeCount      = safe(() => navigator.mimeTypes.length, 0);
  out.languages          = safe(() => Array.from(navigator.languages || []), []);
  out.hasChromeRuntime   = safe(() => typeof window.chrome === "object" && window.chrome !== null, false);
  out.hardwareConcurrency= safe(() => navigator.hardwareConcurrency, 0);
  out.deviceMemory       = safe(() => navigator.deviceMemory, 0);
  out.notificationPerm   = safe(() => Notification.permission, "");
  out.outerDims          = safe(() => [window.outerWidth, window.outerHeight], [0, 0]);
  const gl = safe(() => {
    const c = document.createElement("canvas");
    const ctx = c.getContext("webgl") || c.getContext("experimental-webgl");
    if (!ctx) return null;
    const dbg = ctx.getExtension("WEBGL_debug_renderer_info");
    if (!dbg) return null;
    return {
      vendor: ctx.getParameter(dbg.UNMASKED_VENDOR_WEBGL),
      renderer: ctx.getParameter(dbg.UNMASKED_RENDERER_WEBGL),
    };
  }, null);
  out.webglVendor   = gl ? gl.vendor : "";
  out.webglRenderer = gl ? gl.renderer : "";
  return out;
}"""

#: Substrings in a WebGL renderer that mean "software rasteriser", i.e. a headless
#: container rather than a real GPU.
_SOFTWARE_RENDERERS = ("swiftshader", "llvmpipe", "software", "mesa offscreen")


@dataclass(frozen=True)
class Leak:
    """One detectable signal, and why a defender cares."""

    signal: str
    detail: str
    severity: str = "high"       # high = commonly checked alone; medium = corroborating


@dataclass(frozen=True)
class FingerprintReport:
    leaks: list[Leak] = field(default_factory=list)
    probe: dict[str, Any] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return not self.leaks

    @property
    def high(self) -> list[Leak]:
        return [x for x in self.leaks if x.severity == "high"]

    def summary(self) -> str:
        if self.clean:
            return "no fingerprint leaks detected (does NOT cover TLS, IP or behaviour)"
        parts = [f"{x.signal}: {x.detail}" for x in self.leaks]
        return f"{len(self.high)} high / {len(self.leaks)} total - " + "; ".join(parts)


def score_probe(probe: dict[str, Any]) -> FingerprintReport:
    """Turn raw probe values into named leaks. Pure."""
    leaks: list[Leak] = []

    if probe.get("webdriver") is True:
        leaks.append(Leak("navigator.webdriver", "reports true", "high"))

    ua = str(probe.get("userAgent") or "")
    if "HeadlessChrome" in ua:
        # A JS shim cannot fix this: the string comes from the binary.
        leaks.append(Leak("userAgent", "contains 'HeadlessChrome'", "high"))
    if not ua:
        leaks.append(Leak("userAgent", "empty", "high"))

    if int(probe.get("pluginCount") or 0) == 0:
        leaks.append(Leak("navigator.plugins", "empty list", "high"))
    if int(probe.get("mimeTypeCount") or 0) == 0:
        leaks.append(Leak("navigator.mimeTypes", "empty list", "medium"))
    if not probe.get("languages"):
        leaks.append(Leak("navigator.languages", "empty array", "high"))
    if not probe.get("hasChromeRuntime"):
        leaks.append(Leak("window.chrome", "missing runtime object", "medium"))

    renderer = str(probe.get("webglRenderer") or "").lower()
    if renderer and any(tok in renderer for tok in _SOFTWARE_RENDERERS):
        leaks.append(Leak("WebGL renderer", f"software rasteriser ({renderer[:48]})", "high"))

    if int(probe.get("hardwareConcurrency") or 0) <= 1:
        leaks.append(Leak("hardwareConcurrency", "implausibly low", "medium"))

    dims = probe.get("outerDims") or [0, 0]
    if not any(int(d or 0) for d in dims):
        # Headless reports 0x0 outer dimensions; a real window never does.
        leaks.append(Leak("window.outerWidth/Height", "both zero (headless tell)", "high"))

    return FingerprintReport(leaks=leaks, probe=dict(probe))
