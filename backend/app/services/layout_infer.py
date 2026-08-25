"""Rendered boxes -> Elementor structure (replication stage 3).

THIS IS WHERE THE FIRST ATTEMPT DIED. It walked the HTML in document order and emitted
every block into a single column, producing 31 single-column sections for a page whose
real tree is 19-multi-column-out-of-42. The lesson is structural: an HTML parser sees
ORDER, and only geometry sees LAYOUT - two cards side by side are adjacent in the
markup and 312px apart on the screen, and the second fact is the layout.

INFERENCE USES GEOMETRY ONLY. No Elementor class names, no framework heuristics -
the input may be a hand-coded page with none. But the fixture this module is graded
against happens to BE an Elementor page, so its own `elementor-col-N` classes ride
along in the capture as ground truth: every inferred column width is checked against
the class the source itself declared, across the whole page. The inference never reads
those classes; the tests do.

THE CORE MOVES:

  ROW CLUSTERING. Children of a content node are clustered by vertical overlap - two
  boxes sharing >50% of the shorter one's height sit in one row. A single-item cluster
  that paints nothing and holds children is a row GROUP and recurses; one that paints
  (a card with its own background) is content and does not.

  COLUMN WIDTHS FROM GAPS BETWEEN STARTS, not from each box's own width. For all but
  the last column the width is `x[i+1] - x[i]`; the last takes the remaining span.
  This absorbs gutters, so four 312px cards in a 1248px container come out at exactly
  25/25/25/25 instead of four odd fractions plus three orphaned gaps.

  SNAP, THEN NORMALISE TO EXACTLY 100. Widths snap to Elementor's ladder and the
  remainder lands on the widest column - 3 columns are 33+33+34, never the 99% the
  old `100 // cols` produced.

  OVERLAYS ARE REFUSED, NOT GUESSED AT. Two boxes overlapping in x are not columns -
  they are an overlay (a badge over an image, an absolutely positioned ribbon). The
  row degrades to a single column carrying a note, because a wrong guess here becomes
  a broken page on a client's site while a conservative one merely loses a flourish.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

# Elementor's column-width ladder. `structure` presets place columns on these stops;
# widths measured off a real page land within a point or two of one.
WIDTH_LADDER: tuple[int, ...] = (100, 80, 75, 70, 66, 60, 50, 40, 33, 30, 25, 20, 16)
SNAP_TOLERANCE = 4

# A band shorter than this is a separator artefact, not a section.
MIN_SECTION_HEIGHT = 40
# A candidate narrower than half the viewport is a floating fragment, not a band.
MIN_SECTION_WIDTH_FRACTION = 0.5

# Vertical-overlap fraction (of the shorter box) that makes two boxes row-mates.
ROW_OVERLAP = 0.5

# A cluster only becomes COLUMNS when its items are containers. Measured on the
# reference page: every real column band is 200-900px tall, while every false
# positive - filter pills, 1px decorative slivers, inline footer headings - is at
# most 36px. A row of short items is an inline group (a button row, a nav strip)
# and belongs INSIDE one column, not spread across four.
MIN_COLUMN_ITEM_HEIGHT = 40

# ...and no real column is a sliver. A filter pill measures ~122px in a 1236px
# container (10%); the narrowest genuine column on the reference page is 20%. Items
# under this fraction are an inline strip riding inside one column.
MIN_COLUMN_WIDTH_FRACTION = 0.12

# Widget vocabulary the emitter accepts - the closed switch. An unknown type raises
# HERE, in Python, before anything reaches a client's site.
WIDGET_TYPES: frozenset[str] = frozenset({
    "heading", "text-editor", "image", "button", "icon-list", "icon-box",
    "star-rating", "testimonial", "icon", "accordion", "divider",
    "google_maps", "social-icons", "spacer",
})

_SOCIAL_HOSTS = ("facebook.com", "instagram.com", "twitter.com", "x.com",
                 "linkedin.com", "youtube.com", "tiktok.com", "wa.me", "whatsapp.com")

_GENERIC_CLASSES = (
    "elementor", "e-con", "e-parent", "e-child", "wp-", "has-", "align",
    "container", "wrapper", "inner", "row", "col-", "grid", "section",
)


# --------------------------------------------------------------------------- #
# Node helpers (input is the raw capture dict: {t, box, s, cls, txt, kids...})
# --------------------------------------------------------------------------- #
def _box(n: dict[str, Any]) -> tuple[int, int, int, int]:
    b = n.get("box") or [0, 0, 0, 0]
    return int(b[0]), int(b[1]), int(b[2]), int(b[3])


def _kids(n: dict[str, Any]) -> list[dict[str, Any]]:
    return list(n.get("kids") or [])


def _style(n: dict[str, Any]) -> dict[str, str]:
    return n.get("s") or {}


def _paints(n: dict[str, Any]) -> bool:
    """Whether this node draws something of its own - a background, border or shadow.

    A painting node is CONTENT (a card); a non-painting one is scaffolding the layout
    can see through. The distinction decides whether a single-item cluster recurses.
    """
    s = _style(n)
    bg = (s.get("backgroundColor") or "").strip()
    if bg and bg not in ("rgba(0, 0, 0, 0)", "transparent"):
        return True
    if (s.get("backgroundImage") or "none") != "none":
        return True
    if (s.get("boxShadow") or "none") != "none":
        return True
    try:
        if float((s.get("borderTopWidth") or "0").rstrip("px")) > 0:
            return True
    except ValueError:
        pass
    return False


def _own_classes(n: dict[str, Any]) -> list[str]:
    """The node's meaningful classes - the BEM names, not the framework's."""
    out = []
    for c in n.get("cls") or []:
        low = c.lower()
        if any(g in low for g in _GENERIC_CLASSES):
            continue
        out.append(c)
    return out


def _gather_classes(item: dict[str, Any], *, max_depth: int = 3) -> tuple[str, ...]:
    """Own-classes across the item's subtree, shallow-first, deduplicated.

    The BEM parent (`product-card`) usually sits a level below the column node -
    wrapper collapse merges it into a child - while the pieces
    (`product-card__title`) live deeper. Shallow-first order preserves that
    hierarchy for the component-naming vote.
    """
    seen: set[str] = set()
    out: list[str] = []
    frontier = [item]
    for _ in range(max_depth + 1):
        nxt: list[dict[str, Any]] = []
        for node in frontier:
            for cls in _own_classes(node):
                if cls not in seen:
                    seen.add(cls)
                    out.append(cls)
            nxt.extend(_kids(node))
        frontier = nxt
    return tuple(out[:12])


def _all_text(n: dict[str, Any]) -> str:
    parts = [n.get("txt") or ""]
    for k in _kids(n):
        parts.append(_all_text(k))
    return " ".join(p for p in parts if p)


# --------------------------------------------------------------------------- #
# Output shapes
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class InferredWidget:
    type: str
    node: dict[str, Any]
    classes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.type not in WIDGET_TYPES:
            raise ValueError(f"{self.type!r} is not an emittable widget type")


@dataclass(frozen=True)
class InferredColumn:
    width_pct: int
    x: int
    width_px: int
    widgets: tuple[InferredWidget, ...] = ()
    # A column may hold ROWS instead of widgets - Elementor's one legal nesting level
    # (section > column > inner section > column). The reference hero keeps a 50/50
    # stat pair inside its LEFT column and a 33/33/33 trio inside its right; flattening
    # them to a widget stack is precisely the "demolition" the first attempt shipped.
    rows: tuple[InferredRow, ...] = ()
    classes: tuple[str, ...] = ()
    background: str = ""

    @property
    def signature(self) -> tuple[str, ...]:
        return tuple(w.type for w in self.widgets)

    def all_columns(self) -> list[InferredColumn]:
        out: list[InferredColumn] = [self]
        for row in self.rows:
            for col in row.columns:
                out.extend(col.all_columns())
        return out


@dataclass(frozen=True)
class InferredRow:
    columns: tuple[InferredColumn, ...]
    y: int
    inner: bool = False
    notes: tuple[str, ...] = ()

    @property
    def structure(self) -> str | None:
        return f"{len(self.columns)}0" if len(self.columns) > 1 else None


@dataclass(frozen=True)
class InferredSection:
    y: int
    height: int
    full_bleed: bool
    rows: tuple[InferredRow, ...]
    background: str = ""
    # A band's imagery usually lives on a child spanning the band, not on the
    # section element - the reference hero is a white <section> whose dark look IS
    # its backdrop image. Dropping it turned the hero white with invisible text.
    background_image: str = ""
    classes: tuple[str, ...] = ()
    element_id: str = ""

    @property
    def multi_column(self) -> bool:
        return any(
            len(r.columns) > 1 or any(c.rows for c in r.columns) for r in self.rows
        )


@dataclass(frozen=True)
class Component:
    """A repeated structure - the thing a BEM class names."""

    name: str
    signature: tuple[str, ...]
    count: int


@dataclass(frozen=True)
class InferredPage:
    sections: tuple[InferredSection, ...]
    container_px: int
    components: tuple[Component, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def multi_column_sections(self) -> int:
        return sum(1 for s in self.sections if s.multi_column)


# --------------------------------------------------------------------------- #
# Width snapping
# --------------------------------------------------------------------------- #
def snap_widths(raw_pcts: list[float]) -> list[int]:
    """Snap to the ladder, then normalise so every row sums to EXACTLY 100.

    The old `100 // cols` gave 33+33+33 = 99: Elementor renders it, slightly wrong,
    forever.

    TWO RULES EARNED BY AN ADVERSARIAL REVIEW THAT EXECUTED THE FAILURES:

    - THE LADDER STOPS AT FIVE COLUMNS. Its floor is 16, and 100/n for n >= 6 sits
      within snap tolerance of it - so every column of an 8-across strip snapped to
      16 and the whole -28 correction landed on one column: measured output
      [-12, 16, 16, 16, 16, 16, 16, 16]. A NEGATIVE column width, published. Six or
      more columns use an even split directly; Elementor accepts any _inline_size.
    - THE CORRECTION IS SPREAD, ONE POINT AT A TIME, to the columns whose snap error
      is largest - never dumped on a single column. Dumping it is how an equal
      6-across logo strip rendered 20/16/16/16/16/16.
    """
    n = len(raw_pcts)
    if n == 0:
        return []
    if n >= 6:
        base, rem = divmod(100, n)
        return [base + (1 if i < rem else 0) for i in range(n)]

    snapped: list[int] = []
    for pct in raw_pcts:
        best = min(WIDTH_LADDER, key=lambda w: abs(w - pct))
        snapped.append(best if abs(best - pct) <= SNAP_TOLERANCE else max(1, round(pct)))
    diff = 100 - sum(snapped)
    step = 1 if diff > 0 else -1
    guard = 0
    while diff != 0 and guard < 200:
        # give/take one point where it distorts the least: the column whose current
        # value is furthest from its raw measurement in the correcting direction
        errors = [(snapped[i] - raw_pcts[i]) * step for i in range(n)]
        idx = errors.index(min(errors))
        if snapped[idx] + step < 1:
            idx = snapped.index(max(snapped))
        snapped[idx] += step
        diff -= step
        guard += 1
    return snapped


# --------------------------------------------------------------------------- #
# Widget classification - the closed switch
# --------------------------------------------------------------------------- #
def classify(node: dict[str, Any]) -> str | None:
    """One captured node -> an emittable widget type, or None for scaffolding.

    Deliberately conservative: None is the common answer. A wrong classification puts
    the wrong control in the editor; an unclassified node's text still arrives via its
    parent's text-editor.
    """
    tag = node.get("t") or ""
    text = (node.get("txt") or "").strip()
    s = _style(node)
    kids = _kids(node)

    if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        return "heading"
    if tag == "img" or (node.get("src") and tag != "iframe"):
        return "image"
    if tag == "iframe":
        return "google_maps" if "google.com/maps" in (node.get("src") or "") else None
    if tag == "hr":
        return "divider"
    if tag == "blockquote":
        return "testimonial"
    if tag in ("a", "button"):
        href = node.get("href") or ""
        if any(h in href for h in _SOCIAL_HOSTS):
            return "social-icons"
        padded = False
        try:
            padded = float((s.get("paddingLeft") or "0").rstrip("px")) >= 8
        except ValueError:
            padded = False
        if not text:
            # the label often lives on a child span - an <a> wrapper is judged by
            # what it contains, not by its own (empty) text node
            text = _all_text(node).strip()
        if _paints(node) or padded:
            return "button"
        if len(text) >= 12:
            # A plain link with a sentence of text is CONTENT, not chrome - the
            # reference page's FAQ questions are bare <a> elements, and dropping
            # them emptied the whole FAQ band.
            return "text-editor"
        return None  # a short plain link rides inside its parent's text
    if tag in ("ul", "ol"):
        # A list whose items each open with an icon is an icon-list; a star row is a
        # rating. Both need the children to say so; a plain list stays with the text.
        item_text = _all_text(node)
        stars = item_text.count("★") + item_text.count("⭐")
        if stars >= 3:
            return "star-rating"
        return "icon-list" if kids and all(
            _kids(k) or (k.get("cls") and any("icon" in c for c in k.get("cls") or []))
            for k in kids[:4]
        ) else None
    if tag in ("p", "span", "div") and text:
        stars = text.count("★") + text.count("⭐")
        if stars >= 3 and len(text) <= 24:
            return "star-rating"
        if tag == "p" or not kids:
            return "text-editor"
    if tag in ("i", "svg") and not text:
        return "icon"
    if tag == "details":
        return "accordion"
    if tag in ("div", "figure", "span") and not text and not kids:
        # A PAINTED EMPTY BOX is content, not scaffolding. Measured case: a 2x2
        # photo collage rendered as four 271x204 divs carrying background-image and
        # nothing else - classifying them None dropped the whole grid, because a row
        # with zero widgets is discarded. A background-image tile IS an image; a
        # plain painted tile is Elementor's free `spacer` carrying its background.
        b = _box(node)
        if (s.get("backgroundImage") or "none") != "none":
            return "image"
        if _paints(node) and b[2] >= 60 and b[3] >= 60:
            return "spacer"
    return None


def _collect_widgets(node: dict[str, Any], out: list[InferredWidget]) -> None:
    kind = classify(node)
    if kind is not None:
        out.append(InferredWidget(
            type=kind, node=node, classes=tuple(_own_classes(node))))
        if kind in ("icon-list", "star-rating", "testimonial", "accordion", "button",
                    "image", "google_maps"):
            return  # composite widgets own their subtree
    for k in _kids(node):
        _collect_widgets(k, out)


# --------------------------------------------------------------------------- #
# Rows and columns
# --------------------------------------------------------------------------- #
def _cluster_rows(children: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Cluster siblings into rows by vertical overlap."""
    items = sorted((c for c in children if _box(c)[3] > 4), key=lambda c: _box(c)[1])
    rows: list[list[dict[str, Any]]] = []
    for item in items:
        _, y, _, h = _box(item)
        placed = False
        for row in rows:
            # Overlap with EVERY member, not just the first. Testing only row[0]
            # let one tall item chain bands that share zero overlap with each
            # other into a single "row", which then x-overlapped and flattened a
            # genuine multi-column section to one column.
            def overlaps(member: dict[str, Any], _y: int = y, _h: int = h) -> bool:
                _, my, _, mh = _box(member)
                ov = min(_y + _h, my + mh) - max(_y, my)
                return ov > ROW_OVERLAP * min(_h, mh)

            if all(overlaps(m) for m in row):
                row.append(item)
                placed = True
                break
        if not placed:
            rows.append([item])
    return rows


def _x_overlaps(items: list[dict[str, Any]]) -> bool:
    boxes = sorted((_box(i) for i in items), key=lambda b: b[0])
    # 8px of slack for sub-pixel rounding.
    return any(a[0] + a[2] > b[0] + 8 for a, b in pairwise(boxes))


def _column_widths(items: list[dict[str, Any]]) -> list[float]:
    """Percent widths from the gaps between starts, over the ROW'S OWN span.

    The span runs from the first item's left edge to the last item's right edge -
    not an ancestor's box. Measured failure that forced this: a 4x352px gallery row
    sat in a wider band than the section's nominal content box, and dividing by the
    ancestor's width skewed a perfect quarter split into (33,30,30,7).
    """
    ordered = sorted(items, key=lambda i: _box(i)[0])
    xs = [_box(i)[0] for i in ordered]
    right = max(_box(i)[0] + _box(i)[2] for i in ordered)
    span = max(1, right - xs[0])

    # EVENLY SPACED STARTS MEAN EQUAL TRACKS. Content-sized items in equal columns
    # start on a regular grid even when their own widths differ - the reference
    # hero's right trio starts 141px then 137px apart (1.4% off equal) while the
    # items themselves are 106px of intrinsic text. Gap arithmetic on those gives
    # 42/33/25; the author wrote thirds. Three or more items whose start deltas sit
    # within 12% of their mean ARE an equal grid. (Two items have a single delta,
    # which is trivially "even" - the rule would force every 2-col row to 50/50, so
    # it applies only from three up.)
    if len(xs) >= 3:
        deltas = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
        mean = sum(deltas) / len(deltas)
        # Equal deltas alone are NOT enough: a genuine 25/25/50 row has equal start
        # deltas too, because the wide column is LAST and start positions never see
        # its width. Executed failure: 25/25/50 silently rewritten to 34/33/33. The
        # mean delta must also match the whole span divided by the count - i.e. the
        # last column's own track is as wide as everyone else's.
        track = span / len(xs)
        if (mean > 0 and all(abs(d - mean) <= mean * 0.12 for d in deltas)
                and abs(mean - track) <= track * 0.12):
            return [100.0 / len(xs)] * len(xs)

    gaps = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)] + [right - xs[-1]]
    return [max(0.0, g / span * 100) for g in gaps]


def _widget_extent(item: dict[str, Any]) -> tuple[int, int] | None:
    """The x-range actually occupied by an item's classifiable content."""
    xs: list[int] = []
    rights: list[int] = []

    def visit(n: dict[str, Any]) -> None:
        if classify(n) is not None:
            x, _, w, _ = _box(n)
            xs.append(x)
            rights.append(x + w)
            return
        for k in _kids(n):
            visit(k)

    visit(item)
    if not xs:
        return None
    return min(xs), max(rights)


def _shrink_to_content(cluster: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Shrink the widest item's box to its content extent, if that resolves overlap."""
    widest = max(cluster, key=lambda i: _box(i)[2])
    extent = _widget_extent(widest)
    if extent is None:
        return None
    x0, x1 = extent
    if x1 - x0 >= _box(widest)[2] * 0.9:
        return None  # the content fills the box; nothing to shrink
    shrunk = dict(widest)
    b = _box(widest)
    shrunk["box"] = [x0, b[1], max(1, x1 - x0), b[3]]
    return [shrunk if i is widest else i for i in cluster]


def _descend_to_content(node: dict[str, Any]) -> dict[str, Any]:
    """Skip single-child wrapper chains - a container is not content."""
    cursor = node
    while True:
        kids = _kids(cursor)
        if len(kids) != 1:
            return cursor
        cursor = kids[0]


def _rows_of(node: dict[str, Any], depth: int = 0) -> list[InferredRow]:
    """A content node's children, resolved into rows of columns."""
    if depth > 6:
        return []
    content = _descend_to_content(node)
    out: list[InferredRow] = []
    pending_notes: list[str] = []

    def emit(row: InferredRow) -> None:
        nonlocal pending_notes
        if pending_notes:
            row = InferredRow(columns=row.columns, y=row.y, inner=row.inner,
                              notes=(*pending_notes, *row.notes))
            pending_notes = []
        out.append(row)

    # BACKDROPS COME OUT BEFORE CLUSTERING. A hero's imagery spans the whole band,
    # so it vertically overlaps every real row - and the clustering rule chains
    # items through whatever they overlap, so one 420px image glued three unrelated
    # bands into a single "row" (measured on the reference hero). A backdrop is wide
    # AND tall: a full-width strip only 45px high is a content band, not scenery.
    _cx, _cy, _cw, _ch = _box(content)
    kids_all = _kids(content)
    children = []
    for child in kids_all:
        _, _, w, h = _box(child)
        # Size alone does not make a backdrop - a column wrapper is also full-size.
        # The defining property is GLUING: a backdrop vertically overlaps multiple
        # siblings, which is exactly how one image chained three unrelated bands
        # into a single cluster. First cut of this rule skipped the sibling check
        # and ate the product grid's own container, flattening the whole section:
        # 57% -> 28% on the self-grade, immediately.
        glued = 0
        for other in kids_all:
            if other is child:
                continue
            _, oy, _, oh = _box(other)
            _, cy2, _, ch2 = _box(child)
            overlap = min(cy2 + ch2, oy + oh) - max(cy2, oy)
            if oh and overlap > 0.5 * oh:
                glued += 1
        if (_cw and _ch and w >= _cw * 0.85 and h >= _ch * 0.6 and glued >= 2):
            widgets_bd: list[InferredWidget] = []
            _collect_widgets(child, widgets_bd)
            textual = [x for x in widgets_bd if x.type != "image"]
            if textual:
                emit(InferredRow(
                    columns=(InferredColumn(
                        width_pct=100, x=_box(child)[0], width_px=w,
                        widgets=tuple(textual), classes=_gather_classes(child)),),
                    y=_box(child)[1], inner=depth > 0,
                    notes=("content lifted from a backdrop-sized element",),
                ))
            continue
        children.append(child)


    # Absolutely positioned items: overlay or layout? `position: absolute` alone
    # decides nothing - measured on the reference hero, the author ANCHORS a real
    # 3-column strip absolutely (and Elementor's own truth declares it col-33 x3),
    # while an award ribbon anchored OVER text is the overlay the refusal exists
    # for. The distinguishing property is COVERAGE: an anchored element whose box
    # overlaps the content extent of an in-flow sibling in its y-band is an overlay
    # and comes out; one occupying clear space is layout, approximated as a column
    # (the closest thing legacy Elementor can express), and says so.
    anchored = [c for c in children
                if (_style(c).get("position") or "") in ("absolute", "fixed")]
    for item in anchored:
        ax, ay, aw, ah = _box(item)
        covers = False
        for sib in children:
            if sib is item or sib in anchored:
                continue
            _, sy, _, sh = _box(sib)
            if min(ay + ah, sy + sh) - max(ay, sy) <= 0:
                continue  # different y-band
            extent = _widget_extent(sib) or (_box(sib)[0], _box(sib)[0] + _box(sib)[2])
            if ax < extent[1] - 8 and ax + aw > extent[0] + 8:
                covers = True
                break
        if covers:
            children = [c for c in children if c is not item]
            pending_notes.append(
                f"an absolutely-positioned element at y={ay} overlaps in-flow "
                "content and was left out: overlays are not columns"
            )
        else:
            pending_notes.append(
                f"an absolutely-positioned element at y={ay} occupies clear space "
                "and was approximated as an in-flow column"
            )

    for cluster in _cluster_rows(children):
        if len(cluster) == 1:
            item = cluster[0]
            # A non-painting stack is a row GROUP: its children are more rows.
            if _kids(item) and not _paints(item) and not (item.get("txt") or "").strip():
                for sub_row in _rows_of(item, depth + 1):
                    emit(sub_row)  # not extend: pending notes must reach a row
                continue
            widgets: list[InferredWidget] = []
            _collect_widgets(item, widgets)
            if not widgets:
                continue
            emit(InferredRow(
                columns=(InferredColumn(
                    width_pct=100, x=_box(item)[0], width_px=_box(item)[2],
                    widgets=tuple(widgets), classes=tuple(_own_classes(item)),
                    background=_style(item).get("backgroundColor", ""),
                ),),
                y=_box(item)[1], inner=depth > 0,
            ))
            continue

        notes: list[str] = []
        cx, _, cw, _ = _box(content)

        # A BACKDROP is not a column. A hero keeps its imagery as an absolutely
        # positioned child spanning the whole band, overlapping every real column -
        # refusing the cluster as "an overlay" threw away the hero's actual 50/50
        # split (measured: the reference hero's two columns at y=516 were lost
        # exactly this way). An item covering >=85% of the content width while
        # others sit on top is the section's background; lift it out and cluster
        # the rest as normal.
        backdrops = [i for i in cluster if _box(i)[2] >= cw * 0.85]
        rest = [i for i in cluster if i not in backdrops]
        if backdrops and len(rest) >= 1:
            for b in backdrops:
                widgets_b: list[InferredWidget] = []
                _collect_widgets(b, widgets_b)
                imgs = [w for w in widgets_b if w.type == "image"]
                if imgs:
                    notes.append(
                        f"a full-width image at y={_box(b)[1]} was treated as the "
                        "band's backdrop, not a column"
                    )
            for b in backdrops:
                widgets_b2: list[InferredWidget] = []
                _collect_widgets(b, widgets_b2)
                textual = [w for w in widgets_b2 if w.type != "image"]
                if textual and len(rest) >= 2:
                    # The backdrop's own content must not vanish with it - a wide
                    # marquee strip is a backdrop by geometry and content by nature.
                    emit(InferredRow(
                        columns=(InferredColumn(
                            width_pct=100, x=_box(b)[0], width_px=_box(b)[2],
                            widgets=tuple(textual), classes=_gather_classes(b)),),
                        y=_box(b)[1], inner=depth > 0,
                        notes=("content lifted from a backdrop-sized element",),
                    ))
            cluster = rest if len(rest) >= 2 else cluster
            if len(cluster) == 1:
                item = cluster[0]
                widgets = []
                _collect_widgets(item, widgets)
                if widgets:
                    emit(InferredRow(
                        columns=(InferredColumn(
                            width_pct=100, x=_box(item)[0], width_px=_box(item)[2],
                            widgets=tuple(widgets), classes=_gather_classes(item),
                            background=_style(item).get("backgroundColor", ""),
                        ),),
                        y=_box(item)[1], inner=depth > 0, notes=tuple(notes),
                    ))
                continue

        narrowest = min(_box(i)[2] for i in cluster)
        span_right = max(_box(i)[0] + _box(i)[2] for i in cluster)
        row_span = max(1, span_right - min(_box(i)[0] for i in cluster))
        if (min(_box(i)[3] for i in cluster) < MIN_COLUMN_ITEM_HEIGHT
                or narrowest < row_span * MIN_COLUMN_WIDTH_FRACTION):
            # Inline items, not columns. Keep them in one column, in reading order
            # (left to right), so a pill row stays a row of buttons in the editor.
            widgets = []
            for item in sorted(cluster, key=lambda i: _box(i)[0]):
                _collect_widgets(item, widgets)
            if not widgets:
                continue
            emit(InferredRow(
                columns=(InferredColumn(
                    width_pct=100, x=cx, width_px=cw, widgets=tuple(widgets)),),
                y=min(_box(i)[1] for i in cluster), inner=depth > 0,
            ))
            continue
        if _x_overlaps(cluster):
            # Before refusing: ONE over-wide box whose real content sits clear of
            # the others is a rendering artefact, not an overlay. The reference
            # stats strip renders 1180px wide with both stat boxes in its left 380px
            # while the trio sits at x>=885 - shrinking the strip to its widget
            # extent separates them cleanly into the 67/33 the author built.
            shrunk = _shrink_to_content(cluster)
            if shrunk is not None and not _x_overlaps(shrunk):
                cluster = shrunk
                notes.append(
                    "an over-wide wrapper was shrunk to its content extent to "
                    "resolve an overlap; verify this band against the source"
                )
        if _x_overlaps(cluster):
            # An overlay, not columns. Refuse to guess: one column, flagged.
            widgets = []
            for item in sorted(cluster, key=lambda i: _box(i)[1]):
                _collect_widgets(item, widgets)
            if not widgets:
                continue
            emit(InferredRow(
                columns=(InferredColumn(
                    width_pct=100, x=cx, width_px=cw, widgets=tuple(widgets)),),
                y=min(_box(i)[1] for i in cluster), inner=depth > 0,
                notes=("items overlap horizontally (an overlay, not columns); "
                       "kept as one column rather than guessing",),
            ))
            continue

        ordered = sorted(cluster, key=lambda i: _box(i)[0])
        pcts = snap_widths(_column_widths(ordered))
        columns: list[InferredColumn] = []
        for item, pct in zip(ordered, pcts, strict=True):
            # A column whose own children form multi-column rows is a NESTED layout,
            # and Elementor has a shape for it: the inner section. Flattening it is
            # what lost the hero's internal splits.
            sub = _rows_of(item, depth + 1) if depth < 4 else []
            if any(len(r.columns) > 1 for r in sub):
                columns.append(InferredColumn(
                    width_pct=pct, x=_box(item)[0], width_px=_box(item)[2],
                    rows=tuple(sub), classes=_gather_classes(item),
                    background=_style(item).get("backgroundColor", ""),
                ))
                continue
            widgets = []
            _collect_widgets(item, widgets)
            columns.append(InferredColumn(
                width_pct=pct, x=_box(item)[0], width_px=_box(item)[2],
                widgets=tuple(widgets), classes=_gather_classes(item),
                background=_style(item).get("backgroundColor", ""),
            ))
        if not any(c.widgets or c.rows for c in columns):
            # This guard predates nesting, and without `c.rows` it silently dropped
            # every row whose columns hold inner sections instead of direct widgets -
            # the hero's whole lower band vanished this way while every cluster in
            # it was measured correctly.
            continue
        emit(InferredRow(
            columns=tuple(columns), y=min(_box(i)[1] for i in cluster),
            inner=depth > 0, notes=tuple(notes),
        ))
    return out


# --------------------------------------------------------------------------- #
# Components
# --------------------------------------------------------------------------- #
def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def detect_components(sections: tuple[InferredSection, ...]) -> tuple[Component, ...]:
    """Repeated column structures, named for the BEM class they already carry.

    A signature repeating three or more times is a component - measured on the
    reference page, the product card's signature repeats 13 times and its columns
    already carry `product-card` in their class lists, so the name is READ, not
    invented, wherever the source provides one.
    """
    groups: dict[tuple[str, ...], list[InferredColumn]] = {}
    for section in sections:
        for row in section.rows:
            if len(row.columns) < 2:
                continue
            for col in row.columns:
                if len(col.signature) >= 2:
                    groups.setdefault(col.signature, []).append(col)

    out: list[Component] = []
    used: set[str] = set()
    for signature, cols in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(cols) < 3:
            continue
        # NAME FROM THE SHARED BEM PREFIX, not from any single class. Measured on the
        # rendered reference DOM: the bare parent class (`product-card`) appears in
        # ZERO class attributes - Elementor 4.7 renders `_css_classes` on widgets but
        # not on columns - while the children (`product-card__image`,
        # `product-card__title`, `product-card__price`) appear 43 times. The parent
        # exists only as the prefix its children share, so that is where the name is
        # read from. This also generalises: any BEM-authored site names its
        # components this way whether or not a bare parent class exists.
        prefix_votes: Counter[str] = Counter()
        class_votes: Counter[str] = Counter()
        for col in cols:
            seen_prefixes = set()
            for rank, cls in enumerate(col.classes):
                if "__" in cls:
                    seen_prefixes.add(cls.split("__")[0])
                else:
                    class_votes[cls] += max(1, 6 - rank)
            for prefix in seen_prefixes:
                prefix_votes[prefix] += 1
        winner = ""
        # A prefix shared by most instances beats any single class.
        for prefix, votes in prefix_votes.most_common():
            if votes >= len(cols) * 0.6:
                winner = prefix
                break
        if not winner:
            for cls, votes in class_votes.most_common():
                if votes >= len(cols) * 2:
                    winner = cls
                    break
        name = _slug(winner)
        if not name:
            name = f"{signature[0]}-card" if "image" in signature else f"{signature[0]}-group"
        base, n = name, 2
        while name in used:
            name, n = f"{base}-{n}", n + 1
        used.add(name)
        out.append(Component(name=name, signature=signature, count=len(cols)))
    return tuple(out)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def infer_layout(root: dict[str, Any], *, viewport_width: int) -> InferredPage:
    """A captured page tree -> sections, rows, columns, widgets, components.

    Total: never raises on real-world input. Refusals become notes; a page that defies
    the model degrades to fewer, simpler sections rather than to an exception.
    """
    notes: list[str] = []
    candidates = _kids(root) or [root]

    sections: list[InferredSection] = []
    for cand in sorted(candidates, key=lambda c: _box(c)[1]):
        _x0, y, w, h = _box(cand)
        if h < MIN_SECTION_HEIGHT:
            continue
        if w < viewport_width * MIN_SECTION_WIDTH_FRACTION:
            notes.append(f"skipped a {w}px-wide fragment at y={y}: not a band")
            continue
        rows = _rows_of(cand)
        if not rows:
            continue
        background = _style(cand).get("backgroundColor", "")
        bg_image = ""
        # Look shallowly for the band's real paint: a backdrop image spanning it,
        # and - when the section element itself is unpainted - a full-coverage
        # child's background colour (the reference footer's dark lives one level
        # down; without lifting it the footer rendered white).
        frontier = [cand]
        for _ in range(4):
            nxt: list[dict[str, Any]] = []
            for node in frontier:
                for child in _kids(node):
                    bx, _, bw, bh = _box(child)
                    covers = bw >= w * 0.85 and bh >= h * 0.6
                    if covers and not bg_image:
                        if child.get("t") == "img" and child.get("src"):
                            bg_image = child["src"]
                        else:
                            from_css = _style(child).get("backgroundImage", "")
                            if from_css and from_css != "none":
                                m = re.search(r'url\(["\']?([^"\')]+)', from_css)
                                if m:
                                    bg_image = m.group(1)
                    if covers and (not background
                                   or background in ("rgba(0, 0, 0, 0)", "transparent")):
                        child_bg = _style(child).get("backgroundColor", "")
                        if child_bg and child_bg not in ("rgba(0, 0, 0, 0)", "transparent"):
                            background = child_bg
                    nxt.append(child)
            frontier = nxt
        sections.append(InferredSection(
            y=y, height=h, full_bleed=w >= viewport_width * 0.98,
            rows=tuple(rows),
            background=background,
            background_image=bg_image,
            classes=tuple(_own_classes(cand)),
            element_id=cand.get("eid") or "",
        ))

    # Container width: the MODE of the sections' content-node widths. Summing row
    # column widths under-measured it badly (684px against a real 1236px), because a
    # single-column row's item is often a narrow text block, not the container.
    widths: Counter[int] = Counter()
    for cand in candidates:
        cursor = cand
        while len(_kids(cursor)) == 1:
            cursor = _kids(cursor)[0]
        w = _box(cursor)[2]
        if 400 < w < viewport_width * 0.95:
            widths[w] += 1
    container = widths.most_common(1)[0][0] if widths else viewport_width

    components = detect_components(tuple(sections))
    if not sections:
        notes.append("no section bands were found; the capture may be empty")
    return InferredPage(
        sections=tuple(sections), container_px=container,
        components=components, notes=tuple(notes),
    )
