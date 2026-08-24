# Hooks and Titles

Opening lines and headlines for local pages: the H1, the hero copy under it, the meta title, and the meta description. These are the highest-leverage lines on the page. The meta title and description win the click in the SERP; the H1 and hero confirm the visitor is in the right place and keep them from bouncing back.

Adapted from packaging craft (title and hook patterns) into local-SEO surfaces. Same principle throughout: **package for the click, deliver on the promise.** A title that over-promises and the page under-delivers costs you twice, because bounce-back to the SERP is a signal search engines read. Curiosity plus a concrete outcome, then a page that pays it off.

None of this is clickbait engineering or detector-evasion. It is writing the true, specific version of the promise in the fewest words.

---

## The four surfaces and what each does

| Surface | Job | Length target |
|---|---|---|
| Meta title | Win the click in the SERP; carry the primary keyword + city | ~50 to 60 chars, but fit to pixel width, not a hard count |
| Meta description | Earn the click with a specific promise; not a ranking factor but a CTR factor | ~140 to 160 chars, pixel-fit |
| H1 | Confirm the match the instant the page loads; one per page | 3 to 10 words |
| Hero copy | The 1 to 2 lines under the H1 that stop the bounce and pay off the promise | 1 to 3 short sentences |

Titles and H1s do NOT have to be identical. The title is written for the SERP (keyword + city + a curiosity or outcome hook). The H1 is written for the visitor who already clicked (confirm + reassure, less keyword-stuffed). Aligned, not cloned.

---

## Meta title patterns (local)

Rules:
- Lead with the service + city, or the outcome, depending on intent. For "[service] [city]" money queries, the keyword leads.
- One idea per title. No stacking two services.
- Specific beats vague: a number, a price, a guarantee, a response time.
- Match how people actually search, not formal grammar.
- Avoid scam-radar words ("cheapest," "#1," "best" unqualified) unless you can back them.
- Never keyword-stuff ("Plumber Austin | Plumbing Austin | Austin Plumbing Services"). That fails the over-optimization gate.

Pattern bank:
- "[Service] in [City] | [Brand]" - the clean default for a money page.
- "[Service] in [City] - [Proof or Outcome]" - e.g. "Emergency Plumber in Round Rock - On-Site in 90 Min"
- "[Outcome] [City] Homeowners Trust | [Brand]" - e.g. "Roof Repair Georgetown Homeowners Trust Since 2009"
- "[Service] [City] | [Guarantee]" - e.g. "AC Repair Austin | Fixed Right or the Trip Is Free"
- "How Much Does [Service] Cost in [City]? [Year]" - for the pricing-intent page.

## Meta description patterns (local)

The description is a promise plus a reason to click plus a soft nudge. Include the city and one concrete specific. End with the action.

- "Slab leak, no hot water, or a clogged main in [City]? We answer 24/7 and most calls are on-site within 90 minutes. Upfront pricing, no trip fee. Call [phone]."
- "[Brand] has replaced 6,000+ roofs across [City] since 2009. Free 40-minute inspection with photos of every problem area. Financing available. Book online in 60 seconds."
- "Straight pricing on [service] in [City]: most repairs run $[X] to $[Y]. Licensed, and the person who quotes it is on the crew that does it. Get a same-day estimate."

Never write a description that could belong to any competitor. If you can swap the brand name and city and it still reads fine, it is too generic. Put a real specific in it.

---

## H1 patterns (local)

The H1 confirms the click and carries the primary entity (service + city) once, naturally. It is not the title tag repeated. Keep it human.

- "[Service] in [City], [State]" - clean, direct, the safe default. "Water Heater Repair in Cedar Park, TX"
- The outcome H1: "Your AC Fixed Today in [City]"
- The reassurance H1: "The [City] [Trade] That Actually Shows Up"
- The proof H1: "[City]'s [Trade] Since [Year]" - only if the year is real.

One H1 per page. It contains the primary keyword phrase once, in a way a person would actually say it, never stuffed.

---

## Hero copy: the three hook archetypes

The hero is the 1 to 3 lines under the H1 that stop the bounce. Pick the archetype by page intent. Pay off the exact promise the title made.

- **Problem / pain hook.** Name the pain the visitor already feels. Best for emergency and service pages where the visitor has a sharp, present problem.
  - "Water coming up through the tile at 2am is not a wait-till-morning problem. Call and a real person picks up. We are on the truck within 90 minutes, and the after-hours callout is a flat $95."
- **Result-first hook.** State the outcome before the how. Best for pages where the visitor is comparing options (replacement pages, quote pages).
  - "Most Round Rock roof replacements we do are permitted, torn off, and re-shingled in two days. Here is exactly how it works, and what it costs."
- **Proof / operator hook.** Lead with a first-hand credential only this business has. Best for about pages and location pages where trust is the job.
  - "We have been on 6,000 Austin roofs since 2004. That is not a slogan. It is 15 years times about 400 roofs a year, and it is why we can spot storm damage an adjuster misses."

Draft two or three hero options across archetypes, then tune to the client voice. The result-first archetype is strong for money pages; the problem hook is strong for emergency pages; the proof hook is strong for about and location pages.

---

## The first-line discipline (shared with sentence-rhythm.md)

Whichever surface, the first line does not open with AI scaffolding: no "When it comes to," no "At [Brand], we," no "Are you looking for," no "In today's." The first line of hero copy is 5 to 12 words and lands the promise. The reader decides whether to keep reading in those words.

Bad hero open: "When it comes to finding a reliable plumber in Round Rock that you can trust for all your home's plumbing needs, look no further than [Brand]."

Good hero open: "Round Rock plumber. Real person answers. On-site in 90 minutes."

---

## The compliance line

- Do not promise what the page does not pay off. Title says "90 minutes," the page and the business must actually do 90 minutes.
- Do not use a superlative you cannot back ("the best," "#1," "cheapest") unless it is literally true and supportable; this crosses into the compliance-spine and over-optimization gates.
- Every specific in a title or description (price, response time, year, review count) is a real fact from `brand.yaml` or the SME interview, never invented. A fabricated title specific fails the source gate the same as a fabricated body claim.

---

## How to use this file

The write commands generate 2 to 3 title + description options and 2 to 3 hero options per page, each checked against these patterns, the vocabulary blocklist, and the client `brand.yaml` voice block. The meta quality gate and voice-fidelity gate in `knowledge/quality-gates/gates.md` verify the title, description, H1, and hero before finalize. Lock the title and H1 alongside the page outline, not as an afterthought at the end.
