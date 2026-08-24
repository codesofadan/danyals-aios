# NAP Consistency

NAP is the business's **Name, Address, Phone number**. It is the identity string Google and every directory use to decide whether two mentions of a business are the same entity. For a local service business, NAP consistency is a trust and prominence signal: many listings carrying identical business information tell Google that what it knows about the business is correct, and rankings can suffer when the data conflicts and Google can no longer trust it (BrightLocal, "What is NAP"). Citation signals of this kind are commonly estimated at around 10-11% of local ranking weight in practitioner surveys; treat that as directional, not a Google-published number.

This file owns **NAP exactness** for the writing system: the one canonical string, how it is rendered identically everywhere, and the writer's hard rule for handling it. The silo topology and internal-link mechanics live in `cluster-graph-protocol.md` and `internal-linking.md`. This file is about getting the identity string right, byte for byte, on every page and inside every schema block.

---

## What NAP (and NAP+W) actually is

- **N - Name:** the exact legal/brand business name as it appears on the Google Business Profile (GBP). "Valley Plumbing Co", not "Valley Plumbing", not "Valley Plumbing Company LLC" if the GBP says "Valley Plumbing Co".
- **A - Address:** street line (including suite/unit), city, state/region, postal code, country, exactly as on GBP.
- **P - Phone:** the primary business number, one canonical human-readable format, matching GBP.

**Extended NAP+W** adds:
- **W - Website:** the canonical primary URL (one host, one protocol: `https://`, `www` or not, pick one and never drift).
- **Hours:** opening hours, rendered consistently on-site and in schema.

All of these live in the client's `brand.yaml` and are pulled verbatim. The writer never authors them.

---

## Why exactness matters (and the honest nuance)

Google matches entities on consistency. When the same business appears on its website, its GBP, and dozens of third-party citations and directories with the same NAP, that agreement is corroborating evidence that the entity and its data are real. When the data drifts, the agreement weakens, and in the worst case Google fragments one business into what looks like several partial entities, diluting the local relevance and prominence that should have concentrated on one.

Formatting drift is the common way this happens:
- "St" vs "Street" vs "St."
- "Ste 200" vs "Suite 200" vs "#200" vs "Unit 200"
- "(480) 555-0100" vs "480-555-0100" vs "480.555.0100" vs "+14805550100"
- "Valley Plumbing Co" vs "Valley Plumbing" vs "Valley Plumbing Co."
- "https://valleyplumbing.com" vs "http://www.valleyplumbing.com"

**The honest nuance:** Google itself is often sophisticated enough to normalize minor variations. BrightLocal notes Google will usually understand that "St" and "Street", or "No." and "#", refer to the same thing, and advises businesses not to obsess over every abbreviation. So byte-level identity is not a hard algorithmic requirement in every case.

**But this system enforces byte-level identity anyway, for four reasons that all hold even if Google forgives some drift:**

1. **Zero risk beats "usually fine".** You never have to guess which variation Google will normalize and which it won't. Exact-match removes the judgment call entirely.
2. **Third-party matching is less forgiving than Google's own core.** Citation aggregators, data providers, and directory dedup logic are cruder; a variation Google shrugs off can still split a listing downstream.
3. **Schema is machine-read.** JSON-LD `address` and `telephone` values are parsed literally by consumers that do less normalization than Google Search. Exactness here is not cosmetic.
4. **A writing system needs a mechanical rule, not a judgment call.** "Render the one canonical string identically" is enforceable by a script and by a writer under deadline. "Use your judgment about which abbreviations Google tolerates" is not, and it invites exactly the drift we are trying to prevent.

So: exactness is the operating discipline because it is the cheapest way to be certain, not because every deviation is a proven penalty.

---

## The rules

1. **ONE canonical NAP string, defined in `brand.yaml`.** The fields `nap.name`, `nap.phone`, `nap.street`, `nap.city`, `nap.state_region`, `nap.postal_code`, `nap.country` (plus `client.legal_name`, `client.primary_url`, `schema.opening_hours`) are the single source of truth. There is exactly one correct rendering of each.

2. **Rendered identically everywhere.** Footer, contact/about page, every location page, the LocalBusiness schema on every page. Same name string, same address punctuation, same suite format, same phone format. If it appears in ten places, it is the same ten times, character for character.

3. **Phone in two forms, both derived from the one canonical number:**
   - **Human-readable** for on-page display, matching GBP, e.g. `(480) 555-0100`.
   - **E.164** for schema `telephone` and `tel:` links, e.g. `+14805550100`. The `tel:` href is `tel:+14805550100`; the visible text is the human format.
   Both encode the identical digits; only the presentation differs, and the presentation is fixed.

4. **Suite/unit formatting fixed once.** Pick the GBP rendering ("Ste 200", "Suite 200", "#200", or "Unit B") and use it everywhere, including inside schema `streetAddress`. Do not vary it by page or by context.

5. **Exact legal/brand name matching GBP.** The `name` rendered on-site and in `LocalBusiness.name` must match the GBP name exactly. If `client.legal_name` and the display `brand_name` differ, the writer uses the one that matches GBP for NAP purposes and flags the discrepancy to the operator; it is never resolved by guessing.

6. **Website and hours consistent too.** One canonical host+protocol for the primary URL; opening hours rendered the same on-page and in schema `openingHours`/`openingHoursSpecification`.

---

## The writer's hard rule

> **PULL NAP verbatim from `brand.yaml`. Render it identically on every page and inside every schema block. NEVER alter, reformat, abbreviate, expand, "clean up", or "improve" it. If any NAP fact is missing, internally inconsistent, or appears to conflict with the client's GBP, FLAG it to the operator and stop; do not guess, invent, or normalize it yourself.**

This is a doctrine-grade rule for a writing system: NAP is a fact, and fabricating or reformatting a local fact is the fastest path to a trust penalty (CLAUDE.md hard rules; doctrine Law 8's "value and trust over proxies"). The writer's job is fidelity, not editing. A writer who "tidies" `Ste 200` into `Suite 200` on one page has introduced exactly the drift this file exists to prevent.

---

## Multi-location handling

- **One canonical NAP per real physical location.** A business with three real offices has three canonical NAP strings, each byte-exact to that location's own GBP listing.
- **One location page per real physical address.** Each physical location gets its own page carrying its own canonical NAP and its own `LocalBusiness` schema with that location's address and phone.
- **No fake addresses. No virtual offices. No shared mailboxes dressed as branches.** Creating a location page for an address the business does not physically operate from is a doctrine and Google trust hard line, and it is the doorway/location-fabrication pattern that gets local sites penalized. Service-area coverage (cities you serve but are not located in) is handled by **service-area pages**, which do NOT carry a fake local address; they describe coverage from the real base. See the service-area and location playbooks for the distinction.
- **Service-area businesses** (that hide their address on GBP because they travel to customers) render Name and Phone consistently and follow the GBP address-visibility setting; do not publish a street address the GBP hides.

---

## Worked example: the ONE canonical NAP, rendered three ways

**Canonical values in `clients/valley-plumbing/brand.yaml`:**

```yaml
client:
  legal_name: "Valley Plumbing Co"
  brand_name: "Valley Plumbing Co"
  primary_url: "https://valleyplumbing.com"
nap:
  name: "Valley Plumbing Co"
  phone: "(480) 555-0100"          # human-readable, matches GBP
  street: "1420 W Chandler Blvd, Ste 200"
  city: "Chandler"
  state_region: "AZ"
  postal_code: "85224"
  country: "US"
schema:
  local_business_type: "Plumber"
  opening_hours: ["Mo-Fr 07:00-18:00", "Sa 08:00-14:00"]
```

**1. Rendered in the site footer (every page):**

```
Valley Plumbing Co
1420 W Chandler Blvd, Ste 200, Chandler, AZ 85224
Call: (480) 555-0100
```

**2. Rendered on the Chandler location page (same strings, byte for byte):**

```
Valley Plumbing Co - Chandler
1420 W Chandler Blvd, Ste 200
Chandler, AZ 85224
(480) 555-0100    <a href="tel:+14805550100"> on the linked phone
```

Note: the display suffix "- Chandler" is a page label, not part of the NAP name. The `LocalBusiness.name` and the footer name string remain exactly "Valley Plumbing Co".

**3. Rendered in JSON-LD (`schema.json`, identical address + phone):**

```json
{
  "@context": "https://schema.org",
  "@type": "Plumber",
  "name": "Valley Plumbing Co",
  "url": "https://valleyplumbing.com",
  "telephone": "+14805550100",
  "address": {
    "@type": "PostalAddress",
    "streetAddress": "1420 W Chandler Blvd, Ste 200",
    "addressLocality": "Chandler",
    "addressRegion": "AZ",
    "postalCode": "85224",
    "addressCountry": "US"
  },
  "openingHoursSpecification": [
    { "@type": "OpeningHoursSpecification", "dayOfWeek": ["Monday","Tuesday","Wednesday","Thursday","Friday"], "opens": "07:00", "closes": "18:00" },
    { "@type": "OpeningHoursSpecification", "dayOfWeek": "Saturday", "opens": "08:00", "closes": "14:00" }
  ]
}
```

The `name` string, the `streetAddress` (including `Ste 200`), the locality, region, and postal code are character-identical to the footer and the location page. Only the phone changes presentation: `(480) 555-0100` on display, `+14805550100` in `telephone` and the `tel:` href, same digits.

---

## NAP mismatch audit checklist

Run before finalize (feeds the compliance report) and any time a client site is reviewed:

1. **Name:** does the on-page name string match `nap.name` and the GBP name exactly, including "Co", "LLC", "&", punctuation? (No descriptor added or dropped.)
2. **Address:** street line, suite/unit format, city, state/region, postal code identical to `brand.yaml` on the footer, contact/about page, and every location page?
3. **Suite/unit:** one format everywhere ("Ste 200" not sometimes "Suite 200" / "#200")?
4. **Phone display:** one human format everywhere, matching GBP?
5. **Phone machine:** schema `telephone` and every `tel:` link in E.164, same digits as the display number?
6. **Schema vs page:** does JSON-LD `name`, `address`, `telephone`, `openingHours` match the visible on-page NAP byte for byte?
7. **Website:** one canonical host+protocol used everywhere (no `http`/`https` or `www`/non-`www` drift)?
8. **Hours:** on-page hours match schema hours match GBP?
9. **Multi-location:** one canonical NAP per real address, one location page per real address, zero fabricated/virtual addresses?
10. **Cross-check GBP:** where the client shared GBP access, does the canonical `brand.yaml` NAP match the live GBP listing? Any drift is flagged to the operator, never silently corrected in copy.

Any mismatch is a fail: fix the render to match the one canonical string, or if `brand.yaml` itself looks wrong, flag it to the operator. The writer never resolves a NAP conflict by guessing.

---

Source read this session: BrightLocal, "What is NAP?" (https://www.brightlocal.com/learn/what-is-nap/) for the consistency-as-trust-signal claim and the honest nuance that Google normalizes minor abbreviation variations. The ~10-11% citation-weight figure is a widely-cited practitioner estimate, directional only, not a Google-published ranking number.
