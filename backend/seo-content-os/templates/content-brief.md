# Local Page Content Brief

The input contract for every write command. No page is drafted without a filled
brief. If a field is unknown, it is a question for the SME interview or live
research, never an invented value (see CLAUDE.md hard rules). A brief that is
missing the target query, intent, the one job, or the E-E-A-T anchors is
incomplete and the writer halts and asks.

Save the filled brief to `output/<client>/<page-slug>/brief.md` (the path every
pipeline stage reads: the `/brief` command and each `/write-*` BRIEF step write it,
`keyword-intent-researcher` and the downstream agents read it).

Fields marked (RESEARCH) are filled at the RESEARCH step from live SERP work.
Fields marked (SME) come from the operator interview. Everything else the
operator or the brief step fills before drafting.

---

## 1. Client and page

- **Client slug:** <!-- clients/<slug>/brand.yaml must exist -->
- **Brand name (as used in copy):**
- **Topical map node:** <!-- node_id from clients/<slug>/topical-map.md. This page MUST be a promoted `status: page` node. If the node is index-only (no evidence yet), do not brief it; get the evidence first. If no topical map exists, run /build-topical-map before briefing a greenfield set. -->
- **Section (from the map):** <!-- core (money page) | outer (builds trust) -->
- **Info-gain thesis (from the map node):** <!-- the one net-new fact this page adds beyond the SERP consensus, decided at map time. This is the differentiation the whole page defends. -->
- **Page type:** <!-- location | service | service-in-city | homepage | about-team | service-area -->
- **Command that will run this:** <!-- /write-location-page, etc. -->
- **Page URL / slug (proposed):**
- **Date created (PKT):**
- **Operator approval required:** <!-- true for the first pages in a new engagement -->

## 2. Target search intent

- **Primary target query:** <!-- e.g. "emergency plumber round rock" -->
- **Search intent:** <!-- local-transactional | local-commercial-investigation | informational-local -->
- **Local pack present for this query:** (RESEARCH) <!-- yes/no -->
- **AI Overview / answer-engine present:** (RESEARCH) <!-- yes/no; note what it cites -->
- **What the searcher wants in one sentence:** <!-- the job they are trying to get done -->
- **Top 3 currently ranking (URL + one line why):** (RESEARCH)
  - 1.
  - 2.
  - 3.
- **People Also Ask / real questions (5+):** (RESEARCH / SME)
  - -

## 3. Keywords

- **Primary keyword:** <!-- the one exact-ish phrase this page earns -->
- **Secondary keywords (3-6, natural variants, NOT stuffing fodder):**
  - -
- **Semantic / entity terms to cover naturally:** (RESEARCH) <!-- neighborhoods, materials, brands, adjacent services -->
- **Over-optimization guard:** target primary phrase stays under 2.5% density.
  Run `scripts/keyword_density.py` and `scripts/compliance_lint.py` at GATE.

## 4. The ONE job of this page

<!-- A single sentence. What must this page do? Rank + convert for X. Anchor the
     entity. Prove trust. If you cannot name one job, the page is unfocused. -->

- **The one job:**
- **Primary conversion action:** <!-- call, quote form, book, etc. -->
- **Secondary action (if any):**

## 5. Local context (real facts to include)

<!-- This is what makes the page uncopyable and doorway-proof. Fill from SME +
     live research. Never fabricate a local specific. -->

- **Target city / area:**
- **Service in focus:**
- **Real local facts to work in (SME / RESEARCH):**
  - Neighborhoods / districts actually served:
  - Local landmarks, roads, or ZIP codes relevant to the service:
  - Local conditions that shape the work (climate, soil, housing stock, codes, permits, common local failure modes):
  - Real local pricing / benchmark ranges (RESEARCH, cited):
  - Response-time / coverage truth (no inflating the service radius):
- **Why this page is unique vs the client's other city/service pages:**
  <!-- Mandatory for location and service-area pages. Name the genuine difference. -->

## 6. E-E-A-T assets to use

<!-- Experience and expertise are SHOWN with specifics, not claimed. -->

- **Experience anchors (2+, ideally SME verbatim):**
  - -
- **Expertise markers (2+: licenses with numbers, certifications, specific method):**
  - -
- **Trust markers:** <!-- review count + platform, guarantee, insurance, honest "when not to hire us" -->
  - -
- **Author / reviewer byline (real person from brand.yaml eeat.team):**

## 7. SME questions outstanding

<!-- The specifics only the operator knows. Answer before or during drafting. -->

- 1.
- 2.
- 3.

## 8. Internal linking plan

- **Links INTO this page from (2-4):**
  - -
- **Links OUT of this page to (2-4, with anchor text):**
  - -
- **Money-page / conversion link:** <!-- the service-in-city or contact page this feeds -->

## 9. Schema

- **Primary type:** <!-- LocalBusiness subtype from brand.yaml, or Service -->
- **Also include:** <!-- BreadcrumbList always; FAQPage if 3+ Q&A; Person/Organization as needed -->
- **Validated by:** `scripts/schema_validator.py` at GATE.

## 10. Meta draft

- **Meta title (<= ~60 chars, includes primary intent + brand):**
- **Meta description (<= ~155 chars, one clear promise + action):**

## 11. Pass tests (the GATE this draft must clear)

- [ ] `schema_validator.py` passes on `schema.json`.
- [ ] `nap_checker.py` passes (NAP byte-consistent with brand.yaml / GBP).
- [ ] `readability_scorer.py` grade within the client's reading-level band
      (default 6-9).
- [ ] `compliance_lint.py` returns no ERRORs (H1 present + single, meta present,
      no thin H2 sections, no keyword stuffing, no em dash, no duplicate headings).
- [ ] `keyword_density.py` shows every target under 2.5%.
- [ ] Every H2 is a self-contained, extractable answer (passage-block protocol).
- [ ] Every local specific is real (SME or cited), zero fabricated facts.
- [ ] E-E-A-T shown with specifics: 2+ experience, 2+ expertise, 1+ trust marker.
- [ ] Reads in the client's brand voice on a read-aloud test; no AI tells.
- [ ] Not a doorway page: unique local value vs sibling pages.
- [ ] All five output-contract files exist (page.md, schema.json,
      internal-links.md, compliance-report.md, sources.md).

## 12. Constraints and forbiddens (page-specific)

- **Do NOT mention:** <!-- banned competitors, claims without a license number -->
- **Banned phrases (from brand.yaml voice.banned_phrases):**
- **Compliance notes:** <!-- licensed-trade claims, medical/legal disclaimers, etc. -->

## 13. Approval

- **Brief approved by (name + date PKT):**
