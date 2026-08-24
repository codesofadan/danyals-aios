# Internal Linking for Local Service Pages

Internal linking does three jobs on a local site: it tells Google which page is the answer for "[service] [city]", it routes ranking equity to the pages that make money, and it gives a human a path from "I have a problem" to "book now". This file owns two of the three levers: **anchor-text rules** and **link-equity flow**. The third lever, the silo topology itself (which page types exist and how the graph is shaped), is owned by `cluster-graph-protocol.md`. Read that file for the shape. Read this one for what each link says and where the equity goes.

Scope note: this is a **white-hat internal linking** file. Internal links between the client's own pages, plus link reclamation of the client's own unlinked brand mentions and lost citations. No automated tiered link building, no PBNs, no third-party link schemes. That is a doctrine hard line (Law 8), not a stylistic preference. If a brief asks for tiered or automated off-site links, refuse and cite the doctrine.

---

## Part 1 - Anchor text for local pages

### The core shift, applied locally

The 2018-2024 playbook said exact-match anchors carry the strongest signal: link to the AC-repair-in-Chandler page with the anchor "AC repair Chandler", everywhere, every time. In 2026 that is inverted. Retrieval models read anchor text semantically, and cluster-scale link patterns are scored together, so **descriptive variety beats exact-match repetition**, and exact-match repetition across many pages is a manipulation flag.

For a local site this matters more than for a blog, because a local site has a small number of pages all fighting over the same two or three commercial phrases. If every service-area page, the footer, and every location page links the Chandler money page with the identical anchor "AC repair Chandler", you have manufactured exactly the over-optimized pattern the algorithm looks for, on the exact page you most want to protect. The realistic 2026 downside is not a manual penalty in most cases: it is that the links get discounted and the equity is diluted, so the effort is wasted. On a thin local footprint that waste is expensive.

### The healthy local anchor mix

Anchors to any local target should spread across these families. The city and the service should ride inside the anchor **naturally**, as part of a real phrase, not bolted on as a keyword.

| Anchor family | What it looks like (local) | Role |
|---|---|---|
| Exact-match | "AC repair Chandler" | At most **once** into a given target from the whole site. The single keyword-bearing shot. |
| Partial-match / descriptive | "our AC repair service in Chandler", "same-day AC repair for Chandler homes" | The workhorse. Carries city+service in a real phrase. |
| Branded | "Chandler Cooling Co's AC repair", "book with Chandler Cooling Co" | Homepage and conversion-path links; ties the entity to the service. |
| Natural-phrase / function | "get a broken compressor looked at the same day", "when your unit freezes up in July" | Reads like a human wrote it; feeds passage-level retrieval. |
| Bare URL / brand | "chandlercooling.com/ac-repair", "Chandler Cooling Co" | Rare; footers, citations, references. |

**Target distribution across the whole site's in-body links** (calibrate per site; treat as a directional flag, not a Google rule):

| Anchor type | Share of internal anchors |
|---|---|
| Partial-match / descriptive noun phrase | 40-50% |
| Branded | 15-25% |
| Natural-phrase / function | 15-25% |
| Bare URL / topic-compressed | 5-15% |
| Exact-match | under 10% |

If any single family runs past ~50%, or one exact phrase points at a target from most of its inbound links, flag for diversification.

### How to write a descriptive local anchor

Build the anchor from the **destination's H1 or target query**, then phrase it as something a person would actually say. Three moves:

1. **Name the service and the place in a real phrase.** Not "AC repair Chandler" but "our AC repair service in Chandler" or "same-day AC repair across Chandler". The city+service is present; the phrasing is human.
2. **Vary the surface, keep the target on-topic.** "emergency AC repair in Chandler", "when your Chandler AC quits in a heatwave", "get your Chandler unit fixed today" all point at the same money page and all read as distinct anchors. Vary the words, never the target relevance.
3. **Let the surrounding sentence carry the reason to click.** A good anchor still needs prose around it that tells the reader why the destination helps them right now. The anchor previews; the sentence justifies.

Descriptive local anchor patterns that work:
- "our [service] service in [city]"
- "[service] for [city] homeowners"
- "same-day [service] across [city] and [neighborhood]"
- "book [brand]'s [service]" (conversion links)
- "how we handle [specific problem] in [city]"

### The over-optimization danger (worked failure)

Stuffing "AC repair Chandler" as the anchor on 30 pages pointing at one money page is a spam signal. It reads as engineered, it is the internal-link version of the Penguin-era exact-match risk, and the links get discounted. The fix is never "change one word". The fix is to rebuild each anchor from the destination's H1 and vary across the families above, using exact-match at most once site-wide into that target.

The same failure appears in the footer. A city footer that links every location page with the identical "[service] [city]" anchor, repeated on every page of the site, is both an over-optimized anchor pattern and a doorway-spam risk (see Part 3). Footer city links should use plain city names or branded phrasing ("Chandler", "Gilbert", "Mesa", or "Chandler Cooling Co - Gilbert"), never a stack of exact-match commercial anchors.

### Banned anchor patterns (local)

These fail the anchor self-test and get rewritten:

1. **Generic anchors:** "click here", "learn more", "read more", "this page", "here", "more info". Google's own guidance names these as anti-patterns.
2. **Exact-match repetition:** the same commercial anchor string pointing at a target from many pages, or 3+ times inside one page.
3. **Anchors inside headings:** links belong in body prose, not in an H1/H2/H3.
4. **Anchor-to-target mismatch:** "drain cleaning in Mesa" linking to the water-heater page. The only defect class that actively misinforms; it sends a false relevance signal and gets caught.
5. **Keyword-stuffed anchors over ~10-12 words:** "best affordable emergency 24 hour AC repair company in Chandler Arizona" is an over-eager keyword pack.
6. **Two anchored phrases in one sentence:** a clarity failure; split it.
7. **City-list footer stacks with commercial anchors:** covered above; use plain city names.

### Anchor self-test (run per link before finalize)

1. Read the anchor alone, out of the sentence. Does it tell you what is on the other side, and does it name the right city and service?
2. Does the destination actually match what the anchor promised?
3. Is this the first or second use of this exact string on the page? (No third use.)
4. If it is exact-match: is it the only exact-match anchor pointing into this target from the whole site?
5. Does the city+service ride inside a natural phrase, or is it bolted on?

Any failure means rewrite the anchor from the destination's H1, not patch one word.

---

## Part 2 - Link-equity flow through the local silo

Every followed link on a page splits that page's equity across its outbound links (roughly 1/N). Internal links are how a local site moves the authority it earns (mostly at the homepage and via citations/GBP) down to the pages that convert. The failure mode is informational and secondary pages hoarding equity while the money pages starve.

### The flow, top to bottom

Authority enters the site mainly at the **homepage** (most external links and brand searches land there) and secondarily at **service hub pages** and **location pages** that pick up citations. From there:

```
Homepage  (entity anchor, most equity)
   |  links down to each service hub + each primary location
   v
Service hub pages  ("AC repair", "AC installation" - brand-wide)
   |  links down to each service-in-city spoke
   v
Service-in-city money pages  ("AC repair in Chandler")  <- the pages that make money
   ^  ^
   |  |  ALSO linked from the matching location page (Chandler)
   |
Location pages  (city hubs: "Chandler")
   |  links down to service-area pages within/around the city
   v
Service-area pages  (coverage: neighborhoods / nearby towns)
```

Topology detail (which page type links to which, and why the silo is shaped this way) lives in `cluster-graph-protocol.md`. The equity rules that matter here:

**1. Money pages are the destination, not a way-station.** The service-in-city combo page is where the conversion happens. It should be one of the best-linked pages on the site, receiving contextual in-body links from its service hub, its city/location page, and topically relevant siblings, not just template links.

**2. Every money page must be reachable two ways.** A service-in-city spoke ("AC repair in Chandler") must be linked from **both** its service hub ("AC repair", the service axis) **and** its city/location page ("Chandler", the geography axis). This is the defining rule of a local silo: the two axes cross at the money page. A spoke reached only from the service hub, or only from the city page, is half-supported.

**3. Depth from homepage: money pages within ~3 clicks.** Click depth is a proxy for link prominence and crawl priority, not a hard ranking cliff. Target: money pages and top-strategic pages within **2 clicks** of the homepage; other important pages within **3**; flag any priority page at 4+. On a local site this is easy to hit because the graph is small; the usual cause of a deep money page is that it is only reachable through a collapsed footer or a deep service-area page, which no crawler weights well.

**4. No orphans.** An indexable page with zero internal inbound links can be dropped from the index and gets zero topical reinforcement. Every location page, service page, and money page needs at least one contextual inbound link; priority money pages want 2-3. When you add a new city or service, wire its inbound links in the same pass, or it ships as an orphan.

**5. Contextual in-body links carry the most weight; nav/footer carry the least.** A link inside the main content, in a real sentence, near the top of the passage, passes more signal than the same URL repeated in a sitewide footer. A footer link duplicated across 200 pages functions roughly like one editorial link, no matter how many times it appears. So: **use nav and footer for coverage and usability, use in-body contextual links to actually route equity to money pages.** A money page surviving on footer links alone is under-supported even if its raw inbound count looks high.

**6. Reasonable link counts.** No official limit exists (the old "150 links" figure was never Google policy). Practical local targets: a service or location page carries roughly **3-8 contextual body links** to related pages; a homepage links to every service hub and primary location; a money page links out to a small, tight set (its service hub, its city page, 1-2 sibling services, the contact/booking page) rather than dumping every URL on the site. Scale up with content length, prune bloated nav modules rather than nofollowing them (nofollowing an internal link does not redistribute the equity, it evaporates it).

### Contextual vs boilerplate, stated plainly

- **Contextual (in-body) link:** inside a sentence in the main content, e.g. "If your compressor failed, our [same-day AC repair in Chandler] usually gets a tech out within the hour." Highest weight, best for money pages, feeds AI passage retrieval.
- **Boilerplate (nav/footer/sidebar) link:** repeated across the template. Good for coverage and human navigation, low per-link signal, must not be the *only* support for a money page.

Rule: **every priority money page needs at least one in-body contextual inbound link from a topically relevant, stronger page.** If a money page's inbound links are predominantly template-fed (more footer/nav links than contextual), that is the flag to add contextual links.

---

## Part 3 - Silo structure rules (writer-facing)

The full topology is in `cluster-graph-protocol.md`. What a writer needs at draft time:

1. **Silo services and cities on two axes.** Service hubs group by service; location pages group by geography; money pages sit at the intersection and get linked from both axes. Do not let a service hub link straight to a service-area page and skip the money page, and do not let a location page link to a service hub without also linking the relevant in-city money page.

2. **Cross-link siblings only on real intent fit.** "AC repair in Chandler" can link to "AC installation in Chandler" (same city, adjacent need, a homeowner whose repair is not worth it may need install). It should not link to "drain cleaning in Chandler" if the client is HVAC-only or if the two services share no real customer journey. Cross-link laterally only when a real customer would cross that path.

3. **Footer/nav city linking without doorway spam.** Linking all served cities in the footer is fine and useful. It becomes spam when (a) the anchors are stacked exact-match commercial phrases (use plain city names or branded phrasing), or (b) the pages those links point to are templated near-duplicates with the city name swapped in. The internal-link plan cannot rescue doorway pages: if the location/service-area pages are thin near-duplicates, fix the pages (unique local value per page, per the location and service-area playbooks), not the links. Linking is a routing tool, not a laundering tool.

4. **Link reclamation is in scope.** If the client is mentioned by name on a third-party page without a link, or has a citation pointing at a dead/redirected URL, reclaiming that (asking for the link, or fixing the internal target) is white-hat and encouraged. Manufacturing links on sites you control to point at the client is not.

---

## Worked example: plumber, 3 cities, 4 services

Client: **Valley Plumbing Co**, based in Chandler AZ, serving **Chandler, Gilbert, Mesa**. Services: **drain cleaning, water heater repair, leak detection, repiping**.

Page inventory (from the silo; topology owned by `cluster-graph-protocol.md`):
- Homepage
- 4 service hubs: `/drain-cleaning`, `/water-heater-repair`, `/leak-detection`, `/repiping`
- 3 location pages: `/chandler`, `/gilbert`, `/mesa`
- Up to 12 service-in-city money pages, e.g. `/drain-cleaning-chandler`
- Service-area pages under each location page for neighborhoods (e.g. Ocotillo, Sun Lakes under Chandler)

### Internal link plan for ONE money page: `/drain-cleaning-chandler`

**Pages that link INTO it (inbound), with anchors:**

| Source page | DOM region | Anchor | Type |
|---|---|---|---|
| `/drain-cleaning` (service hub) | in-body | "our drain cleaning service in Chandler" | descriptive/partial |
| `/chandler` (location page) | in-body | "same-day drain cleaning across Chandler" | descriptive/partial |
| `/water-heater-repair-chandler` (sibling money page) | in-body | "if the backup is in your main line, that is a drain cleaning job" | natural-phrase/function |
| Homepage | in-body (services list, only if Chandler is a priority city) | "drain cleaning in Chandler" | exact-match (the single site-wide exact shot) |
| Footer city+service module (optional) | footer | "Chandler" or "Valley Plumbing Co - Chandler" | branded/plain |

Result: two-axis support (service hub + location page), one topically-relevant sibling, an exact-match used exactly once from the homepage, and plain-name footer coverage. Depth from homepage: 1 click (homepage link) or 2 (via hub or location page). No orphan risk.

**Pages it links OUT to (outbound), with anchors:**

| Target page | Anchor | Reason |
|---|---|---|
| `/drain-cleaning` (its service hub) | "how we approach drain cleaning" | up to the service axis |
| `/chandler` (its location page) | "everything we cover across Chandler" | up to the geography axis |
| `/water-heater-repair-chandler` (sibling) | "if your water heater is also acting up" | real adjacent need, same city |
| Contact / booking page | "book a Chandler drain cleaning visit" | branded action, conversion path |

That is 4 tight outbound contextual links plus nav/footer. It routes up both axes, cross-links one genuinely related sibling, and pushes to the booking page. It does not dump all 12 money pages or all 3 cities into the body.

### Anchor-mix check for the whole Valley Plumbing site

Across every in-body internal link on the site, the distribution should land near the target table in Part 1: descriptive/partial dominant (40-50%), branded and natural-phrase filling the middle, exact-match under 10% and used at most once per target site-wide. If an audit shows "drain cleaning Chandler" as the anchor on 9 of 12 inbound links to the money page, that is the over-optimization flag: rewrite 8 of them into the descriptive, branded, and natural-phrase families.

---

## Finalize checklist (internal links)

Before a page ships (this feeds `output/<client>/<page-slug>/internal-links.md`):

- [ ] Every money page reachable within ~3 clicks of the homepage.
- [ ] Every money page linked from BOTH its service hub and its city/location page (two-axis rule).
- [ ] No orphan: the new page has at least one contextual inbound link (2-3 for priority money pages).
- [ ] At least one in-body contextual inbound link per priority page (not footer-only).
- [ ] Exact-match anchor used at most once into any target, site-wide.
- [ ] No single anchor family over ~50% of a page's or target's anchors.
- [ ] Anchors carry city+service inside natural phrases; no generic anchors; no headings-as-anchors.
- [ ] Footer city links use plain/branded names, not stacked commercial anchors.
- [ ] Cross-links to siblings are on real intent fit only.
- [ ] All internal links resolve to a 200 URL (no links to 3xx/4xx, no chains); no `rel="nofollow"` on internal editorial links.
