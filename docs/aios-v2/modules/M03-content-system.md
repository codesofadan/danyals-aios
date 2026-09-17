# M03 · Content System

**The largest module and the one the client is buying.** Requirements: `REQ-CNT-001` …
`REQ-CNT-031`.

Three sub-systems: **design analysis** (learn the client's design language), the **word
bank** (what to write about, with volumes), and **page production** (plan → write → QA →
review → publish as an editable Elementor page).

---

## PART A — DESIGN ANALYSIS

### A1. What is analysed

The operator pastes the client's **previous version of their website**. That site is the
source of truth for the design language the new pages must speak. It is not a competitor
and not necessarily the live site.

- One **primary** reference URL per client; additional reference URLs optional.
- Up to **5 pages** are captured, auto-selected by type: home, a service/product page, a
  blog/article page, a contact page, and one deep interior page. Selection comes from the
  sitemap where available, from the nav otherwise.

### A2. How it is analysed — two sources, one reconciliation

**A plain HTTP GET returns a modern site's empty JS shell.** Every capture renders in a
real browser.

| Source | What it gives | Rank |
|---|---|---|
| **Declared** — CSS custom properties the author wrote | Named, deduplicated, already the author's own compression of intent. `--brand-brass: #A16207` carries a *name*, which no clustering can recover | **Highest** |
| **Derived** — clustered computed styles from the rendered DOM | Covers every role the declarations miss, which is most hand-coded sites | Second |
| **Vision** — a model reading a screenshot | Corroborates roles, catches what computed styles cannot express: visual rhythm, imagery style, the *feel* of the shape language | Third — **corroboration only, never the sole source of a token** |

The `design_extraction` LangGraph reconciles the three and writes a provenance `method` on
every value: `declared` > `derived` > `inferred` > `defaulted`.

**Colour parsing must handle CSS Color 4** — `oklch()`, `lab()`, `lch()`, `color()`.
Tailwind v4 and most sites built since 2024 emit these. v1 parsed them as nothing, so every
brand colour collapsed to the literal whites and the extracted palette was "2 roles, both
`#ffffff`". Verify the transforms **without trusting any colour table**: implement `lab()`
and `oklch()` as independent code paths and assert they converge on the same byte.

**Content-root detection** is the other trap v1 hit. Falling back to `document.body` makes
the chrome guard reject every header and footer inside it, producing a torso replica that
blames the source site. Prefer the tallest real body child; the chrome guard may reject only
a candidate that *is* or *wraps* the root; widen the selector list to `<nav>`,
`[role=banner]`, `[role=contentinfo]` with position sanity so a mid-page nav is not adopted
as the header.

### A3. DesignIR — the captured design system

`REQ-CNT-004`. This is the contract between analysis and generation.

```jsonc
{
  "version": 3, "client_id": "...", "source_url": "...", "captured_at": "...",
  "state": "approved",

  "color": {
    "roles": {                          // every entry: value + method + source_ref
      "background": {...}, "surface": {...}, "surface_alt": {...},
      "ink": {...}, "ink_muted": {...}, "ink_inverse": {...},
      "brand": {...}, "brand_alt": {...}, "accent": {...},
      "border": {...}, "success": {...}, "warning": {...}, "danger": {...}
    },
    "scheme": "light" | "dark" | "both"
  },

  "type": {
    "families": { "display": {...}, "body": {...}, "mono": {...} },
    "scale":    { "h1": {size, weight, line_height, letter_spacing, transform}, ... "body", "small", "eyebrow" },
    "webfont_sources": [ ... ]          // so the published page can load the same faces
  },

  "space": { "base": 8, "steps": [4,8,12,16,24,32,48,64,96,128],
             "section_padding_y": {...}, "section_padding_x": {...}, "gap": {...} },

  "layout": { "container_max": 1200, "gutter": 24, "breakpoints": {sm, md, lg, xl},
              "grid_columns": 12, "content_width": 720 },

  "shape": { "radius": {sm, md, lg, pill}, "border": {width, style, color_role},
             "shadow": {sm, md, lg}, "divider_style": "..." },

  "components": {
    "button": { "primary": {...}, "secondary": {...}, "ghost": {...} },   // padding, radius, weight, transform, hover
    "link":   {...}, "input": {...}, "card": {...}, "badge": {...},
    "image":  { "radius": "...", "aspect_defaults": [...], "treatment": "none|rounded|duotone|overlay" },
    "icon":   { "style": "line|solid|duotone", "stroke": 1.5, "set_hint": "..." },
    "nav":    { "variant": "...", "sticky": true, "height": 72 },
    "footer": { "columns": 4, "variant": "..." }
  },

  "sections": [                          // the section GRAMMAR, in observed order
    { "kind": "hero", "ordinal": 1, "spec": {...}, "method": "derived" },
    { "kind": "trust_bar", ... }, { "kind": "services_grid", ... },
    { "kind": "testimonials", ... }, { "kind": "cta_band", ... }
  ],

  "motion": { "present": true, "kinds": ["fade_up","counter"], "duration_ms": 400 },

  "coverage": { "roles_grounded": 11, "roles_defaulted": 2, "pages_captured": 5 }
}
```

`coverage` is how an operator judges whether the capture is worth approving. v1's failure
mode — every profile collapsing silently to dataclass defaults — is made visible rather than
prevented, because a partially-grounded profile is often still useful.

### A4. Human approval and editing

`REQ-CNT-006`. The extracted profile is **never** used until approved.

The review surface shows: a rendered token sheet (swatches, type specimen, spacing ruler,
component samples), the wireframe of the observed section grammar, the source screenshots
side by side, and a coverage report naming every defaulted value. Any token is editable
inline; an edit sets `method: "declared"` with the editor as `source_ref`.

Approval is versioned. Re-capture creates a new version; the old one stays, and pages record
which version built them.

### A5. Fidelity target

`REQ-CNT-008`. **Same design system, new composition — not pixel replication.**

The test is **token conformance**, not a pixel diff:

> Every colour, font family, font size, weight, radius, shadow and spacing value used by a
> generated page must exist in the approved DesignIR.

This is a hard invariant, checked programmatically on every generated page before publish.
A page that introduces an off-system value fails, and the emitter is the bug — not the page.

A section type the source site does not have (FAQ accordion, comparison table, pricing
tiers) is **synthesised from DesignIR tokens** and recorded in the composition with
`method: "inferred"`, so a reviewer knows which parts are observed and which are extrapolated
(`REQ-CNT-009`).

---

## PART B — THE WORD BANK

### B1. Definition

`REQ-CNT-010`. The word bank is the **SEO keyword bank with volumes**, sourced from M08 —
not a brand glossary and not a vague term list.

Per term: `term` · `search_volume` + `volume_measured_at` · `difficulty` · `cpc` ·
`intent` (informational / commercial / transactional / navigational / local) ·
`cluster_id` · `serp_features` · `source` · `status`.

Three companions ship with it:

| Companion | Purpose | Requirement |
|---|---|---|
| **Cluster tree** | Parent/child topic structure; the unit the topical map maps to page types | `REQ-KW-004` |
| **Entity / must-mention set** per cluster | Topical completeness scoring — what a page about this topic has to mention to read as authoritative | `REQ-CNT-013` |
| **Banned terms** | Competitor names, compliance-sensitive words, AI-tell phrases. Enforced at draft time **and re-checked at publish** | `REQ-CNT-012` |

### B2. Ownership

Per client, seeded from niche templates, **human-editable**, versioned. The SEO lead owns
it. M03 never sources terms independently — if a term is not in the bank, it is not a target
(`REQ-KW-007`). This single rule is what stops content and tracking from drifting apart.

### B3. Enforcement

Coverage is **scored, not mandated**. A draft's QA scorecard includes a topical-coverage
dimension measuring the must-mention set. Hard keyword-density requirements are not
implemented — they produce worse writing and no ranking benefit. Banned terms *are* a hard
block.

---

## PART C — PAGE PRODUCTION

### C1. Planning

```
  keyword bank + cluster tree  (M08)
        └── LangGraph: page_set_proposal
              └── proposes: page_type, working title, target cluster,
                  primary + secondary terms, intent, priority, internal-link role
                    └── interrupt() → HUMAN APPROVES THE SET      ← REQ-CNT-014
                          └── fan-out job, one child per page
```

**No drafting money is spent before the set is approved.** The proposal itself is a single
cheap call over the cluster tree.

Page types (`REQ-CNT-015`): home · service · location · service×location · blog/article ·
about · contact · comparison · FAQ · category hub.

### C2. The page graph

```
research → outline → draft → grounding → internal_links → schema → title_meta → qa
              ↑                   │
              └─── repair ────────┘        (bounded: 2 repair loops, then escalate to human)
```

| Node | Contract |
|---|---|
| `research` | Gathers evidence: SERP analysis for the primary term, the client profile, competitor page structure. Output is a cited evidence set, not prose |
| `outline` | Section plan mapped onto the DesignIR **section grammar** — the outline is design-aware from the start, which is what makes composition possible later |
| `draft` | Writes per section against the evidence set. Banned terms blocked at generation |
| `grounding` | `REQ-CNT-018`. Every factual claim about the client — services offered, areas served, hours, credentials, guarantees — must resolve to the client profile or a cited source. **Unresolved claims block the draft.** Not a warning |
| `internal_links` | Produces the link plan: new→new links applied automatically, new→existing proposed for approval (`REQ-CNT-028`) |
| `schema` | Emits the JSON-LD for the page type, validated before publish (`REQ-CNT-029`) |
| `title_meta` | Title and meta variants, length-checked against SERP truncation |
| `qa` | The scorecard (§C3) |

Images (`REQ-CNT-027`): generated by default with a per-image cost line, or client-supplied,
or stock. Alt text generated from page context. **Never scraped from the reference site** —
that is someone else's licence.

### C3. QA scorecard

`REQ-CNT-019`. **Advisory with mandatory acknowledgement until calibrated; then hard.**

Dimensions: search intent match · topical coverage (against the must-mention set) ·
factual grounding · readability · originality · structure and scannability · internal
linking · schema validity · design-token conformance.

Ships with:
- A weighted total and a per-dimension floor, both **stored as configuration**, not
  constants in code.
- A `mode` switch: `advisory` (default) → `hard`.
- The **calibration set** as a first-class artefact (`REQ-CNT-020`): ≥30 human-graded drafts
  across page types, with machine scores stored alongside. The threshold is set from that
  correlation, and a drift report runs monthly.

Until the calibration set exists, the gate cannot be switched to `hard`. This is enforced in
code, not by policy.

### C4. Review

A rendered preview beside the QA breakdown, with inline editing. Approve / reject /
request-change, reason captured. This is the review checkpoint from M01 — one queue.

---

## PART D — PUBLISHING TO WORDPRESS

### D1. The hard requirement

`REQ-CNT-022`: **a genuinely editable Elementor block tree.**

> **Acceptance:** open the published page in Elementor. Select any heading, paragraph,
> image, button or section. Edit it natively. Save.

A single HTML widget containing the whole page is an **explicit failure**, not a fallback.
This is the piece v1 never built, and it is the difference between a product and a demo.

### D2. Capability discovery first

`REQ-CNT-024`. Before the first publish to any site, probe and store: REST reachable ·
authentication method · Elementor present and version · **Elementor data model**
(`container` flex model in 3.16+ vs legacy `section`/`column`) · active theme · Elementor
Pro · upload limits · our companion plugin present.

Everything downstream branches on this record — never on a guess.

### D3. The emitter

```
  DesignIR + page content + section grammar
        └── COMPOSITION PLAN          (ordered sections, each with a role and content slots)
              └── ELEMENTOR EMITTER
                    ├── Global Kit sync: write DesignIR colours + typography into the
                    │   Elementor global kit, so every widget REFERENCES a global token
                    │   rather than hard-coding a hex. The client can then restyle
                    │   globally and our pages follow.
                    ├── element tree: container → container → widget
                    │     widget types: heading · text-editor · image · button · icon-box ·
                    │     icon-list · image-box · divider · spacer · toggle/accordion · tabs
                    ├── per-widget settings drawn ONLY from DesignIR tokens
                    └── stable element ids so a re-publish diffs instead of replacing
```

**Writing it correctly matters as much as generating it.** Publishing goes through our
companion plugin, not raw REST meta writes, because the meta write alone is not enough:

- `_elementor_data` — the JSON tree, stored with WordPress's slashing rules honoured.
  Written raw through the REST meta API it will be mangled.
- `_elementor_edit_mode` = `builder`
- `_elementor_template_type` = `wp-page`
- `_elementor_version` = the site's Elementor version
- **CSS regeneration** — Elementor caches per-post CSS. The cached file and
  `_elementor_css` meta must be cleared and regenerated, or the page renders unstyled.
  The plugin calls Elementor's own files manager to do this.

The companion plugin exposes one authenticated endpoint that takes the tree, validates it
against the site's Elementor version, writes the meta transactionally, regenerates CSS, and
returns the post id plus a render check. It also implements revert.

**Gutenberg** (`REQ-CNT-023`) is the fallback where Elementor is absent, emitting core
blocks with theme.json-aligned styles. Same editability bar.

### D4. Publish workflow

`REQ-CNT-025`:

```
  approved draft
    └── publish → WordPress DRAFT (default)
          └── render check: fetch the preview, assert the tree rendered and
              the design tokens are present in the computed styles
                └── go-live (explicit second action)
                      └── register with M09 for indexing
                            └── version recorded; revert available
```

`REQ-CNT-026`: a publish that cannot complete — no credentials, REST blocked, Elementor
absent, upload rejected — ends in **`blocked`** with the cause named. **Never `done`.** v1
recorded `status="done"` for publishes with no WordPress credentials at all; a test asserts
this specific case ends `blocked`.

---

## E. Acceptance criteria

| # | Criterion |
|---|---|
| A1 | Design extraction of 10 real sites yields ≥9 roles grounded (`declared` or `derived`) on at least 8 of them; `oklch()`/`lab()` sites parse correctly |
| A2 | Header and footer are captured, not rejected as chrome — verified on a site where both live inside the body root |
| A3 | A human can edit any DesignIR token and the change takes effect on the next generated page |
| A4 | **Token conformance: 100%.** No generated page uses a colour, face, size, radius, shadow or spacing value absent from its approved DesignIR |
| A5 | An inferred section (FAQ on a source site with no FAQ) renders in-system and is labelled `inferred` |
| A6 | A page set of 50 is proposed, approved, and fans out with per-page resumability; killing the worker at page 31 resumes at page 31 |
| A7 | A draft containing an unsupported claim about the client is **blocked**, not warned |
| A8 | A banned term never appears in a published page, verified at both draft and publish |
| A9 | **A published page opens in Elementor and every heading, paragraph, image and button is an individually editable widget.** Asserted automatically by parsing `_elementor_data` and manually verified once per release |
| A10 | The published page's colours and fonts resolve through Elementor **global** tokens, so a global restyle propagates |
| A11 | A publish with no WordPress credentials ends `blocked` with a named reason, and reports zero success |
| A12 | Revert restores the previous version and the page renders correctly afterwards |
| A13 | The 50-page run completes with zero manual repair and every page passing token conformance and schema validation |
| A14 | The QA gate cannot be switched to `hard` until a calibration set of ≥30 human-graded drafts exists |
