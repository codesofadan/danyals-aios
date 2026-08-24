# Review Content Strategy - the review corpus as a first-class content and ranking asset

This system writes web pages. It does not manage the client's Google Business Profile, and it cannot post a review, respond inside the GBP dashboard, or move review velocity by itself. But review content is now too large a lever to touch only passively. Reviews are a **~20% category** in the local relevance equation (Whitespark 2026 Local Search Ranking Factors, per secondary coverage of the gated report), and the review *text* itself is a **measured relevance signal**, not just a trust badge. This file is the spec for how the writing system produces and surfaces review content: the on-page testimonial layer, the review-response copy, and the review-request copy, and exactly where the line sits between what this system writes and what only the operator can do.

**Doctrine binding.** This is Law 8 territory (optimize the reward function, not a proxy) and Law 16 territory (experience must be proven, not asserted). Review content is a real-value signal, not a trick. We surface the *real* review corpus, we write *honest* responses in the owner's voice, we make the *ask* easier and policy-compliant. We never fabricate a review, a reviewer, a rating, or a count, and we never help a client gate or incentivize reviews (Google policy, section 4). Fabrication here is the fastest path to a trust penalty and, for review markup, a structured-data-spam and FTC problem.

---

## 1. Why review text is a relevance signal, not just social proof

The strongest evidence class in local SEO is Sterling Sky's controlled tests. Their 2025 near-me study (8,186 businesses across 200 cities, correlation plus controlled tests) found two things this system must act on:

- **Reviews with written text rank stronger.** In their words, "Google relies on review content to understand business offerings." A review that says "they replaced the flashing on our roof in Pflugerville after the hail storm" tells Google three ranking-relevant facts (service, location, real event) that a bare 5-star rating with no text does not. Review text is a corpus Google reads to build relevance, the same way it reads the page body. Source: https://www.sterlingsky.ca/what-gets-you-ranking-for-near-me-2025/ (fetched 2026-07-20 PKT).
- **Recent review volume beats total.** A dental client posting 60+ reviews a month dominated; an 18-day pause dropped them. Review recency jumped from 20th (2023 survey) into Darren Shaw's personal top-5 for 2026 (Whitespark). Recency and velocity are the lever, and they are a lever **content cannot pull** - the system can only make the ask easier and more frequent. Sources: Sterling Sky near-me study; Whitespark 2026 via https://www.soci.ai/blog/local-memo-local-ranking-factors-of-2026-have-arrived/ (secondary, directional).

The reading: reviews are a content signal on the *GBP* surface (their text builds the entity's relevance), and reflecting the real review corpus on the *website* corroborates the entity across the single data stream Google and the AI engines now read (Near Media: the GBP, website, reviews, and social are read as one corpus, https://www.nearmedia.co/memo/). Two surfaces, one truth. The writer's job is to keep them saying the same thing.

**Evidence-class caution.** Sterling Sky is a controlled-test source (strong). Whitespark category weights are expert survey read from secondary coverage of a gated report (directional). Correlation is not causation for any ranking-factor figure. Re-verify before quoting a weight to a client.

---

## 2. The three review-content jobs this system does

| Job | Command / file | Moves which lever | Honesty boundary |
|---|---|---|---|
| **Surface real review themes on-page** | every page-type playbook, section 4 (proof) | On-page relevance (19%) + prominence + conversion | Real, permissioned testimonials only; themes match the live GBP |
| **Respond to reviews in the owner's voice** | `/write-review-responses` -> `playbooks/review-responses.md` | Consumer trust (89% expect responses); feeds review-text relevance indirectly | No PII, no fabrication, no keyword stuffing, owner voice |
| **Ask for reviews compliantly** | `/write-review-requests` -> `playbooks/review-requests.md` | Review recency/velocity (the ranking lever) - *indirectly*, by making the ask easy | No gating, no incentivizing, no review-station text that filters by sentiment |

What the system does **not** do: post reviews, respond inside the GBP dashboard, manufacture velocity, or run a review-gating funnel. Those are either operator actions or policy violations. Where a lever needs a GBP action the writer cannot take, the writer flags it for the operator (section 6).

---

## 3. Surfacing real review themes on-page (the corroboration layer)

Every page-type playbook already carries a proof section. Review content strengthens it when it is *specific and real*:

- **Pull the recurring themes from the client's actual GBP reviews** (via `brand.yaml.eeat.proof` or the SME interview): the exact outcomes customers praise ("same-day", "explained the broken spring", "cleaned up after"), the neighborhoods they name, the services they mention. These become the specifics that make a proof block un-copyable and locally credible, and they echo the real GBP reputation Google already reads.
- **Rating and count must be true and current** at publish time, matching the live GBP. A number that disagrees with the GBP is both a trust problem and a schema-eligibility problem (`nap-consistency.md`, `local-gbp-signals.md` s4).
- **Review / AggregateRating markup may only reflect reviews genuinely displayed on that page.** Self-serving `AggregateRating` on your own `LocalBusiness`/`Organization` is ineligible for star rich results; the failure mode to avoid is marking up reviews that are not on the page (`schema-library.md`).
- **Do not scrape-and-paste the whole GBP feed.** Reflect themes and a few real, permissioned testimonials. The goal is corroboration and specificity, not duplication.

BrightLocal's consumer research is the demand-side case: 41% of consumers now "always" read reviews (up from 29%), only 4% never do, and 83% use Google to read them (Local Consumer Review Survey, https://www.brightlocal.com/research/local-consumer-review-survey/, fetched 2026-07-20 PKT). The on-page review layer is read by both humans and engines.

---

## 4. The policy boundary: what Google forbids on review generation

The writer must know these rules cold, because the review-request copy this system writes is where they bite. From Google's prohibited and restricted practices for reviews (Google Business Profile / Maps user-contributed content policy) and the FTC's rule on fake and manipulated reviews:

- **No review gating.** Do not build a funnel that first asks "how was your experience?" and routes only the happy customers to Google while diverting the unhappy ones to a private form. Google's policy prohibits "discouraging or prohibiting negative reviews, or selectively soliciting positive reviews." Every review-request asset this system writes asks *all* customers, the same way, and links straight to the review surface. Source: Google's review policies, https://support.google.com/business/answer/7091 (verify live before quoting to a client).
- **No incentivizing.** Do not offer a discount, entry into a draw, cash, or any reward in exchange for a review. Google prohibits review incentives, and the FTC's final rule on fake and manipulated consumer reviews (effective 2024) makes incentivized reviews that do not disclose the incentive a civil-penalty exposure. The compliant ask offers nothing but the ease of asking. Source: FTC rule on fake reviews and testimonials, https://www.ftc.gov/news-events/news/press-releases (verify live).
- **No fake, no self-review, no employee review, no review-swapping.** Prohibited outright.
- **No sentiment filtering at a review station.** A kiosk or SMS flow that asks for a star rating first and only forwards 4-5 star raters to Google is gating. Do not write that copy.

The one compliant move: **make asking easy, ask everyone, ask soon after the job, and give a direct link.** That improves recency and volume honestly. It does not touch what customers say.

---

## 5. The recency lever, and why the system can only assist it

Recency and velocity are the review sub-lever that moves rankings (Sterling Sky), and they are **not a content lever**. The system cannot post a review. What it can do:

- Write review-request copy (email / SMS / in-person script) that lowers the friction of asking, so the operator asks more often and sooner (`review-requests.md`).
- Write a review landing / instructions asset that gets the customer to the right review surface in one tap.
- Flag the operator when review cadence is the binding constraint (section 6).

Everything past that is the operator's action and the customer's choice. The honest framing to a client: "We make asking effortless and compliant; we cannot and will not manufacture the reviews themselves."

---

## 6. Operator-flag set (levers content cannot move)

When these surface during a build, the writer names them for the operator rather than papering over them with copy:

- **Review velocity / recency is stalled.** If the GBP shows no recent reviews, no page copy fixes it. Flag: "Ranking lever here is review cadence, not the page. Recommend a standing review-request routine (see `/write-review-requests`)."
- **Rating or count on the page would not match the live GBP.** Do not publish a stale number. Flag for the operator to confirm the current figure.
- **The client wants a gating or incentive funnel.** Refuse and cite section 4. Offer the compliant alternative.
- **Reviews are the heavy vertical lever.** Reviews weigh more in some verticals than others; "the importance of reviews may be much greater with lawyers than with hospitals" (Local SEO Guide, https://www.localseoguide.com/guides/local-seo-ranking-factors/). For a law firm, flag review cadence as a top-tier priority; for a vertical where photos or proximity dominate, weight accordingly.

---

## 7. How this file connects to the rest of the system

- `local-gbp-signals.md` s4 owns the on-page review-surfacing rules and the schema-eligibility line; this file is the strategy layer above it.
- `playbooks/review-responses.md` is the deep spec for response copy.
- `playbooks/review-requests.md` is the deep spec for request copy, and carries the full policy-compliance rules from section 4.
- `playbooks/gbp-posts.md` is a *separate* engagement asset with **zero ranking value** (Sterling Sky posts study); it is not a review asset and must never be sold as a ranking lever.
- `scripts/review_response_lint.py` enforces the response-copy quality bar (no PII, no stuffing, no templated duplication, on-voice).
- The `sme-interviewer` agent captures the real review corpus (themes, recent volume, response gaps) so the writer works from truth, not invention.

**The one rule that governs all of it:** reviews are the moat because they are real and they are the customer's, and Google reads them as content. We surface the real ones, respond honestly, and ask compliantly. We never manufacture the signal. That is Law 8 and Law 16 in practice.
</content>
</invoke>
