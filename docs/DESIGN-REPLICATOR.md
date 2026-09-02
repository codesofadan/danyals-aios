# The Design Replicator

**Paste a URL, get that page rebuilt as an editable Elementor page on the client's own
WordPress site.** One page per run. The rebuild carries the source page's real copy,
its real imagery, its real layout and its real design tokens — it is a *reconstruction*,
not a screenshot and not a theme.

This document is the working reference for the module: how to drive it, what it can and
cannot do, what every stage costs, how to diagnose a bad run, and how to re-measure any
claim made here yourself.

---

## 1. Using it

**Where:** Admin → WordPress → *Design Replicator* (`/admin/wordpress`).
**Permission:** `publish_content` (staff only — the same permission that pushes content live).

1. Pick the **client**. The target site is resolved from that client's *stored* WordPress
   connection; credentials never travel in the request.
2. Paste the **page URL**, exactly as published.
3. Tick **"The client owns this site."** This is a hard gate, not a formality — the
   rebuild carries the source page's own words and pictures, so a person has to assert
   ownership. The button stays disabled without it and the server refuses the request
   anyway.
4. **Replicate design.** You get a queued job immediately; the work runs on the `browser`
   queue, never inside the request.

While it runs, the row reports the stage it is actually in — "Opening the page in a
browser and measuring it at three viewports", "Building 9 section(s) as Elementor
widgets", and so on. When it finishes you get **Open the preview →**.

**The result is always a DRAFT.** Nothing goes live. Open it in Elementor and edit it
like any page you built by hand.

### Prerequisites

| Requirement | Why | What you see if it is missing |
|---|---|---|
| The **AIOS Publisher plugin** on the client's site | The replica writes `_elementor_data` and a design stylesheet; that needs the plugin door, not XML-RPC or an app password | `blocked` → "This client's connection can't write Elementor data." |
| A stored **WordPress connection** for the client | The worker resolves it server-side | `blocked` → "This client's WordPress site isn't connected yet." |
| A readable stored **credential** | The vault has to open it | `blocked` → "This client's stored WordPress credential couldn't be opened." |

A `blocked` run is **not** a failure and needs no retry-hunting. Fix the connection and
run it again — and re-running now genuinely re-runs (see §6).

---

## 2. What comes out

For a real page (measured on `elementor.com`, 2026-09-01):

- **9 sections, ~190 Elementor widgets**, ~103 KB of `_elementor_data`
- Widget mix: `text-editor`, `heading`, `image`, `button`, `divider`, `icon-list`,
  `social-icons`, `spacer`
- **Per-breakpoint settings**: section padding at tablet and mobile, heading font sizes
  at tablet and mobile, column widths on mobile where the row genuinely stays inline
- The page's `<head>` fundamentals — meta title and description — travel with it
- The site's **navbar and footer**, rebuilt as ordinary editable sections when they can
  be recognised
- Internal links rewritten **path-relative**, so sibling pages replicated at matching
  slugs connect to each other on the new site

The canonical is deliberately **not** copied: the source's canonical names the source's
domain, and a replica claiming it would point search engines at someone else's URL.

---

## 3. The pipeline, and what each stage costs

```
    URL
     │
     ├─ 1. CAPTURE ......... Chromium, one page load, three viewports     ~85-95% of the run
     │      desktop 1440×900 · tablet 834×1194 · mobile 390×844
     │
     ├─ 2. LAYOUT .......... rendered boxes → sections / rows / columns          ~7 ms
     ├─ 3. DESIGN SYSTEM ... colours, type scale, spacing, radii                 ~2 ms
     ├─ 4. BUILD ........... InferredPage → Elementor widget tree                ~2 ms
     ├─ 5. CAPABILITY ...... what can this target actually render?        one HTTP round trip
     ├─ 6. CHROME .......... navbar + footer as their own sections               ~2 ms
     ├─ 7. VALIDATE ........ every setting against Elementor's registry          ~1 ms
     └─ 8. PUBLISH ......... draft page + design CSS, images imported     one HTTP round trip
```

**The whole non-browser half of this pipeline is ~13 milliseconds.** That is measured, on
the repo's own 611-node reference capture, not estimated. If a run feels slow, the time is
in Chromium or in the two WordPress round trips — it is never in the layout inference, the
design system or the emitter. *Do not optimise stages 2, 3, 4, 6 or 7 for speed.*

Reproduce that number:

```bash
cd backend && ./.venv/bin/python - <<'PY'
import json, sys, time; sys.path.insert(0, ".")
from app.services.layout_infer import infer_layout
from app.services.design_system import extract
from app.services.elementor_replica import build_tree, to_json, validate_tree
F = "tests/fixtures/replica/"
raw = json.load(open(F + "spotino_desktop.json"))
nodes = []
def flat(n):
    nodes.append(n)
    for k in n.get("kids") or []: flat(k)
flat(raw)
for label, fn in (("infer_layout", lambda: infer_layout(raw, viewport_width=1440)),):
    t = time.perf_counter(); page = fn(); print(f"{label}: {time.perf_counter()-t:.4f}s")
t = time.perf_counter(); ds = extract(nodes); print(f"design_system: {time.perf_counter()-t:.4f}s")
t = time.perf_counter(); tree = build_tree(page, ds); print(f"build_tree: {time.perf_counter()-t:.4f}s")
t = time.perf_counter(); validate_tree(tree); print(f"validate: {time.perf_counter()-t:.4f}s")
print(f"{len(page.sections)} sections, {to_json(tree).count('widgetType')} widgets")
PY
```

### Where the browser time actually goes

Navigation dominates, and it is dominated by *the target site*, not by us. A healthy page
captures in ~8–12s end to end. The same page on a bad day for its own CDN takes 30s, and
that is the site, not the replicator — so **never quote an absolute number without an
interleaved A/B against the same URL in the same minutes** (§8).

Navigation is deliberately bounded in three steps so a chatty site cannot hold the run
hostage:

| Step | Budget | On timeout |
|---|---|---|
| `goto(domcontentloaded)` | `timeout_ms` (45s) | the run genuinely failed |
| `wait_for_load_state("load")` | `load_ms` (8s) | note it, measure anyway |
| `wait_for_load_state("networkidle")` | `quiet_ms` (6s) | note it, measure anyway |

This replaced a single `goto(wait_until="networkidle", timeout=45_000)`, which is a trap: a
site with a chat widget, a poller or an ad exchange never goes network-quiet, so the call
burned the full 45 seconds *and then raised*, discarding the entire capture. The operator
waited 45s to be told "no desktop viewport was measured".

Known tracker hosts (`BLOCKED_HOSTS`) are refused at the network layer so the quiet wait
can actually succeed. Fonts, images, media and CSS are **never** blocked — they decide how
the page looks, which is the one thing this exists to measure.

---

## 4. Honest limits

Read this section before promising a client anything.

**Images are imported, but nothing else is.** The AIOS Publisher plugin walks the Elementor
tree on arrival and sideloads every image into the client's own media library, rewriting
both the URL and the attachment id (the id is what lets Elementor emit `srcset`). Fonts,
videos, and background videos are not imported.

**Responsive is measured, not complete.** Three viewports are captured and these facts
survive into per-breakpoint Elementor settings:

| Fact | Emitted? |
|---|---|
| Section vertical padding at tablet / mobile | ✅ `padding_tablet`, `padding_mobile` |
| Heading font size at tablet / mobile | ✅ `typography_font_size_tablet` / `_mobile` |
| Columns that genuinely stay side-by-side on a phone | ✅ `_inline_size_mobile` |
| Column widths at tablet | ❌ falls back to Elementor's stacking |
| Section min-height (full-height heroes) | ❌ collapses to content height |
| Per-breakpoint column gap | ❌ hardcoded `default` |
| Per-breakpoint image sizing | ❌ |
| Elements hidden at one breakpoint | ❌ |

**Widget coverage is the free Elementor set.** Fourteen widget types are emittable. A
source construct with no emitter degrades to the nearest thing that renders, *with a note
saying so* — it is never dropped silently. Forms, sliders, galleries, tab strips, pricing
tables and post feeds all degrade.

**A widget must satisfy two authorities**: the client's site must be able to *render* it,
and the oracle (`oracle_4_7.json`, Elementor's own controls registry) must be able to
*validate* it. This is why an Elementor Pro site currently still gets the approximated
navbar rather than a real `nav-menu` widget — `nav-menu` is in every Pro registry and is
not yet in the oracle. Emitting it anyway is worse than approximating it: Elementor stores
an unknown widget and **silently ignores it**, so the page renders with a hole and nothing
appears in any log. Adding `nav-menu`'s real control ids to the oracle — read off a live
Pro editor bootstrap, never invented — re-enables the real menu with no code change.

**One page per run.** Replicating a whole site means running it per URL. Nothing is cached
between runs today: the same site is re-opened, re-measured and re-probed every time.

---

## 5. Reading the notes

Every run carries `notes` — the honest account of anything approximated, skipped or
refused. The ones worth recognising:

| Note | Means |
|---|---|
| `the capture budget was reached` | The page is larger than the node budget. Content walked **last** is missing; the bottom of the page will be thin. |
| `the layout was still moving when it was measured` | The page never stopped reflowing within budget. Spacing on that viewport is approximate. |
| `the page returned HTTP 4xx/5xx` | You replicated an error page. Check the URL. |
| `the request was redirected to …` | You replicated a different URL than you typed. |
| `a header element WAS found but could not be measured` | Ours, not the site's. |
| `no header element was found on the source` | Genuinely no recognisable header. |
| `capability: assuming the free Elementor widget set` | The site did not answer the probe. Never guessed upward. |
| `design system is ungrounded` | Too few measured values; styling will be thin. |
| `refused by the oracle: …` | A bug in **our** emitter. Nothing was published. Report it. |

---

## 6. Re-running the same URL

**A terminal run no longer blocks a fresh one.** Re-running the same page is a normal,
supported action — the source page changes, and a run that degraded or was blocked
deserves a second attempt once the cause is fixed.

Mechanically: the job's idempotency key carries a **generation**. While a run is
`queued`/`running`, a second request collapses onto it (a double-click is one capture).
Once it is terminal, the next request takes the next generation and genuinely runs.

This matters more than it sounds. Before it, the *first* replication of a URL was the only
one that could ever happen: a run that was `blocked` because WordPress was not connected
yet answered every later request with its own dead handle, so connecting the site could not
make the replication work. The operator clicked, got a `202`, and watched the same dead row.

---

## 7. Diagnosing a run

**It sits on "Waiting for the worker…" and never moves.**
Check that a worker is consuming the `browser` queue. `-Q` is required and must include
`browser`; without it the message is never read.

> **If you run the worker with `--pool=threads`** (which `Start-Worker.bat` does), note
> that Celery sends `worker_process_init` only from the *solo* and *prefork* pools. The
> handler that builds the worker's database pools hangs off that signal, so under the
> thread pool it never ran and **every** database-touching job died at its first ledger
> write — presenting exactly as "queued forever". `workers/celery_app.py` now also builds
> pools from `worker_init`, which fires for every pool, skipping prefork (where building
> pre-fork would share a psycopg connection across a fork). If you see this symptom on an
> older build, that is the cause.

**It says `degraded` with a capture note.** The page fought the measurement. Read the note:
truncation means the page is very large; "still moving" means it never settled.

**It says `blocked`.** A connection problem, not a bug. The card tells you which one and
what to do. Fix it and run again.

**It completed but the page looks wrong.** Check, in order: (1) are there truncation notes?
(2) did the capability probe fall back to the free set? (3) is the missing thing on the
"not emitted" list in §4?

---

## 8. Measuring it yourself

Everything asserted in this document is reproducible. **Absolute seconds are dominated by
the target site**, so always compare interleaved against the same URL rather than quoting a
single number.

```bash
# End-to-end against a live URL with a stub publisher — fidelity, stages and wall clock.
cd backend && ./.venv/bin/python - <<'PY'
import re, sys, time; sys.path.insert(0, ".")
from collections import Counter
from app.services.replica_publish import replicate
class Stub:
    post_id = 1; preview_url = "https://example.test/?p=1"
    def capabilities(self): return {}
    def publish(self, p): self.payload = p; return self
URL = "https://example.com/"          # <-- the page to measure
pub = Stub(); t0 = time.perf_counter()
res = replicate(URL, publisher=pub, owner_confirmed_source=True,
                on_stage=lambda s: print(f"  {time.perf_counter()-t0:5.1f}s  {s}"))
print(f"\nWALL {time.perf_counter()-t0:.2f}s  ok={res.ok}  "
      f"sections={res.sections}  widgets={res.widgets}")
for n in res.notes: print("  -", n)
js = pub.payload["elementor_data"]
bk = re.findall(r'"([a-zA-Z0-9_]+_(?:tablet|mobile))"', js)
print(f"breakpoint keys: {len(bk)} {dict(Counter(bk).most_common(6))}")
PY
```

To compare a change against `HEAD`, load both modules in one process and **alternate**, so
a slow moment for the target site hits both equally:

```bash
git show HEAD:backend/integrations/replica_capture.py > /tmp/orig_capture.py
# then import both and call capture_replica() round-robin, reporting the MEDIAN of each
```

The signals worth tracking, beyond seconds:

- `node_count` summed across viewports — how much of the page was actually seen
- `truncated` — any viewport that hit the budget
- `doc_height` **equal to the viewport height** — the collapsed-measurement artefact
  (§9); it should never happen
- count of `_tablet` / `_mobile` keys in `elementor_data` — how responsive the output is

### Tests

```bash
cd backend && ./.venv/bin/python -m pytest \
  tests/test_replica_capture.py tests/test_replica_publish.py \
  tests/test_replica_route.py tests/test_elementor_replica.py -q
```

These run in seconds because **not one of them launches a browser** — they are fed frozen
fixtures. That is worth knowing when you read a green suite: the browser stage, where all
the wall-clock and most of the fidelity live, is covered by the harness in §8 and by
reading the notes, not by this suite.

---

## 9. The 2026-09-01 audit

The module was audited layer by layer against live pages after the owner reported it was
"taking too much time, and not working properly". Both complaints were real, and neither
had the cause anyone assumed. **The CPU pipeline was never the problem** — it is 13 ms.

Seven defects, each measured before and after.

**1 · The depth cap was discarding 72% of every page's text.**
`MAX_DEPTH` was 14. A real Elementor DOM runs 23 levels deep. On `elementor.com` a depth-14
walk captured 229 nodes carrying **3,762 characters** of copy; depth-18 captured 319 nodes
carrying **13,571** — whole FAQ and feature blocks amputated, and the page published anyway
with a note nobody read as fatal. The cap bought **6 milliseconds** and 47 KB against an
1.8 MB budget. Now 20, with the payload guard doing the work it was always meant to do.
*Widgets on a live page: 123 → ~192.*

**2 · The tablet and mobile measurements were a coin flip.**
The capture changed viewport and immediately scrolled and measured, with one blind 500 ms
sleep for the whole reflow. Responsive sites do not reflow that predictably: a mobile nav
or cookie wall commonly puts `position: fixed; overflow: hidden` on `<body>` for a few
hundred milliseconds. A scroll-locked body reports its height as *the viewport's*, and
`window.scrollTo` becomes a no-op so no lazy imagery loads. Two runs of the shipped code,
same URL, minutes apart:

```
run 1:  desktop 15776   tablet 16576   mobile 12227     ← correct
run 2:  desktop 15794   tablet  1194   mobile   844     ← collapsed to viewport heights
```

Those two viewports exist *only* to produce the responsive facts, so the responsive half of
every rebuild was intermittently derived from a page measured as one screen tall. The
capture now unlocks the page for the measurement and waits for `scrollHeight` to actually
stop moving. *Collapsed measurements across an interleaved A/B: 1–2 per run → 0.*

**3 · "Completely responsive" was 27 setting keys.**
Three viewports captured every run, and the tablet/mobile captures were mined for exactly
two facts. Of 153 text anchors present at all three viewports on the reference page, **153**
had mobile band padding different from desktop — the source uses 88 px of vertical padding
on a desktop band and 10–25 px on a phone. Every section shipped its desktop spacing to
phones. `responsive_band_padding()` now recovers it, anchored by text the way the heading
sizes already were. *Breakpoint keys on a live page: 57 → 77, and every padded section
now carries its own tablet and mobile rhythm.*

Two further defects sat inside the same text-anchoring mechanism, and both are fixed:

- **A third of headings could never be matched at all.** The map was keyed on a node's
  *own* text, while the emitter looks its heading up by `own text or joined inline text`.
  A heading whose words live on nested spans — `Comfort that feels like <em>home</em>`,
  the hero-headline pattern — was never entered in the map, so its lookup could never
  hit. 12 of the reference page's 37 headings, and precisely the large display headings
  whose desktop size most needs reducing on a phone. *Match rate 25/37 → 37/37.*
- **Repeated card labels forced columns side-by-side on phones.**
  `mobile_text_positions` kept only the *first* position per text, so three stacked
  cards each ending in "View more" all resolved to the same coordinates — identical y,
  zero spread, judged "this row stays inline", pinned to 33% width at 390px. 21 of 160
  distinct strings on the reference page repeat, and they are exactly the across-a-row
  labels ("Get a quote" three times, spread over 10,343px). An ambiguous anchor now
  identifies nothing and the row falls back to Elementor's stacking — the correct
  default, since forcing inline is only right when the source *provably* stays inline.

**4 · Every image was hotlinked to the source domain.**
The plugin's sideloader only ever looked at the post *body*; a replica puts its whole page
in `_elementor_data` and sends a one-line placeholder as the body, so it matched nothing.
27 of 27 images on a live replication pointed at the source host — a page that borrows its
pictures, breaks when the source moves them, and bills the source's bandwidth for the
client's traffic. The plugin now walks the Elementor tree and imports each distinct image
once, setting both URL and attachment id.

**5 · A URL could be replicated exactly once, forever.**
`POST /replica` returned the stored handle for any prior run carrying a Celery id, without
looking at how it ended. A run that was `blocked` because WordPress was not connected
answered every later request with its own dead handle — so fixing the connection could not
fix the replication. A fresh handle alone would not have been enough either: `job_runs`
holds a unique index on `idempotency_key` across the whole table, so re-enqueueing under the
spent key would be claimed with `created=False` and declined, reading "queued" forever. The
key now carries a generation (§6).

**6 · An Elementor Pro site published nothing at all.**
`build_navbar` promoted to `nav-menu` on capability alone; `nav-menu` is not in the oracle;
`validate_tree` refused the finished tree and `replicate()` returned "refused by the oracle"
having published **no page**. The better the client's site, the more total the failure. Six
of the seven upgrade entries named a widget the oracle does not carry. A promotion now
requires both authorities to agree (§4).

**7 · The run reported nothing for its whole duration.**
Fourteen internal stages, and the card showed one fixed sentence from start to finish —
indistinguishable from a hang, which invites a re-run that doubles the real cost. The
progress mechanism already existed end to end (`ctx.progress()` → the ledger's `detail`
column → `JobRun.detail` in the frontend types); this module simply never used either end.
It now reports each stage, and the card renders it.

Beyond those: the node budget no longer starves the site's chrome (the header and footer
were being silently deleted on long pages, and the pipeline then told the operator the site
*had* no header); and a 404, 500 or Cloudflare interstitial is no longer replicated as
though it were the page.

### Still open

- `nav-menu` and the six other Pro/addon widgets are absent from the oracle. Add their real
  control ids from a live editor bootstrap and the promotions re-enable themselves.
- Nothing is cached between runs. For a 10-page site the same navbar, footer, design tokens
  and capability probe are re-derived ten times.
- Column widths at tablet, section min-height, per-breakpoint gaps and per-breakpoint image
  sizing are measured and discarded (§4).
- No cancel button, and the task's checkpoints sit outside the browser window, so a cancel
  could not land during the long stage anyway.
- The browser queue shares a worker with long jobs, so a replica can wait behind unrelated
  work.
