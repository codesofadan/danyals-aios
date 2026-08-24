# Topical Map - Sunbridge Dental (sample-dental)

Built by /build-topical-map (topical-map-architect) per knowledge/foundations/topical-map-protocol.md.
DEMONSTRATION map for a multi-location YMYL client, built in `lite` mode. All specifics trace to
clients/sample-dental/brand.yaml + sme-answers.md; [SAMPLE] where a value stands in for a real one.

Rules enforced: every node traces to a real capability/demand; the grid is the ceiling, not this list;
every node defaults index-only and is promoted only on real first-party evidence; no coverage %, no score.

---

## Entity anchor (from brand.yaml `entity`)

- **Map mode:** lite  (single-brand, 3 offices, ~10 candidate pages - well under the 25-page full-mode threshold)
- **Central entity:** Sunbridge Dental dental implants (brand + hero service; 6,000+ implants placed since 2009)
- **Source context:** three-office LA-area implant-focused dental group; revenue from implant, restorative, and cosmetic treatment
- **Central search intent:** LOCAL-TRAN - a patient seeking implant or general dental care at a nearby office
- **Primary GBP category (head-term anchor):** Dentist
- **Real footprint (from brand.yaml):** services = 8, service_areas = 7, locations = 3
- **Grid ceiling:** LITE mode - not computed as a formal artifact (the map below is the evidence-gated subset)
- **Date built (PKT):** 2026-07-22

Multi-location note: this brand is one entity with three location sub-entities (Santa Monica, Pasadena, Glendale offices). Each real staffed office earns a location page (its own NAP + GBP is the un-copyable evidence, distinct from a service-area doorway page). The hero service (implants) is a brand-wide service hub, not a per-city page (per sme-answers.md: "No single-city claim on this page").

---

## Node table

Status: `index-only` = acknowledged coverage, linked but no dedicated URL yet. `page` = promoted, evidence-backed, gets built.
Section: `core` = converts, built first, link priority. `outer` = builds trust, funds the core.

| node_id | entity / attribute | section | page_type | target_query | intent | geography (user_cluster) | status | priority | command |
|---|---|---|---|---|---|---|---|---|---|
| homepage | Sunbridge Dental (implants anchor) | core | homepage | sunbridge dental | NAV / LOCAL-TRAN | brand-wide | page | 1 | /write-homepage |
| dental-implants-hub | biz + dental implants | core | service | dental implants los angeles | LOCAL-TRAN | brand-wide (3 offices) | page | 2 | /write-service-page |
| location-santa-monica | biz + Santa Monica office | core | location | dentist santa monica | LOCAL-TRAN | Santa Monica (west) | page | 3 | /write-location-page |
| location-pasadena | biz + Pasadena office | core | location | dentist pasadena | LOCAL-TRAN | Pasadena (east) | page | 4 | /write-location-page |
| location-glendale | biz + Glendale office | core | location | dentist glendale | LOCAL-TRAN | Glendale (east: Glendale/Burbank/Eagle Rock) | page | 5 | /write-location-page |
| about-team | biz + in-house implant team | outer | about-team | sunbridge dental periodontist prosthodontist | LOCAL-COMM / NAV | brand-wide | page | 6 | /write-about-page |
| invisalign-hub | biz + Invisalign | core | service | invisalign los angeles | LOCAL-COMM | brand-wide | index-only | - | /write-service-page |
| cosmetic-dentistry-hub | biz + cosmetic dentistry | core | service | cosmetic dentist los angeles | LOCAL-COMM | brand-wide | index-only | - | /write-service-page |
| emergency-dentistry-hub | biz + emergency dentistry | core | service | emergency dentist los angeles | EMERGENCY | brand-wide | index-only | - | /write-service-page |
| dental-implants-brentwood | biz + implants Brentwood | core | service-in-city | dental implants brentwood | LOCAL-TRAN | Brentwood (no office) | index-only | - | /write-service-city-page |

---

## Per-node detail

### homepage

- **Section:** core
- **Page type + command:** homepage - `/write-homepage`
- **Target query:** sunbridge dental (+ "dental implants los angeles" as the entity's primary service query)
- **Query network:** sunbridge dental, sunbridge dental reviews, dental implants los angeles, implant dentist near me
- **Intent:** NAV / LOCAL-TRAN
- **Geography / user cluster:** brand-wide (anchors all three offices)
- **Demand trace:** brand_terms + GBP primary category "Dentist" + the implants head query
- **Parents:** root
- **Evidence (the promotion gate):** three staffed LA-area offices (Santa Monica, Pasadena, Glendale); 6,000+ implants placed since 2009; in-house board-certified periodontist and prosthodontist; CBCT and guided surgery at all three locations
- **Info-gain thesis:** one group where the periodontist who places the implant and the prosthodontist who restores it are the same in-house team, across three offices - not a referral chain
- **Status:** page
- **Priority:** 1
- **Build state:** planned

### dental-implants-hub

- **Section:** core
- **Page type + command:** service (brand-wide) - `/write-service-page`
- **Target query:** dental implants los angeles
- **Query network:** dental implants cost los angeles, all-on-4 los angeles, single tooth implant, implant dentist near me, how long do dental implants take
- **Intent:** LOCAL-TRAN + LOCAL-COMM (cost)
- **Geography / user cluster:** brand-wide (delivered across all three offices; no single-city claim)
- **Demand trace:** GBP services "Dental implants" + autocomplete on "dental implants los angeles" + competitor implant pages (competitive_set)
- **Parents:** homepage
- **Contextual bridges:** about-team (shared attribute: the in-house perio + prosthodontist team) - link direction outer_to_core
- **Evidence (the promotion gate):** 6,000+ implants placed since 2009; in-house board-certified periodontist (Dr. Marquez) and prosthodontist (Dr. Chen) place and restore under one record; CBCT-planned guided surgery; All-on-4 with a same-day temporary fixed set of teeth; honest cost-driver breakdown (extraction, graft, sedation, crown material) quoted after the CBCT consult
- **Info-gain thesis:** the periodontist who surgically places and the prosthodontist who restores are one in-house team on one record - the competitors in the SERP refer the restoration out
- **Status:** page
- **Priority:** 2
- **Build state:** planned

### location-santa-monica

- **Section:** core
- **Page type + command:** location - `/write-location-page`
- **Target query:** dentist santa monica
- **Query network:** dentist santa monica, dental implants santa monica, emergency dentist santa monica
- **Intent:** LOCAL-TRAN
- **Geography / user cluster:** Santa Monica (west-side cluster, incl. West LA / Brentwood proximity)
- **Demand trace:** real staffed office + GBP for this location + "dentist santa monica" demand
- **Parents:** homepage; dental-implants-hub (service axis)
- **Evidence (the promotion gate):** real staffed office at 1234 Wilshire Blvd, Suite 300, Santa Monica; own GBP and phone (310) 555-0140; CBCT guided-surgery on site; a dated geotagged implant case photo (Santa Monica, 2026-05)
- **Info-gain thesis:** the Wilshire-corridor office with in-house CBCT guided surgery, the west-side base for implant cases coordinated across the three-office team
- **Status:** page
- **Priority:** 3
- **Build state:** planned

### location-pasadena

- **Section:** core
- **Page type + command:** location - `/write-location-page`
- **Target query:** dentist pasadena
- **Query network:** dentist pasadena, dental implants pasadena, invisalign pasadena
- **Intent:** LOCAL-TRAN
- **Geography / user cluster:** Pasadena (east-side)
- **Demand trace:** real staffed office + GBP for this location + "dentist pasadena" demand
- **Parents:** homepage; dental-implants-hub
- **Evidence (the promotion gate):** real staffed office at 45 South Lake Ave, Suite 210, Pasadena; own phone (626) 555-0177; full-arch surgical visits coordinated with the periodontist's cross-office schedule
- **Info-gain thesis:** the South Lake Avenue office; Pasadena patients start their implant consult here and the surgical visit is scheduled with the group's periodontist
- **Status:** page
- **Priority:** 4
- **Build state:** planned

### location-glendale

- **Section:** core
- **Page type + command:** location - `/write-location-page`
- **Target query:** dentist glendale
- **Query network:** dentist glendale, dental implants glendale, emergency dentist glendale
- **Intent:** LOCAL-TRAN
- **Geography / user cluster:** Glendale (east cluster: Glendale, Burbank, Eagle Rock)
- **Demand trace:** real staffed office + GBP for this location + "dentist glendale" demand
- **Parents:** homepage; dental-implants-hub
- **Evidence (the promotion gate):** real staffed office at 500 North Brand Blvd, Suite 120, Glendale; own phone (818) 555-0193; serves the Glendale / Burbank / Eagle Rock cluster
- **Info-gain thesis:** the North Brand Boulevard office, the group's east-side base for Glendale, Burbank, and Eagle Rock patients
- **Status:** page
- **Priority:** 5
- **Build state:** planned

### about-team

- **Section:** outer
- **Page type + command:** about-team - `/write-about-page`
- **Target query:** sunbridge dental periodontist prosthodontist
- **Query network:** sunbridge dental team, dr marquez periodontist, dr chen prosthodontist, sunbridge dental reviews
- **Intent:** LOCAL-COMM / NAV
- **Geography / user cluster:** brand-wide
- **Demand trace:** brand_terms + provider-name queries; the E-E-A-T surface for a YMYL practice
- **Parents:** homepage
- **Contextual bridges:** dental-implants-hub (shared attribute: the in-house team credential) - link direction outer_to_core
- **Evidence (the promotion gate):** Dr. Elena Marquez, DDS, board-certified periodontist (CA license on file); Dr. David Chen, DMD, prosthodontist (CA license on file); in-house team operating together since 2009; 6,000+ implants placed. No patient testimonials or before/after used (zero HIPAA consents on file - MED-4)
- **Info-gain thesis:** the two named board-certified specialists who form the single in-house place-and-restore implant team - the credential story competitors cannot copy, told without a single patient photo
- **Status:** page
- **Priority:** 6
- **Build state:** planned

### invisalign-hub

- **Section:** core
- **Page type + command:** service (brand-wide) - `/write-service-page`
- **Target query:** invisalign los angeles
- **Intent:** LOCAL-COMM
- **Geography / user cluster:** brand-wide
- **Demand trace:** GBP services "Invisalign" + real service in brand.yaml (demand is real)
- **Evidence (the promotion gate):** <none yet - Invisalign is a real service but no case volume, provider specialization, or differentiating specific is documented in the SME material>
- **Info-gain thesis:** <tbd - needs the Invisalign differentiator: case count, provider, or a workflow the competitors lack>
- **Status:** index-only
- **Priority:** -
- **Build state:** planned
- **Held because:** real demand + real service, but no first-party specific to make the page un-copyable. SME homework.

### cosmetic-dentistry-hub

- **Section:** core
- **Page type + command:** service (brand-wide) - `/write-service-page`
- **Target query:** cosmetic dentist los angeles
- **Intent:** LOCAL-COMM
- **Geography / user cluster:** brand-wide
- **Demand trace:** GBP secondary category "Cosmetic dentist" + real service (veneers, whitening, bonding)
- **Evidence (the promotion gate):** <none yet - no cosmetic case proof documented, and MED-4 forbids patient before/after without HIPAA consent (zero on file)>
- **Info-gain thesis:** <tbd - needs a cosmetic specific that is not a patient photo: a named method, material, or clinician approach>
- **Status:** index-only
- **Priority:** -
- **Build state:** planned
- **Held because:** the usual cosmetic proof (before/after) is blocked by MED-4; needs an alternative documented specific.

### emergency-dentistry-hub

- **Section:** core
- **Page type + command:** service (brand-wide) - `/write-service-page`
- **Target query:** emergency dentist los angeles
- **Intent:** EMERGENCY
- **Geography / user cluster:** brand-wide
- **Demand trace:** GBP service "Emergency dentistry" + high-intent "emergency dentist" demand
- **Evidence (the promotion gate):** <none yet - "same-week emergency implant consults" is an implant differentiator, not a documented general emergency-dentistry capability per office (hours, same-day slots, on-call)>
- **Info-gain thesis:** <tbd - needs the real per-office emergency capability: same-day availability, after-hours, walk-in policy>
- **Status:** index-only
- **Priority:** -
- **Build state:** planned
- **Held because:** the emergency claim needs real per-office operational specifics before it earns a page.

### dental-implants-brentwood

- **Section:** core
- **Page type + command:** service-in-city - `/write-service-city-page`
- **Target query:** dental implants brentwood
- **Intent:** LOCAL-TRAN
- **Geography / user cluster:** Brentwood (a service-area with no staffed office)
- **Demand trace:** "dental implants brentwood" demand + Brentwood in service_areas
- **Evidence (the promotion gate):** <none yet - no implant case documented in Brentwood and no office there; a service-in-city page with no local specific would be a doorway page>
- **Info-gain thesis:** <tbd - needs a documented Brentwood-area case or a Brentwood-specific fact; otherwise Brentwood stays a linked entry on the Santa Monica location page>
- **Status:** index-only
- **Priority:** -
- **Build state:** planned
- **Held because:** no office and no documented local case; promoting it would be the doorway pattern the gate exists to prevent.

---

## Publishing plan (the status:page nodes, core-first)

1. **homepage** - the entity anchor, published first.
2. **dental-implants-hub** - the hero money page (implants), the highest-value service.
3. **location-santa-monica** - the flagship office (main NAP, on-site CBCT, a documented case).
4. **location-pasadena** - east-side office.
5. **location-glendale** - east-side office.
6. **about-team** - the E-E-A-T / trust surface that funds the implant core.

**Held at index-only (SME homework, in priority order to promote):**
- invisalign-hub - waiting on: the Invisalign differentiator (case count / provider / workflow).
- emergency-dentistry-hub - waiting on: real per-office emergency capability (same-day, after-hours).
- cosmetic-dentistry-hub - waiting on: a cosmetic specific that is not a consent-blocked patient photo.
- dental-implants-brentwood - waiting on: a documented Brentwood case, or it stays a linked entry on the Santa Monica location page.

---

## Coverage reality (not a score)

- **Promoted (pages):** 6 nodes - homepage, the implants hub, the three real offices, and the team page. Each carries a first-party specific competitors cannot copy (the in-house place-and-restore team, the CBCT offices, the named specialists).
- **Held (index-only, awaiting evidence):** 4 nodes. Three are real services (Invisalign, cosmetic, emergency) that lack a documented differentiator; one (implants Brentwood) is a service-area city with no office and would be a doorway page.
- **Next evidence step:** the SME interview should surface (1) Invisalign case volume and the treating provider, (2) each office's real emergency capability, (3) a cosmetic specific that is not a HIPAA-blocked patient photo, and (4) whether any implant cases were done for Brentwood-area patients. Supplying any of these promotes the corresponding node from index-only to page.
- **Levers this plan does NOT move:** proximity, GBP configuration (the three offices' categories/services), and review velocity/recency - these dominate the local pack for a dental group but are not on-page content. Reviews -> `/write-review-requests` + `/write-review-responses` (a dental practice with 60+ reviews/month dominates; recency is the lever); GBP + proximity are operator work per office.
