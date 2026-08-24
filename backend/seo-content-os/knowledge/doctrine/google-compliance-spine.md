# Google Compliance Spine - The Hard Rule Catalog

The pass/fail ruleset every local-SEO page in this system is checked against before it ships. This is the wall. A page that fails any `auto-fail` rule does not publish, full stop. Warnings are logged in the compliance report and fixed unless a documented reason overrides.

Distilled from primary Google sources, fetched live 2026-07-20 PKT. Each rule cites the exact Google doc it comes from. Re-verify the sources quarterly; Google rewrites these pages without notice (FAQ rich results, for example, died May 2026, see rule D6).

**Governing law:** `seo-system-doctrine.md` Law 8. Google's policy is method-agnostic. It punishes scaled low-value content, not AI provenance. Nothing in this file is a detector-evasion rule. Every rule below makes a page more genuinely useful, more accurate, or more honestly represented. That is the only kind of compliance that survives a core update.

**Primary sources (all fetched 2026-07-20 PKT):**
- Google Search Essentials: https://developers.google.com/search/docs/essentials
- Creating helpful, reliable, people-first content: https://developers.google.com/search/docs/fundamentals/creating-helpful-content
- Spam policies for Google web search: https://developers.google.com/search/docs/essentials/spam-policies
- Structured data general guidelines: https://developers.google.com/search/docs/appearance/structured-data/sd-policies
- Review snippet structured data: https://developers.google.com/search/docs/appearance/structured-data/review-snippet
- FAQPage structured data (feature removed): https://developers.google.com/search/docs/appearance/structured-data/faqpage
- Google Business Profile - represent your business: https://support.google.com/business/answer/3038177
- Search Quality Rater Guidelines (Sept 11, 2025 version): https://guidelines.raterhub.com/searchqualityevaluatorguidelines.pdf
- How Search Works / rater overview: https://services.google.com/fh/files/misc/hsw-sqrg.pdf

Severity key: **AF** = auto-fail (blocks publish). **W** = warning (log + fix, override only with written reason in the compliance report).

---

## Group A - Content helpfulness and people-first

Source for the whole group: Creating helpful, reliable, people-first content (helpful-content doc) and Search Essentials key best practices.

### A1 - People-first purpose
- **Check:** Was this page created primarily to help a person choosing or hiring this service, not primarily to rank? PASS/FAIL.
- **Source:** helpful-content doc, "Who, How, and Why" - "Why are you creating content? ... to primarily help people ... is in line with E-E-A-T. Creating content primarily to attract search engine visits ... is a problem."
- **Severity:** AF.
- **Detect:** Read the page as a homeowner with a burst pipe. Does it answer their real question, or does it circle the keyword? If every H2 exists to hold a keyword variant rather than a real sub-question, fail.
- **Fix:** Rebuild the outline from the buyer's actual decision questions (cost, timeline, credentials, what to expect, service area) using the page-type playbook, not from keyword permutations.

### A2 - Original value over sources
- **Check:** Does the page provide original information, first-hand experience, or analysis a competitor could not have copied from the same public sources? PASS/FAIL.
- **Source:** helpful-content self-assessment - "Does the content provide original information, reporting, research, or analysis?" and "does it avoid simply copying or rewriting those sources, and instead provide substantial additional value and originality?"
- **Severity:** AF.
- **Detect:** Strip out every sentence that is true of any competitor in the vertical. If more than ~40% of the page survives as generic, it is thin. Local pages especially: no city-specific fact, no real price/range, no SME detail = fail.
- **Fix:** Inject SME-interview specifics (real jobs done in that city, local permit quirks, actual price ranges, named neighborhoods served, verifiable credentials). See doctrine Law 8 and the E-E-A-T foundation.

### A3 - Satisfying, complete answer
- **Check:** Will a visitor leave satisfied, or need to search again for the same thing? PASS/FAIL.
- **Source:** helpful-content, search-engine-first signals - "Does the content leave readers feeling like they need to search again to get better information from other sources?"
- **Severity:** W.
- **Detect:** For the page's target query, list the top 5 sub-questions a buyer has. Each must be answered on the page. Missing 2+ = fail.
- **Fix:** Add the missing passage blocks. Do not pad; answer the gap.

### A4 - No unhelpful automation / churn tells
- **Check:** Is the page free of mass-produced tells - filler intros, restated headings, "in today's world" throat-clearing, padded word count? PASS/FAIL.
- **Source:** helpful-content search-engine-first signals - "Are you using extensive automation to produce content on many topics?" / "producing lots of content ... hoping some ... performs well" / sloppy or hastily produced.
- **Severity:** W (becomes AF if it co-occurs with A2 failure - thin AND padded = scaled content, see B1).
- **Detect:** Run the voice/anti-tell blocklist. Flag any paragraph that says nothing falsifiable.
- **Fix:** Cut filler. One idea per passage. If a section cannot carry a real fact, delete it.

### A5 - Honest title and headings (no clickbait/mismatch)
- **Check:** Do the meta title, H1, and H2s accurately describe what the page delivers, with no exaggerated or unfulfilled promise? PASS/FAIL.
- **Source:** helpful-content - "Does the main heading or page title ... avoid exaggerating or being shocking?" and spam policy on misleading content.
- **Severity:** W.
- **Detect:** Compare each heading's promise to the section body. "Emergency 24/7 service" in a heading with no such service in the body = fail.
- **Fix:** Rewrite the heading to match delivered content, or add the content the heading promises (only if true per the client profile).

### A6 - Content quality execution
- **Check:** Is the page free of spelling errors, broken grammar, and evidence of hasty production? PASS/FAIL.
- **Source:** helpful-content self-assessment - "Does the content have any spelling or stylistic issues?" / "Is the content produced well, or does it appear sloppy or hastily produced?"
- **Severity:** W.
- **Detect:** Readability/lint pass.
- **Fix:** Copy-edit.

---

## Group B - Spam policy hard lines

Source for the whole group: Spam policies for Google web search. These are the policies that get a page or a whole site ranked lower or removed. For a local content system, the two live grenades are **doorway pages** and **scaled content abuse**, because location, service-area, and service-in-city pages are structurally close to both. They get their own expanded treatment (B1, B2) and are the reason the location and service-area playbooks exist.

### B1 - Scaled content abuse (the location-page killer)
- **Check:** Across the client's set of location / service-area / service-city pages, is each page genuinely unique and valuable on its own, NOT one of many near-identical pages generated primarily to rank? PASS/FAIL, judged across the SET, not just this page.
- **Source:** spam policies - Scaled content abuse: "generating many pages for the primary purpose of manipulating search rankings and not helping users ... creating large amounts of unoriginal content that provides little to no value to users."
- **Severity:** AF.
- **Detect:** Diff this page against its sibling city/service pages. If the only differences are the swapped city name and a few tokens (a mad-libs template), fail. Compute a same-vertical similarity read: >70% shared boilerplate across siblings = fail. Also fail if the page has no fact that is true only of this city/service.
- **Fix:** Each page must carry city-specific or service-specific substance the SME provided: real local jobs, local conditions (climate, water hardness, soil, building stock, local codes), named neighborhoods with a real reason they are named, genuine local pricing. If the client cannot supply unique value for a city, do not publish a page for that city. Fewer real pages beats many templated ones.

### B2 - Doorway pages
- **Check:** Does this page deliver real end value itself, rather than funneling the user to a more useful page (the real service page or the contact form) while existing only to capture a "[service] [city]" query? PASS/FAIL.
- **Source:** spam policies - Doorways: "sites or pages created to rank for specific, similar search queries ... that lead users to intermediate pages that are not as useful as the final destination," including "multiple ... pages ... to funnel users into the actual usable ... portion of your site" and pages "generated to funnel visitors into the actual usable ... portion of your site."
- **Severity:** AF.
- **Detect:** Ask: if this page were the only page a searcher landed on, is it a complete, useful destination? A thin city page whose real content is "we serve [city], call us" and a link to the main service page is a doorway. Multiple city pages that all resolve to the same generic service content = doorway network.
- **Fix:** Give each geo/service page standalone value: local proof, local specifics, a real answer to the local query, its own genuine service detail. It must be a destination, not a turnstile. See the service-area playbook for the compliant "coverage without doorways" pattern.

### B3 - Keyword stuffing
- **Check:** Is the page free of unnatural keyword or location repetition inserted to rank rather than to read naturally? PASS/FAIL.
- **Source:** spam policies - Keyword stuffing: "filling a web page with keywords or numbers in an attempt to manipulate rankings ... often appears unnatural," including "lists of ... cities and regions a web page is trying to rank for."
- **Severity:** AF.
- **Detect:** Flag exact-match keyword density that reads unnaturally; flag any list of cities/regions/zip codes stuffed for coverage; flag the target phrase repeated verbatim more than it would occur in natural writing. City-name repetition in every heading and sentence is the classic local tell.
- **Fix:** Use natural language and descriptive variation. Say the service and place once where it helps a reader; use pronouns and natural phrasing elsewhere. Replace any city/zip list with genuine coverage content or a real service-area description.

### B4 - Hidden text and links
- **Check:** Is all ranking-relevant content visible to a human visitor, with nothing hidden (white-on-white text, off-screen text, `font-size:0`, hidden divs, CSS-clipped keyword blocks)? PASS/FAIL.
- **Source:** spam policies - Hidden text and links: "placing content on a page in a way solely to manipulate search engines and not to be easily viewable by human visitors."
- **Severity:** AF.
- **Detect:** No keyword block should be hidden by styling. In the emitted markup, check for hidden containers holding keyword or city lists. Content that only exists for crawlers = fail.
- **Fix:** Remove hidden content entirely. If it matters, show it. If it does not matter enough to show, it does not belong on the page.

### B5 - Cloaking
- **Check:** Does the page serve the same content to Google and to users, with no bot-vs-human divergence? PASS/FAIL.
- **Source:** spam policies - Cloaking: "presenting different content to users and search engines with the intent to manipulate search rankings and mislead users."
- **Severity:** AF.
- **Detect:** This system emits static, single-version page copy, so cloaking should never occur by construction. Verify the delivered page is not paired with any user-agent-conditional content swap.
- **Fix:** Serve one version to everyone.

### B6 - Sneaky redirects
- **Check:** Does every link and the page itself send users where they expect, with no redirect that shows users something different from what search saw? PASS/FAIL.
- **Source:** spam policies - Sneaky redirects: "maliciously redirecting ... to show ... search engines different content ... or show users unexpected content."
- **Severity:** AF.
- **Detect:** No JS/meta redirect that diverges by user-agent or destination. Internal links resolve to the page their anchor promises.
- **Fix:** Remove deceptive redirects; make anchors truthful.

### B7 - Misleading functionality
- **Check:** Does the page avoid promising interactions or content it cannot deliver (fake "instant quote," dead calculators, "download" buttons that do nothing, fake booking widgets)? PASS/FAIL.
- **Source:** spam policies - Misleading functionality: "intentionally creating sites that trick users into thinking they'll be able to access ... content or services ... but in reality ... cannot."
- **Severity:** AF.
- **Detect:** Every CTA and interactive promise on the page must map to a real capability the client has (real booking, real quote form, real phone line).
- **Fix:** Remove or correct any element that promises functionality the business does not provide.

### B8 - Expired-domain and site-reputation abuse
- **Check:** Is this page's content native to the site's real business, NOT parasitic content placed on a domain to borrow ranking signals it did not earn? PASS/FAIL.
- **Source:** spam policies - Expired domain abuse ("purchased and repurposed primarily ... to manipulate search rankings by hosting content that provides little to no value") and Site reputation abuse ("third-party ... content published ... mainly because of the host site's already-established ranking signals").
- **Severity:** AF.
- **Detect:** Relevant when a client runs content on a domain with unrelated history, or hosts third-party/guest content that trades on the main site's authority. For a normal single-business local site, verify the page belongs to the business that owns the domain.
- **Fix:** Only publish first-party content that reflects the actual business on its own domain. Do not place client content on a borrowed-authority domain.

### B9 - No thin affiliate / copied merchant content
- **Check:** Is the page free of content copied from a manufacturer, franchise HQ, directory, or another site without original added value? PASS/FAIL.
- **Source:** spam policies - Scraping and Thin affiliation ("product descriptions and reviews ... copied directly from the original merchant without any original content or added value").
- **Severity:** AF.
- **Detect:** Franchise and dealer local pages often paste corporate boilerplate. Any block lifted from a supplier/franchise/other site = fail.
- **Fix:** Rewrite from the local operator's own experience and facts. Corporate copy is a starting reference, never the page.

---

## Group C - E-E-A-T and YMYL

Source for the whole group: Search Quality Rater Guidelines (Sept 11, 2025 version) and the helpful-content doc's E-E-A-T section. Note: E-E-A-T is not a direct ranking factor; raters use it to validate whether the algorithms are surfacing trustworthy pages. But the guidelines define what "trustworthy" looks like, and the December 2025 core update extended experience-weighting to competitive non-YMYL queries too. Trust is the most important member of the family; the rest support it.

### C1 - Trust is present and the page is not deceptive
- **Check:** Is the business real, reachable, and honestly presented, with nothing that would make a rater distrust the page? PASS/FAIL.
- **Source:** QRG - "Trust is the most important member of the E-E-A-T family" and Lowest ratings for deceptive or untrustworthy pages.
- **Severity:** AF.
- **Detect:** Page must expose real NAP, a real way to contact the business, and no deceptive claim. A local page with no verifiable business identity fails.
- **Fix:** Surface real contact info, real business identity, honest claims. Link to the About page that carries the credentials.

### C2 - First-hand experience shown (the "E" that wins)
- **Check:** Does the page demonstrate first-hand experience with this service in this place, with 3+ concrete markers, at least one of which only the operator could know? PASS/FAIL.
- **Source:** QRG experience dimension ("first-hand or life experience for the topic") + helpful-content "Who/How" transparency. Reinforced by `ai-search-reality-2026.md` Truth 1.
- **Severity:** AF.
- **Detect:** Count falsifiable experience markers: real job examples, photos of real work, specific local conditions handled, named team member who did the work, measured outcomes. Fewer than 3, or all generic = fail.
- **Fix:** Pull markers from the SME interview. If the operator did not supply them, the pipeline halts for SME input; do not fabricate (see C6).

### C3 - Author / business expertise is evident
- **Check:** Is it clear who stands behind the content and why they are qualified (credentials, licenses, years, certifications), verifiably? PASS/FAIL.
- **Source:** QRG expertise/authoritativeness + helpful-content "Is this content written or reviewed by an expert ... who demonstrably knows the topic?"
- **Severity:** W (AF for YMYL, see C5).
- **Detect:** Named author or business authority present; credentials stated and true per client profile. Anonymous YMYL content = fail.
- **Fix:** Add the byline / business-authority block linking to the About/team page; state real licenses and certifications from the client profile.

### C4 - YMYL classification is applied
- **Check:** Has the page been correctly flagged YMYL when the vertical touches health, safety, finance, or major life decisions, and held to the higher bar? PASS/FAIL.
- **Source:** QRG - YMYL topics "could significantly impact the health, financial stability, or safety of people, or the welfare or well-being of society" and get "very high Page Quality standards." Sept 2025 version added elections/institutions.
- **Severity:** AF (process gate).
- **Detect:** Is the vertical YMYL? Medical/dental, legal, financial/tax/insurance, home-safety-critical trades (electrical, gas, roofing structural, mold/asbestos, pest, water damage, garage doors, security), childcare, addiction/recovery = YMYL. If YMYL and not flagged, fail.
- **Fix:** Flag YMYL in the brief; route to the stricter C5 requirements.

### C5 - YMYL heightened requirements
- **Check:** For YMYL pages: named credentialed author or reviewer, accurate and current information, no unsupported medical/legal/financial claims, clear sourcing, and license/registration numbers where the profession requires them. PASS/FAIL.
- **Source:** QRG YMYL standard; helpful-content factual-accuracy question ("Does the content have any easily-verified factual errors?").
- **Severity:** AF.
- **Detect:** YMYL page with anonymous authorship, or any health/legal/financial claim stated without support, or missing required license number = fail. No guarantees of medical/legal/financial outcomes.
- **Fix:** Add credentialed authorship/review, cite authoritative sources for any factual claim, state license numbers from the client profile, remove or qualify any outcome guarantee.

### C6 - No fabricated E-E-A-T
- **Check:** Is every experience, credential, review count, year-in-business, certification, and outcome on the page true and sourced to the client profile or SME interview, with zero invented specifics? PASS/FAIL.
- **Source:** helpful-content ("avoid ... untrue ... information") + QRG lowest-quality for deceptive/inaccurate content + doctrine hard rule (no fabricated local facts).
- **Severity:** AF.
- **Detect:** Every falsifiable claim must trace to `sources.md` (SME-tagged or URL-cited). Any specific with no source = fabricated = fail. "Family-owned since 1998," "500+ jobs," "licensed master plumber" all require a source tag.
- **Fix:** Replace with a sourced fact, or cut it. Fabricated E-E-A-T is the fastest route to a trust penalty and is the single worst failure this system can make.

---

## Group D - Structured data content rules

Source for the whole group: Structured data general guidelines and the per-type docs (review snippet, FAQPage). Schema is a machine-readable claim; the same honesty rules as the visible page apply, plus type-specific ones.

### D1 - Markup matches visible content
- **Check:** Does every schema property describe content actually visible to users on that page? PASS/FAIL.
- **Source:** sd-policies - "Don't mark up content that is not visible to readers of the page."
- **Severity:** AF.
- **Detect:** Every field in `schema.json` (services, ratings, hours, area served, FAQ Q&A) must have a matching on-page element. Schema-only content = fail. Run `scripts/schema_validator.py` against the page body.
- **Fix:** Either show the content on the page or remove it from the schema.

### D2 - Relevant and accurate markup
- **Check:** Is the schema type correct for the page and free of misleading or irrelevant markup? PASS/FAIL.
- **Source:** sd-policies - avoid "irrelevant or misleading content" and use markup that genuinely represents the page.
- **Severity:** AF.
- **Detect:** LocalBusiness subtype matches the actual business; no Event/Recipe/Product markup shoehorned onto a service page for rich-result bait.
- **Fix:** Use the correct type from the schema-library foundation; remove irrelevant types.

### D3 - No self-serving review markup
- **Check:** Is the page free of `review` / `aggregateRating` markup about the business itself placed on the business's own pages? PASS/FAIL.
- **Source:** review-snippet doc - "the entity that's being reviewed controls the reviews about itself ... pages that use LocalBusiness or any other type of Organization structured data are ineligible for the star review feature," and "don't rely on human editors to create, curate, or compile ratings ... for local businesses," and "don't aggregate reviews or ratings from other websites."
- **Severity:** AF.
- **Detect:** Any self-hosted review/aggregateRating on a LocalBusiness/Organization page (including embedded Google/Facebook widgets marked up as review schema) = fail. This is the single most common local-schema violation.
- **Fix:** Remove self-serving review markup. Reviews still belong on the visible page for humans and AI extraction; just do not mark them up as review structured data on your own business page.

### D4 - Honest ratings, real reviewers
- **Check:** If any review markup is legitimately used (third-party subject, not self), are ratings sourced from real users with valid names, not invented or promotional strings? PASS/FAIL.
- **Source:** review-snippet - "Ratings must be sourced directly from users" and reviewer name must be "a valid name" (e.g. "50% off until Saturday" is invalid).
- **Severity:** AF.
- **Detect:** No fabricated ratings, no promo text in reviewer names, ratingCount/reviewCount real.
- **Fix:** Only mark up genuine, sourced ratings; otherwise remove.

### D5 - No deceptive / impersonating markup
- **Check:** Does the schema avoid impersonating another entity or misrepresenting ownership, affiliation, or purpose? PASS/FAIL.
- **Source:** sd-policies - "Don't use structured data to deceive or mislead users. Don't impersonate any person or organization, or misrepresent your ownership, affiliation, or primary purpose."
- **Severity:** AF.
- **Detect:** Organization/LocalBusiness identity, sameAs links, and affiliations must be true.
- **Fix:** Correct to the real entity; remove false sameAs or parent-org claims.

### D6 - FAQPage: no rich-result reliance
- **Check:** Is the page NOT depending on FAQPage markup for a SERP rich result, given the feature was removed? PASS/FAIL.
- **Source:** faqpage doc / Search changelog - FAQ rich results deprecated May 2026, documentation removed June 2026; feature "no longer shown in Google Search results." (Consistent with `ai-search-reality-2026.md` Truth 7.)
- **Severity:** W.
- **Detect:** If FAQPage markup is present, it is allowed ONLY when there is a genuine, visible Q&A block on the page (helps AI extraction), never stuffed schema-only and never expected to produce a SERP accordion.
- **Fix:** Keep FAQ schema only alongside a real visible Q&A section; otherwise remove. Do not add fake Q&A to farm a dead rich result.

### D7 - Schema crawlable, not blocked
- **Check:** Are structured-data pages and their referenced image URLs crawlable and indexable (not blocked by robots.txt/noindex)? PASS/FAIL.
- **Source:** sd-policies - "Don't block your structured data pages ..." and "All image URLs ... must be crawlable and indexable."
- **Severity:** W.
- **Detect:** Referenced images resolve and are indexable.
- **Fix:** Unblock; use crawlable image URLs.

---

## Group E - Business representation and local accuracy

Source for the whole group: Google Business Profile "represent your business" guidelines. These govern the GBP but map directly onto on-site NAP, business name, and category content, which must match the profile (see the NAP-consistency foundation).

### E1 - Business name is the real name (no keyword/geo stuffing)
- **Check:** Does the business name used on the page (and in schema, and matching GBP) reflect the real-world name only, with no added keywords, city, tagline, phone, hours, or descriptors? PASS/FAIL.
- **Source:** GBP guidelines - name must "reflect your business's real-world name," and it is not permitted to add marketing taglines, location info, business hours, phone/URL, or product/service descriptors; doing so "could result in the suspension of your Business Profile."
- **Severity:** AF.
- **Detect:** "Joe's Plumbing" is fine. "Joe's Plumbing | Emergency Plumber Dallas TX 24/7" is a violation. Check the H1, title, schema `name`, and any NAP block.
- **Fix:** Use the legal/real-world name in name fields. Put the service and city in descriptive copy and headings where natural, never inside the business-name string.

### E2 - NAP accuracy and consistency
- **Check:** Do the name, address, and phone on the page exactly match the client's real, verified NAP and the GBP (same format)? PASS/FAIL.
- **Source:** GBP guidelines (accurate address, real-world consistency) + local AI entity-confidence research (`ai-search-reality-2026.md`).
- **Severity:** AF.
- **Detect:** Compare page NAP to `clients/<client>/brand.yaml` verified NAP, character-for-character on the phone and address format. Any mismatch = fail. Run `scripts/nap_checker.py` if present.
- **Fix:** Correct to the canonical NAP. If the client's own NAP is inconsistent across sources, flag it as an SME item; do not guess.

### E3 - Real, accurate location (no fake presence)
- **Check:** For a location or service-area page, does the business have a genuine, permitted presence or service relationship with that place (no fake addresses, no PO-box storefronts, no cities the business does not actually serve)? PASS/FAIL.
- **Source:** GBP guidelines - precise, accurate address reflecting a real location; no P.O. boxes/virtual offices posing as storefronts; permanent signage for storefront listings.
- **Severity:** AF.
- **Detect:** A city page for a city the operator does not serve, or a claimed office that does not exist, = fail. Service-area businesses describe areas served, they do not fake addresses.
- **Fix:** Only publish geo pages for places the business genuinely serves. For service-area businesses, describe the service relationship honestly; do not invent an address.

### E4 - Honest categories / services
- **Check:** Do the services and categories described match what the business actually does, without listing unrelated services just to rank? PASS/FAIL.
- **Source:** GBP guidelines - choose the fewest categories that describe the core business ("this business IS a," not "HAS a"); avoid keyword stuffing.
- **Severity:** W.
- **Detect:** Service lists padded with things the business does not really offer = fail.
- **Fix:** List only real services; move genuine-but-secondary services to their own honest sections.

### E5 - Consistent entity across page, schema, and GBP
- **Check:** Do the business identity, name, address, phone, hours, and services agree across the visible page, the JSON-LD, and the GBP? PASS/FAIL.
- **Source:** GBP accurate-representation principle + sd-policies markup-matches-content (D1) + AI entity-confidence research.
- **Severity:** W (AF if the NAP itself disagrees - that is E2).
- **Detect:** Cross-check the three surfaces. Hours in schema must match hours on page; services in schema must match services listed.
- **Fix:** Reconcile all three to the canonical client profile.

---

## Compliance gate - the exact checklist `/qa` and the compliance-auditor agent run

Run every rule below in order. Record PASS/FAIL with one line of evidence per rule in `compliance-report.md`. Any **AF** fail blocks publish and returns a specific error to the writing loop (fix, re-run, max 2 retries per doctrine Law 8, then human queue). **W** fails are logged and fixed unless the report carries a written override reason.

**Stage 1 - Spam hard lines (any fail = block):**
- [ ] B1 Scaled content abuse - unique value vs siblings (AF)
- [ ] B2 Doorway - page is a standalone destination (AF)
- [ ] B3 Keyword stuffing - natural language, no city/zip lists (AF)
- [ ] B4 Hidden text/links - nothing hidden for crawlers (AF)
- [ ] B5 Cloaking - one version for all (AF)
- [ ] B6 Sneaky redirects - honest links (AF)
- [ ] B7 Misleading functionality - every CTA is real (AF)
- [ ] B8 Expired-domain / site-reputation - first-party content on own domain (AF)
- [ ] B9 Thin affiliate / scraped - no copied merchant/franchise blocks (AF)

**Stage 2 - Trust and E-E-A-T (any AF fail = block):**
- [ ] C1 Trust present, not deceptive (AF)
- [ ] C2 First-hand experience, 3+ markers, 1 SME-only (AF)
- [ ] C6 No fabricated E-E-A-T - every specific sourced (AF)
- [ ] C4 YMYL correctly flagged (AF process gate)
- [ ] C5 YMYL heightened requirements met, if applicable (AF)
- [ ] C3 Expertise/authorship evident (W, AF if YMYL)

**Stage 3 - People-first content quality:**
- [ ] A1 People-first purpose (AF)
- [ ] A2 Original value over sources, not thin (AF)
- [ ] A3 Complete, satisfying answer (W)
- [ ] A4 No unhelpful-automation / padding tells (W, AF if with A2)
- [ ] A5 Honest title/headings (W)
- [ ] A6 Clean execution, no errors (W)

**Stage 4 - Structured data (any AF fail = block):**
- [ ] D1 Markup matches visible content (AF)
- [ ] D2 Relevant, correct type (AF)
- [ ] D3 No self-serving review markup on own LocalBusiness page (AF)
- [ ] D4 Honest ratings, valid reviewers (AF)
- [ ] D5 No impersonation/misrepresentation (AF)
- [ ] D6 No reliance on dead FAQ rich result (W)
- [ ] D7 Schema + images crawlable (W)

**Stage 5 - Business representation and local accuracy:**
- [ ] E1 Real business name, no keyword/geo stuffing (AF)
- [ ] E2 NAP accurate and consistent with GBP (AF)
- [ ] E3 Real location / genuine service area (AF)
- [ ] E4 Honest categories/services (W)
- [ ] E5 Entity consistent across page/schema/GBP (W)

**Gate result:** PASS only if every AF rule passes and every W is either passed or carries a written override. Emit the filled checklist as part of the page package. A page with no passed compliance gate is an unfinished draft, not a shippable page.

---

*Sources fetched live 2026-07-20 PKT. Google rewrites these docs without notice; re-verify the URLs above quarterly and on any reported core update. The laws are stable; the exact wording drifts.*
