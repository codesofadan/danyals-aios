"""The component stylesheet - what Elementor settings cannot carry (stage 5).

THE HYBRID CONTRACT'S OTHER HALF. Layout, spacing, colour and typography live in real
Elementor settings so the editor's controls work. What remains is component POLISH:
image fill behaviour, card surfaces, hover states - the things a settings key cannot
express, or that must apply uniformly to every instance of a detected component.

DRIVEN BY DETECTION, NOT IMAGINATION. Rules are emitted only for the component classes
the layout stage actually found on the page (`product-card`, `review-card`...), plus
the author's own design tokens carried verbatim into `:root`. A stylesheet inventing
classes the tree does not carry styles nothing and bloats every page load.

SIZE MATTERS: this ships in `_aios_design_css` post meta on every rebuilt page. The
reference site's own design system is 93KB; this aims an order of magnitude lower by
styling components once rather than elements each.
"""

from __future__ import annotations

from app.services.design_system import DesignSystem
from app.services.layout_infer import InferredPage

MAX_CSS_BYTES = 24_000


def generate(page: InferredPage, ds: DesignSystem,
             author_vars: dict[str, str] | None = None) -> str:
    out: list[str] = []
    surface = ds.palette.get("surface", "#f5f5f5")
    border = ds.palette.get("border", "#e5e7eb")
    radius = (ds.radius_scale[len(ds.radius_scale) // 2]
              if ds.radius_scale else 8)

    # The author's own tokens, verbatim - their names are their documentation.
    author_vars = author_vars or {}
    own = {k: v for k, v in author_vars.items()
           if not k.startswith(("--e-global", "--elementor", "--wp", "--ast", "--kit"))}
    if own:
        decls = "".join(f"{k}:{v};" for k, v in sorted(own.items()))
        out.append(f":root{{{decls}}}")

    # Images inside any rebuilt page behave like the source's: fill their box.
    out.append(
        "[data-elementor-type] .elementor-widget-image img"
        "{max-width:100%;height:auto;display:block}"
    )

    for comp in page.components:
        name = comp.name
        # the card itself
        out.append(
            f".{name}{{background:#ffffff;border:1px solid {border};"
            f"border-radius:{radius}px;overflow:hidden}}"
        )
        # its image child fills and crops - a natural-size placeholder in a 25%
        # column is a postage stamp; the source stretches it to the card
        out.append(
            f".{name}__image img,.elementor-widget.{name}__image img"
            f"{{width:100%;aspect-ratio:4/3;object-fit:cover;background:{surface}}}"
        )
    css = "\n".join(out)
    if len(css) > MAX_CSS_BYTES:
        css = css[:MAX_CSS_BYTES]
    return css
