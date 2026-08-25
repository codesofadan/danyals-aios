"""Measure a page well enough to REBUILD it (design replication, stage 1).

`site_analyzer.capture()` answers "what does this site look like, roughly" - 24
top-level blocks, 7 computed properties, `getBoundingClientRect()` called and x/y
thrown away. Measured against the reference page it finds 4 sections where the page
actually has 42. That is fine for the brand-kit job it was built for and useless for
rebuilding a layout.

This is a SECOND capture path beside it. `site_analyzer` is deliberately untouched:
`visual_diff.diff_design_against_capture` and `site_builder.design_ir_from_capture`
both consume its exact shape, and regressing them to add a feature they do not use
would be a poor trade.

WHAT MAKES THE PAYLOAD SURVIVABLE. A real page is ~1,300 layout-bearing elements and
34 properties each - naively ~0.9MB per viewport, ~2.8MB for three. Four levers, in
the order they matter:

  1. STYLE INTERNING. Computed styles repeat enormously - every card in a grid resolves
     identically. Styles are deduplicated into a table and each node stores an INDEX.
     Lossless, and the single biggest win.
  2. PRUNE TO LAYOUT-BEARING NODES. A node is kept when it holds text, is a replaced
     element, PAINTS something its parent does not, or contains a real row of children.
     Everything else is div soup that describes no layout.
  3. COLLAPSE WRAPPER CHAINS, merging the wrapper's classes into its child. Themes nest
     four divs to draw one card; the classes are the part worth keeping, because BEM
     names live on the wrappers.
  4. HARD CAPS, then a size guard that drops the deepest level and says so.

DOCUMENT COORDINATES, NOT VIEWPORT. `rect.x + scrollX`. A viewport-relative y is
meaningless for a page taller than the window, and layout inference is entirely about
where things sit relative to each other.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# The properties that decide how a box looks and where it sits. Chosen to cover what
# Elementor has a control for (so it can be re-emitted as a setting) plus what a real
# design system's CSS actually declares.
CAPTURED_PROPS: tuple[str, ...] = (
    # flow
    "display", "flexDirection", "flexWrap", "justifyContent", "alignItems",
    "gap", "gridTemplateColumns", "position",
    # box
    "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
    "marginTop", "marginRight", "marginBottom", "marginLeft",
    "width", "maxWidth", "minHeight",
    # paint
    "backgroundColor", "backgroundImage", "backgroundSize", "backgroundPosition",
    "borderRadius", "boxShadow", "borderTopWidth", "borderTopColor", "borderTopStyle",
    "opacity", "transform",
    # type
    "fontFamily", "fontSize", "fontWeight", "lineHeight", "letterSpacing",
    "textTransform", "textAlign", "color",
)

MAX_NODES = 1400
MAX_DEPTH = 14
MAX_TEXT = 400
# Above this the capture drops its deepest level and retries, flagging `truncated`.
MAX_PAYLOAD_BYTES = 1_800_000

DEFAULT_VIEWPORTS: tuple[tuple[str, int, int], ...] = (
    ("desktop", 1440, 900),
    ("tablet", 834, 1194),
    ("mobile", 390, 844),
)


def _extractor_js() -> str:
    """The in-page extractor, built with the property list injected.

    Kept as a function rather than a constant so `CAPTURED_PROPS` stays the single
    source of truth - a property added there is captured, indexed and named on the
    Python side with no second edit.
    """
    props = json.dumps(list(CAPTURED_PROPS))
    return _JS_TEMPLATE.replace("__PROPS__", props).replace(
        "__MAX_NODES__", str(MAX_NODES)).replace(
        "__MAX_DEPTH__", str(MAX_DEPTH)).replace("__MAX_TEXT__", str(MAX_TEXT))


_JS_TEMPLATE = """
(() => {
  const PROPS = __PROPS__;
  const MAX_NODES = __MAX_NODES__, MAX_DEPTH = __MAX_DEPTH__, MAX_TEXT = __MAX_TEXT__;
  const SKIP = new Set(['SCRIPT','STYLE','NOSCRIPT','TEMPLATE','SVG','CANVAS',
                        'LINK','META','BR','HEAD']);
  const REPLACED = new Set(['IMG','PICTURE','VIDEO','IFRAME','SVG','CANVAS']);
  // Hashed CSS-in-JS class names carry no meaning and inflate the payload.
  const GENERATED = /^(css-|sc-|jsx-|emotion-|[A-Za-z]+_[A-Za-z0-9]{5,}$)/;
  // Framework classes are kept but rank BEHIND the author's own. The cap used to be
  // applied in DOM order, and an Elementor column carries eight of its own classes
  // before the author's - so `product-card`, sitting last in the attribute, was cut
  // by the cap on every single card. The author's classes are the BEM names the
  // whole component-detection stage keys on; the framework's are reconstructible.
  const FRAMEWORK = /^(elementor|e-|wp-|ast-|has-|is-|aios-|et_|fl-|vc_|fusion-)/;
  const classesOf = (el) => {
    if (!el.className || typeof el.className !== 'string') return [];
    const all = el.className.trim().split(/\\s+/).filter(c => c && !GENERATED.test(c));
    const own = all.filter(c => !FRAMEWORK.test(c));
    const fw = all.filter(c => FRAMEWORK.test(c));
    return own.concat(fw).slice(0, 10);
  };

  const styles = [], styleIx = new Map();
  const intern = (cs) => {
    const vals = PROPS.map(p => cs[p] == null ? '' : String(cs[p]));
    const key = vals.join('\\u0001');
    let i = styleIx.get(key);
    if (i === undefined) { i = styles.length; styles.push(vals); styleIx.set(key, i); }
    return i;
  };

  const px = (v) => { const n = parseFloat(v); return isNaN(n) ? 0 : n; };
  const paints = (cs, pcs) => {
    if (cs.backgroundColor !== pcs.backgroundColor &&
        cs.backgroundColor !== 'rgba(0, 0, 0, 0)') return true;
    if (cs.backgroundImage && cs.backgroundImage !== 'none') return true;
    if (px(cs.borderTopWidth) > 0) return true;
    if (px(cs.borderRadius) > 0) return true;
    if (cs.boxShadow && cs.boxShadow !== 'none') return true;
    if (px(cs.paddingTop) >= 8 || px(cs.paddingLeft) >= 8) return true;
    return false;
  };
  const ownText = (el) => {
    let t = '';
    for (const n of el.childNodes) if (n.nodeType === 3) t += n.nodeValue;
    return t.replace(/\\s+/g, ' ').trim();
  };
  const kids = (el) => Array.from(el.children).filter(c => !SKIP.has(c.tagName));
  // A real row: two or more children whose vertical extents overlap.
  const hasRow = (el) => {
    const cs = kids(el).map(c => c.getBoundingClientRect()).filter(r => r.height > 4);
    for (let i = 0; i < cs.length; i++)
      for (let j = i + 1; j < cs.length; j++) {
        const a = cs[i], b = cs[j];
        const ov = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (ov > 0.5 * Math.min(a.height, b.height)) return true;
      }
    return false;
  };

  let count = 0, truncated = false;
  const sx = window.scrollX, sy = window.scrollY;

  function walk(el, depth, pcs) {
    if (count >= MAX_NODES) { truncated = true; return null; }
    if (SKIP.has(el.tagName)) return null;
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden') return null;
    if (r.width < 1 || r.height < 1) return null;

    let children = [];
    if (depth < MAX_DEPTH) {
      for (const c of kids(el)) {
        const n = walk(c, depth + 1, cs);
        if (n) children.push(n);
      }
    } else if (kids(el).length) { truncated = true; }

    const text = ownText(el).slice(0, MAX_TEXT);
    const replaced = REPLACED.has(el.tagName);
    const keep = !!text || replaced || paints(cs, pcs) || children.length >= 2 ||
                 (children.length && hasRow(el));

    // Collapse: a wrapper that draws nothing and holds one child is noise - but its
    // CLASSES are not, because BEM names sit on wrappers.
    if (!keep && children.length === 1) {
      const only = children[0];
      const merged = Array.from(new Set([...classesOf(el), ...(only.cls || [])]));
      const own = merged.filter(c => !FRAMEWORK.test(c));
      only.cls = own.concat(merged.filter(c => FRAMEWORK.test(c))).slice(0, 10);
      return only;
    }
    if (!keep && children.length === 0) return null;

    count++;
    const cls = classesOf(el);
    const node = {
      t: el.tagName.toLowerCase(),
      s: intern(cs),
      box: [Math.round(r.x + sx), Math.round(r.y + sy),
            Math.round(r.width), Math.round(r.height)],
    };
    if (cls.length) node.cls = cls;
    if (el.id) node.eid = el.id;
    if (text) node.txt = text;
    if (el.tagName === 'A' && el.getAttribute('href')) node.href = el.getAttribute('href');
    if (el.tagName === 'IMG') {
      node.src = el.currentSrc || el.getAttribute('src') || '';
      node.alt = el.getAttribute('alt') || '';
      if (el.naturalWidth) node.nat = [el.naturalWidth, el.naturalHeight];
    }
    if (children.length) node.kids = children;
    return node;
  }

  // Content root: an Elementor page states its own boundary; otherwise main/article.
  const root = document.querySelector('[data-elementor-type]') ||
               document.querySelector('main') ||
               document.querySelector('article') || document.body;

  const tree = walk(root, 0, getComputedStyle(document.body));

  // :root custom properties - the source author's own design tokens.
  const vars = {};
  try {
    const rs = getComputedStyle(document.documentElement);
    for (let i = 0; i < rs.length; i++) {
      const p = rs.item(i);
      if (p && p.startsWith('--')) vars[p] = rs.getPropertyValue(p).trim().slice(0, 120);
    }
  } catch (e) { /* engine-dependent; the stylesheet scan below is the fallback */ }
  if (Object.keys(vars).length === 0) {
    try {
      for (const sheet of Array.from(document.styleSheets)) {
        let rules; try { rules = sheet.cssRules; } catch (e) { continue; }
        for (const rule of Array.from(rules || [])) {
          if (rule.style && rule.selectorText === ':root') {
            for (let i = 0; i < rule.style.length; i++) {
              const p = rule.style[i];
              if (p.startsWith('--')) vars[p] = rule.style.getPropertyValue(p).trim().slice(0,120);
            }
          }
        }
      }
    } catch (e) { /* cross-origin sheets are opaque; report what we got */ }
  }

  const fonts = Array.from(document.querySelectorAll('link[rel=stylesheet]'))
    .map(l => l.href).filter(h => /fonts\\.(googleapis|gstatic)/.test(h)).slice(0, 10);

  return {
    url: location.href,
    title: document.title || '',
    lang: document.documentElement.lang || '',
    docHeight: Math.round(document.documentElement.scrollHeight),
    props: PROPS,
    styles: styles,
    tree: tree,
    vars: vars,
    fonts: fonts,
    nodeCount: count,
    truncated: truncated,
  };
})()
"""


@dataclass
class ReplicaNode:
    """One layout-bearing element, with its style resolved from the intern table."""

    tag: str
    box: tuple[int, int, int, int]  # x, y, w, h in DOCUMENT coordinates
    style: dict[str, str] = field(default_factory=dict)
    classes: tuple[str, ...] = ()
    element_id: str = ""
    text: str = ""
    href: str = ""
    src: str = ""
    alt: str = ""
    natural: tuple[int, int] | None = None
    children: list[ReplicaNode] = field(default_factory=list)

    @property
    def x(self) -> int: return self.box[0]
    @property
    def y(self) -> int: return self.box[1]
    @property
    def width(self) -> int: return self.box[2]
    @property
    def height(self) -> int: return self.box[3]
    @property
    def right(self) -> int: return self.box[0] + self.box[2]
    @property
    def bottom(self) -> int: return self.box[1] + self.box[3]

    def walk(self) -> list[ReplicaNode]:
        out = [self]
        for c in self.children:
            out.extend(c.walk())
        return out


@dataclass
class ReplicaViewport:
    viewport: str
    width: int
    height: int
    root: ReplicaNode | None = None
    doc_height: int = 0
    node_count: int = 0
    truncated: bool = False


@dataclass
class ReplicaCapture:
    url: str
    title: str = ""
    lang: str = ""
    viewports: list[ReplicaViewport] = field(default_factory=list)
    css_vars: dict[str, str] = field(default_factory=dict)
    font_links: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def viewport(self, name: str) -> ReplicaViewport | None:
        return next((v for v in self.viewports if v.viewport == name), None)

    @property
    def desktop(self) -> ReplicaViewport | None:
        return self.viewport("desktop") or (self.viewports[0] if self.viewports else None)


def _node_from(raw: dict[str, Any], styles: list[list[str]], props: list[str]) -> ReplicaNode:
    idx = raw.get("s")
    vals = styles[idx] if isinstance(idx, int) and 0 <= idx < len(styles) else []
    style = {p: v for p, v in zip(props, vals, strict=False) if v}
    box = raw.get("box") or [0, 0, 0, 0]
    nat = raw.get("nat")
    return ReplicaNode(
        tag=str(raw.get("t") or ""),
        box=(int(box[0]), int(box[1]), int(box[2]), int(box[3])),
        style=style,
        classes=tuple(raw.get("cls") or ()),
        element_id=str(raw.get("eid") or ""),
        text=str(raw.get("txt") or ""),
        href=str(raw.get("href") or ""),
        src=str(raw.get("src") or ""),
        alt=str(raw.get("alt") or ""),
        natural=(int(nat[0]), int(nat[1])) if nat else None,
        children=[_node_from(k, styles, props) for k in (raw.get("kids") or [])],
    )


def parse_extraction(raw: dict[str, Any]) -> tuple[ReplicaNode | None, dict[str, Any]]:
    """Rehydrate one viewport's extraction into a node tree plus its page-level facts."""
    styles = raw.get("styles") or []
    props = raw.get("props") or list(CAPTURED_PROPS)
    tree = raw.get("tree")
    root = _node_from(tree, styles, props) if isinstance(tree, dict) else None
    return root, raw


def capture_replica(
    url: str,
    *,
    viewports: tuple[tuple[str, int, int], ...] = DEFAULT_VIEWPORTS,
    timeout_ms: int = 45_000,
    settle_ms: int = 500,
) -> ReplicaCapture:
    """Measure ``url`` at each viewport into a node tree.

    Total: never raises. A page that will not load, a missing browser, or a hostile
    document all degrade into a capture carrying `notes` and no viewports - the caller
    reports that rather than crashing a worker on a site it does not control.
    """
    notes: list[str] = []
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return ReplicaCapture(url=url, notes=("playwright is not installed",))

    js = _extractor_js()
    out = ReplicaCapture(url=url)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(args=["--disable-dev-shm-usage"])
            try:
                page = browser.new_page(viewport={"width": viewports[0][1],
                                                  "height": viewports[0][2]})
                page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                for name, width, height in viewports:
                    page.set_viewport_size({"width": width, "height": height})
                    # Lazy-loaded imagery only resolves once it has been near the
                    # viewport, and a page rebuilt without its images is not a rebuild.
                    page.evaluate(
                        "() => new Promise(r => { let y = 0; const t = setInterval(() => {"
                        " window.scrollTo(0, y); y += window.innerHeight;"
                        " if (y > document.body.scrollHeight) { clearInterval(t);"
                        " window.scrollTo(0, 0); r(); } }, 40); })"
                    )
                    page.wait_for_timeout(settle_ms)
                    raw = page.evaluate(js)
                    root, meta = parse_extraction(raw)
                    out.viewports.append(ReplicaViewport(
                        viewport=name, width=width, height=height, root=root,
                        doc_height=int(meta.get("docHeight") or 0),
                        node_count=int(meta.get("nodeCount") or 0),
                        truncated=bool(meta.get("truncated")),
                    ))
                    if name == viewports[0][0]:
                        out.title = str(meta.get("title") or "")
                        out.lang = str(meta.get("lang") or "")
                        out.css_vars = dict(meta.get("vars") or {})
                        out.font_links = tuple(meta.get("fonts") or ())
            finally:
                browser.close()
    except Exception as exc:
        notes.append(f"capture failed: {type(exc).__name__}: {str(exc)[:160]}")

    for vp in out.viewports:
        if vp.truncated:
            notes.append(
                f"{vp.viewport}: the node budget was reached, so the deepest level was "
                "dropped - the rebuild will be shallower than the source"
            )
    if not out.css_vars:
        notes.append("no :root custom properties were readable (cross-origin stylesheets?)")
    out.notes = tuple(notes)
    return out
