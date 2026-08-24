# Quality Gates - The Pass/Fail Stack

Every local page clears this gate stack before it is finalized. A page is not "done" until every gate passes with evidence and the compliance report is written (the Output contract in `CLAUDE.md`). A draft with no gate report is an unfinished draft.

**How the stack works.** The gates run in order, cheap-to-expensive, fail-fast. A structural or trust miss (thin content, fabricated facts) kills the page before spending effort on the later checks. Each gate returns PASS, WARNING, or FAIL. A FAIL returns a specific error, reroutes to the fix, and re-runs. Max 2 automated retries, then the page is flagged for the operator (Law 8: refine only against a specific external error report, never blind self-refinement).

**Auto-fail vs warning.** An **auto-fail** gate blocks finalize on its own, no matter how good the rest of the page is. A **warning** gate flags a quality issue that is logged in the compliance report and should be fixed, but does not block on its own; two or more warnings on one page escalate to a hold.

**Who runs it.** The PLAN gate is enforced at plan time by `/build-topical-map` (which runs `topical_map_lint.py` on the map it writes) and re-confirmed at write-time GATE by the `compliance-auditor`. The `compliance-auditor` agent and the `/qa` command execute the rest of this stack. The `conversion-optimizer` agent runs G13 one step upstream (between `critical-editor` and `compliance-auditor`) and records its result, which `compliance-auditor` then verifies and logs in the report. The deterministic gates (blocklist scan, keyword density, meta length, schema validity, conversion linting) run as Python checks in `scripts/`; source resolution runs as an agent WebFetch check, because scripts make no network calls; the judgment gates (specificity, E-E-A-T, doorway risk, voice, conversion readiness) are the agent's reasoned pass with evidence recorded.

This whole stack is method-agnostic quality enforcement, never detector-evasion (Law 8, Hard Line 5). No gate references an AI detector, an AI-score, or "passing AI detection." Every gate optimizes something with a demonstrated link to rankings, citations, conversions, or trust.

---

## Run order at a glance

| # | Gate | Type |
|---|------|------|
| PLAN | Topical-map promotion (page is a status:page node; map lint clean) | auto-fail |
| G0 | Intent match and worth-writing | auto-fail |
| G1 | First-hand specificity and real local facts | auto-fail |
| G2 | E-E-A-T presence | auto-fail (money pages), warning (thin reference) |
| G3 | Doorway and thin-content risk | auto-fail |
| G4 | Passage-block extractability | warning to fail by threshold |
| G5 | Keyword-stuffing and over-optimization | auto-fail |
| G6 | Meta quality (title, description, H1) | auto-fail on missing/duplicate, else warning |
| G7 | Internal-link presence | warning to fail by threshold |
| G8 | Readability | warning |
| G9 | Voice fidelity | auto-fail on Tier-1 hit |
| G10 | Source resolution and no fabricated facts | auto-fail |
| G11 | Schema validity | auto-fail |
| G12 | Google compliance spine | auto-fail |
| G13 | Conversion readiness | auto-fail on hard misses, warning on soft |

---

## PLAN gate - Topical-map promotion

**Checks:** this page corresponds to a `status: page` node in `clients/<slug>/topical-map.md` (the evidence-gated plan built by `/build-topical-map`), and the client's map itself passes `scripts/topical_map_lint.py` with no unbacked promotions (every `status: page` node carries a real `evidence` line and `info_gain_thesis`).

**Why it matters:** the topical map is where node selection and the anti-doorway evidence gate live. A page written for an `index-only` or absent node is an unplanned, unearned page: it skipped the plan, so it never proved it carries a first-party specific that makes it un-copyable. Enforcing this at the plan level, before writing, is far cheaper than catching a doorway page at the final gate, and it is the machine backstop to the map architect's judgment (`knowledge/foundations/topical-map-protocol.md`, the evidence gate). This is NOT a topical-authority score (that is forbidden, Law 8 / topical-map-protocol trap #2); it is a binary presence-and-promotion check.

**Detect a fail:** resolve this page's node in `topical-map.md` (by `target_query` or `node_id`). Fail if the node is `index-only` or absent. Run `python scripts/topical_map_lint.py clients/<slug>/topical-map.md --manifest clients/<slug>/brand.yaml`; a non-zero exit (an unbacked promotion anywhere in the map) fails. **If no `topical-map.md` exists at all, FAIL** (do not skip): the page cannot ship without a plan. Allowing a no-map page to pass would reopen exactly the doorway-by-omission bypass the map exists to close.

**Fix:** run `/build-topical-map` and promote this node - supply the real first-party evidence that earns the page - or accept that the node stays `index-only` (a linked entry on the service-area/hub page) and do not write it. Reroute to `/build-topical-map`.

**Auto-fail.** Runs first, before G0: a page not in the evidence-gated plan does not get written. Enforced at PLAN time by `/build-topical-map` (which runs the lint on the map it produces) and re-confirmed at write-time GATE by `compliance-auditor`.

---

## G0 - Intent match and worth-writing

**Checks:** the page answers the one job it exists for, matches the dominant intent of its target query ("[service] [city]" is commercial-local, not informational), and has a real reason to exist that is not already fully served by the SERP or the AI Overview.

**Why it matters:** an intent miss is total invisibility, not a soft penalty; a large share of local informational queries now resolve inside the AI answer above the fold. A location page that duplicates the service page's intent is wasted production and a cannibalization risk. Getting this wrong voids every downstream gate.

**Detect a fail:** state the page's one job in a sentence; if you cannot, or if the draft answers a different question than the target query asks (a how-to written against a "hire a [trade] in [city]" query), fail. If the live SERP shows the AIO fully answers the query and this page adds nothing a person would still click for, it is a citation-only play and must be justified as one or killed, not shipped as a traffic page.

**Fix:** re-brief. Re-scope the angle to the real intent, or kill/merge the page. Reroute to the brief step.

**Auto-fail.**

---

## G1 - First-hand specificity and real local facts

**Checks:** the page carries genuine first-hand, locally specific detail that an LLM could not reconstruct from public web content: real neighborhoods served, the actual price or price band, real response times, named crew or credentials, a real job pattern, a specific local condition (the 1980s slab foundations, the hard water, the storm season). At least a few such markers, distributed across sections, at least one sourced from the SME interview.

**Why it matters:** first-hand experience is the dominant local ranking and trust lever, and it is the system's core differentiator versus a vanilla LLM. A page without it is generic by definition and gets cited and ranked at a fraction of the rate. This is the highest-priority gate.

**Detect a fail:** scan for concrete local specifics. If the page could be re-pointed to any other city or any competitor by find-and-replace on the business name, it fails. Generic industry claims ("with years of experience," "we handle all types of jobs"), invented scenarios ("imagine you wake up to..."), and quoted external stats with no local interpretation do NOT count as markers.

**Fix:** pull real specifics from `brand.yaml` and the SME interview. If the source material is thin, the fix is upstream: re-run the SME interview with pointed questions, or flag missing evidence to the operator. Never invent a local specific to pass this gate (that trips G10).

**Auto-fail.** Cannot be bypassed. The only way past is real markers from real source material.

---

## G2 - E-E-A-T presence

**Checks:** the page shows (not just claims) experience, expertise, authoritativeness, and trust with specifics: real credentials with numbers where public (license #, insurance, certifications), named people with real detail, verifiable proof (review counts and platforms, years in business, notable local projects), and the trust signals (real NAP, guarantees stated plainly). The about-page and money pages carry an author/business entity tied to real `sameAs` profiles.

**Why it matters:** the trust surface is what a fully-hands-off pipeline cannot fake, and Google's trust systems reward genuinely credible content. "Family-owned since 1998" is worthless without the specifics that prove it. For local service (often YMYL-adjacent: a bad roofer or electrician can hurt someone), shown E-E-A-T is load-bearing.

**Detect a fail:** look for claimed-but-unproven authority ("trusted experts," "years of experience" with no number, no named person, no credential). If every trust claim is a bare adjective, fail. Check credentials are real and, where they imply a license, that a real license number backs them.

**Fix:** surface the genuine experience the business actually has, from `brand.yaml` eeat block and the SME interview. Never manufacture a credential or a "we tested" that did not happen.

**Auto-fail on money pages** (service, service-city, homepage, about). **Warning on thin reference pages.**

---

## G3 - Doorway and thin-content risk

**Checks:** location, service-area, and service-city pages each carry unique, genuinely useful, locally-specific value. No templated near-duplicates across cities with only the city name swapped. Each page's core content is substantially different from its siblings and worth a standalone visit.

**Why it matters:** templated near-duplicate location pages are a named Google spam-policy violation (doorway pages / scaled content abuse) and the fastest path to a site-wide penalty. This is the single biggest risk in local SEO content at scale, and a hard line in the doctrine and the compliance spine.

**Detect a fail:** diff the page against its sibling pages (other city or service-area pages). If the unique content is below a meaningful threshold (the non-boilerplate body is mostly shared, with city name and a few tokens swapped), fail. A page that says nothing true and specific about *this* city that is not equally true of the next city over is a doorway page.

**Fix:** inject real per-city specifics (neighborhoods, local conditions, a real local job, city-specific pricing or permitting facts). If the business has nothing genuinely different to say about a given city, the correct action is to not publish that page, or to consolidate into a service-area page. Reroute to the location/service-area playbook.

**Auto-fail.**

---

## G4 - Passage-block extractability

**Checks:** most H2 sections are self-contained extractable answers: ~120 to 220 words, open with a one-sentence direct answer, one verifiable claim per paragraph, close with a citable factual statement, and survive the paste-this-sentence-alone test (no anaphora depending on a prior paragraph). FAQ and short-answer sections exempted.

**Why it matters:** AI answer engines lift and cite passages structured this way far more often than flowing essay sections. Extractability is the selection layer on top of ranking (Law 13). A well-structured local page can earn multiple citations for multiple sub-queries ("how much does X cost," "how fast can you come," "do you serve Y").

**Detect a fail:** per section, check the direct-answer lead (does the first sentence answer, or is it "When considering..." filler), the word band, one-claim-per-paragraph, and whether a lifted sentence still parses alone. Aggregate: 80%+ of sections clean = PASS, 60 to 79% = WARNING, below 60% = FAIL.

**Fix:** rewrite failing sections to lead with the answer, split multi-claim paragraphs, add a citable closer. For sections failing multiple sub-checks, regenerate rather than patch. Reroute to the outline/write step.

**Warning at 60-79%, FAIL below 60%.**

---

## G5 - Keyword-stuffing and over-optimization

**Checks:** the primary and secondary keywords appear at a natural density, not stuffed. No unnatural repetition of "[service] [city]" jammed into every sentence, header, and alt text. Exact-match anchor text is not over-used. The copy reads for the human first.

**Why it matters:** keyword stuffing and over-optimization are spam-policy violations and read as spam to the human too. Modern local ranking rewards natural entity coverage (repeat the real service and city term where it belongs, per voice lever 9), not density gaming. Over-optimization is a penalty surface.

**Detect a fail:** scan keyword density and distribution. Red flags: the exact "[service] [city]" phrase appearing so often it breaks readability, headers that all stuff the keyword, a sentence that names the city three times, exact-match anchors on every internal link. If reading the page aloud sounds like a keyword list, fail.

**Fix:** cut the stuffing. Use natural variation and pronouns where the entity is already established; keep exact-match where it reads naturally. Reroute to the write step.

**Auto-fail.**

---

## G6 - Meta quality

**Checks:** the meta title and description exist, are unique across the site, fit their pixel-width targets, carry the primary keyword + city naturally (title), make a specific non-generic promise (description), and the page has exactly one H1 that confirms the query match. Title and H1 are aligned but not required to be identical. Per `knowledge/voice/hooks-and-titles.md`.

**Why it matters:** the title and description win the click in the SERP; a generic or missing one leaves ranking on the table and tanks CTR. Duplicate titles across location pages compound the doorway risk. The H1 confirms the visitor is in the right place and stops the bounce.

**Detect a fail:** missing title/description, duplicate title across pages, no H1 or multiple H1s, title over the pixel band, or a description that could belong to any competitor (swap the brand name and it still fits). Also fail a title that keyword-stuffs (ties to G5) or promises what the page does not deliver.

**Fix:** rewrite to the hooks-and-titles patterns with a real specific in the description. Reroute to the write step.

**Auto-fail on missing, duplicate, or missing/multiple H1. Warning on a weak-but-present meta.**

---

## G7 - Internal-link presence

**Checks:** the page links out to its logically related pages (service page to relevant city pages and the homepage; location page to the services offered there and the service-area parent) with descriptive, varied anchor text, and is itself linked to from the right parents. No orphan page. 2 to 4 contextual internal links minimum for a standard page, placed at decision-relevant moments, not stuffed in a footer block.

**Why it matters:** internal linking distributes authority and signals topical structure; orphan pages are treated as low-authority and rarely cited or ranked. For a local site the cluster of service and location pages needs a coherent link graph to compound (Law 10, Law 13).

**Detect a fail:** count contextual internal links in and out. Zero outbound contextual links, or the page not reachable from any parent, fails. Over-linking with exact-match anchors on every link crosses into G5. Fewer than 2 contextual links = WARNING, orphan = FAIL.

**Fix:** add contextual links per the internal-linking foundation with descriptive anchors; add the reverse link from the parent. Reroute to the internal-linking step.

**FAIL if orphan, WARNING if under 2 contextual links.**

---

## G8 - Readability

**Checks:** the copy reads at the client's target reading level (`brand.yaml` reading_level, usually Grade 6 to 8 for home services), sentence and paragraph rhythm hit the distribution in `knowledge/voice/sentence-rhythm.md`, no wall-of-text block over ~4 sentences, and it passes the read-aloud test.

**Why it matters:** local visitors read on phones, mid-problem. Copy above their level or in flat monotone rhythm bounces them, and flat rhythm also reads as machine-written to a human before they process a word. Readability is a conversion factor and a human-trust factor.

**Detect a fail:** run a readability score against the target band; run the rhythm self-test (distribution, adjacent variance, anaphora scan). Sections well above the target grade or with metronome rhythm flag.

**Fix:** apply the rhythm rules and the natural-voice levers; simplify the advanced mechanism, not by dumbing down but by shorter sentences and plainer words. Reroute to the humanize step.

**Warning.** (Escalates to a hold if combined with a voice-fidelity warning.)

---

## G9 - Voice fidelity

**Checks:** two layers. Layer 1 (universal): zero Tier-1 vocabulary-blocklist hits, no Tier-3 structural anti-patterns, naturalness rubric passed (`knowledge/voice/`). Layer 2 (client): the draft matches `brand.yaml` one_line_direction, the tone_by_context for this page type, respects the client banned_phrases, and reads closer to the good_examples than the off_brand_examples.

**Why it matters:** voice fidelity is what makes the page read as this specific business and not as generic AI. A Tier-1 blocklist hit ("seamless solutions," "your trusted partner," "peace of mind") is an instant tell that undermines every trust signal on the page.

**Detect a fail:** deterministic scan for Tier-1 and client banned phrases (any hit = fail). Agent pass for Tier-3 structures and the naturalness rubric. Read the draft against the client good/off-brand examples: if it reads like the off-brand column, fail.

**Fix:** rewrite from a more specific premise (not word-substitution). Reroute to the humanize step. If the fix keeps failing because the source is thin, escalate: the premise or the SME material is the problem.

**Auto-fail on any Tier-1 or client-banned-phrase hit. Warning on rubric/tone drift.**

---

## G10 - Source resolution and no fabricated facts

**Checks:** every external factual or quantitative claim carries a source URL that resolves (HTTP 200) and actually supports the claim; every local specific (price, response time, review count, years, credentials, service areas) traces to `brand.yaml`, the SME interview, or a cited source. Zero fabricated facts, zero fabricated citations, zero invented local specifics.

**Why it matters:** a fabricated local specific is the fastest path to a trust penalty and a furious client, and a broken citation is a credibility hit that compounds. This is the last line of defense against the defining failure mode of AI drafting: the confident, plausible, false number. Cite or do not claim (Hard rule in CLAUDE.md).

**Detect a fail:** resolve every URL (agent WebFetch check, since scripts make no network calls); a single 404/dead link fails. For each local specific, confirm it appears in `brand.yaml` or the tagged SME answers or a cited source; an untraceable specific is treated as fabricated. Under starvation (thin proof manifest), the correct behavior is a missing-evidence flag, never an invented stat.

**Fix:** replace or remove any claim whose source does not resolve or does not support it; source every untraceable local specific or cut it. A dead URL cannot be shipped; either re-source or remove.

**Auto-fail.** Cannot be overridden for a dead URL or a fabricated specific.

---

## G11 - Schema validity

**Checks:** the JSON-LD bundle parses as valid JSON, validates against schema.org types, all `@id` references resolve internally, all URLs are absolute, dates are ISO 8601, and the mandatory local set is present: the correct LocalBusiness subtype (from `brand.yaml`), plus Service/Article as fitting, BreadcrumbList, and FAQPage where FAQ content is on the page. NAP in schema is byte-identical to the page and to `brand.yaml`. Validated by `scripts/schema_validator.py`.

**Why it matters:** schema is a machine-readable trust and entity signal (Law 13); invalid JSON-LD breaks parsers and, when it references content not on the page (e.g. FAQ schema with answers absent from the body), risks a manual action under the spam policies. NAP mismatch between schema, page, and GBP damages local ranking (the NAP-consistency foundation).

**Detect a fail:** run the validator. JSON parse error, missing required property, unresolved `@id`, relative URL, malformed date, missing mandatory type, or NAP mismatch = fail. FAQ schema whose answers are not on the page = fail.

**Fix:** regenerate the bundle from `brand.yaml` and the schema-library foundation. Reroute to the schema step.

**Auto-fail** on invalid JSON, missing mandatory type, or NAP mismatch.

---

## G12 - Google compliance spine

**Checks:** the final governing pass. The page obeys every rule in `knowledge/doctrine/google-compliance-spine.md`: no doorway pages (re-confirms G3 at the site level), no scaled low-value content, no keyword stuffing (re-confirms G5), no unverifiable superlatives ("the best," "#1," "cheapest" unless literally supportable), no cloaked or deceptive claims, real E-E-A-T (re-confirms G2), compliant claims for regulated trades (a licensed-trade claim carries a real license; medical/legal/financial claims align with consensus and carry required disclaimers), and no fabricated facts (re-confirms G10). If a technique on the page is not defensible under Google's published guidance, it does not ship.

**Why it matters:** this is the whole point of the system: Google-compliant by construction. Every earlier gate feeds this one; G12 is the single sign-off that the page is penalty-proof because it was written to Google's own rules. It is where regulated-trade and superlative-claim risks that slip past the content gates get caught.

**Detect a fail:** run the compliance checklist. Any doorway signal, any unsupported superlative, any regulated claim without its substantiation or disclaimer, any spam-policy touch = fail. When in doubt on a specific claim, read the actual current Google or regulatory doc live before signing off.

**Fix:** remove or correct the non-compliant element. A regulated claim gets its real credential/disclaimer or is cut. A superlative gets its proof or is cut. Reroute to the specific earlier gate that owns the fix.

**Auto-fail.** The final compliance sign-off. It proves every conversion element on the page is truthful (no fabricated urgency, scarcity, or proof, Law 20) before G13 judges whether those real elements are arranged to convert. G13 is the last quality gate; the page does not finalize until both pass.

---

## G13 - Conversion readiness

**Checks:** the page does not just rank, it asks for and earns the call or the booking. G0 to G12 can all pass on a page that still converts poorly, so this gate tests the conversion arrangement directly, on elements the earlier gates have already proven real (G1 specificity, G2 E-E-A-T, G10 sources, G12 truthfulness). Seven sub-checks:

1. **One primary action, repeated, no co-equal competitor.** The page has a single dominant conversion goal repeated at the decision points (hero and closing at minimum), not two co-equal primary CTAs that split intent, and not a full multi-link global nav competing with the ask on a conversion page (Oli Gardner attention ratio). Offering both a click-to-call and a form/scheduler is NOT a competing CTA: they serve the two local intent states (URGENT leads with the call, CONSIDERED leads with the form or scheduler, per the page-type playbook), and both point at the one goal of becoming a lead. A leak is a second, unrelated primary ask (a newsletter signup, a lead-magnet download, a "learn more" of equal weight) or an 8-link nav, not a call-and-form pair.
2. **Mobile click-to-call present.** A real, tappable `tel:` link, NAP-consistent (byte-identical to `brand.yaml.nap` and to the page, ties to G11), reachable without hunting. Local emergency-intent traffic converts by phone; a phone number that is plain text on mobile is a dropped call.
3. **First-person / outcome CTA verb.** The CTA verb names the outcome the visitor gets ("Get my free roof inspection," "Book my consult," "Claim my estimate"), not a mechanical "Submit," "Send," or a bare "Get a quote." (Direction is well-replicated; the oft-cited magnitude is folklore, do not quote a lift figure, research file 03.)
4. **A real price or price-driver signal.** The page carries a real price, price band, or price driver ("$149 drain camera inspection," "$55 off," "free local estimate," "0% APR for 12 months"), or an explicit, honest "custom quote because [reason]" for verticals that genuinely cannot post a price. A bare "contact us for pricing" with no driver and no honest reason is the fail. Every price traces to `brand.yaml` or the SME answers (ties to G1/G10, never invented).
5. **A genuine risk-reversal where the ticket warrants it.** For higher-ticket considered work (roof, remodel, implants, legal, solar) a named, precise risk-reversal is present at the ask (a workmanship warranty with a duration, "no fee until we win," "free re-inspection," a punitive on-time guarantee), not a hollow "100% satisfaction guaranteed" with no mechanism or duration. Low-ticket urgent work may carry a lighter reversal ("free estimate, no service fee"). The guarantee is real and operationally true (ties to G12/Law 20).
6. **Proof distributed, not pooled.** Social proof sits next to the claim it supports (an on-time review beside the on-time promise), with one compact proof element repeated near the final CTA, rather than every review dumped in a single bottom carousel the F-pattern scanner never reaches (Bencivenga distributed proof, NN/g). Each proof element is attributable and verifiable (ties to G2/G10).
7. **The ask comes after the proof and the FAQ.** A CTA appears after the proof block and after the FAQ/objection block, so the scroller who read the whole page and had objections answered still meets an ask. A page that informs, proves, answers, and never asks again is a failed local page.

All conversion elements must be truthful per Law 20: no countdown that resets, no "only 2 spots left" that is not true, no invented review, no stock testimonial, no fabricated scarcity or urgency. The legitimate substitutes are real risk-reversal, real attributable social proof, and real truthful urgency (a genuine seasonal deadline, a real booked-out calendar).

**Why it matters:** the system's stated job is to convert the local buyer (call or book), not only to rank. Nothing in G0 to G12 fails a page for a weak CTA verb, proof pooled where no one reads it, a missing price signal, a missing risk-reversal at the ask, or a second co-equal CTA bleeding intent. This gate closes that gap, and it does it only on elements already proven real, so it can never reward a page for a persuasive lie.

**Detect a fail:** run `scripts/conversion_linter.py` for the deterministic flags (count of competing primary CTAs, presence of a `tel:` click-to-call, first-person vs mechanical CTA verb, presence of a price/driver token vs bare "contact us," presence of a risk-reversal keyword, whether a CTA follows the proof and FAQ blocks). Then read for what the script cannot judge: is the "guarantee" a real mechanism or a hollow badge, is proof genuinely next to its claim or merely present, is the price driver honest, does the primary CTA match the URGENT/CONSIDERED intent the playbook prescribes. Cross-check every urgency, scarcity, guarantee, and proof element against `brand.yaml` or a cited source for truthfulness.

- **Auto-fail** on any of: no mobile click-to-call (`tel:`) present; two or more co-equal competing primary CTAs (a call-and-form pair does not count) or a full global nav on the conversion page; no CTA after the proof and FAQ blocks (the page never asks again); any fabricated urgency, scarcity, guarantee, or proof element (Law 20, also caught by G10/G12).
- **Warning** on any of: a mechanical CTA verb ("Submit," "Send," bare "Get a quote") where a first-person outcome verb belongs; no price or price-driver signal and no honest custom-quote reason; no risk-reversal where the ticket clearly warrants one; proof pooled in a single block instead of distributed next to its claims. Two or more warnings on one page escalate to a hold (per the stack rule).

**Fix:** for a competing-CTA leak, demote everything but the one primary action to a text link (keep the intent-appropriate call/form pair). Add the `tel:` click-to-call and make it NAP-consistent. Rewrite the CTA verb to name the outcome. Inject a real price or price driver from `brand.yaml`/SME, or state the honest custom-quote reason. Add a real, named risk-reversal from `brand.yaml.eeat` where the ticket warrants it (never invent one). Move pooled proof next to the claims it supports and repeat one compact element near the closing CTA. Add the closing CTA after the proof and FAQ. Reroute to `critical-editor` for surgical placement, or to `sme-interviewer` if a real price/guarantee/proof is missing from source. Never invent a conversion element to pass this gate (that trips G10/G12/Law 20).

**Auto-fail on the hard misses above, warning on the soft ones.**

---

## After the stack

When every gate passes, the `compliance-auditor` writes the filled `compliance-report.md` with each gate marked PASS and its evidence, per the Output contract. Only then is the page package complete (page.md, schema.json, internal-links.md, compliance-report.md, sources.md). The gate results append to the client case file so the system compounds (Law 10).
