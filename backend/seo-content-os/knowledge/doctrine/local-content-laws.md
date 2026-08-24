# Local Content Laws - workspace extension (Laws 15-20)

v1.0 - 2026-07-20 PKT. Workspace-specific extension to the portable `seo-system-doctrine.md` (Laws 1-14). These six laws are the content-writing laws that general SEO doctrine does not cover. They are downstream of Law 8 (optimize the reward function, not proxies) and Law 13 (optimize for the answer). Each is grounded in the 2026-07-20 research pass (see `research/expansion-2026-07/`). Same rule as the parent doctrine: every law HOLDS, PARTIALLY HOLDS, or IS VIOLATED for a given page; there is no not-applicable.

Authority order: founder > seo-system-doctrine.md > this file > local convenience.

---

### Law 15 - Information gain over coverage.
The content-optimization tool category (Surfer, Clearscope, MarketMuse, Frase) scores a draft by how completely it matches the term and structure profile of the current top results. That can only make a page converge on the consensus. Google's information-gain patent (US 2024/0086439 lineage) rewards the opposite: net-new value that diverges from the SERP. A page earns rank by what it adds beyond the consensus, not by how completely it matches it. Coverage of the expected terms is a floor to clear, never the goal, and never an auto-fail gate. The durable source of divergence is first-party fact: real prices, real project data, real local conditions, real operator judgment.
**Test:** generate the bland consensus answer for the target query, then diff the draft against it. If the residual (the material present in the draft but absent from the consensus) is thin, the page is a rehash and PARTIAL at best. Measured by `scripts/information_gain_scorer.py`.
**Evidence:** research file 01. Corollary of Law 8 and Hard Line 5.

### Law 16 - Experience must be proven, not asserted.
Experience is the first E of E-E-A-T and the one signal no competitor and no model can scrape, remix, or synthesize, because it lives only in the operator. Every commercial AI content tool sources from the SERP or the model's parametric memory, so none can manufacture it. Therefore first-party Experience is the moat, and it is only a moat when it is shown, not claimed. Every falsifiable Experience claim (years, review count, project count, credentials, results, service areas) resolves to a dated, externally checkable first-party artifact: an original photo of this crew's work, an invoice-backed count, a permit or license number, a named real result. "Family-owned since 1998" with no proving specifics is worthless. An unprovable Experience claim is cut, never softened.
**Test:** for each Experience claim on the page, name the artifact that proves it and where it came from (brand.yaml, SME interview, or cited source). Any claim with no proving artifact is a fabrication risk and fails G1/G10. Enforced by `scripts/experience_gate.py` and the SME Experience-harvest.
**Evidence:** research file 05.

### Law 17 - Add statistics, citations, and operator quotes; never stuff.
The strongest controlled evidence on what content changes increase citation in generative engines (Princeton/Georgia Tech GEO study, KDD 2024): adding quotations lifted citation ~+41%, statistics ~+37%, and cited sources ~+30% versus baseline, while keyword stuffing was the only tested tactic that reduced it (~-10%). For the local Business-and-Facts domain these pages live in, substance (statistics, cited sources, fluent direct answers) beats an authoritative tone. So every page front-loads a direct answer per section, carries real statistics with their sources, and embeds real operator quotes, and never pads keyword density to fake relevance.
**Test:** count the statistics-with-source and the operator/customer quotes per page against the page-type playbook minimum; run keyword density and confirm no exact-match phrase exceeds the natural-use threshold. Enforced by `scripts/geo_page_linter.py` and `scripts/keyword_density.py`.
**Evidence:** research file 04. Numbers are directional (single study), the direction is well-supported; re-verify before quoting externally.

### Law 18 - A page is not shipped, it is enrolled.
Doctrine Law 6 says measure or you are guessing. For content that means the write is not the end of the job. A page is done only when it is registered in the client's measurement sheet with its target query, publish date, and a one-sentence success hypothesis, so its performance can be watched and its decay caught. A page that ships without being enrolled is unmeasured by construction and violates Law 6.
**Test:** every finalized page has a row in the client decay/measurement sheet before it counts as done. No row, not shipped. Supported by `scripts/decay_monitor.py` and the client case log.
**Evidence:** research file 06.

### Law 19 - No date without a delta.
Refreshing decayed content is among the highest-ROI moves in SEO, but only when the content materially changes. Bumping a "last updated" date with no substantive change is signal-gaming: crawlers discount date-only changes, and presenting a page as fresh when it is not is a low-value tactic under Law 8. A date change is earned by a real content delta (new facts, new data, restructured answer, corrected information), never applied to fake freshness.
**Test:** any page whose visible or schema date advances must show a diff with material content change. A date-only diff fails. Supported by the `/refresh` protocol and `scripts/decay_monitor.py`.
**Evidence:** research file 06.

### Law 20 - No fabricated urgency, scarcity, or proof.
Conversion craft is encouraged; manufactured pressure is banned. No countdown that resets, no "only 2 spots left" that is not true, no invented review, no stock testimonial, no fake scarcity or urgency. This is both an FTC dark-patterns exposure and a trust-penalty surface, and it is the conversion-side twin of Law 16: proof and urgency must be real. Real risk-reversal (a genuine guarantee), real social proof (attributable, verifiable), and real, truthful urgency (a real seasonal deadline, a real booked-out calendar) are the tools instead.
**Test:** every urgency, scarcity, guarantee, and proof element on the page is truthful and verifiable against brand.yaml or a cited source. Any invented pressure or proof fails. Enforced by the conversion gate (G13) and the compliance spine.
**Evidence:** research file 03, plus FTC guidance on dark patterns.

---

These laws extend, never override, Laws 1-14. When a local page decision is not covered here, fall back to the parent doctrine. Constants and study figures were current 2026-07-20 PKT; re-verify quarterly.
