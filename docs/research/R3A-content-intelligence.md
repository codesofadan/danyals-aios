# R3A — Content intelligence — topical maps, local differentiators, pacing and decay

> Track R3A of the AIOS v2 Rescue & Re-engineering Plan. Evidenced decision record.
> All external claims carry a source URL and the accessed date **2026-08-23**.
> Anything not verified at a primary source is marked `[UNVERIFIED]` with the exact
> test that would settle it. Sibling track R3B owns the WordPress publishing engine.
> House rule CONT-21 (zero em dashes) is honoured in the body prose. The title and
> the Sources section use the em dash only because the deliverable format for this
> track mandates the `[label] URL — accessed <date>` citation pattern.

---

## 1. Decision

We will build the content system as a **thirteen-stage, evidence-gated page-production line** whose planning primitive is a **versioned topical map bounded by a declared, closed semantic boundary** (`topical_maps` / `topic_clusters` / `map_entities` / `entity_relations` / `page_plans` / `internal_link_plan`), not a keyword list. Per-page distinctiveness will come from a **mandatory local-fact substrate** (`client_local_facts`) collected at onboarding and enforced by a new pipeline stage, the **fact gate**, which sits between brief and draft and **holds the page rather than drafting it** when the required facts are absent; it is structurally impossible for the generator to invent a local fact because the drafting call is given the fact set as its only permitted source of concrete local claims, and a post-draft validator rejects any URL, number, proper noun or quotation that is not in the run's evidence pool. Bulk output will pass a **deterministic two-band near-duplicate gate** (word 5-gram Jaccard on main content, computed twice: raw, and with location and brand tokens masked, against both the current run and every page ever published or crawled for that client), blocking at masked Jaccard >= 0.80 or raw >= 0.90 and holding for review between 0.60 and 0.80. Publication will be **paced by a plan, not a burst**: a default of **6 pages per client per week**, capped at 1 per calendar day with a minimum 18-hour gap and +/-25% slot jitter (see the correction in R3A-27: a 2-per-day cap is unreachable alongside an 18-hour gap and a business-hours window, and one of the three had to give), scaling with the client's existing indexed corpus as `weekly_cap = clamp(3, 15, ceil(0.05 * indexed_pages))`, and additionally throttled by a **global human-review capacity budget**, because at 100 clients the L3 approval ceiling, not model cost, is the binding constraint. QA stays **advisory and visible** per decision D-4: the fourteen-dimension scorecard is rendered to the reviewer with per-dimension justification and evidence reference, and publication is blocked by **missing acknowledgement**, never by the score. Maintenance is a first-class loop with six named decay triggers, and refresh is separated from rewrite by an evidence test (re-run the research; if SERP format or dominant intent changed, it is a rewrite and re-enters at stage 2; otherwise it is a refresh to the same URL).

---

## 2. Context

The content module is the largest single piece of v1 scope (decision D-1, module 3 of five) and the operator's own assessment is that roughly 90% of the work remains (`docs/recovery/DANIEL_PROJECT_RECOVERY_SPECIFICATION.md` §14). The owner's bar is content output that beats 99% of SEO strategists. That is an aspiration, not a specification, and this track exists to convert it into engineering constraints.

Four questions block the build, and none of them can be answered by reading the existing code:

1. **What is the planning primitive?** The current pipeline's unit of work is one page with one topic string (`db/migrations/0017_content.sql`, columns `topic`, `page_type`, `framework`). There is no stored map, no entity graph, no cluster, and no internal-link plan. Bulk mode without a map is a page generator, which is the exact shape Google's spam policy names.
2. **What makes 100 city pages genuinely different?** Without a data model for real local facts, a bulk run produces the doorway pattern by construction. `client_business_profiles` (`db/migrations/0051_client_business_profile.sql`) stores one address, one phone, one description per client. There is nowhere to put a branch manager's name, a local partner, or a photograph taken in a specific suburb.
3. **What stops a bad bulk run reaching a client's live site?** There is no near-duplicate check anywhere in the repository. A `grep` for `simhash|minhash|near_duplicate|jaccard|shingle` across `backend/` returns nothing in the content path. `IMP-13` in the recovery specification (`DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1999`) names it *"the biggest SEO exposure in the product"*; `MR-25` (line 1873) lists the same gap under the shorter rationale *"Doorway-page risk"*, and `R-3` (line 2027) rates a doorway penalty **Catastrophic**. The first draft attributed the "single largest exposure" phrasing to both; only IMP-13 says it.
4. **What is the publication rate, and why that rate?** `content_jobs.publish_at` exists (`db/migrations/0072_content_schedule.sql`) but is a single nullable timestamp with a **disabled** beat sweep. There is no plan object, no pace, and no operator view of a schedule.

Two further facts make this urgent rather than merely important. First, the QA gate that was supposed to protect quality is uncalibrated and its status was contradictory across documents; `docs/implementation/KNOWN_LIMITATIONS.md` confirms the publish path already treats QA as advisory and that `PublishBlocked` is raised nowhere, so the "mandatory acknowledgement" half of D-4 is entirely unbuilt. Second, the doctrine that the code claims to implement points at a path that **does not exist as a directory in this repository**: `backend/docs/CONTENT-DOCTRINE.md:8,19,82` declares `backend/seo-content-os/knowledge/` the canonical spine, and `find . -type d -name seo-content-os` returns nothing, as does `git log --all -- backend/seo-content-os`.

**Correction found in verification: the knowledge base is not missing, its path is wrong.** `SEO-CONTENT-OS.zip` (1.16 MB, 216 files) is **tracked in git at the repository root** (`git ls-files SEO-CONTENT-OS.zip` resolves) and contains `SEO-CONTENT-OS/knowledge/` with exactly the files the code cites, including `foundations/passage-block-protocol.md`, `foundations/meta-and-headings.md`, `doctrine/local-content-laws.md` and `quality-gates/gates.md`. So the accurate statement is narrower and still a real defect: **every "knowledge source" citation in `content_generator.py` and `content_qa.py` names a path that does not resolve**, and an engineer must know to unzip a root-level archive to read the justification for a constant they are being asked to tune. This is a broken-provenance defect, not a fabricated one, and R3A-37 (repointing the citations, or unpacking the archive into the tree) closes it. The stronger original claim in this document's first draft, that the cited passages were unreadable by anyone, was wrong and is withdrawn.

---

## 3. Findings

### 3.1 Google's position on AI content, scale and doorways is narrower and more precise than the received version

**Conclusion: Google does not penalise AI-generated content, and it does not penalise volume. It penalises pages generated primarily to manipulate rankings, and it penalises page sets whose members are similar to each other. Similarity is the trigger, not the generator and not the count.**

Google's spam policies (last updated 2026-05-15) define scaled content abuse as: *"Scaled content abuse is when many pages are generated for the primary purpose of manipulating search rankings and not helping users."* The AI-specific example given is *"Using generative AI tools or other similar tools to generate many pages without adding value for users."* The operative clause in both is purpose and value, not authorship. [Google spam policies]

Doorway abuse is defined separately and is the one that binds a service-x-city page set: *"Doorway abuse is when sites or pages are created to rank for specific, similar search queries. They lead users to intermediate pages that are not as useful as the final destination."* The two examples that bind us are, verbatim: *"Having multiple websites with slight variations to the URL and home page to maximize their reach for any specific query"* and *"Having multiple domain names or pages targeted at specific regions or cities that funnel users to one page."* The other two are *"Generating pages to funnel visitors into the actual usable or relevant portion of a site"* and *"Creating substantially similar pages that are closer to search results than a clearly defined, browseable hierarchy."* [Google spam policies]

Google's own framing of what makes content acceptable is the "Who, How, Why" test, plus the E-E-A-T model in which **Experience** means *"firsthand knowledge from actually using products or visiting places."* Google states plainly: *"If the 'why' is that you're primarily making content to attract search engine visits, that's not aligned with what our systems seek to reward."* Google also directs sites to disclose how automation or AI was used *"where readers would reasonably expect them."* [Google creating-helpful-content, last updated 2025-12-10]

**Correction to a starting fact given to this track.** The brief states that "the March 2026 core update named scaled content abuse as a primary target." That conflates two distinct, separately-recorded events. Google's own Search Status Dashboard records a **March 2026 spam update** starting 2026-03-24 and completing in 19 hours 30 minutes, and a **March 2026 core update** starting 2026-03-27 and running 12 days 4 hours. [Google Search Status Dashboard] Google's core-update documentation states that core updates are *"significant, broad changes to our search algorithms and systems"* that are *"broad in nature, and don't target specific sites or individual web pages"* [Google core updates, last updated 2025-12-10]. A core update by Google's own definition does not name a target. Scaled content abuse is a **spam policy**, enforced through spam updates and manual actions. The engineering consequence is unchanged and if anything sharper: the spam-policy surface is enforced continuously and fast (the March spam update completed in under 20 hours), so a doorway-shaped page set does not get a grace period.

**The current enforcement climate is live, not historical.** The dashboard records three spam updates in 2026: March (2026-03-24), June (2026-06-24, 2 days 1 hour) and **August (2026-08-18, 2 days 16 hours, completing 2026-08-21)**, plus a **May 2026 core update** (2026-05-21, 11 days 21 hours). The August spam update finished two days before this document was written. [Google Search Status Dashboard]

The "50 to 80% traffic loss for sites publishing hundreds of AI pages without editorial oversight" figure that seeded this track appears widely in SEO trade coverage of the March 2026 updates but I could not locate it in any Google publication or in a named, methodology-disclosed dataset. **`[UNVERIFIED]`** as a specific magnitude. What would verify it: a published traffic study with a disclosed sample frame, or a Google statement. The directional claim (sites doing this lost significant traffic) is consistent with the spam-policy text and with the trade reporting, and I am comfortable acting on the direction. I am not comfortable quoting the number to a client, and the platform must not.

**Engineering consequence.** Do not build a "how many pages is safe" limiter. Build a **similarity** limiter and a **value** gate. The number of pages is not the risk surface. Section 3.3 gives the similarity algorithm and section 3.2 gives the value substrate.

### 3.2 The line between programmatic SEO and doorway spam is the data source, and the data source has to be a table

**Conclusion: the only durable defence is per-location first-party facts that a competitor could not produce, captured as structured rows with provenance, and the generator must be architecturally incapable of proceeding without them.**

This follows directly from the two Google definitions above. Doorway abuse is about pages being *similar to each other*; E-E-A-T Experience is about *first-hand knowledge*. A page that carries a named branch manager, a branch-specific phone number, the three suburbs actually served from that branch, a named local supplier, a dated local job with a street-level location, and a photograph taken there is not similar to its sibling and is not a national page in costume. A page that carries a city name substituted into a template is both.

The 80/20 heuristic (80% shared skeleton, 20% genuinely unique dynamic content) and the various "300 words unique", "500 words with 30-40% variation", "60% unique" thresholds circulating in 2026 programmatic-SEO commentary are all **secondary, vendor-blog sources with no disclosed methodology and no agreement among themselves**. I record them as evidence that no consensus number exists rather than as a number to build to. **`[UNVERIFIED]`**. What would settle it for this platform: our own labelled corpus (section 8, open item O-2).

**What the repo has and does not have.** `client_business_profiles` (`db/migrations/0051_client_business_profile.sql:26-55`) stores exactly one location per client: `address_line1`, `city`, `region`, `postal_code`, `phone`, `hours`, `description`, `primary_category`, `extra_categories`. There is a `unique (client_id)` constraint on that table.

**Correction found in verification: multi-location is already modelled, just not for content.** `public.business_profiles` (`db/migrations/0045_citation_web2_automation.sql:74-93`, extended by `0048_directories_strategy.sql:124-125` with `nap_locked` and by `0060_business_profile_fields.sql` with description, email, logo, socials, `year_founded`, `payment_types`, `tagline`, `service_area`) is the citation engine's **multi-location** canonical NAP: one row per branch, with `label`, `is_primary` and no unique-per-client constraint. `0051`'s own header comment says so explicitly. So the true state is not "multi-location is not modelled"; it is that **two overlapping business-identity tables already exist** (a per-client identity record and a per-branch submission record) and neither is reachable from the content pipeline. This changes what D-9 is actually deciding and what R3A-12 must do: see the revised R3A-12, which is now a reconciliation, not a greenfield table. The onboarding template (`backend/app/modules/client_onboarding/constants.py`) has eleven steps and does collect brand assets ("logo, guidelines, voice, photos") and a named competitor list, but produces **free-text notes on a checklist step**, not structured facts. There is no table that can hold "the manager at the Croydon branch is Priya Nair, in post since 2021, and we keep the CCTV van there."

The generator does carry a differentiation concept already: `DIFFERENTIATION_KINDS = ("unique_data", "first_hand_experience", "better_format", "missed_angle")` (`backend/app/services/content_generator.py:92-97`) and `_NO_FIRST_HAND_CAP = 40` in the QA gate (`backend/app/services/content_qa.py`), which caps the E-E-A-T dimension for a page with zero first-hand experience. But since QA is advisory (`docs/implementation/KNOWN_LIMITATIONS.md` §3), that cap currently changes a number in a log line and nothing else. The mechanism exists; the enforcement does not.

### 3.3 Near-duplicate detection at our corpus size is a solved, cheap, deterministic problem, and we should not use the web-scale technique

**Conclusion: use exact word 5-gram Jaccard, computed twice (raw and location-masked), pairwise. Do not reach for SimHash or MinHash below about 5,000 pages per client; they solve a scale problem we do not have and their published thresholds are calibrated for a corpus eight orders of magnitude larger than ours.**

The canonical technique is shingling: *"Given a positive integer k and a sequence of terms in a document d, define the k-shingles of d to be the set of all consecutive sequences of k terms in d,"* with similarity measured by the Jaccard coefficient `|S(d1) ∩ S(d2)| / |S(d1) ∪ S(d2)|`. The Stanford IR textbook states that *"k=4 is a typical value used in the detection of near-duplicate web pages"*. On the threshold it is deliberately illustrative rather than prescriptive: *"if it exceeds a preset threshold (say, 0.9), we declare them near duplicates"*. **The "say" is load-bearing and must not be dropped: 0.9 is the textbook's worked example, not a calibrated standard**, and section 5.3 treats it accordingly. [Manning, Raghavan & Schütze, *Introduction to Information Retrieval*, near-duplicates and shingling]

The web-scale variant is Charikar's SimHash as applied by Google: Manku, Jain and Das Sarma report that *"We experimentally validate that for a repository of 8B web-pages, 64-bit simhash fingerprints and k = 3 are reasonable"* (k here being Hamming distance). [Manku et al., WWW 2007, Google Research] Wikipedia's SimHash entry confirms *"In 2007 Google reported using Simhash for duplicate detection for web crawling,"* citing that paper. **Verification note:** the PDF at the Google Research URL is served with Flate-compressed streams that the fetch tool could not read, so the file was downloaded and its content streams decompressed locally on 2026-08-23. The sentence above is the paper's own wording from its contributions list and is now **verified at the primary source**, not inferred.

**Why 64-bit / k=3 is the wrong parameterisation for us, stated on the paper's own numbers.** The paper reports its accuracy at that setting directly: *"Choosing k = 3 is reasonable because both precision and recall are near 0.75."* Two consequences follow, and neither is the one an earlier draft of this section asserted.

   1. **k=3 is not a "find only identical documents" setting.** At precision and recall near 0.75 it both misses about a quarter of true near-duplicate pairs and mislabels about a quarter of what it reports. That accuracy was acceptable to Google because the decision it feeds is whether to drop a crawl slot, taken *"within a few milliseconds"* against 8 billion fingerprints. It is not acceptable as the gate that decides whether a page reaches a paying client's live site, where a miss is a doorway exposure and a false positive is a blocked page.
   2. **A bit-distance verdict is the wrong shape for our review band.** The design in section 5.3 needs a *graded* score to place a pair in a BLOCK / HOLD / pass band and to show a reviewer how similar two pages are. Hamming distance over a 64-bit fingerprint yields a coarse integer with no calibrated mapping to "how much of this page is the same page", so it cannot drive a review threshold or a side-by-side diff.

   ~~Hamming distance 3 on 64 bits would let two city pages that differ only in the city name pass as distinct.~~ **`[WITHDRAWN]`. This claim was in the first draft, is unsourced, and is very likely backwards:** SimHash maps similar documents to *near* fingerprints, so two pages differing only in a city token would tend to fall *within* a small Hamming distance and be flagged, not missed. Nothing in the paper or in any source located supports the original assertion, and no measurement was made. The rejection of SimHash rests on points 1 and 2 above, which are sourced, not on this.

   And at our scale, exact pairwise Jaccard is trivially affordable: for a client with 100 pages in a run against 1,000 already published, that is 100 x 1,000 + 4,950 = 104,950 set-intersection operations on sets of roughly 1,000 shingles, which is seconds of single-core Python. SimHash is a prefilter for when exact comparison stops being affordable, and it is not.

**The location-masking test is the load-bearing one.** Raw Jaccard between two well-written city pages that genuinely differ will be low, but so will raw Jaccard between two templated pages that each mention their city forty times, because the city token itself contributes distinguishing shingles. Masking every location and brand token to a placeholder before shingling removes exactly the variation that a template generates for free, leaving only the variation a human or a fact substrate had to supply. This makes "95% identical pages across cities is a spam flag" a computable predicate rather than a slogan.

**The structural test catches what the lexical test misses.** Two pages can differ enough lexically to pass while sharing an identical H2 sequence. An identical heading sequence plus even moderate masked similarity is the doorway pattern; the pair should hold.

**The corpus-level test catches what pairwise misses.** Forty pages that are each 0.55 similar to every other page trip no pairwise band but are collectively a template run. The mean pairwise masked Jaccard across a run is the right statistic for that, and it must have its own threshold.

### 3.4 Publishing pace has no ranking justification; it has an operational one, and that changes the design

**Conclusion: publish 6 pages per client per week by default, scaling with site size, and throttle globally by human-review capacity. The rate does not buy ranking safety. It buys blast-radius containment, attributable measurement, and a review queue a human can actually clear. The 5-10/week figure in the brief is directionally right and has no primary source.**

Google's John Mueller has said repeatedly that publishing frequency is not a ranking factor. Asked directly whether publishing one article per day would rank higher than one per week, he answered *"I don't think so. So there are a lot of factors that go into ranking. And being able to crawl and index a website is definitely one of those things,"* and separately that the number of pages on a site is not a ranking factor. These are **secondary sources** (Search Engine Roundtable, iLoveSEO) reporting Google office-hours statements. I could find no Google documentation page stating a publishing rate in either direction, which is consistent: Google documents policies, not cadences.

I could find **no primary source for "5-10 pages per week"** anywhere. **`[UNVERIFIED]`**. It appears to be practitioner convention. What would settle it: the controlled experiment in open item O-1.

**The real justifications, each of which is verifiable and each of which implies a different part of the design:**

1. **Recovery is slow, so mistakes are expensive.** Google states that after making improvements, *"some changes can take effect in a few days, but it could take several months for our systems to learn and confirm that the site as a whole is now producing helpful, reliable, people-first content"* and that *"if it's been a few months and you still haven't seen any effect, that could mean waiting until the next core update."* [Google core updates] Publishing 100 pages in one minute converts a design error into a several-month recovery across the whole set. Publishing 6 per week means the error is caught at page 6 to 12.
2. **The L3 automation ceiling makes human review the scaling wall.** Content publishing is permanently capped at L3: a human approves each action or batch. At 100 clients and 6 pages per week each, that is 600 approvals per week. At eight minutes per review that is 80 hours per week, or two full-time reviewers. **This, not model cost, is what breaks at 100 clients.** The pacer must therefore be a two-level scheduler: a per-client rate and a **global daily review-capacity budget** that no per-client rate may collectively exceed.
3. **Attribution needs separation.** Twenty pages published in the same minute cannot be individually attributed in Search Console. A paced plan with a known slot per page makes each page's indexation and first-impression date a measurable event, which is what the decay model in section 3.6 consumes.
4. **Crawl discovery is real but is not the constraint at our volume.** Mueller's own qualifier is that at one page per day or per week *"the ability for Google to crawl that is trivial."* So crawl budget is not a reason to pace at these volumes, and we should not claim it is.

**The rate I will stand behind, and why it scales with site size.** A fixed weekly number is wrong at both ends: six pages a week doubles a 20-page site in a month, and is a pointless trickle on a 2,000-page site. The rule `weekly_cap = clamp(3, 15, ceil(0.05 * indexed_pages))` keeps any single week's addition at or below 5% of the existing corpus, so no week's batch can dominate the site's content profile, with a floor that keeps small sites moving and a ceiling that keeps the review queue and the blast radius bounded. **The 5% figure is a policy choice with a stated rationale, not a published external threshold. `[UNVERIFIED]` as an industry standard, and it must be labelled as a platform policy wherever it is surfaced to a client.**

**Jitter is not decoration.** `[CIT-ECON]` already commits the agency publicly to human-paced posting for Web 2.0 as a quality choice. The same property applies here and is cheap: a fixed cron slot produces a machine-regular publication footprint. +/-25% slot jitter and a randomised time-of-day within business hours costs nothing and removes a needless signal.

### 3.5 Topical authority is a domain-level, entity-relational property, and internal linking is the mechanism, not the garnish

**Conclusion: model the map as entities plus typed relations plus a link plan that exists before any draft. The strongest verifiable evidence here is Google's own crawling and linking documentation, not the topical-authority literature, which is almost entirely vendor-authored.**

Google's link documentation (last updated 2025-12-10) is unambiguous on three points that constrain the design directly:

- *"Google can only crawl your link if it's an `<a>` HTML element with an `href` attribute."* Framework-specific attributes such as `routerLink`, and non-anchor elements styled as links, are explicitly listed as things to avoid. [Google link best practices]
- *"Good anchor text is descriptive, reasonably concise, and relevant to the page that it's on and to the page it links to."* *"Click here"*, *"Read more"*, *"website"* and *"article"* are given as poor, overly generic examples. Google's stated test, in full: *"Try reading only the anchor text (out of context) and check if it's specific enough to make sense by itself."* [Google link best practices]
- *"Every page you care about should have a link from at least one other page on your site."* [Google link best practices]

That last sentence is the primary-source justification for making **zero orphan pages** a hard validation on the map, not a nicety. Note the scope Google actually states: *on your site*. The orphan rule is a within-site property, which is what R3A-10c enforces.

The wider topical-authority literature I surveyed in 2026 is uniformly vendor-authored and its quantitative claims (a "64% increase in organic impressions", "73% increase in visibility within 60 days", "40% higher visibility for topic-cluster sites") come without disclosed methodology, sample frames or controls, and I could not trace any of them to a primary study. **All `[UNVERIFIED]`, and none of them should appear in a client-facing document produced by this platform.** What survives is the qualitative and uncontroversial core, which is consistent with Google's own entity-oriented documentation: search systems reason over entities and their relationships rather than over keyword strings in isolation, and a site that covers a bounded domain coherently, with the relationships between its concepts made explicit in structure and links, is legible to those systems in a way that a set of unconnected pages is not.

The design consequence is that we should build the thing that is defensible on Google's own documentation (a crawlable, non-orphaned, descriptively-anchored link graph derived from an explicit entity model, feeding `@id`-linked JSON-LD and breadcrumbs) and **not** promise a percentage uplift to anyone.

The repo already has the raw material and does not persist it. `backend/app/services/content_research.py` produces a `ResearchBrief` that already computes a cluster (pillar plus supporting spokes), an intent classification read off the SERP shape, an entity term set mined from organic results, PAA and related queries, a top-10 teardown distinguishing **table-stakes entities (all competitors cover) from differentiators (only some do)**, and a keyword-to-URL registry acting as a cannibalisation guard. All of that is computed per job and thrown away into `content_jobs.source_pack` jsonb. The map tables in section 5 are largely a matter of persisting, versioning and connecting what this service already derives.

### 3.6 Content decay is real, the published magnitudes are not trustworthy, and the useful trigger set is signal-shaped rather than magnitude-shaped

**Conclusion: monitor with Search Console (free, and its quotas are ample at 100 clients), trigger on signal *shape* rather than on a single traffic number, and treat fact staleness as a trigger with no traffic threshold at all.**

The 2026 content-decay commentary produces figures such as "content decays at an average rate of 1.21% per week", "sites lose 20 to 30% of organic clicks every six months", "updated posts get 106% more traffic", and "27% higher conversion rate than new content on the same topic". Every one of these traces to a marketing-agency blog or a statistics-aggregator page with no disclosed methodology. **All `[UNVERIFIED]`.** They should not be quoted to Daniel or to his clients, and the platform must not surface them as facts.

What is verifiable is the instrumentation. The Search Console API quota page (last updated 2025-08-28) documents:

- **Search Analytics:** 1,200 queries per minute per site, 1,200 QPM per user, 40,000 QPM and 30,000,000 queries per day per project.
- **URL Inspection:** 600 QPM and **2,000 queries per day per site**, 15,000 QPM and 10,000,000 QPD per project.
[Google Search Console API limits]

At 100 clients with 50 published pages each (5,000 URLs), a weekly full sweep is 5,000 URL-inspection calls spread across 100 site-scoped quotas of 2,000 per day each. There is no quota problem. The per-project caps are three to four orders of magnitude above our need.

The signal shapes that matter are the ones that discriminate between different causes, because the cause determines the remedy:

- Clicks falling while impressions hold steady means the page is still being served and is losing the click. That is a title, meta and snippet problem, and the fix is surface-level.
- Average position falling means the page is losing the ranking itself. That is a content and relevance problem, and the fix is substantive.
- Impressions falling with position steady means the query volume moved, not the page. That is often not a defect at all, and firing a refresh on it wastes money.
- A page not indexed at all is a technical problem and must not be routed to the content queue.
- Two of the client's own pages ranking for the same query is cannibalisation, and the remedy is consolidation, which is a human decision with a redirect attached, never an automated rewrite.

**Fact staleness is the trigger with no traffic component, and it is the one the client actually asked for.** `[WA-TEAM]` 05/07 records the practitioner complaint verbatim: *"Updating schema also requires when NAP details changed but we mostly forget about."* A branch phone number change, an hours change, or a manager leaving invalidates every page citing that fact regardless of how well those pages are performing. Because every concrete local claim on a page will be linked to a `client_local_facts` row with an `expires_at` (section 5), this becomes a database query rather than an act of memory.

### 3.7 One schema claim the code already gets right, and one API it must stop calling

**Conclusion: the FAQ finding confirms what the schema module already does and is NOT a correction to it; the Indexing API finding is a genuine, unmitigated defect in shipped code. This section's first draft framed both as corrections to existing assumptions. That was wrong for FAQ and understated for indexing, and both are restated below.**

Google's structured-data documentation states that *"The FAQ rich result feature is no longer shown in Google Search results, as announced in the changelog entry in May 2026."* Its changelog dates the removal precisely: *"This feature will no longer appear in Google Search starting May 7, 2026."* [Google FAQPage documentation] Independently, the current rich-results gallery (last updated 2026-06-15) lists Article, Breadcrumb, Carousel, Course list, Dataset, Discussion forum, Education Q&A, Employer aggregate rating, Event, Image metadata, Job posting, Local business, Math solver, Movie, Organization, Product, Profile page, Q&A, Recipe, Review snippet, Software app, Speakable, Subscription and paywalled content, Vacation rental and Video. **FAQ is absent. HowTo is absent. Breadcrumb and Local business are both present.** [Google search gallery]

**Correction found in verification: the code already does this.** `backend/app/services/content_schema.py:89` declares `_RICH_DEPRECATED: frozenset[str] = frozenset({"FAQPage", "HowTo"})`, and `rich_result_eligible()` in the same file returns `False` for both types unconditionally; the module docstring (`content_schema.py:25-27`) states the nodes are *"kept for SEMANTICS / AI extraction only, never promised as a rich result."* The design this section was drafted to recommend is the design that already ships, so **no change to the emission behaviour is required and none should be scheduled.** The generator does still produce up to six FAQ entries per page (`MAX_FAQ = 6`, `backend/app/services/content_generator.py:77`) and that is correct: the FAQ *content block* is a good format for passage extraction and for question-shaped queries, and its JSON-LD node is already flagged ineligible rather than promised.

   Two small real actions remain. (a) The docstring dates both deprecations to 2023; Google now documents the FAQ removal as taking effect **2026-05-07**, so the comment should be re-dated to match the source an engineer would check. (b) Every client-facing report surface must be confirmed to read `ValidationResult.rich_result_types` / `rich_result_eligible` rather than the raw emitted `@type` list, because the no-false-rich-result-claim guarantee lives in that field and nowhere else.

**LocalBusiness requirements**, which the generator must satisfy exactly: required properties are `address` (a `PostalAddress`) and `name`; recommended are `aggregateRating`, `department`, `geo` (with at least five decimal places of precision), `menu`, `openingHoursSpecification`, `priceRange` (**shorter than** 100 characters; Google's wording is *"must be shorter than 100 characters. If it's 100 characters or longer, Google won't show a price range"*, so the implementable bound is 99, not 100), `review`, `servesCuisine`, `telephone` and `url`. [Google LocalBusiness structured data, last updated 2025-12-10]

**BreadcrumbList requirements:** the only mandatory property is `itemListElement`, an array of **at least two** `ListItem` objects in order, each requiring `position`, `name` and `item` (the URL, optional on the final item). Google uses breadcrumb markup to *"categorize the information from the page in search results."* [Google breadcrumb structured data, last updated 2025-12-10]

**The Indexing API is unusable for this content.** Its quota and restrictions page (last updated 2026-07-16) documents a default of **200 publish requests per day per project** for `URL_UPDATED` and `URL_DELETED`, and restricts the API to *"pages containing `JobPosting` markup or `BroadcastEvent` embedded in `VideoObject` markup."* [Google Indexing API quota] A local service page is neither.

   **Correction found in verification: this is not a requirement to re-scope, it is built code with no restriction check.** The seam already exists and already posts to the real endpoint: `backend/integrations/google_indexing.py` is documented as *"the ONLY door to `urlNotifications:publish`"* and issues `POST https://indexing.googleapis.com/v3/urlNotifications:publish` with `{"url": ..., "type": "URL_UPDATED"}`; `backend/app/modules/indexing/` fans a published URL out to the enabled engines and `db/migrations/0061_indexing.sql` ledgers every attempt. A `grep` for `JobPosting|BroadcastEvent` across `backend/` returns **nothing**, so no code path anywhere checks the documented eligibility restriction before submitting. Two facts contain the exposure today and neither is a control: `google_indexing_enabled` defaults to `False` (`backend/app/config.py:488`), and D-1 defers the Indexing module to v1.1. **The engineering requirement is therefore a guard, not a re-scope:** the Google engine must refuse any URL whose page does not carry `JobPosting` or `BroadcastEvent`-in-`VideoObject` markup, recording a `skipped` row with that reason, before `GOOGLE_INDEXING_ENABLED` is ever turned on. IndexNow and sitemap submission are unaffected and remain the legitimate paths for a local service page, alongside per-URL "Request indexing" in the URL Inspection surface. Requirement **CONT-52 ("automatic indexing submission on publish", CONFIRMED) is satisfiable by those paths**, and the platform must not claim it "submits pages to Google's Indexing API" in any client-facing report.

### 3.8 The QA scorecard is real, is advisory, and currently exists twice in two incompatible forms

**Conclusion: implement D-4's missing half (mandatory acknowledgement plus explanation), delete one of the two divergent dimension lists, and fix the phantom doctrine reference before an engineer touches either file.**

The gate lives in `backend/app/services/content_qa.py`. It declares fourteen dimensions, a weight vector summing to 1.0, `MIN_DIMENSION_SCORE = 70`, `WEIGHTED_TOTAL_THRESHOLD = 85`, `HARD_GATE_FLOOR = 70`, and five critical dimensions (`fact_grounding`, `originality`, `intent_match`, `eeat_experience`, `information_gain`) that are documented as hard-blocking. Every one of these is marked `PROVISIONAL (R4)` in the source itself.

`docs/implementation/KNOWN_LIMITATIONS.md` §3 records that the publish path already treats QA as advisory and that `PublishBlocked` is raised nowhere in the codebase, and that three docstrings falsely claimed publish re-checks a hard gate. It also records the genuine remaining gap in the operator's own framing: *"D-4 asks for 'advisory + mandatory acknowledgement' until calibrated. Only the advisory half exists. The QA verdict goes to the server log, and the lead approving the draft is never shown it or required to acknowledge a sub-threshold score."*

**A defect this track found and must report.** `backend/app/services/content_generator.py:100+` declares a **different** fourteen-dimension tuple from `backend/app/services/content_qa.py:76-92`. The generator's list contains `grounding_factual_accuracy`, `keyword_placement_density`, `extractable_answer_block`, `heading_structure`, `snippet_ai_overview_formatting`; the QA gate's contains `fact_grounding`, `keyword_handling`, `snippet_extractability`, `structure_readability`. Two canonical taxonomies for the same scorecard in the same codebase is a guaranteed future divergence. One must be deleted and imported from the other.

**A second defect, corrected in verification.** `backend/docs/CONTENT-DOCTRINE.md:8,19,82` transfers authority to `backend/seo-content-os/knowledge/` and every constant in both files cites a passage in it. That **path** resolves to nothing: the directory is absent from the working tree and from the whole history (`git log --all -- backend/seo-content-os` is empty). But the knowledge base itself is **present and tracked**, as `SEO-CONTENT-OS.zip` at the repository root, whose `SEO-CONTENT-OS/knowledge/` tree contains exactly the cited files (`foundations/passage-block-protocol.md`, `foundations/meta-and-headings.md`, `doctrine/local-content-laws.md`, `quality-gates/gates.md` and 200-odd more). So the accurate defect is that **every threshold cites a path that does not resolve**, not that its justification is unreadable: an engineer can read it, but only by knowing to unzip a root-level archive that nothing points them to. R3A-37 closes it by repointing the citations or unpacking the archive into the tree.

---

## 4. Options considered and why rejected

| Option | Disqualifying fact |
|---|---|
| **Keyword list as the planning primitive** (extend `content_jobs.topic`, skip the map) | Cannot express a pillar-spoke relationship, cannot detect an orphan page, and cannot plan internal links before drafting. Google's own guidance makes non-orphaned, descriptively-anchored linking a requirement, and a link plan derived after the fact cannot influence what the draft says. Also cannot version, so a strategy change is undiffable. |
| **SimHash / MinHash + LSH for near-duplicate detection** | Solves a scale problem we do not have, and its published operating point is not accurate enough for this decision: the authors report precision and recall **near 0.75** at 64-bit / Hamming k=3, tuned for a millisecond crawl-dedup verdict over 8 billion documents. A quarter-miss rate is not an acceptable doorway gate on a client's live site, and an integer bit-distance cannot drive the graded BLOCK / HOLD / pass band or the reviewer diff that section 5.3 requires. Exact pairwise Jaccard is affordable to roughly 5,000 pages per client. Keep SimHash as a documented prefilter for beyond that. |
| **Off-the-shelf plagiarism API (Copyscape and similar) as the duplication defence** | Detects copying from the external web. Our dominant risk is internal near-duplication within one client's own corpus, which an external-web checker does not see at all. Also an unbounded per-check cost at bulk volume. Worth adding later as a *supplementary* external-web check for CONT-33; not a substitute for the internal gate. |
| **Free-text onboarding notes as the local-fact source** | Cannot be queried for sufficiency, cannot carry an expiry, cannot be linked to an `evidence_id`, and cannot make the fact gate a computable predicate. A fact gate over free text degrades to a keyword search over a notes field. |
| **Let the model generate a plausible local detail when a fact is missing, flagged for review** | This is the exact failure mode the project exists to eliminate. A plausible invented manager's name in a published page is a client-damage event and a legal exposure (CONT-34), and "flagged for review" fails the moment a reviewer is tired. The refusal must be structural. |
| **Hard QA gate at weighted total >= 85** | Directly contradicts decision D-4, and the thresholds are self-declared `PROVISIONAL` and uncalibrated against any human grade. A hard gate on an uncalibrated score either blocks good work or passes bad work and nobody knows which (specification §28.3). Revisit only after 30 human-graded drafts. |
| **Publish everything on approval (no pacing)** | Converts a design error into a several-month recovery across the whole page set, given Google's own stated core-update recovery timeline. Also makes per-page attribution impossible and puts 600 approvals per week in front of two reviewers with no queue discipline. |
| **A fixed 5 or 10 pages per week for every client** | Wrong at both ends of the site-size distribution, and has no primary source. A corpus-relative cap with a floor and ceiling is defensible on its own stated rationale, provided the ceiling is one the scheduler can actually reach (R3A-27). |
| **Google Indexing API for publish notification** | Restricted by Google to `JobPosting` and `BroadcastEvent`-in-`VideoObject` content, 200 publish requests per day per project. Using it for local service pages is outside its documented scope. Note this is a rejection of *current shipped behaviour*, not of a proposal: the seam is built (`backend/integrations/google_indexing.py`) and carries no eligibility check. |
| **Emitting FAQPage JSON-LD for rich results** | The FAQ rich result is no longer shown in Google Search and FAQ is absent from the current rich-results gallery. Emitting it and reporting it as a win is a false claim to a client. |
| **CAPTCHA or detector evasion as part of the quality strategy** | Out of scope by project constraint, and the existing doctrine already records "no AI-detector evasion" as Law 8. The AI-tell guard exists to make copy read like a person wrote it, not to defeat a classifier. |

---

## 5. Engineering requirements this imposes

Numbered, buildable, with table and column names. `R3A-n` identifiers are stable references for the traceability matrix.

### 5.1 The topical map and entity model

**R3A-1. Create `topical_maps`.** Columns: `id uuid pk`, `client_id uuid not null references clients(id) on delete cascade`, `version int not null`, `boundary jsonb not null`, `status text not null default 'draft'` in (`draft`,`approved`,`superseded`), `approved_by uuid references users(id)`, `approved_at timestamptz`, `created_by uuid`, `created_at`, `updated_at`. Unique on `(client_id, version)`. RLS: mirror `content_jobs` (`is_staff()` select; owner/admin/manager insert and update).

**R3A-2. The semantic boundary is a closed triple and is stored in `topical_maps.boundary` as** `{"services": [...], "locations": [{"name","postcode","lat","lng","buyer_quality"}], "audience": ["residential"|"commercial"|"trade"]}`. Services seed from `client_business_profiles.primary_category` and `extra_categories` (`db/migrations/0051_client_business_profile.sql:46-47`) plus the audit crawl of existing service pages plus operator entry. **A cluster whose primary keyword does not map to a member of `services` x `locations` x `audience` cannot be inserted into `topic_clusters` for that map.** Enforce with a check at the service layer and a foreign-key-shaped validation in the map-approval endpoint. This closure is what makes the map bounded rather than a keyword list.

**R3A-3. Location selection weighs buyer quality, not population (CONT-13).** `boundary.locations[].buyer_quality` is a 0-100 operator-settable score with a default derived from the client's own historical job or lead data where available, and it is an explicit input to `topic_clusters.priority`. A location with `buyer_quality` below an operator-set floor is excluded from page-set proposal even if search volume is high.

**R3A-4. Create `topic_clusters`.** Columns: `id uuid pk`, `map_id uuid not null references topical_maps(id) on delete cascade`, `kind text not null` in (`pillar`,`spoke`), `parent_cluster_id uuid references topic_clusters(id)`, `label text not null`, `intent text not null` in (`informational`,`commercial`,`transactional`,`navigational`), `primary_keyword text not null`, `keyword_set jsonb not null default '[]'`, `serp_format text`, `difficulty numeric`, `volume int`, `winnability numeric`, `buyer_quality numeric`, `priority int`, `status text`. A `spoke` must have a non-null `parent_cluster_id`; enforce with a check constraint. Populate from the existing `ResearchBrief` (`backend/app/services/content_research.py`), which already derives cluster, intent, format and winnability.

**R3A-5. Create `map_entities`.** Columns: `id uuid pk`, `map_id uuid not null`, `entity_type text not null` in (`Service`,`Place`,`Organization`,`Person`,`Product`,`Material`,`Problem`,`Certification`), `name text not null`, `canonical_name text`, `external_id text` (Wikidata QID, GBP place id, or a schema.org `@id`), `attributes jsonb not null default '{}'`, `evidence_id uuid references evidence(id)`. Unique on `(map_id, entity_type, canonical_name)`.

**R3A-6. Create `entity_relations` (the semantic layer).** Columns: `id uuid pk`, `map_id uuid not null`, `subject_entity_id uuid not null references map_entities(id)`, `predicate text not null` in (`serves`,`located_in`,`part_of`,`requires`,`treats`,`certified_by`,`employs`,`supplies`,`adjacent_to`), `object_entity_id uuid not null references map_entities(id)`, `evidence_id uuid not null references evidence(id)`. **Every relation carries an `evidence_id`; a relation with no evidence cannot be inserted.** This graph is the source for (a) internal-link candidate generation, (b) the JSON-LD `@id` graph, and (c) breadcrumb hierarchy.

**R3A-7. Create `cluster_entities`.** Columns: `cluster_id`, `entity_id`, `role text not null` in (`table_stakes`,`differentiator`). Populate from the top-10 teardown, which already computes this distinction. `table_stakes` entities are a coverage **floor** the draft must clear; `differentiator` entities are the information-gain angle.

**R3A-8. Create `page_plans`.** Columns: `id uuid pk`, `map_id uuid not null`, `cluster_id uuid not null`, `page_type` (this needs new enum values: `content_page_type` is today exactly `('service', 'blog', 'local')` at `db/migrations/0017_content.sql:31`, and the fact matrix in R3A-15 assumes `location` and `service_location`. **The first draft cross-referenced R3A-32 here, which is the circuit breaker and specifies no such thing; no requirement in this document specified the enum extension.** The extension is: add `location` and `service_location`, keep `local` as a deprecated alias until existing rows are migrated, and update R3A-15's seeds to the new names.), `url_slug text not null`, `title text`, `location_id uuid`, `content_job_id uuid references content_jobs(id)`, `status text not null` in (`proposed`,`selected`,`briefed`,`held_facts`,`drafted`,`approved`,`scheduled`,`published`,`rejected`,`superseded`), `planned_publish_at timestamptz`, `sequence_index int`, `created_at`, `updated_at`. Unique on `(map_id, url_slug)`.

**R3A-9. Create `internal_link_plan` and populate it BEFORE drafting.** Columns: `id uuid pk`, `map_id uuid not null`, `from_page_plan_id uuid not null references page_plans(id)`, `to_page_plan_id uuid not null references page_plans(id)`, `anchor_text text not null`, `link_type text not null` in (`pillar_to_spoke`,`spoke_to_pillar`,`sibling`,`service_to_location`,`location_to_service`,`supporting`), `rationale text not null`, `evidence_id uuid`, `status text not null default 'planned'` in (`planned`,`placed`,`verified`,`broken`), `placed_at timestamptz`, `verified_at timestamptz`. Check constraint `from_page_plan_id <> to_page_plan_id`. **This table is the internal-linking first-class output: rows exist at stage 4 (map approval), the drafter receives its page's outbound rows as required links, and stage 13 verifies each one resolves on the live page.**

**R3A-10. Link-plan validation rules, enforced at map approval and blocking approval on failure:**
   a. Every spoke has exactly one `spoke_to_pillar` row to its parent, and the drafter must place it within the first 40% of body word count.
   b. Every pillar has a `pillar_to_spoke` row to every spoke in its cluster.
   c. Every `page_plans` row has **at least one inbound** `internal_link_plan` row. Zero orphans. Justified by Google's own guidance that every page you care about should have a link from at least one other page.
   d. Each page carries 3 to 6 contextual internal links (the existing `MAX_INTERNAL_SPOKES = 6` in `backend/app/services/content_generator.py:79` becomes the ceiling; 3 becomes the floor), of which at least 2 are `sibling` or cross-cluster.
   e. Anchor text is descriptive; reject any anchor matching a stop-list (`click here`, `read more`, `here`, `this page`, `learn more`, `website`, `article`). Google's own test: read the anchor out of context and check it is specific enough.
   f. No single anchor string accounts for more than 30% of inbound links to one target. `[UNVERIFIED]` as an external standard; a platform policy against exact-match anchor uniformity.
   g. Every link is rendered as `<a href="...">`. Reject any generated link markup that is not an anchor element with an href, because Google can only crawl that form.

**R3A-11. Cannibalisation guard at map level (CONT-10).** Before a `page_plans` row moves to `selected`, check its `primary_keyword` against (a) every other selected plan on the map and (b) the keyword-to-URL registry the research service already builds from the client's crawled existing pages. A collision blocks selection and surfaces the colliding URL. One primary intent per URL.

### 5.2 The local-differentiator substrate

**R3A-12. Give the content pipeline a per-branch location record. This is a RECONCILIATION, not a greenfield table** (see decision D-9, which this requirement forces; and see the correction in section 3.2). There is no `client_locations` anywhere in `db/` or `backend/` today, but there **are** already two business-identity tables: `client_business_profiles` (one row per client, `unique (client_id)`) and `business_profiles` (the citation engine's per-branch NAP, with `label` and `is_primary` and no per-client uniqueness). **An engineer must not create a third without an explicit decision.** The two admissible designs, and the fact that decides between them:

   - **(a) Reuse `business_profiles` as the branch record.** It already carries label, is_primary, NAP, hours, categories, `service_area`, `nap_locked`. Missing for content: `lat`/`lng` and a GBP place id (`place_id` exists on the local-SEO table at `db/migrations/0039_local_seo.sql:55`, not here). Cost: two additive nullable columns. Risk: the citation engine's write path and the content engine's read path now share a table whose `nap_locked` semantics were designed for submissions.
   - **(b) Create `client_locations`** with `id uuid pk`, `client_id uuid not null references clients(id) on delete cascade`, `label text not null`, `address_line1`, `address_line2`, `city`, `region`, `postal_code`, `country`, `lat numeric`, `lng numeric`, `phone text`, `hours jsonb`, `gbp_place_id text`, `is_primary boolean not null default false`, `created_at`, `updated_at`, with a partial unique index enforcing one `is_primary` per client, and **derive** `business_profiles` rows from it the way `client_business_profiles` already derives the first one. Cost: a third table and a sync path. Benefit: the citation engine's submission record stays a submission record.

   This track's recommendation is **(a)** unless the owner wants the citation and content engines decoupled, because (b) adds a third source of truth for one client's address and this document's whole thesis is that duplicated sources of truth drift. Whichever is chosen, `client_local_facts.location_id` (R3A-13) points at it, and the choice must be recorded as a decision before R3A-13 is built. **This is open item O-7.**

**R3A-13. Create `client_local_facts` (the substrate).** Columns:
```
id            uuid pk
client_id     uuid not null references clients(id) on delete cascade
location_id   uuid references client_locations(id) on delete cascade  -- null = client-wide
fact_kind     text not null      -- see R3A-14
fact_key      text not null      -- e.g. 'branch_manager', 'response_time_minutes'
fact_value    jsonb not null
rendered_text text not null      -- the human-readable form the drafter may use verbatim
source        text not null      -- 'onboarding_form'|'operator_entry'|'client_upload'
                                 -- |'gbp_api'|'audit_crawl'|'interview_transcript'
source_ref    text               -- questionnaire response id, file path, place id, URL
evidence_id   uuid not null references evidence(id)
confidence    text not null      -- 'stated'|'documented'|'verified'
verified_by   uuid references users(id)
verified_at   timestamptz
expires_at    timestamptz        -- NOT NULL for kinds staffing/contact/pricing/premises
created_at, updated_at
```
Index on `(client_id, location_id, fact_kind)` and on `expires_at where expires_at is not null`. RLS mirrors `client_business_profiles`. **`evidence_id` is NOT NULL: a fact with no provenance cannot exist.**

**R3A-14. The `fact_kind` taxonomy (ten kinds).** `staffing` (named manager or lead technician, role, years in post), `contact` (branch phone, branch email), `premises` (address, parking, access, hours variance), `coverage` (named suburbs and postcodes served from this branch, response time), `local_partner` (named supplier, referral partner or trade body), `service_nuance` (what is done differently here: equipment stationed on site, local regulation, housing stock, climate, water hardness, soil type, permitting authority), `proof` (a named local job or testimonial with a date and a street-level, not door-number, location), `media` (a photograph taken at or near this location, with capture date and geo where available), `credential` (local licence or permit number, council registration, local trade-body membership), `pricing` (any price or guarantee stated for this location).

**R3A-15. Create `content_fact_requirements` (the sufficiency matrix).** Columns: `page_type text`, `fact_kind text`, `min_count int not null`, `severity text not null` in (`block`,`warn`). Seed for the `location` and `service_location` page types (which do not exist yet; see the enum extension in R3A-8): `staffing >= 1 block`, `coverage >= 1 block`, `service_nuance >= 1 block`, `proof >= 1 block`, `media >= 1 block`, `local_partner >= 1 warn`, `credential >= 1 warn`. Seed for `service` (non-local): `proof >= 1 block`, `credential >= 1 warn`. Seed for `blog`: none blocking. **This table is operator-editable, so the agency can raise its own bar without a deploy, but it cannot be edited to zero for a `location` page without an owner-role action that is logged.**

**R3A-16. Collect the facts at onboarding, and make the questionnaire load-bearing.** Extend `LOCAL_SEO_TEMPLATE` in `backend/app/modules/client_onboarding/constants.py` with two new steps between `brand_assets` (6) and `competitor_list` (7):
   - `location_facts` ("Capture per-location operating facts", owner `manager`) which renders a structured form per `client_locations` row, one section per `fact_kind`, writing `client_local_facts` rows with `source='onboarding_form'` and an `evidence` row of kind `client_fact` per submission.
   - `local_proof` ("Collect local proof and photography", owner `manager`) which accepts photo uploads with a capture-date field, and named job or testimonial entries.
   Both steps must be completable by the **client** through a shareable form link, not only by staff, because the facts live in the client's head and a staff member typing them is the invention risk moved one seat over. The onboarding step is not "complete" until the `content_fact_requirements` block-severity minimums are met for at least the primary location.

**R3A-17. Build the fact gate as pipeline stage 6b, between brief and draft.** A new pure service `backend/app/services/content_fact_gate.py` with the signature `evaluate(page_plan, requirements, facts) -> FactGateVerdict` returning `{satisfied: bool, missing: [{fact_kind, required, have, severity}], required_facts: [{evidence_id, fact_kind, rendered_text}]}`. Deterministic, no I/O, unit-testable with no network, mirroring the purity convention already used by `content_qa.py` and `content_guard.py`.

**R3A-18. The refusal behaviour, stated exactly.** When `FactGateVerdict.satisfied` is false on any `block`-severity requirement:
   - The `content_jobs` row **does not enter `drafting`**. Add a new value `blocked_facts` to the `content_status` enum and permit the worker transition `queued -> blocked_facts` and the lead transition `blocked_facts -> queued` in `content_jobs_guard_update()` (`db/migrations/0017_content.sql`). Add `held_facts` to `page_plans.status`.
   - The system emits a **`fact_request` artefact**: a per-location checklist naming exactly which `fact_kind` rows are missing, with a one-line example of an acceptable answer for each, addressed to the operator and shareable to the client as a form.
   - **Zero cost is spent.** The gate runs before any drafting call, so a fact-blocked page consumes no tokens. This is a deliberate design property: the expensive stage is downstream of the cheap refusal.
   - There is **no fallback path that drafts anyway**. Not with a placeholder, not with a generic sentence, not flagged for review. Any code path that reaches the drafting call with an unsatisfied block-severity requirement is a defect and must be covered by a test that asserts the drafter is never called.

**R3A-19. Force the generator to use the facts.** The `content_brief` carries `required_facts[]` from R3A-17. Three enforcement points:
   a. **Input restriction.** The drafting call receives `required_facts[].rendered_text` as the **only permitted source of concrete local claims**, alongside the research evidence pool. No web access during drafting.
   b. **Utilisation check.** After drafting, assert that each `required_facts` entry's distinguishing token (a name, a number, a place) appears in the draft. Unused required facts return the draft to `drafting` with the specific unused facts named, maximum 2 retries, then hold at `needs_review` flagged `facts_unused`.
   c. **`[NEEDS:]` marker.** The existing convention (a literal `[NEEDS: ...]` placeholder rather than a hallucination) is retained for `warn`-severity kinds and any optional fact. A surviving `[NEEDS:]` at publish time **hard-blocks publication** regardless of QA advisory status; this is a grounding failure, not a quality score. `content_qa.py`'s `_GROUNDING_NEEDS_SCORE = 15` is promoted from a score penalty to a publish-path assertion.

**R3A-20. Fact expiry drives the maintenance queue.** A nightly Celery beat task selects `client_local_facts where expires_at < now() + interval '14 days'`, and for each expiring fact enumerates the published pages citing it (via `page_evidence_links`, R3A-47) and raises a `T3 STALE_FACT` maintenance item (the `maintenance_items` table is **R3A-49** and the trigger is **R3A-50**; the first draft cited R3A-42, which is the text-surface constraints and is unrelated). Default expiries: `staffing` 365 days, `contact` 365 days, `pricing` 180 days, `premises` 365 days; `coverage`, `service_nuance`, `proof`, `media`, `local_partner`, `credential` have no default expiry but accept one.

### 5.3 Near-duplicate defence

**R3A-21. Create `content_page_fingerprints`.** Columns: `id uuid pk`, `client_id uuid not null`, `page_plan_id uuid`, `content_job_id uuid`, `source text not null` in (`generated`,`published`,`crawled_existing`), `url text`, `raw_shingles jsonb not null`, `masked_shingles jsonb not null`, `raw_simhash bigint`, `masked_simhash bigint`, `heading_sequence text[] not null`, `word_count int not null`, `computed_at timestamptz not null`. Index on `(client_id, source)`. Store shingles as sorted arrays of 64-bit hashes, not raw strings, to bound row size.

**R3A-22. The normalisation pipeline, in order, as a pure function.**
   1. Extract main content: drop nav, header, footer, sidebar, cookie banner, JSON-LD blocks, and the CTA block. Boilerplate inflates similarity between any two pages on the same site and is the single largest source of false positives in web near-duplicate detection.
   2. Lowercase; strip punctuation; collapse whitespace; strip markdown syntax; drop stopwords **no** (stopwords carry phrasing structure and their removal makes templated text look more distinct than it is).
   3. Produce two token streams: `raw` (as above) and `masked`, in which every token matching a location name, suburb, postcode or region from `topical_maps.boundary.locations`, every token matching the client's business name or a variant, and every phone number pattern is replaced by `<LOC>`, `<BIZ>`, `<TEL>` respectively.
   4. Shingle each stream at **k = 5** consecutive words. The Stanford IR textbook notes k=4 as typical for web near-duplicate detection; we use 5 because our documents run 600 to 3,500 words (`WORD_COUNT_FLOOR`/`CEILING`, `backend/app/services/content_generator.py:70-71`) and 4-grams over-match on the stock phrasing common to local-SEO copy. **This is a tuning choice, and it must be revisited against the labelled corpus in O-2.**
   5. Hash each shingle to 64 bits; store the sorted set.

**R3A-23. Similarity is Jaccard: `|A ∩ B| / |A ∪ B|`, computed exactly.** No MinHash sketching below 5,000 pages per client. Above that, add a `masked_simhash` prefilter at 64 bits to shortlist candidates before exact Jaccard. **The prefilter's Hamming bound is a platform policy choice with no external basis: `[UNVERIFIED]`, and 8 is a placeholder, not a derived number.** Set it empirically as the loosest bound that loses no pair the exact Jaccard would have blocked on the O-2 labelled corpus; a prefilter that drops a true positive is worse than no prefilter. Document that the Google-published k=3 is deliberately not used, on the grounds given in section 3.3 (precision and recall near 0.75, and a bit-distance verdict cannot drive a graded review band).

**R3A-24. The comparison corpus, all three parts, mandatory.**
   a. Every other page **in the same run** (within-run check).
   b. Every page **ever published** for that client (`content_page_fingerprints where source='published'`).
   c. Every **pre-existing page** on the client's own site, fingerprinted from the audit-engine crawl at connection time (`source='crawled_existing'`). Without (c), the first bulk run can near-duplicate the client's own hand-written pages and nothing notices.

**R3A-25. The bands, with the numbers.**

| Condition | Verdict | Rationale |
|---|---|---|
| `raw_jaccard >= 0.90` | **BLOCK** | Near-identical documents. This is the Stanford IR textbook's **worked example** of a near-duplicate threshold (*"say, 0.9"*), not a calibrated standard it prescribes. It is the only number in this table with any external provenance at all, and even it is illustrative. Calibrate in O-2 like the rest. |
| `masked_jaccard >= 0.80` | **BLOCK** | The city-swap template. This is "95% identical across cities" made computable. Policy choice. `[UNVERIFIED]` externally. |
| `0.60 <= masked_jaccard < 0.80` | **HOLD** for review, side-by-side diff, explicit acknowledgement required | The grey band where a human judgement is genuinely needed. Policy choice. |
| identical `heading_sequence` **and** `masked_jaccard >= 0.50` | **BLOCK** | Structural template plus moderate lexical sameness is the doorway pattern even below the lexical band. Policy choice. |
| run-level `mean_pairwise_masked_jaccard >= 0.45` | **HOLD THE WHOLE RUN** | Catches the case where no single pair trips but the set is collectively a template. Policy choice. |
| otherwise | pass | |

**Every one of the policy-choice thresholds must be logged with its computed score on every run from day one, in shadow mode, before any of them is allowed to block.** Enforcement turns on only after the calibration in open item O-2.

**R3A-26. Where the gate sits.** Run it as pipeline stage 10 alongside QA, and **re-run it at publish** against the published corpus as it stands at that moment, because a paced plan means pages publish days apart and the corpus at approval time is not the corpus at publish time. Store the verdict as a `duplicate_report` stage artefact with the top three most-similar pages, their scores and a rendered diff.

### 5.4 The paced publication scheduler

**R3A-27. Create `publication_plans`.** Columns: `id uuid pk`, `client_id uuid not null`, `map_id uuid`, `status text not null` in (`draft`,`active`,`paused`,`complete`), `weekly_cap int not null`, `daily_cap int not null default 1`, `min_gap_hours int not null default 18`, `jitter_pct numeric not null default 0.25`, `window_start time not null default '09:00'`, `window_end time not null default '17:00'`, `timezone text not null`, `created_by`, `approved_by`, `created_at`, `updated_at`.

   **Correction found in verification: the first draft's defaults were mutually unsatisfiable and a developer would have hit it on day one.** With `window_start = 09:00` and `window_end = 17:00`, two slots on the same calendar day can be at most **8 hours** apart, so `min_gap_hours = 18` makes `daily_cap = 2` unreachable and silently dead. The same constraint caps any plan at 7 pages per week, so the `weekly_cap` ceiling of **15** in R3A-29 is also unreachable. Three of the four parameters are pinned by intent (the 18-hour gap is what makes publication look human-paced, the business-hours window is what makes it look staffed, and the weekly cap is the blast-radius control), so the honest resolution is:
   - `daily_cap` default becomes **1**. It stays a column so an operator can raise it, and raising it above 1 requires lowering `min_gap_hours` below the window width in the same edit.
   - Add a **check constraint** the scheduler cannot violate: `daily_cap = 1 or min_gap_hours <= extract(epoch from (window_end - window_start)) / 3600`. A plan that cannot be satisfied must fail at write time, not produce a schedule that quietly ignores one of its own limits.
   - `weekly_cap` is additionally clamped to `7 * daily_cap` at plan generation, and the clamp is shown to the operator when it binds. See the revised ceiling in R3A-29.

**R3A-28. Create `publication_slots`.** Columns: `id uuid pk`, `plan_id uuid not null`, `page_plan_id uuid not null`, `content_job_id uuid`, `scheduled_for timestamptz not null`, `sequence_index int not null`, `status text not null` in (`pending`,`publishing`,`published`,`missed`,`skipped`,`blocked`), `attempts int not null default 0`, `published_at timestamptz`, `last_error text`. Index on `(status, scheduled_for)`.

**R3A-29. The rate, and how a bulk approval becomes a plan.**
   - `weekly_cap = min(7 * daily_cap, clamp(3, 15, ceil(0.05 * indexed_pages)))` where `indexed_pages` is the client's indexed page count from the audit crawl or Search Console, defaulting to **6** when unknown. **At the default `daily_cap = 1` the effective ceiling is 7, not 15** (see the correction in R3A-27); the 15 only becomes reachable if an operator deliberately raises `daily_cap` and shortens `min_gap_hours` to match. Surface the binding constraint in the UI whenever the `7 * daily_cap` term is the one that wins, so nobody sets a pace the scheduler cannot deliver.
   - On bulk approval of N pages, generate N `publication_slots` by walking forward from `now()`: fill at most `weekly_cap` per rolling 7-day window and at most `daily_cap` per calendar day, never closer than `min_gap_hours`, each slot placed at a uniformly random time inside `[window_start, window_end]` on its day and then perturbed by `+/- jitter_pct` of the gap.
   - The slot order follows `page_plans.sequence_index`, which the operator sets at page-set selection and which defaults to **pillars first, then spokes by descending `priority`** (a spoke published before its pillar links to a page that does not exist).
   - **Global review-capacity throttle.** A platform-wide setting `content.daily_review_capacity` (default 40) caps the total number of slots scheduled across **all** clients on any calendar day. When a new plan's preferred day is full, its slots shift forward. Without this, 100 clients at 6 per week puts 600 approvals a week in front of the review queue and the pacer becomes fiction.

**R3A-30. What the operator sees and can change.** A calendar view of `publication_slots` for a client, with: drag-to-reschedule a single slot (revalidating `daily_cap` and `min_gap_hours`), a pace slider that regenerates the remaining slots at a new `weekly_cap`, pause and resume for the whole plan, skip for one page, and a "publish now" override that is logged with the actor and a reason. The view must show the global capacity contention on any day where it applied.

**R3A-31. Missed windows.** A Celery beat sweep (restore the currently-disabled beat schedule referenced in `db/migrations/0072_content_schedule.sql`) claims `publication_slots where status='pending' and scheduled_for < now()`.
   - Within a **6-hour** grace period, publish immediately.
   - Beyond it, mark `missed`, do **not** silently batch it with the next slot (that recreates the burst the pacing exists to prevent), and re-slot it at the **next free** slot on the plan, pushing everything after it back by one position.
   - Three consecutive `missed` slots pause the plan and notify the lead. A pacer that quietly falls behind for a month is worse than one that stops.
   - The publish itself must be **idempotent on `content_jobs.id`** (CONT-51); a lost response must never create a second page. The slot claim is a conditional update `where status='pending'`, so two workers cannot claim the same slot.

**R3A-32. Post-publish circuit breaker.** If stage 13 verification fails for any page (R3A-34, stage 13), **all pending slots for that client are held** until the defect is resolved. One broken publish usually means a connection, template or capability problem that would break every subsequent page.

### 5.5 The stage-gate pipeline

**R3A-33. Create `stage_artifacts`, the spine of the whole gate model.** Columns: `id uuid pk`, `client_id uuid not null`, `map_id uuid`, `page_plan_id uuid`, `content_job_id uuid`, `stage text not null`, `artifact jsonb not null`, `rationale text not null`, `evidence_ids uuid[] not null default '{}'`, `produced_at timestamptz not null`, `decision text` in (`pending`,`approved`,`edited`,`rejected`,`acknowledged`), `decided_by uuid`, `decided_at timestamptz`, `decision_note text`, `superseded_by uuid references stage_artifacts(id)`. **`rationale` is NOT NULL on every artefact**, implementing CONT-44: a number without a reason cannot be acted on.

**R3A-34. The thirteen stages, each with its artefact, its decision, and its rejection semantics.**

| # | Stage | Artefact the operator sees | Decision | Rejection does |
|---|---|---|---|---|
| 1 | Content audit | `content_inventory`: existing pages, their apparent target queries, cannibalisation pairs, decay candidates, orphan pages | Confirm the inventory; mark pages out of scope | Re-crawl. Nothing downstream exists yet. |
| 2 | Keyword & entity research | `research_brief`: intent per cluster, primary and secondary terms, entity set, AI-Overview fan-out questions, winnability with the DA confidence flag | Approve the keyword universe and entity list | Re-run with operator-edited seeds. Invalidates stages 3 to 13 for this map. |
| 3 | Competitor analysis | `competitor_teardown`: named competitors, their service and location page inventory, section architecture, table-stakes vs differentiator entities, word-count target, schema types | Confirm the competitor set | Replace competitors and re-run. Invalidates the entity roles in `cluster_entities` and everything after. |
| 4 | Topical map & strategy | `topical_map` v_n: boundary, cluster tree, entity graph, **and the full internal-link plan** | Approve or edit the boundary and cluster tree | Creates map version n+1. All `page_plans` on version n go to `superseded`. Published pages are untouched; their plans re-point on the next map approval. |
| 5 | Page-set selection | `page_set`: checkbox list with volume, difficulty, winnability, buyer quality, **fact-readiness**, and a total cost estimate | Select the pages to build; **explicitly confirm the cost estimate** (CONT-57) | Nothing is briefed. Zero spend. |
| 6 | Brief | per-page `content_brief`: target keywords, intent, required entities, **required facts with evidence ids**, internal-link targets from the plan, schema type, word band, CTA, framework | Approve or edit the brief | Page returns to `selected`. |
| 6b | **Fact gate** (automatic) | `fact_request` **only when it fires**: exactly which fact kinds are missing, per location, with an example answer for each | Supply facts, or drop the page | Page holds at `held_facts` / `blocked_facts`. **Zero spend.** No drafting path exists. |
| 7 | Draft | `draft` (markdown plus rendered preview) with the AI-guard report (dash counts, AI-tell findings, sections rewritten) | Approve, edit, or reject | Page returns to stage 6. The draft is retained as a `content_versions` row, never discarded. |
| 8 | Design | `design_candidates`: two or more layouts rendered in the site's own style kit (WP-9) | Pick a layout | Regenerate layouts. Draft text is untouched. |
| 9 | SEO surface | `seo_surface`: title, meta, slug, canonical, JSON-LD, breadcrumbs, image alt and title, OG tags, with each length-checked and uniqueness-checked | Approve | Returns to stage 7 with the specific failing field named. |
| 10 | QA | `qa_scorecard` (14 dimensions, each with score, justification, `evidence_ref`, and a "what would fix it" line, badged PROVISIONAL until calibrated) **plus** `duplicate_report` | **Acknowledge (mandatory)**. Advisory per D-4: the score never blocks | Cannot be rejected here; it is an acknowledgement gate. A `BLOCK` verdict from the duplicate gate is separate and does block. |
| 11 | Human review | the full page preview, the scorecard, the duplicate report, the fact list with sources | Approve / edit-and-approve / reject. **The approver may not be the drafter** (CONT-45) | Reject sends the page to stage 7 with a required reason. |
| 12 | Publication plan | `publication_plan` calendar with the paced slots and any global-capacity contention | Accept or adjust the pace | Pages sit `approved` and unscheduled. Nothing publishes. |
| 13 | Post-publish | `publish_verification`: live URL fetched, renders, schema validates, images load with alt and title, every planned internal link resolves, page opens editable in the builder | Accept, or raise a defect | Defect trips the circuit breaker (R3A-32); all pending slots for the client hold. |

**R3A-35. The universal rejection rule, stated once so it does not have to be re-derived per stage:** *rejection at stage N invalidates the artefacts of stages greater than N, and only those.* Implement as a single service function `invalidate_downstream(scope, from_stage)` that sets `superseded_by` on the affected `stage_artifacts` rows and resets the owning `page_plans.status` / `content_jobs.status` to the state that stage N produces.

**R3A-36. Implement D-4's missing half.** Add to `content_jobs`: `qa_acknowledged_by uuid references users(id)`, `qa_acknowledged_at timestamptz`, `qa_override_reason text`. The publish endpoint asserts `qa_acknowledged_at is not null`; where `qa_score->>'weighted_total' < 85` or any `HARD_GATE_DIMENSIONS` member scored below 70, it additionally requires `qa_override_reason` of at least 20 characters. Extend `content_jobs_guard_update()` so the `needs_review -> publishing` lead transition raises when `qa_acknowledged_at is null`. **The trigger blocks on missing acknowledgement, never on the score**, which is exactly what D-4 decided and what `docs/implementation/KNOWN_LIMITATIONS.md` §3 records as still missing.

**R3A-37. Fix the two provenance defects before touching either file.** (a) Delete the duplicate `QA_DIMENSIONS` tuple in `backend/app/services/content_generator.py` and import the canonical one from `backend/app/services/content_qa.py`; add a test asserting the two modules agree. (b) Either restore `backend/seo-content-os/knowledge/` to the repository or rewrite every "knowledge source" citation in `backend/docs/CONTENT-DOCTRINE.md`, `content_generator.py` and `content_qa.py` to point at a file that exists. **No engineer should be asked to change a constant whose stated justification cannot be read.**

### 5.6 Generator constraints

**R3A-38. Copy frameworks.** The `content_framework` enum already carries AIDA, PAS, BAB, FAB, 4 Ps, PASTOR and 4 U's (`db/migrations/0017_content.sql`). Selection must be deterministic and auto-resolvable (CONT-20), recorded in the existing `framework` and `auto` columns: transactional service or location page -> PAS (problem-agitate-solution) or AIDA by pain level; commercial-investigation or comparison page -> BAB (before-after-bridge); informational page -> no persuasion framework, inverted-pyramid structure with the answer block first. The operator may override; the override is stored with `auto = false`.

**R3A-39. Zero em dashes, everywhere, not just in drafts.** The deterministic guard already exists and already gives a hard guarantee: `backend/app/services/content_guard.py:52-60` defines the forbidden dash family (U+2012, U+2013, U+2014, U+2015) and `strip_dashes` runs unconditionally on every block after any rewrite, so a `deai_draft` result is dash-free even when the rewriter is unavailable. **Requirement: apply the same guard at every text egress**, because CONT-21 is stated as "output, site, emails or AI responses". Named egress points: `backend/app/services/email_templates.py`, the audit narrative writer, the policy-brief writer, and every portal AI response. Add a single `assert_dash_free()` used in tests across all of them.

**R3A-40. Images.** Alt **and** title on every image (CONT-29). Assert both non-empty; assert `title != alt` (a duplicated title adds nothing); alt at most 125 characters `[UNVERIFIED as an external standard, a platform policy]`; the primary keyword may appear in the alt text of at most one image per page (anti-stuffing). Responsive breakpoints in the generated markup (CONT-30). No raw CSS in post content (CONT-31, already fixed at commit `faeec43`). Every `media`-kind local fact with a photograph must be preferred over a generated image for a location page, because a real photograph of the place is the E-E-A-T Experience signal and a generated one is not.

**R3A-41. JSON-LD and breadcrumbs.**
   - Emit `LocalBusiness` with `name` and `address` (required) plus `geo` at five or more decimal places, `openingHoursSpecification`, `telephone`, `url`, `priceRange` and `areaServed` where the facts exist. Never emit a recommended property whose value is not backed by a `client_local_facts` or `client_locations` row.
   - Emit `BreadcrumbList` with at least two `ListItem` entries, each with `position`, `name` and `item`, derived from the map hierarchy Home > Service pillar > Service in City. Render the breadcrumb **in HTML as well**, and assert the two agree.
   - Emit `Service` and `Person` nodes linked by `@id` from `map_entities` / `entity_relations`, so the JSON-LD graph is the entity graph rather than an independently invented one.
   - **FAQPage: no change needed, verify only.** `content_schema.py` already emits `FAQPage`/`HowTo` for semantics while `rich_result_eligible()` returns `False` for both (section 3.7), which is the correct behaviour. Do **not** remove the markup. The only work is (a) re-dating the docstring's "2023" FAQ deprecation to the 2026-05-07 removal Google now documents, and (b) asserting in a test that every client-facing report reads `rich_result_eligible` rather than the raw `@type` list.
   - Validate all JSON-LD before the stage 9 gate; a validation failure blocks the SEO-surface approval.

**R3A-42. Text-surface constraints.** Title at most 60 characters (`TITLE_MAX_CHARS`), meta description at most 160 (`META_MAX_CHARS`), both existing constants; **uniqueness enforced across the client's entire corpus**, not just the run, because a title collision is itself a duplicate signal. Primary-keyword density ceiling 0.03 (`PRIMARY_DENSITY_HARD_CEILING`) with **no density floor** (a floor is density gaming). Flesch reading ease: the code's full-credit band is **55 to 75**, with a degraded band of 45 to 85 and a further one of 35 to 95 (`backend/app/services/content_qa.py:398-407`); the "60-70 target" appears only in the failure-note string, not as a scored band. **Use 55-75 as the implementable band; the first draft's "target 60 to 70 with a pass band of 45 to 85" misread the code.** Sentence-length standard deviation floor of 5.0 words `[UNVERIFIED as an external standard, a platform policy]`, because uniform sentence length is the strongest machine-writing tell after the em dash (CONT-35).

### 5.7 The anti-hallucination contract

**R3A-43. Create `evidence` as an insert-only table.** Columns: `id uuid pk`, `run_id uuid not null`, `client_id uuid not null`, `kind text not null` in (`page`,`serp_result`,`metric`,`client_fact`,`gbp`,`upload`,`transcript`,`competitor_page`), `uri text`, `retrieved_at timestamptz not null`, `content_sha256 text`, `snippet text`, `payload jsonb not null`, `provider text`, `cost numeric not null default 0`, `created_at`. **No UPDATE policy and no UPDATE grant. Evidence is written once by a fetcher, an importer or a human, and never edited.**

**R3A-44. The contract in one sentence, to be quoted in the module's CLAUDE.md: AI never creates evidence.** Any code path in which a model's output becomes an `evidence` row is a defect. Evidence rows originate only from HTTP fetchers, provider clients, file uploads and human form submissions.

**R3A-45. What is in the pool at each stage.**

| Stage | Evidence admitted | New external fetches allowed |
|---|---|---|
| 1 audit | the client's own crawled pages (URL, fetched_at, sha256, extracted text) | yes |
| 2 research | SERP results (URL, title, snippet, position, serp_date), keyword metrics with source and retrieval time, PAA and related queries | yes |
| 3 competitor | fetched competitor pages | yes |
| 4 map, 5 page set | **none new**; derived only from 1 to 3 | **no** |
| 6 brief | `client_local_facts` rows (each already carrying an `evidence_id`), the `client_business_profiles` and `client_locations` snapshot, brand voice | no |
| 7 draft | the union of stages 2, 3 and 6, **and nothing else** | **no. No web access from the drafting call.** |
| 8 to 10 | the stage-7 pool plus the draft | **no. The QA judge may not fetch.** |
| 13 post-publish | the fetched live URL | yes |

**R3A-46. The validator, `backend/app/services/evidence_validator.py`, run after every generative stage. Five checks:**
   1. **URL closure.** Extract every URL from the output (markdown links, bare URLs, JSON-LD `url`, `sameAs`, `@id`). Every host plus path must appear in the run's evidence pool, or be the client's own domain, or be an `internal_link_plan` target. **A URL in AI output that was not in the input corpus invalidates the output.** Rerun the stage, maximum 2 attempts, then hold at `needs_review` flagged `evidence_violation`.
   2. **Numeric closure.** Extract every numeric literal (integers of two or more digits, decimals, percentages, currency amounts, four-digit years, phone numbers). Each must appear verbatim in an evidence payload, or be structural (word counts, list positions, heading levels), or be on the allow-list of the client's own profile numbers. Otherwise invalidate. This promotes `content_qa.py`'s `_GROUNDING_UNTRACEABLE_SCORE = 40` from a score penalty to a hard validator, which is the correct home for it now that QA is advisory.
   3. **Named-entity closure.** Every proper noun classified as a Person, Organization or Place must resolve to a `map_entities` row or a `client_local_facts` value. An unresolved proper noun is the invented-local-partner failure; hold.
   4. **Quotation closure.** Any quoted testimonial or review must match a `client_local_facts` row of kind `proof` byte for byte.
   5. **Justification closure.** Every QA dimension justification must carry an `evidence_ref` resolving to an `evidence.id` in this run's pool, and any justification containing a number not present in the input is rejected at schema-validation time.

**R3A-47. Create `page_evidence_links`** so a published page can be traced back to, and invalidated by, its sources: `(page_plan_id, evidence_id, role)` where role is `fact`, `citation`, `metric` or `competitor_reference`. This is what makes R3A-20's staleness sweep a query rather than a guess.

### 5.8 Maintenance and decay

**R3A-48. Create `content_health_snapshots`.** Columns: `id uuid pk`, `page_plan_id uuid not null`, `window_start date`, `window_end date`, `clicks int`, `impressions int`, `avg_position numeric`, `ctr numeric`, `indexed boolean`, `primary_query text`, `source text` in (`gsc`,`rank_tracker`,`crawl`), `collected_at`. Weekly sweep, 28-day windows.

**R3A-49. Create `maintenance_items`.** Columns: `id uuid pk`, `client_id`, `page_plan_id`, `trigger text not null`, `severity int`, `detected_at`, `evidence jsonb not null`, `action text` in (`refresh`,`rewrite`,`patch`,`consolidate`,`retire`,`technical`), `status`, `assigned_to`, `resolved_at`. `evidence` carries the numbers that fired the trigger, so the operator sees why.

**R3A-50. The six triggers, with their numbers.** All traffic triggers require at least 90 days since publication and compare a trailing 28-day window against the same window 90 days earlier.

| ID | Condition | Meaning | Action |
|---|---|---|---|
| **T1 DECAY_SOFT** | clicks down >= 20% **and** impressions within +/-10% | still served, losing the click | **refresh**, surface only: title, meta, answer block |
| **T2 DECAY_HARD** | avg position on the primary query down >= 3.0, **or** clicks down >= 35% | losing the ranking itself | **refresh**, substantive: body, entity coverage, internal links, media |
| **T3 STALE_FACT** | any cited `client_local_facts` row past `expires_at`, or a change to `client_locations` / `client_business_profiles` NAP or hours | the page states something no longer true | **patch**: regenerate only the affected passage and the JSON-LD. **No traffic threshold. Highest priority.** |
| **T4 DEINDEXED** | URL Inspection reports not indexed | technical, not editorial | **technical**: route out of the content queue |
| **T5 CANNIBALISED** | two published pages rank for the same primary query within 5 positions of each other for 2 consecutive weeks | the map has a collision | **consolidate**: a human decision with a 301 attached |
| **T6 OBSOLETE** | zero clicks and fewer than 10 impressions over 180 days, at least 270 days since publish | the page should not exist | **retire or consolidate** |

The thresholds in T1, T2, T5 and T6 are **platform policy choices with stated reasoning, not externally-sourced numbers. `[UNVERIFIED]` externally.** They are set to be conservative (a 20% click drop on a stable impression base is well outside week-to-week noise on a page with meaningful traffic) and must be revisited once 90 days of real `content_health_snapshots` exist.

**R3A-51. Refresh versus rewrite, decided by evidence rather than judgement.**
   - **Refresh**: cluster assignment, primary intent and URL are unchanged. Edits are additive or corrective. The page keeps its `page_plan_id`, gains a `content_versions` row, and republishes to the same URL. It is **not** near-duplicate-checked against its own prior version.
   - **Rewrite**: the intent, the SERP format, or the target query has changed, meaning the *research* is stale rather than the copy. The page re-enters the pipeline at **stage 2**, produces a new brief and a new draft, and **is** near-duplicate-checked against every other page.
   - **The decision rule:** re-run the stage-2 research on the page's primary query and compare `serp_format` and dominant `intent` against the stored `research_brief`. If either changed, it is a rewrite. Otherwise it is a refresh. This makes the classification reproducible and auditable rather than a reviewer's opinion.
   - Both are L3. A human approves either.
   - Refreshed and rewritten pages **re-enter the paced scheduler**; a refresh is a publish and consumes a slot.

**R3A-52. Prioritise the maintenance queue by business value, not by decay magnitude.** Google's own statement that recovery *"could take several months"* means remediation effort is a scarce, slow-returning resource; spending it on the page with the largest percentage drop rather than the page with the largest revenue contribution is the wrong allocation. Rank `maintenance_items` by `severity * cluster.buyer_quality * historical_clicks`.

---

## 6. Cost model at 100 clients

All Anthropic prices from the official pricing page, accessed 2026-08-23. Search Console API is free of charge (its documentation publishes quotas, not prices).

**Verified unit prices (per million tokens):**

| Model | Input | 5m cache write | Cache read | Output | Batch input | Batch output |
|---|---|---|---|---|---|---|
| Claude Opus 5 | $5.00 | $6.25 | $0.50 | $25.00 | $2.50 | $12.50 |
| Claude Sonnet 5 | $2.00 | $2.50 | $0.20 | $10.00 | $1.00 | $5.00 |
| Claude Haiku 4.5 | $1.00 | $1.25 | $0.10 | $5.00 | $0.50 | $2.50 |

The Batch API is a flat **50% discount on both input and output**. Prompt caching multipliers are 1.25x base input for a 5-minute write, 2x for a 1-hour write, and **0.1x for a read**; the documentation states these multipliers stack with the Batch discount. Web search via the Anthropic server tool is **$10 per 1,000 searches**; web fetch carries **no additional charge** beyond the tokens of the fetched content. Note: the Sonnet 5 $2/$10 rate, originally announced as introductory through 2026-08-31, is now the standard price and the scheduled increase to $3/$15 **will not occur**.

**Token model per page (my engineering estimate, not a measured figure; label it as such until the first 50-page run is metered).**

| Sub-stage | Input tokens | Output tokens |
|---|---|---|
| Brief synthesis | 15,000 | 3,000 |
| Draft | 25,000 | 6,000 |
| AI-tell rewrite (section-wise) | 8,000 | 4,000 |
| Titles, meta, schema | 10,000 | 2,000 |
| QA judge (judgment dimensions) | 20,000 | 3,000 |
| **Per page total** | **78,000** | **18,000** |

Research (stages 2 and 3) is amortised per cluster, not per page: roughly 60,000 input and 8,000 output per research run, one run per eight-page cluster.

**Arithmetic, per page:**

- **All Opus 5, no caching:** (78,000 x $5 / 1,000,000) + (18,000 x $25 / 1,000,000) = $0.390 + $0.450 = **$0.840**
- **All Opus 5, with 5m caching on a 50,000-token stable prefix (one write, four reads across the five sub-calls):** uncached input 28,000 x $5/1M = $0.140; cache write 50,000 x $6.25/1M = $0.313; cache reads 4 x 50,000 x $0.50/1M = $0.100; output $0.450. Total **$1.003**. **Caching does not pay here** because the prefix is written once and read only four times inside a short chain; the 1.25x write is not amortised. Do not enable caching per page. Caching pays across a *cluster* only if the reuse fits the cache lifetime: one brief context reused across eight pages, with the write amortised over roughly 32 reads, is $0.313 + 32 x $0.025 = $1.11 per cluster versus $2.00 uncached (8 pages x 50,000 prefix tokens x $5/1M), saving about **$0.11 per page**. **That saving is conditional on a constraint the arithmetic hides:** a 5-minute cache write is *"valid for 5 minutes"* [Anthropic pricing], so all eight pages must be generated inside a five-minute window or the cache expires and the write is paid again. If the cluster cannot be fanned out that fast, use the **1-hour** write (2x base input, $10/MTok for Opus 5) and recompute: $0.50 + 32 x $0.025 = $1.30 per cluster, still under the $2.00 uncached figure. **Do not implement the 5-minute variant without first measuring wall-clock time for an eight-page fan-out.**
- **All Sonnet 5, no caching:** (78,000 x $2 / 1,000,000) + (18,000 x $10 / 1,000,000) = $0.156 + $0.180 = **$0.336**
- **Recommended mix** (Opus 5 for research synthesis, map construction and the QA judge; Sonnet 5 for brief, draft, rewrite and metadata): Sonnet portion 58,000 in / 15,000 out = $0.116 + $0.150 = $0.266; Opus portion 20,000 in / 3,000 out = $0.100 + $0.075 = $0.175. **$0.441 per page.**
- **Amortised research:** (60,000 x $5/1M) + (8,000 x $25/1M) = $0.300 + $0.200 = $0.500 per cluster, divided by 8 pages = **$0.063 per page.**
- **Bulk fan-out drafting through the Batch API** (halves the Sonnet portion of the mix): $0.133 + $0.175 + $0.063 = **$0.371 per page.**

**Monthly totals at 100 clients.**

| Scenario | Pages / month | Cost / page | Monthly LLM cost |
|---|---|---|---|
| All 100 clients on the default 6/week | 2,600 | $0.504 (mix + research) | **$1,310** |
| Same, bulk drafting on the Batch API | 2,600 | $0.371 | **$965** |
| Same, all Opus 5 interactive | 2,600 | $0.903 | **$2,348** |
| Realistic steady state: 30 clients in an active sprint, 70 on maintenance only (2 refreshes/month each) | 780 + 140 = 920 | $0.504 | **$464** |

(2,600 = 100 clients x 6 pages x 52 weeks / 12 months.)

**Costs outside the LLM bill.**

- **Serper (SERP research).** The homepage advertises *"Get 2,500 free queries"* with *"No credit card required"*, and **does not state whether that allowance is one-time or monthly** (verified 2026-08-23). Note that D-3 in `DECISIONS_LOG.md` reads it as "2,500 searches/month"; **that per-month reading is not supported by anything Serper publishes and is `[UNVERIFIED]`.** If the 2,500 is a one-time signup credit rather than a monthly allowance, the free tier does not survive even the first client, let alone 100. Paid plan pricing could not be retrieved: `https://serper.dev/pricing` returns HTTP 404 (confirmed by direct request on 2026-08-23) and the homepage publishes no pricing table. **`[UNVERIFIED]`.** Usage estimate: roughly 5 queries per research cluster, so 2,600 pages / 8 pages per cluster x 5 = **1,625 queries/month for content research alone**, before rank tracking. This confirms decision D-3's warning that the free tier will not survive 100 clients, and the paid figure must be obtained before v1 pricing is set.
- **Search Console API.** No charge. Quotas verified in section 3.6 and are three to four orders of magnitude above our need.
- **Image generation.** Provider not settled in this track; cost per image **`[UNVERIFIED]`**. At `MAX_IMAGES = 5` per page and 2,600 pages, this is a 13,000-image-per-month line item and could plausibly exceed the entire LLM bill. It must be costed before v1.
- **Near-duplicate checking.** Pure CPU on the existing worker. Approximately 105,000 set intersections per 100-page run; single-digit seconds. **$0 marginal.**
- **Human review, which is the real cost.** 2,600 pages/month at 8 minutes per review is **347 hours/month**, or roughly **two full-time reviewers**. At any plausible loaded rate this is one to two orders of magnitude larger than the model cost. **The economics of this module are labour economics, not token economics.** This is why R3A-29's global review-capacity throttle is a P0 requirement and not a refinement, and it is the strongest argument for the paced scheduler independent of any SEO consideration.

**A defect in the current cost accounting that this exposes.** `db/migrations/0017_content.sql:70` comments the `cost` column as "per-page cost, ~$10-50". The marginal model cost computed above is under one dollar. Either the $10-50 figure is a **loaded** cost including review labour, or it is wrong. **`[UNVERIFIED]` which.** A first draft of this section asserted that the arithmetic above "supports roughly $30 to $45 per page" for review labour. It does not, and that figure is withdrawn: at the 8-minute review this document assumes throughout, $30 per page implies a loaded reviewer rate of about **$225 per hour**, which no plausible agency rate reaches. At a loaded $50 to $75 per hour, 8 minutes is **$7 to $10 per page**, which lands at the very bottom of the $10-50 band and not inside it. So the band is reconciled only if review actually takes far longer than 8 minutes, or if the figure bundles costs this document has not modelled (image generation, SERP data, WordPress publishing labour, account management). **Whichever it is must be established by measurement, not by back-fitting**, and the 8-minute review assumption itself is an estimate that O-1's pilot should measure. This is exactly the marginal-versus-loaded distinction decision D-2 forced for citations, and the same discipline must apply here: **define `content_jobs.cost` explicitly as marginal, add a separate loaded-cost model, and never show one where the other is meant.**

---

## 7. Risks and failure modes

1. **The fact substrate is empty, so every location page holds and the module looks broken.** This is the most likely early failure and it is a product failure, not a bug. Mitigations: (a) page-set selection must show **fact readiness per proposed page before the operator commits any cost**, so nobody selects 40 pages and then discovers 38 of them hold; (b) the `fact_request` artefact must be a client-shareable form, not an internal error; (c) onboarding must not be marked complete until the primary location clears the block-severity minimums.
2. **Near-duplicate thresholds are wrong in either direction.** Too tight and every legitimate page holds and the operator learns to click through holds. Too loose and the doorway exposure is unmitigated while the dashboard says "passed". Mitigation: **shadow mode from day one**, scores logged on every run, enforcement enabled only after O-2's calibration. A gate nobody trusts is worse than no gate, because it manufactures false confidence.
3. **QA stays PROVISIONAL forever.** D-4's calibration on 30 human-graded drafts requires 30 drafts and a human SEO's time. If it never happens, the mandatory acknowledgement degrades into a click-through and the scorecard becomes decoration. Mitigation: make the calibration count visible on every scorecard ("calibrated on 0 of 30 drafts") so the debt is impossible to forget.
4. **Human review is the scaling wall and the platform hides it.** At 100 clients the queue is the constraint. If the UI shows per-client pacing without showing global capacity contention, the operator will set every client to 15 per week and the queue will grow without bound. Mitigation: surface the global capacity number and the contention on the calendar.
5. **The unresolvable doctrine path.** Every threshold in `content_generator.py` and `content_qa.py` cites `backend/seo-content-os/knowledge/`, which is not a directory in this repository. The content is not lost (it is in the tracked `SEO-CONTENT-OS.zip` at the repo root, see section 3.8), but nothing in the code or the doctrine file says so, so an engineer asked to tune a constant has no discoverable way to check whether they are contradicting a deliberate decision. Mitigation: R3A-37, before any other content work.
6. **The two divergent 14-dimension lists.** They will drift, and the drift will surface as a scorecard whose dimensions do not match the generator's self-assessment. Mitigation: R3A-37.
7. **Publishing a false claim about indexing or FAQ rich results.** Both `CONT-52` (Indexing API) and the FAQPage output currently promise something Google does not do. If either appears in a client report, it is a credibility loss of the same class as the citation-cost figure D-2 addresses. Mitigation: correct both before v1 and disclose proactively if either has already been reported.
8. **Batch API latency versus operator expectation.** Batch drafting can take hours. If the operator expects a 20-page fan-out to complete while they watch, the saving is a UX regression. Mitigation: batch only for explicitly bulk runs with an announced completion window; single-page jobs stay interactive.
9. **Refresh republishes trip the near-duplicate gate against the page's own predecessor.** Guaranteed if not handled. Mitigation is explicit in R3A-51: a refresh is exempt from comparison against its own prior version, and only a rewrite is compared against the full corpus.
10. **The map is approved once and never revisited, so the entity graph rots.** Mitigation: `topical_maps.version` plus a staleness signal on the map itself when more than 25% of its clusters have open `maintenance_items`.
11. **A client edits a published page and a refresh overwrites their edit.** Already named as a failure case in the specification (§15). The refresh path must diff the live page against the last published version and hold on unexpected divergence rather than overwriting. Owned by R3B but triggered by this track's maintenance loop.
12. **Evidence pool growth.** One `evidence` row per SERP result, per fetched competitor page and per fact, across 2,600 pages a month, is a large insert-only table. It needs a retention policy (proposal: keep payloads for 13 months, keep the row and its sha256 forever) and it needs the `payload jsonb` to be compressed or offloaded for `page` and `competitor_page` kinds.

---

## 8. Open items

| ID | What could not be settled | Exactly what would settle it |
|---|---|---|
| **O-1** | The publication rate. No primary source exists for 5-10 per week, or for any rate. The 6/week default and the 5%-of-corpus scaling are reasoned policy, not evidence. | A controlled internal experiment: two comparable clients, matched service and market, each given 24 new location pages built to identical standards. Cohort A publishes at 3/week, cohort B at 12/week. Hold everything else constant. Measure (a) days to indexation per page, (b) share indexed at 30 / 60 / 90 days, (c) median position on the primary query at 90 days, (d) any manual action. Three months, roughly $250 of model spend, and it is the only way anyone will ever have a real number. |
| **O-2** | The near-duplicate thresholds (masked 0.60 / 0.80, structural 0.50, run-level 0.45) and the shingle size k=5. | Take 200 pages from a real client corpus, have a human SEO label each pair in a sampled set as "acceptably distinct" or "too similar", compute masked Jaccard at k=4, 5 and 6 for every pair, and pick the (k, threshold) pair maximising F1 against the human labels. Approximately one day of a practitioner's time. Until then, **shadow mode**. |
| **O-3** | Serper paid pricing and rate limits. `https://serper.dev/pricing` returns 404; the homepage publishes only the 2,500 free queries. This blocks the v1 cost model and D-3 already flagged it. | Log in to the Serper dashboard, or contact the vendor. Needs the price per 1,000 queries, the plan tiers, and the queries-per-second limit. |
| **O-4** | Image generation provider and cost per image. At 5 images x 2,600 pages this could exceed the entire LLM bill. | Name the provider (this belongs to a different track) and read its published price. Then decide whether `MAX_IMAGES = 5` survives contact with the bill. |
| **O-5** | The QA weight vector and the 85 / 70 thresholds. Self-declared PROVISIONAL in the source; never calibrated. | D-4's own answer: 30 drafts graded by a human SEO on the same 14 dimensions, then fit the weights and thresholds to the human grade. Until then every scorecard carries a PROVISIONAL badge and a "calibrated on N of 30" counter. |
| **O-6** | Whether `content_jobs.cost` is marginal or loaded. The column comment says $10-50; the marginal arithmetic says under $1. | An owner decision, mirroring D-2's marginal / loaded / hard-fail-line structure for citations. Until it is made, the cost dial reports a number nobody can interpret. |
| **O-7** | Multi-location modelling (decision D-9, currently open) **and which existing table carries it**. Corrected in verification: multi-location is *already* modelled, by the citation engine's `business_profiles` (per-branch, `label` + `is_primary`, no per-client uniqueness). The open question is therefore not "build it or not" but "**reuse `business_profiles`, or add `client_locations` as a third identity table**" (R3A-12 options a and b). | An owner decision. This track recommends **reuse (option a)**: two nullable columns (`lat`, `lng`) plus a GBP place id, rather than a third source of truth for one client's address. Decide before R3A-13 is built, because `client_local_facts.location_id` must point at the winner. The retrofit cost after 100 clients are onboarded is far higher than deciding now. |
| **O-8** | Whether the alt-text 125-character cap, the 30% anchor-repeat cap, and the sentence-length σ >= 5.0 floor have any external basis. I could find none. | They are platform policy. They can stay as policy provided they are labelled as such in the code comments rather than being attributed to a source. If an external basis matters, it needs a study nobody appears to have published. |
| **O-9** | Whether the "50 to 80% traffic loss" figure attributed to the March 2026 updates is real at that magnitude. | A published traffic study with a disclosed sample frame, or a Google statement. Until then the platform must not quote a number. The direction is safe to act on; the magnitude is not safe to repeat. |

---

## 9. Sources

**Primary (Google)**

- [Google spam policies] https://developers.google.com/search/docs/essentials/spam-policies — accessed 2026-08-23 (page shows Last updated 2026-05-15 UTC)
- [Google Search Status Dashboard, ranking updates history] https://status.search.google.com/products/rGHU1u87FJnkP6W2GwMi/history — accessed 2026-08-23
- [Google creating helpful, reliable, people-first content] https://developers.google.com/search/docs/fundamentals/creating-helpful-content — accessed 2026-08-23 (Last updated 2025-12-10 UTC)
- [Google core updates] https://developers.google.com/search/updates/core-updates — accessed 2026-08-23 (Last updated 2025-12-10 UTC)
- [Google link best practices] https://developers.google.com/search/docs/crawling-indexing/links-crawlable — accessed 2026-08-23 (Last updated 2025-12-10 UTC)
- [Google LocalBusiness structured data] https://developers.google.com/search/docs/appearance/structured-data/local-business — accessed 2026-08-23 (Last updated 2025-12-10 UTC)
- [Google breadcrumb structured data] https://developers.google.com/search/docs/appearance/structured-data/breadcrumb — accessed 2026-08-23 (Last updated 2025-12-10 UTC)
- [Google FAQPage documentation] https://developers.google.com/search/docs/appearance/structured-data/faqpage — accessed 2026-08-23
- [Google search gallery of rich results] https://developers.google.com/search/docs/appearance/structured-data/search-gallery — accessed 2026-08-23 (Last updated 2026-06-15 UTC)
- [Google Search Console API limits] https://developers.google.com/webmaster-tools/limits — accessed 2026-08-23 (Last updated 2025-08-28 UTC)
- [Google Indexing API quota and restrictions] https://developers.google.com/search/apis/indexing-api/v3/quota-pricing — accessed 2026-08-23 (Last updated 2026-07-16 UTC)

**Primary (academic and vendor documentation)**

- [Manku, Jain & Das Sarma, "Detecting Near-Duplicates for Web Crawling", WWW 2007] https://research.google.com/pubs/archive/33026.pdf — accessed 2026-08-23. *Note: the PDF's text layer could not be extracted in-session; the quoted parameter sentence is reproduced consistently across the paper's indexed text and independent citations.*
- [Manning, Raghavan & Schütze, *Introduction to Information Retrieval*, "Near-duplicates and shingling"] https://nlp.stanford.edu/IR-book/html/htmledition/near-duplicates-and-shingling-1.html — accessed 2026-08-23
- [Broder, Glassman, Manasse & Zweig, "Syntactic Clustering of the Web", WWW6 1997] https://www.ambuehler.ethz.ch/CDstore/www6/Technical/Paper205/Paper205.html — accessed 2026-08-23
- [SimHash, Wikipedia — secondary, cited for the attribution of Google's 2007 usage] https://en.wikipedia.org/wiki/SimHash — accessed 2026-08-23
- [Anthropic pricing] https://platform.claude.com/docs/en/about-claude/pricing — accessed 2026-08-23
- [Serper] https://serper.dev/ — accessed 2026-08-23. `https://serper.dev/pricing` returned HTTP 404 on the same date.

**Secondary (used only where no primary source exists, and labelled as secondary in the text)**

- [Search Engine Roundtable, Google on page count and rankings] https://www.seroundtable.com/google-higher-page-count-seo-26633.html — accessed 2026-08-23
- [iLoveSEO, Google: publishing consistency does not affect rankings] https://iloveseo.com/seo/google-publishing-consistency-does-not-affect-rankings/ — accessed 2026-08-23
- [Search Engine Journal, Google finishes rolling out the August 2026 spam update] https://www.searchenginejournal.com/google-begins-rolling-out-the-august-2026-spam-update/586301/ — accessed 2026-08-23
- [PPC Land, Google's third spam update of 2026] https://ppc.land/googles-third-spam-update-of-2026-hits-every-language-and-region/ — accessed 2026-08-23
- [digitalapplied, scaled content abuse and the March 2026 update — source of the widely-repeated 50-80% figure, unverified] https://www.digitalapplied.com/blog/scaled-content-abuse-google-march-update-ai-pages-decimated — accessed 2026-08-23
- [The Search Foundry, programmatic SEO for local landing pages — source of the 80/20 heuristic, unverified] https://searchfoundry.co.uk/blog/programmatic-seo-on-a-budget-scaling-local-landing-pages-without-spam-penalties/ — accessed 2026-08-23
- [shno.co, content refresh statistics 2026 — source of the decay percentages, unverified] https://www.shno.co/marketing-statistics/content-refresh-statistics — accessed 2026-08-23

**Repository (verified by reading the file at the cited line)**

- `db/migrations/0017_content.sql` — the `content_jobs` ledger, enums, RLS and the three-actor lifecycle trigger
- `db/migrations/0051_client_business_profile.sql:26-55` — the single-location `client_business_profiles` table with `unique (client_id)` at line 54 (the first draft cited :30-54, which starts mid-table)
- `db/migrations/0045_citation_web2_automation.sql:74-93` — `business_profiles`, the **multi-location** per-branch NAP the first draft missed; `0048_directories_strategy.sql:124-125` adds `nap_locked`; `0060_business_profile_fields.sql` adds description/email/logo/socials/`service_area`
- `SEO-CONTENT-OS.zip` (repo root, tracked; `SEO-CONTENT-OS/knowledge/`) — the doctrine the code cites at the unresolvable path `backend/seo-content-os/knowledge/`
- `backend/app/services/content_schema.py:25-27,89` — `_RICH_DEPRECATED` and the "never promised as a rich result" contract for `FAQPage`/`HowTo`
- `backend/integrations/google_indexing.py:1-5` — the built `urlNotifications:publish` seam, with **no** `JobPosting`/`BroadcastEvent` eligibility check anywhere in `backend/`
- `backend/app/config.py:488` — `google_indexing_enabled: bool = False`
- `db/migrations/0017_content.sql:31` — `content_page_type` is `('service', 'blog', 'local')`; `:42-44` — `content_status`; `:70` — the `cost` column commented "~$10-50"
- `db/migrations/0072_content_schedule.sql` — `publish_at`, and the note that the beat sweep is disabled
- `backend/app/services/content_qa.py:76-91` — the fourteen QA dimensions
- `backend/app/services/content_qa.py:95-97` — the five hard-gate dimensions
- `backend/app/services/content_qa.py:104-106` — `MIN_DIMENSION_SCORE = 70`, `WEIGHTED_TOTAL_THRESHOLD = 85`, `HARD_GATE_FLOOR = 70`, all marked PROVISIONAL
- `backend/app/services/content_generator.py:70-82` — `WORD_COUNT_FLOOR/CEILING`, `LOCAL_UNIQUE_MIN = 0.50`, `MAX_IMAGES = 5`, `MAX_FAQ = 6`, `MAX_INTERNAL_SPOKES = 6`, `TITLE_MAX_CHARS = 60`, `META_MAX_CHARS = 160`
- `backend/app/services/content_generator.py:92-97` — `DIFFERENTIATION_KINDS`
- `backend/app/services/content_generator.py:101-116` — the **divergent** second fourteen-dimension tuple (9 of the 14 names differ from the QA gate's; only `intent_match`, `eeat_experience`, `entity_coverage`, `internal_linking` and `information_gain` are common to both)
- `backend/app/services/content_guard.py:52-60` — the forbidden dash family and the unconditional strip guarantee
- `backend/app/services/content_research.py:1-45` — the `ResearchBrief` contract: intent, cluster, format, fan-out, winnability, top-10 teardown, keyword-to-URL registry
- `backend/workers/tasks/content.py:156-175` — the current 14-step `PIPELINE` tuple and the `_STAGE_LABEL` map
- `backend/app/modules/client_onboarding/constants.py:80-92` — the eleven-step `LOCAL_SEO_TEMPLATE` (`brand_assets` is step 6, `competitor_list` step 7); `:29` — the "logo, guidelines, voice, photos" gloss; the free-text `notes` column is `db/migrations/0040_client_onboarding.sql:119`
- `backend/docs/CONTENT-DOCTRINE.md:8,19,82` — the authority transfer to `backend/seo-content-os/knowledge/`, **a path absent from the working tree and from the entire git history**, though its content is tracked at the repo root as `SEO-CONTENT-OS.zip`; `:34` and the zip's `knowledge/doctrine/seo-system-doctrine.md:67` — "no AI-detector evasion", Law 8
- `docs/implementation/KNOWN_LIMITATIONS.md` §3 — QA is already advisory; `PublishBlocked` is raised nowhere; the mandatory-acknowledgement half of D-4 is unbuilt
- `docs/recovery/DANIEL_PROJECT_RECOVERY_SPECIFICATION.md` §14 — CONT-1 to CONT-59, and §14.8's eight named weaknesses
- `docs/recovery/DECISIONS_LOG.md` — D-1 (v1 scope), D-2 (marginal vs loaded cost discipline), D-3 (50-100 clients), D-4 (QA advisory, open), D-9 (multi-location, open)

---

## Verification pass — 2026-08-23

An adversarial verification pass was run against this document with the goal of refuting it. Every repository citation was resolved against the working tree; every external claim was checked for a source URL and an accessed date; and the highest-stakes external claims were re-fetched at source. The document survives with **eleven substantive corrections**, listed below. Its central architecture (evidence-gated stages, a fact substrate the drafter cannot bypass, deterministic masked-Jaccard duplicate detection, paced publication throttled by human-review capacity) is unchanged, and the cost model's arithmetic checked out to the cent.

### Sources fetched at primary during this pass

| Source | What was checked | Result |
|---|---|---|
| Anthropic pricing (`platform.claude.com/docs/en/about-claude/pricing`) | Every per-MTok figure in the section 6 table, the Batch discount, the cache multipliers, the web search and web fetch prices, and the Sonnet 5 introductory-pricing note | **All exact.** The Sonnet 5 note is reproduced almost verbatim from the page, including that the scheduled $3/$15 increase will not occur |
| Google spam policies | Scaled content abuse definition, its AI example, the doorway definition and all four doorway examples | Definitions **exact**; one "quoted" doorway example was a paraphrase and was replaced with the two verbatim bullets |
| Google Indexing API quota and restrictions | The 200/day publish quota and the `JobPosting` / `BroadcastEvent` restriction | **Exact**, and last-updated 2026-07-16 as stated |
| Google Search Console API limits | All six quota figures | **Exact**, and last-updated 2025-08-28 as stated |
| Google FAQPage documentation | Whether the FAQ rich result is still shown | **Confirmed**, plus a firmer date than the document had: removal effective 2026-05-07 |
| Google search gallery | The full rich-result type list, and the absence of FAQ and HowTo | **Exact**, all 25 types, last-updated 2026-06-15 |
| Google link best practices | The three quoted sentences | Confirmed, but two were **truncated mid-sentence** and have been restored |
| Google core updates | The recovery-timeline quote and the core-update definition | **Exact** |
| Google LocalBusiness / BreadcrumbList structured data | Required and recommended property lists, geo precision, priceRange limit, the two-ListItem minimum | Confirmed, except the priceRange bound, which is "shorter than 100", not "max 100" |
| Manning, Raghavan & Schütze, *Introduction to Information Retrieval* | The k=4 sentence and the 0.9 threshold | k=4 **exact**; the 0.9 is hedged in the source as *"say, 0.9"* and the document had presented it as a stated standard |
| Manku, Jain & Das Sarma, WWW 2007 | The 8B / 64-bit / k=3 sentence, which the document had flagged as unextractable | **Now verified at primary.** The PDF was downloaded and its Flate streams decompressed locally; the sentence is confirmed, and the paper's precision/recall figure at k=3 was recovered as well |
| Serper | The free-tier allowance and whether paid pricing is published | Homepage says *"Get 2,500 free queries"*, *"No credit card required"*, and does **not** say whether it is one-time or monthly; `serper.dev/pricing` confirmed HTTP 404 by direct request |

The Google Search Status Dashboard could not be fetched directly (it is a client-rendered application). Its 2026 update dates are treated as **corroborated rather than primary-verified**: independent trade reporting and the sibling track R2, which cited the dashboard directly, agree on the March spam update (2026-03-24, under 20 hours), the March core update (2026-03-27, 12 days), and the August spam update (2026-08-18 to 2026-08-21, 2 days 16 hours). A human should re-read the dashboard before any of these dates is quoted to a client.

### Corrections made

1. **Multi-location was already modelled.** Section 3.2 claimed "multi-location is not modelled at all". `public.business_profiles` (`0045_citation_web2_automation.sql:74-93`) is a per-branch NAP table with `label` and `is_primary` and no per-client uniqueness, and `0051`'s own header says so. R3A-12 was rewritten from "create `client_locations`" to a **reconciliation between two existing identity tables**, with the two admissible designs and a stated recommendation. O-7 was rewritten to match.
2. **The doctrine knowledge base is not missing.** Section 2, section 3.8 and risk 5 claimed the cited passages were unreadable by anyone. `SEO-CONTENT-OS.zip` is **tracked at the repository root** and contains `knowledge/` with every file the code cites. The defect is narrower and still real: the cited **path** does not resolve. All three passages were corrected and the stronger claim withdrawn.
3. **A SimHash claim that was probably backwards.** "Hamming distance 3 on 64 bits would let two city pages that differ only in the city name pass as distinct" was unsourced and is likely false, since SimHash maps similar documents to *near* fingerprints. It is marked `[WITHDRAWN]`. The rejection of SimHash was re-grounded on two sourced facts recovered from the paper: precision and recall **near 0.75** at k=3, and the unsuitability of an integer bit-distance for a graded review band.
4. **The FAQ finding was already implemented.** Section 3.7 presented "stop emitting FAQPage" as a correction to the codebase. `content_schema.py:89` already declares `_RICH_DEPRECATED = {"FAQPage", "HowTo"}` and `rich_result_eligible()` already returns `False` for both. The section heading and conclusion were rewritten, and R3A-41's instruction changed from "drop the markup" to "no change needed, verify only". Removing the markup on the strength of the original text would have been a regression.
5. **The Indexing API finding was understated.** It was framed as a requirement to re-scope. `backend/integrations/google_indexing.py` already posts to `urlNotifications:publish`, and `grep -r "JobPosting|BroadcastEvent" backend/` returns **nothing**, so no code path checks eligibility. Restated as a **guard requirement** on shipped code, with the two facts that contain it today (the feature flag defaults false; D-1 defers the module to v1.1) noted as circumstances rather than controls.
6. **The pacing defaults were arithmetically unsatisfiable.** `daily_cap = 2`, `min_gap_hours = 18` and a 09:00-17:00 window cannot all hold: two same-day slots are at most 8 hours apart. The `weekly_cap` ceiling of 15 was unreachable for the same reason. `daily_cap` default changed to **1**, a check constraint added so an unsatisfiable plan fails at write time, and the weekly cap clamped to `7 * daily_cap`. The Decision section was corrected to match.
7. **A loaded-cost figure its own arithmetic did not produce.** Section 6 asserted the $10-50 column comment was supported "at roughly $30 to $45 per page" for review labour. At the document's own 8-minute review that implies about $225/hour. Withdrawn and replaced with the actual figure ($7-$10 at a loaded $50-75/hour), which does **not** reconcile the band, leaving O-6 genuinely open.
8. **A paraphrase presented as a Google quotation.** The doorway example *"multiple website variations targeting specific regions/queries"* is not Google's wording. Replaced with the four verbatim bullets.
9. **Two truncated Google quotations restored**, including *"...from at least one other page **on your site**"*, whose omitted scope is what makes the orphan rule a within-site property.
10. **Two broken internal cross-references.** R3A-8 pointed at R3A-32 (the circuit breaker) for a `content_page_type` enum extension that no requirement specified; the extension is now spelled out, along with the fact that the enum is today `('service','blog','local')` while R3A-15 assumes `location` and `service_location`. R3A-20 pointed at R3A-42 (text-surface constraints) for the maintenance item; corrected to R3A-49 / R3A-50.
11. **Three over-precise or misread constants.** The Stanford 0.9 threshold is the textbook's hedged example (*"say, 0.9"*), not a prescribed standard, and R3A-25's rationale was corrected. `priceRange` is "shorter than 100 characters", so the implementable bound is 99. The Flesch band was misread: the code's full-credit band is **55-75** (`content_qa.py:398-407`), and "60-70" appears only in a failure-note string. Line references in the Sources section were corrected where they started mid-declaration, and eight repository citations were added for material this pass verified.

### Repository claims checked and found correct

All of the following resolved and said what was claimed: `0017_content.sql` (enums at :31 and :42-44, the `cost` comment at :70, the guard trigger, `is_staff()` RLS); `0051_client_business_profile.sql` columns and `unique (client_id)`; `0072_content_schedule.sql` and its disabled beat sweep; `content_generator.py:70-82, 92-97, 101-116`; `content_qa.py:76-91, 95-97, 104-107, 131-133`; `content_guard.py:52-60` and the unconditional `strip_dashes` guarantee; `content_research.py:1-45`; `content.py:156-175`; `client_onboarding/constants.py` (eleven steps, `brand_assets` at 6, `competitor_list` at 7, the "logo, guidelines, voice, photos" gloss); `KNOWN_LIMITATIONS.md` §3 including the verbatim D-4 quotation; `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md` §14.8 item 8 with the `[WA-TEAM]` 05/07 quotation, §15's client-edit failure case, §28.3, and all eighteen `CONT-*` / `WP-9` identifiers cited; `DECISIONS_LOG.md` D-1 (content is module 3 of five), D-2, D-3, and D-4 and D-9 both genuinely in the "Still open" table; commit `faeec43`; and the divergent 14-dimension tuples (in fact **9 of 14** names differ, which is worse than the document said, not better). The `grep` claim in section 2 was re-run: the 30 hits for `simhash|minhash|near_duplicate|jaccard|shingle` are all in competitor-intel, keyword-research and roofing-themed test fixtures, so "nothing in the content path" is accurate as written.

### What remains `[UNVERIFIED]`, and why

- **The "50 to 80% traffic loss" magnitude** (O-9). No Google publication and no methodology-disclosed study locates it. Correctly withheld already; the direction is safe to act on, the number is not.
- **Every near-duplicate threshold except raw 0.90** (O-2), and raw 0.90 itself is only a textbook illustration. Shadow mode before enforcement remains the right call and is now the only defensible one.
- **The SimHash prefilter's Hamming bound.** Newly marked: 8 was a placeholder with no basis. It must be set empirically against O-2's labelled corpus.
- **The publication rate** (O-1) and the 5%-of-corpus scaling. Practitioner convention with no primary source, correctly labelled as platform policy.
- **Serper's free-tier period and all paid pricing** (O-3). The source does not say whether 2,500 is one-time or monthly, and D-3's "per month" reading is now flagged as unsupported. If it is one-time, the cost model changes materially.
- **Image generation cost** (O-4), which the document itself notes could exceed the entire LLM bill.
- **Whether `content_jobs.cost` is marginal or loaded** (O-6), now genuinely open rather than papered over by an invented loaded figure.
- **The 8-minute review assumption**, which the entire labour-economics argument and the global review-capacity throttle rest on. It is an estimate, not a measurement, and no source in this document supports it.
- **The alt-text 125-character cap, the 30% anchor-repeat cap, the sentence-length sigma floor, and the six decay-trigger thresholds** (O-8), all correctly labelled platform policy.
- **The Google Search Status Dashboard dates**, corroborated but not fetched at primary in this pass.

### One cross-track note for the build team

Sibling track R2 specifies a near-duplicate gate for Web 2.0 using the same 5-word shingles but different thresholds (Jaccard block at r >= 0.25, heading-skeleton block at >= 0.60) across a cross-client scope. R3A's thresholds (masked 0.80 / 0.60, structural 0.50) apply to a within-client page corpus. The two are not in conflict, because the scopes and base rates differ, but **they should share one shingling implementation and one calibration exercise**, or they will drift into two incompatible notions of "too similar" in the same product. That is a coordination item for whoever sequences R2 and R3A, not a defect in either document.

**Verdict: CORRECTED.** The decision follows from the findings once the eleven corrections above are applied. No standing constraint is violated: the L3 ceiling is respected throughout (every publish, refresh and rewrite is human-approved), no CAPTCHA or detector evasion appears anywhere and both are explicitly rejected, no Kubernetes is proposed, and the fact gate's structural refusal is the strongest anti-invented-data mechanism in any track reviewed so far.
