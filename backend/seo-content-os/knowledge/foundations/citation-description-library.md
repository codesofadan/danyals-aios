# Citation Description Library: NAP-Locked Business Descriptions for Directories

A citation is any listing of the business on a third-party site: the Google Business Profile description, Yelp, BBB, Facebook, Apple Business Connect, industry directories, chambers, aggregators. Each carries a **business description** blurb. This file owns the **description blurbs** and the discipline that governs them: one canonical set of descriptions, at fixed lengths, every fact pulled verbatim from `brand.yaml`, rendered identically everywhere a description is placed. Its sibling `nap-consistency.md` owns the Name-Address-Phone identity string; this file owns the prose that travels with it.

The governing principle, from Near Media: AI answer engines (Gemini over Search and Maps, plus ChatGPT, Perplexity, Claude) read the **website, the GBP, the reviews, and the social profiles as a single data stream** and decide from that combined entity whether to surface the business (nearmedia.co, via `research/expansion-2026-07/02-local-seo-authorities.md`, fetched 2026-07-20; expert analysis, not a study). Citations gained renewed value specifically because AI Overviews pull from them. The whole point of a citation description is **consistency**: the same business, described the same way, with the same facts, across the whole data stream, so the entity is unambiguous. A description that contradicts the site or the GBP on hours, services, or founding year fragments the entity and weakens the corroboration.

The honest nuance, stated up front: **the GBP "from the business" description is not, on its own, a meaningful ranking factor** (widely reported; the description text does not move local rank the way category and proximity do). Its value here is **entity consistency for the single data stream**, plus conversion (a human reading the blurb), not keyword ranking. Do not sell a citation description as a ranking lever. It is a consistency and clarity asset.

---

## 1. Why descriptions are NAP-locked

Every fact in a description that also appears in the NAP or the schema must match it byte-for-byte, for the same reasons NAP itself is locked (`nap-consistency.md`):

- **Third-party matching is cruder than Google's core.** A description that says "serving Chandler since 1998" while the site says "since 1999", or names a service the site does not, gives directory dedup logic and answer engines conflicting entity data. The safe move is one canonical set of facts everywhere.
- **The description is part of the data stream.** An answer engine reading the GBP blurb, the Yelp blurb, and the site's about text wants them to agree. Agreement is the corroboration; drift is the doubt.
- **A description is a fact, not a creative brief.** Founding year, services, service area, credentials, and NAP inside a blurb are pulled verbatim from `brand.yaml`. The writer's job is fidelity, not embellishment. "Family-owned since 1998" is only allowed if `brand.yaml.client.founded_year` says 1998; if the year is blank, the claim is cut, never guessed (Law 16, Law 20).

The hard rule (inherited from `nap-consistency.md`):

> **PULL every factual element of a citation description verbatim from `brand.yaml`. Render the canonical descriptions identically across every citation. NEVER invent a founding year, a service, a credential, a review count, or a service area to fill a blurb. If a fact is missing or inconsistent, FLAG it to the operator and stop; do not guess.**

A description that inflates coverage ("serving all of Arizona") past `brand.yaml.service_areas`, or claims a credential not in `brand.yaml.eeat.credentials`, is a false entity claim and a trust exposure. Cut it or flag it.

---

## 2. The canonical description set (fixed lengths)

Directories accept different character limits. Rather than improvise per directory (which produces drift), the system generates **one canonical set** at fixed lengths, all built from the same facts, and each placement uses the longest one that fits. Same facts, same order, same phrasing; only the length varies.

| Variant | Length | Where it goes | Must contain |
|---|---|---|---|
| **Micro** | ~60 chars | Short-field directories, aggregator tags | Business type + primary city |
| **Short** | ~150 chars | GBP short contexts, compact directory fields | Business type + primary city + one differentiator |
| **Standard** | ~250-300 chars | Most directories, Yelp/BBB blurb | Above + services + years/credential + one honest proof |
| **Long** | ~700-750 chars | GBP "from the business" description (750-char cap), Facebook About, rich directories | Above + service-area list + a second real differentiator + a soft CTA |

Rules for the whole set:
- **Same facts in the same order across all four.** The long is the short expanded, not a different story. An engine reading two of them should see one consistent entity.
- **NAP inside a description matches `nap-consistency.md` exactly** (name string, city spelling, any phone rendered).
- **No keyword stuffing.** The GBP description is not a ranking field; padding it with "plumber Chandler plumber Chandler AZ" is both useless and a spam tell (Law 17: stuffing reduces citation). Write the business type and city once, naturally.
- **No fabricated proof.** Review counts, years, awards, and credentials are real, from `brand.yaml`, or absent.
- **One soft CTA** in the long variant only ("Call for a free estimate"), and only if it is honestly available.

---

## 3. The description-generation rule (from brand.yaml only)

The description is assembled from these `brand.yaml` fields and no invented content:

- `client.brand_name` (the name; must match `nap.name` / GBP)
- `schema.local_business_type` -> the business-type noun ("plumber", "roofing contractor")
- `nap.city` / `primary_city` -> the primary city
- `services` -> the service list (name the real ones; do not invent)
- `service_areas` -> the coverage list for the long variant (claim only these)
- `client.founded_year` -> "since [year]" only if present
- `eeat.credentials` -> a license/insured/bonded/certification mention only if real
- `eeat.proof` -> a review count or award only if real
- `eeat.differentiators` -> the one or two honest differentiators

If any field needed for a chosen variant is blank, the description drops that element (it does not guess). A missing founding year means no "since [year]" clause, not a guessed one.

---

## 4. Worked example (from a sample brand.yaml)

Using the `nap-consistency.md` worked-example client:

```yaml
client:
  brand_name: "Valley Plumbing Co"
  founded_year: "2009"
nap:
  name: "Valley Plumbing Co"
  city: "Chandler"
  state_region: "AZ"
schema:
  local_business_type: "Plumber"
services: ["drain cleaning", "water heater repair", "leak detection", "repiping"]
service_areas: ["Chandler", "Gilbert", "Mesa"]
eeat:
  credentials: ["Licensed AZ ROC #123456", "insured and bonded"]
  proof: ["4.8 stars, 210+ Google reviews"]
  differentiators: ["flat upfront pricing", "same-day service"]
```

**Micro (~60 chars):**
> Licensed plumber serving Chandler, AZ.

**Short (~150 chars):**
> Valley Plumbing Co is a licensed Chandler, AZ plumber offering same-day service and flat upfront pricing.

**Standard (~280 chars):**
> Valley Plumbing Co is a licensed, insured Chandler, AZ plumber serving the area since 2009. We handle drain cleaning, water heater repair, leak detection, and repiping with flat upfront pricing and same-day service. Rated 4.8 stars across 210+ Google reviews.

**Long (~730 chars):**
> Valley Plumbing Co is a licensed and insured plumber based in Chandler, AZ, serving Chandler, Gilbert, and Mesa since 2009. We handle drain cleaning, water heater repair, leak detection, and repiping for local homeowners, with flat upfront pricing quoted before any work starts and same-day service on most calls. Our team is licensed under AZ ROC #123456 and fully insured and bonded, and we are rated 4.8 stars across more than 210 Google reviews. Whether it is a slow drain, a failed water heater, or a hidden leak, we give you the flat price before we begin, not a starting estimate. Call for a free estimate.

Notes on the set:
- Every fact (2009, the four services, ROC #123456, the three service areas, 4.8/210+) is verbatim from `brand.yaml`. Nothing is invented.
- The name string "Valley Plumbing Co" is byte-identical to `nap.name` in all variants.
- Coverage is exactly the three real `service_areas`; the long variant does not inflate to "all of Arizona".
- The business type "plumber" and city "Chandler, AZ" appear naturally, once or twice, never stuffed.
- The soft CTA appears only in the long variant, and only because same-day free estimates are a real offer.

If `founded_year` were blank, every "since 2009" clause would drop, not become a guess.

---

## 5. The rules

1. **One canonical description set per business**, at four fixed lengths, all built from the same `brand.yaml` facts in the same order.
2. **Every factual element pulled verbatim from `brand.yaml`.** Founding year, services, credentials, review counts, service areas: real or absent, never guessed.
3. **NAP inside any description is byte-identical to `nap-consistency.md`.** Same name string, same city spelling.
4. **Coverage claims match `brand.yaml.service_areas` exactly.** No inflation to regions the business does not serve.
5. **No keyword stuffing.** Business type and city once, naturally. The description is not a ranking field; stuffing is useless and a spam tell.
6. **No fabricated proof.** No invented review count, award, year, or credential.
7. **Consistency is the objective**, for the AI single-data-stream and for the human reader, not keyword ranking. Do not sell a description as a ranking lever.
8. **Flag, do not guess.** Any missing or inconsistent fact is surfaced to the operator; the writer never resolves it by inventing.

---

## 6. Validation

Run `scripts/nap_checker.py` (extended per the 2026-07-20 research recommendation to validate a citation-description asset against the canonical NAP + category set, not just page NAP) before the description set ships:

1. The name string in every variant matches `nap.name` exactly.
2. City/state spelling matches `nap.city` / `nap.state_region`.
3. Every service named is in `brand.yaml.services`.
4. Every area named (long variant) is in `brand.yaml.service_areas`; none added.
5. Any "since [year]" matches `client.founded_year` (and is dropped if blank).
6. Any credential/review-count matches `brand.yaml.eeat`; none invented.
7. No exact business-type-plus-city phrase repeated past natural use (stuffing check).

Any failure is fixed to match the canonical facts, or flagged to the operator if `brand.yaml` itself looks wrong. The writer never resolves a conflict by guessing.

---

## Source read this session

- Near Media, the single-data-stream thesis (AI reads website + GBP + reviews + social as one entity; citations renewed for AI Overviews): https://www.nearmedia.co/memo/ (via `research/expansion-2026-07/02-local-seo-authorities.md`, fetched 2026-07-20; expert analysis, not a measured study).
- BrightLocal, "What is NAP?" and consistency-as-trust framing (via `nap-consistency.md`): https://www.brightlocal.com/learn/what-is-nap/. The GBP description's minimal ranking role is widely reported practitioner consensus, not a Google-published statement; treat as directional and re-verify before quoting to a client.

Evidence-class reminder: the single-data-stream thesis is expert opinion (high authority, not a study); the "GBP description is not a ranking factor" point is practitioner consensus. The binding discipline here does not depend on either being a ranking lever - it rests on entity consistency and no-fabrication, which hold regardless.
