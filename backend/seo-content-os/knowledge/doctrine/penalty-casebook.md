# Penalty Casebook - Law 8 as cited evidence

This file turns doctrine **Law 8** (Google's policy is method-agnostic: it punishes scaled low-value content and manipulative intent, not AI provenance) and the compliance-spine hard lines from assertion into a sourced casebook. Every case below is a real, documented enforcement event with the Google policy it violated quoted from Google's own docs and the lesson for how we write. It is the evidence the writer and the client can see when either asks "why not just generate hundreds of pages."

**Reading rule.** These are cases to reason about, not tactics to copy in reverse. The point is not "avoid the specific thing site X did"; it is that Google penalizes an *intent and outcome* (pages that exist to manipulate rankings and add no value for users) regardless of production method. Our system is penalty-proof by construction because every page carries a differentiated first-party dataset (the SME Experience harvest), which is the exact property that separates safe scale from doorway abuse.

**Verification discipline (per CLAUDE.md: cite or do not claim).** Primary policy language is quoted from Google's own documentation, fetched 2026-07-20 PKT. Enforcement events are cited to news and analysis; where a specific figure is secondary and I could not re-verify it against a primary source this session, it is labeled. One widely shared article on this topic (digitalapplied's "AI pages decimated") was found to be future-dated and hypothetical on inspection and is deliberately excluded rather than cited as a real case.

---

## The policy spine (quoted primary text)

Three spam policies govern everything in this casebook. All three are on one page: https://developers.google.com/search/docs/essentials/spam-policies (fetched 2026-07-20 PKT).

**Scaled content abuse:**
> "Scaled content abuse is when many pages are generated for the primary purpose of manipulating search rankings and not helping users."

The same section explicitly lists as a violation "using generative AI tools or other similar tools to generate many pages without adding value for users," and Google's launch language states the abuse applies "no matter how it's created" (automation, human effort, or a combination). Provenance is not the test; value and intent are.

**Doorway abuse:**
> "Doorway abuse is when sites or pages are created to rank for specific, similar search queries. They lead users to intermediate pages that are not as useful as the final destination."

**Site reputation abuse:**
> "Site reputation abuse is a tactic where third-party content is published on a host site mainly because of that host's already-established ranking signals, which it has earned primarily from its first-party content."

These three map directly onto our hard lines: no scaled low-value content, no doorway pages (templated near-duplicate location pages), and no trading on borrowed authority.

---

## Case 1 - Site reputation abuse ("parasite SEO"), November 2024

**What happened.** In November 2024 Google began issuing manual actions under its new site reputation abuse policy against major publishers running low-relevance affiliate/review sections on their high-authority domains. Reporting names **Forbes, The Wall Street Journal, Time, and CNN** among the penalized. The commerce sub-brands collapsed in search: Forbes Advisor's top-three-position organic keywords fell from roughly **10,402 to 3,279**, reported as a drop of about **1.4 million** in estimated traffic; CNN Underscored and WSJ Buyside took comparable hits, with affected pages returning 404s or redirecting to homepages.

**The policy violated.** Site reputation abuse (quoted above). On **November 19, 2024** Google tightened the policy to clarify that first-party involvement does **not** exempt the content: per the update and Google's defense of it, first-party oversight does not protect content "primarily designed to exploit ranking signals." The practice targeted was spammers paying established domains to host content (payday-loan reviews on education sites, coupon pages on news sites) purely to borrow the host's ranking signals. The European Commission has since opened a Digital Markets Act inquiry after publisher complaints, and Google notes a German court ruled the policy "valid, reasonable, and applied consistently."

**The lesson for our writing.** Authority is not transferable and not borrowable. A page ranks on the value and trust *it* carries, not on the domain it sits under. For us this means: (1) never build a page whose plan is "publish on a strong domain to rank," and (2) every page must earn its own ranking with its own first-party Experience. It also sharpens Law 16 - even genuine editorial oversight does not launder a page whose primary purpose is ranking rather than helping the user. The intent test is the real test.

**Sources.**
- Primary policy update: https://developers.google.com/search/blog/2024/11/site-reputation-abuse
- https://www.searchenginejournal.com/google-defends-parasite-seo-crackdown-as-eu-opens-investigation/560822/
- https://www.seroundtable.com/google-site-reputation-abuse-policy-expanded-38438.html
- https://hellopartner.com/2024/11/22/forbes-cnn-wsj-affiliate-pages-collapse-as-google-rolls-out-site-reputation-abuse-update/ (specific Forbes Advisor keyword/traffic figures; secondary, partially paywalled - figures corroborated by the SEJ and seroundtable reporting)

---

## Case 2 - Scaled content abuse enforcement, March 2024 spam update

**What happened.** In the March 2024 core-plus-spam update Google introduced **scaled content abuse** as a named spam policy and enforced it with manual actions at scale. Independent tracking widely reported that roughly **1,446 sites** received a manual action out of about 79,000 monitored, and that many mass-AI-content and programmatic sites were deindexed. An Originality.ai analysis of the deindexed set found **100% had at least some AI-generated posts and about 50% were 90-100% AI-generated** - the correlation is with *unreviewed scaled publishing*, not with AI use per se (thin, human-spun content at scale is caught by the same policy).

**The policy violated.** Scaled content abuse (quoted above). Google's own framing is the load-bearing line: action applies "no matter how it's created," building on the older automatically-generated-content policy so that the target is large volumes of unoriginal, low-value pages, whether produced by automation, humans, or a mix.

**The lesson for our writing.** This is Law 8 vindicated by enforcement data, and the exact case for our anti-volume posture. Scale itself is not penalized; scale *without differentiated per-page value* is. Programmatic SEO at scale is fine only when every generated page is backed by a rich, differentiated dataset that creates real value; it crosses into abuse when the templated pages are thin and near-identical. Our reconciliation: the SME Experience harvest is that differentiated dataset, and the future `duplication_gate.py` plus the G3 doorway gate are how we would scale a legitimate multi-location client *safely* where Byword/Cuppa-style volume gets penalized. We market against volume (fewer, deeper, fact-backed pages), not toward it.

**Sources.**
- Primary launch post: https://developers.google.com/search/blog/2024/03/core-update-spam-policies
- Primary spam policy (definition, "no matter how it's created"): https://developers.google.com/search/docs/essentials/spam-policies
- https://blog.google/products-and-platforms/products/search/google-search-update-march-2024/
- Originality.ai AI-share analysis of deindexed sites: https://originality.ai/can-google-detect-penalize-ai-content (manual-action count and AI-share figures are secondary tracking data, not a Google-published number)

---

## Case 3 - Doorway abuse: templated per-location pages

**What happened.** The doorway policy is the direct risk of programmatic city/suburb page generation - the core use case of the bulk tools (Byword, Cuppa) and the classic failure mode of cheap local SEO. The documented pattern: a local/regional service business builds hundreds of near-identical per-suburb or per-city landing pages that differ only by a swapped place name, ranks them briefly, then loses them in a core or spam update because each page leads to a less useful intermediate destination than a genuine local page would. A regional HVAC company that built hundreds of per-suburb doorway pages is reported to have lost rankings across 80%+ of them after the March 2024 core update, with a roughly 63% organic-traffic drop in about 30 days.

**The policy violated.** Doorway abuse (quoted above): pages "created to rank for specific, similar search queries" that "lead users to intermediate pages that are not as useful as the final destination." The distinguishing factor is deceptive, ranking-driven user flow plus near-duplication, not the existence of location pages themselves - legitimate, genuinely-differentiated local landing pages are explicitly fine.

**The lesson for our writing.** This is why G3 (doorway and thin-content risk) is an auto-fail gate and why the location, service-area, and service-city playbooks demand unique, locally-specific value per page. The line is bright: a page that says nothing true and specific about *this* city that is not equally true of the next city over is a doorway page and must not be published. The fix is real per-city substance from the SME harvest (named neighborhoods, local failure patterns, local code/permit paths, city-specific pricing and reviews - the street-level marker in `experience-signals.md`), or consolidation into a single honest service-area page. If a business has nothing genuinely different to say about a given city, the correct action is to not build that page.

**Sources.**
- Primary policy: https://developers.google.com/search/docs/essentials/spam-policies (doorway abuse, quoted)
- https://securityboulevard.com/2025/11/the-programmatic-seo-paradox-why-your-fear-of-creating-thousands-of-pages-is-both-valid-and-obsolete/
- The specific regional-HVAC figures (80%+ of pages, 63% traffic drop in 30 days) are reported by bigredseo and the Security Boulevard write-up; **secondary, and the bigredseo source did not resolve for re-verification this session (HTTP 418)**. Treat the numbers as illustrative-reported, not independently confirmed. The doorway *mechanism* and policy are primary and confirmed.

---

## The reconciliation: safe scale vs doorway abuse

The three cases resolve to one line the writer should hold: **Google penalizes pages that exist to manipulate rankings and add no value for users, by any production method.** Programmatic scale is not the crime; thin near-duplication and borrowed authority are. Two sources state the reconciliation directly - programmatic pages are fine when each is backed by a rich, differentiated dataset that creates real value, and cross into doorway territory only when templated pages are thin, near-identical, and offer nothing useful.
- https://seomatic.ai/blog/programmatic-seo-best-practices
- https://guptadeepak.com/the-programmatic-seo-paradox-why-your-fear-of-creating-thousands-of-pages-is-both-valid-and-obsolete/

Our system is built on the safe side of that line by construction: the SME Experience harvest gives every page a first-party dataset no competitor holds, the G1/G3/G10/G12 gates enforce it, and the doctrine's hard lines forbid the practices these cases punish (no scaled low-value content, no doorway pages, no borrowed-authority plays, no automated link schemes or PBNs). That is what "penalty-proof because every line is written to Google's own rules" means in practice.

## How each case maps to our defenses

| Case | Policy violated | Our defense |
|---|---|---|
| 1. Parasite SEO (Nov 2024) | Site reputation abuse | Every page earns its own ranking with its own Experience; no borrowed-authority plays (doctrine hard lines) |
| 2. Scaled content abuse (Mar 2024) | Scaled content abuse | Differentiated first-party dataset per page (SME harvest); anti-volume posture; G1, future `duplication_gate.py` |
| 3. Doorway pages | Doorway abuse | G3 auto-fail; street-level Experience markers; consolidate-or-drop rule for thin city pages |

Enforcement events and figures reflect sources fetched 2026-07-20 PKT. Google's spam policies change; re-verify the quoted policy text and any figure before quoting externally, and re-check quarterly.
