"""CSS Color 4 colour spaces -> sRGB hex.

WHY THIS EXISTS, measured rather than assumed. Replicating a live Tailwind v4
storefront produced a palette of exactly two roles (background, text), BOTH
``#ffffff``, and the pipeline reported "design system is ungrounded; styling will be
thin" about a page whose header was a pink-to-purple gradient. The page was not
colourless and the extractor was not broken - it simply could not READ the colours.

Chrome's ``getComputedStyle`` returns whatever colour space the author wrote, and
Tailwind v4 (and every modern framework following it) writes ``oklch()`` and
``lab()``. The site's own declared tokens looked like this::

    --color-purple-500: lab(52.0183% 66.11 -78.2316)
    --color-pink-300:   lab(77.8308% 38.525 -10.5394)

A parser that understands only ``#rrggbb`` and ``rgb()`` returns "" for every one of
them, so the ONLY colours that survived were the handful of literal whites - hence a
white-on-white palette. Every site built after ~2024 hits this.

The conversions here are the CSS Color 4 reference transforms, not approximations:

* ``oklch``/``oklab`` -> OKLab -> LMS -> linear sRGB -> gamma-encoded sRGB
* ``lab``/``lch``     -> CIE Lab (D50, per spec) -> XYZ(D50) -> linear sRGB
* ``hsl``             -> sRGB directly
* ``color(srgb ...)`` and ``color(display-p3 ...)``

Out-of-gamut results are CLAMPED per channel rather than discarded. A clamped
approximation of a vivid brand colour is a far better design token than no colour at
all, which is what the old behaviour produced.

Pure + stdlib only (``math`` and ``re``), so it unit-tests against known values with
no dependency and no network.
"""

from __future__ import annotations

import math
import re

__all__ = ["css_color_to_rgb"]

# --- matrices (CSS Color 4 reference values) -------------------------------- #

# OKLab -> LMS' (cube roots), then LMS -> linear sRGB.
_OKLAB_TO_LMS = (
    (1.0, 0.3963377774, 0.2158037573),
    (1.0, -0.1055613458, -0.0638541728),
    (1.0, -0.0894841775, -1.2914855480),
)
_LMS_TO_LINEAR_SRGB = (
    (4.0767416621, -3.3077115913, 0.2309699292),
    (-1.2684380046, 2.6097574011, -0.3413193965),
    (-0.0041960863, -0.7034186147, 1.7076147010),
)
# XYZ (D50, which is what CSS `lab()` is referenced to) -> linear sRGB. The Bradford
# adaptation D50->D65 is already folded into these coefficients, per the spec.
_XYZ_D50_TO_LINEAR_SRGB = (
    (3.1341359569958707, -1.6173863321612538, -0.4906619460083532),
    (-0.978795502912089, 1.9161404054721572, 0.03344273116131949),
    (0.07195537988411677, -0.2289768264158322, 1.405386058324125),
)
# Display P3 -> linear sRGB.
_P3_TO_LINEAR_SRGB = (
    (1.2249401762805062, -0.2249401762805062, 0.0),
    (-0.0420569547346539, 1.0420569547346539, 0.0),
    (-0.0196376449994070, -0.0786361456707680, 1.0982737906701750),
)

# CIE standard illuminant D50 white point.
_D50 = (0.3457 / 0.3585, 1.0, (1.0 - 0.3457 - 0.3585) / 0.3585)

_NUM = r"[-+]?(?:\d*\.\d+|\d+)"
_FUNC_RE = re.compile(r"^([a-z]+)\s*\(\s*(.*?)\s*\)$", re.I | re.S)
_TOKEN_RE = re.compile(rf"{_NUM}%?|[a-z][a-z0-9-]*", re.I)


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def _mul(matrix: tuple[tuple[float, float, float], ...],
         v: tuple[float, float, float]) -> tuple[float, float, float]:
    return tuple(sum(row[i] * v[i] for i in range(3)) for row in matrix)  # type: ignore[return-value]


def _gamma(c: float) -> float:
    """Linear-light sRGB -> gamma-encoded sRGB."""
    if c <= 0.0031308:
        return 12.92 * c
    return float(1.055 * (abs(c) ** (1 / 2.4)) - 0.055)


def _to_bytes(linear: tuple[float, float, float]) -> tuple[int, int, int]:
    """Gamma-encode, clamp and quantise. Clamping keeps an out-of-gamut brand colour
    as its nearest representable sRGB neighbour rather than throwing it away."""
    return tuple(round(_clamp(_gamma(c)) * 255) for c in linear)  # type: ignore[return-value]


def _parse_args(body: str) -> list[str]:
    """Split a CSS function body into positional tokens, dropping the alpha clause.

    CSS Color 4 allows commas or spaces and an optional ``/ alpha``; a legacy
    ``rgba(r, g, b, a)`` puts alpha in the fourth slot instead. Both are handled by
    the callers, which know their own arity.
    """
    body = body.split("/")[0]
    return _TOKEN_RE.findall(body.replace(",", " "))


def _num(token: str, *, pct_scale: float = 1.0) -> float:
    if token.endswith("%"):
        return float(token[:-1]) / 100.0 * pct_scale
    return float(token)


def _oklab_to_linear_srgb(lightness: float, a: float, b: float) -> tuple[float, float, float]:
    lms_ = _mul(_OKLAB_TO_LMS, (lightness, a, b))
    lms = tuple(x ** 3 for x in lms_)
    return _mul(_LMS_TO_LINEAR_SRGB, lms)  # type: ignore[arg-type]


def _lab_to_linear_srgb(lightness: float, a: float, b: float) -> tuple[float, float, float]:
    fy = (lightness + 16.0) / 116.0
    fx = fy + a / 500.0
    fz = fy - b / 200.0
    delta = 6.0 / 29.0

    def finv(t: float) -> float:
        return t ** 3 if t > delta else 3.0 * delta * delta * (t - 4.0 / 29.0)

    xyz = (finv(fx) * _D50[0], finv(fy) * _D50[1], finv(fz) * _D50[2])
    return _mul(_XYZ_D50_TO_LINEAR_SRGB, xyz)


def _hsl_to_rgb(h: float, s: float, lightness: float) -> tuple[int, int, int]:
    h = h % 360.0
    c = (1.0 - abs(2.0 * lightness - 1.0)) * s
    x = c * (1.0 - abs((h / 60.0) % 2.0 - 1.0))
    m = lightness - c / 2.0
    sextant = int(h // 60.0) % 6
    rgb = [(c, x, 0.0), (x, c, 0.0), (0.0, c, x),
           (0.0, x, c), (x, 0.0, c), (c, 0.0, x)][sextant]
    return tuple(round(_clamp(v + m) * 255) for v in rgb)  # type: ignore[return-value]


def css_color_to_rgb(value: str) -> tuple[int, int, int] | None:
    """Parse any CSS Color 4 function into 8-bit sRGB, or ``None``.

    Returns ``None`` for a colour that is fully transparent, for a keyword this module
    does not resolve, and for anything unparseable - the caller treats all three the
    same way (no measurement), which is correct: a colour nobody can read is not a
    design token.
    """
    raw = (value or "").strip().lower()
    m = _FUNC_RE.match(raw)
    if not m:
        return None
    fn, body = m.group(1), m.group(2)

    # Alpha is checked before conversion: a fully transparent colour is not a token,
    # whatever its hue. The threshold matches the legacy rgb() path's 0.05.
    if "/" in body:
        alpha_token = body.split("/", 1)[1].strip()
        try:
            alpha = _num(alpha_token.rstrip("%") + ("%" if alpha_token.endswith("%") else ""))
            if alpha < 0.05:
                return None
        except ValueError:
            pass

    args = _parse_args(body)
    try:
        if fn in ("oklch", "lch"):
            if len(args) < 3:
                return None
            lightness = _num(args[0], pct_scale=1.0 if fn == "oklch" else 100.0)
            chroma = _num(args[1], pct_scale=0.4 if fn == "oklch" else 150.0)
            hue = math.radians(_num(args[2]))
            a, b = chroma * math.cos(hue), chroma * math.sin(hue)
            linear = (_oklab_to_linear_srgb(lightness, a, b) if fn == "oklch"
                      else _lab_to_linear_srgb(lightness, a, b))
            return _to_bytes(linear)

        if fn in ("oklab", "lab"):
            if len(args) < 3:
                return None
            lightness = _num(args[0], pct_scale=1.0 if fn == "oklab" else 100.0)
            a = _num(args[1], pct_scale=0.4 if fn == "oklab" else 125.0)
            b = _num(args[2], pct_scale=0.4 if fn == "oklab" else 125.0)
            linear = (_oklab_to_linear_srgb(lightness, a, b) if fn == "oklab"
                      else _lab_to_linear_srgb(lightness, a, b))
            return _to_bytes(linear)

        if fn in ("hsl", "hsla"):
            if len(args) < 3:
                return None
            return _hsl_to_rgb(_num(args[0]), _num(args[1], pct_scale=1.0) if args[1].endswith("%")
                               else _num(args[1]),
                               _num(args[2], pct_scale=1.0) if args[2].endswith("%")
                               else _num(args[2]))

        if fn == "color":
            if len(args) < 4:
                return None
            space, chans = args[0], [_num(t) for t in args[1:4]]
            if space in ("srgb", "srgb-linear"):
                if space == "srgb":
                    return tuple(round(_clamp(c) * 255) for c in chans)  # type: ignore[return-value]
                return _to_bytes((chans[0], chans[1], chans[2]))
            if space in ("display-p3", "p3"):
                linear_p3 = tuple(
                    c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in chans
                )
                return _to_bytes(_mul(_P3_TO_LINEAR_SRGB, linear_p3))  # type: ignore[arg-type]
            return None
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    return None
