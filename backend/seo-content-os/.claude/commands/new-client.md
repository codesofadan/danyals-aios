---
description: Onboard a new client - interactively build clients/<slug>/brand.yaml from the template, running the SME interviewer to fill the E-E-A-T and voice profile before any page is written.
argument-hint: <client-slug> [business name]
allowed-tools: Task, Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
---

Onboard a new client. Arguments: `$ARGUMENTS` (the kebab-case client slug, and optionally the business name, e.g. `austin-roofing-co "Austin Roofing Co"`).

Read `CLAUDE.md` first if not already in context. This command builds `clients/<slug>/brand.yaml` from `clients/_template/brand.yaml` so the writing pipeline has a real client profile and a real voice profile to work from. No page ships in a generic voice; this builds the voice first.

**Hard rule:** every field is filled from a real, confirmed fact - the operator, the client's live site, or the GBP - never invented. Blank stays blank rather than guessed (the template says so: "do not guess"). A fabricated NAP, credential, or service area poisons every page written for this client.

## Steps

1. **Scaffold.** Copy `clients/_template/brand.yaml` to `clients/<slug>/brand.yaml`. Set `client.slug`, and `client.brand_name` / `client.legal_name` if provided.

2. **Auto-fill what is publicly verifiable.** If the client has a live site or GBP, research it (WebSearch / WebFetch) and pre-fill the verifiable fields: `nap` (name, phone, address - captured byte-identical from the GBP, which is the source of truth), `primary_url`, `schema.local_business_type` (the most specific LocalBusiness subtype), `schema.opening_hours`, `schema.same_as` (GBP, Facebook, LinkedIn, BBB, Yelp), `services`, `service_areas`, `primary_city`, and any public `eeat.credentials` / `eeat.proof` (review counts + platform). Also draft the `entity` block from the site/GBP: `entity.central_entity` (business + primary service, anchored to the GBP primary category), `entity.source_context` (what it is + how it monetizes, one line), `entity.canonical_description` (1-2 factual sentences, not ad copy), `entity.same_as` (same registry as `schema.same_as`). Tag each auto-filled field with its source; the operator confirms.

3. **Run the SME interview for the profile.** Launch the **sme-interviewer** agent in profile mode: instead of a page, it targets the `brand.yaml` fields that only the operator can supply and that no page can fabricate later:
   - `eeat.team` (real people: name, role, years, one specific detail each)
   - `eeat.credentials` (license/cert/insurance numbers if public)
   - `eeat.proof` (real review counts + platforms, awards, guarantees, notable projects)
   - `eeat.differentiators` (what is genuinely true and different vs local competitors)
   - `competitive_set` (the real local competitors: `{name, url, strength, gap_we_fill}` each - the operator knows who they actually compete with and where those competitors are thin; this drives the topical map's information-gain theses)
   - confirmation of the auto-filled `entity` block (`central_entity`, `source_context`, `canonical_description`) - the operator corrects the disambiguation to how the business truly positions and monetizes
   - `voice.one_line_direction`, `voice.reading_level`, `voice.tone_by_context`, `voice.banned_phrases`, `voice.good_examples`, `voice.off_brand_examples`
   - `founded_year`, and confirmation of the auto-filled NAP / services / service_areas
   Write the questions to `clients/<slug>/onboarding-questions.md` and **halt** for the operator to answer (or answer interactively in chat).

4. **Fill brand.yaml from the answers.** Populate every field from the confirmed answers. For the `voice:` block: if the client has real existing copy (current site pages, email replies, GBP posts the operator can paste in), invoke the **`corpus-voice-ingest`** skill to derive the voice from their actual writing (it runs `scripts/voice_fingerprint.py` on the corpus and writes the voice block) - a corpus-derived voice beats a hand-written one. Otherwise synthesize `one_line_direction` and `good_examples` / `off_brand_examples` from how the operator describes and talks about the business (see `knowledge/voice/humanization-layer.md` Layer 2). Leave a field blank only if the operator genuinely has no answer, and list every blank for follow-up.

5. **Validate.** Confirm the NAP is internally consistent and byte-identical to the GBP, the LocalBusiness subtype is the most specific valid one, and `service_areas` reflects genuine coverage (no inflation). Run `scripts/nap_checker.py --brand clients/<slug>/brand.yaml <page files>` if present.

6. **Report.** Summarize the built profile: the LocalBusiness subtype, the service + coverage lists, the E-E-A-T assets captured, the `entity` block and `competitive_set`, the voice direction, and any blank fields the operator still needs to supply. The next step is `/build-topical-map <slug>` to plan the page set before any page is written; name that as the handoff, and flag any missing `entity` / `competitive_set` field that would block it.

## Output

`clients/<slug>/brand.yaml` fully populated from real facts, plus `clients/<slug>/onboarding-questions.md` (the interview record). No page is written by this command; it only builds the profile the write commands depend on.
