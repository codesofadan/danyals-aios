# Vertical Compliance Overlay - Medical and Dental (Health Practices)

**What this is.** A YMYL compliance overlay the `compliance-auditor` applies ON TOP of the base gate stack (`knowledge/quality-gates/gates.md`) and the compliance spine (`knowledge/doctrine/google-compliance-spine.md`) whenever `brand.yaml.vertical == medical-dental`. It does not replace any base gate. It adds licensed-provider and health-claim auto-fails to G2, G10, G12, and spine C3/C4/C5, and adds a privacy dimension (HIPAA) the base system does not otherwise carry, because a health claim or a patient story here can harm a reader's health and expose the client to FTC, state-board, and HIPAA liability at once.

**Why the bar is highest here.** Health is the archetypal YMYL topic: the QRG holds medical/dental content to "very high Page Quality standards" (spine C4/C5) precisely because bad information can hurt someone. Beyond Google, three real regulators bind the client: the FTC (health claims must be truthful and backed by "competent and reliable scientific evidence"), state medical/dental boards (advertising rules, often barring guarantees and requiring truthful before/after use), and HHS (HIPAA authorization before any patient information is used in marketing). This overlay makes the writing satisfy all three by construction.

**Jurisdiction warning.** State medical and dental board advertising rules vary (many prohibit "guarantee of cure," restrict "painless"/superlative claims, and set specific before/after photo conditions). HIPAA is federal and uniform. FTC guidance is federal. Where a rule is state-board-dependent, this file says so; confirm the client's state board rule live before a close claim.

---

## Trigger and inputs

- **Trigger:** `brand.yaml.vertical == medical-dental`.
- **Required `brand.yaml` fields:** `eeat.providers[]` (each `name`, `credential` e.g. MD/DO/DDS/DMD, `license_number`, `license_state`, `board_certifications[]`, `npi` optional), `eeat.reviewer` (the clinician who reviews clinical content), `eeat.consents[]` (patient authorizations on file, keyed to any testimonial/photo used), `eeat.health_claims[]` (each claim with its substantiation source).
- If a page makes a clinical claim or uses a patient story and these fields are empty, the overlay fails closed: route to `sme-interviewer`. Never draft a health claim or a patient testimonial without the credential and the consent on file.

---

## Extra requirements per page type

| Page type | Medical/dental-specific requirement added on top of the base playbook |
|---|---|
| Homepage | Named licensed provider(s) with credential visible or one click away. No guarantee-of-outcome or "painless"/"#1"/"safest" superlative. |
| About / team page | Heaviest load. Each provider: full name, credential (MD/DO/DDS/DMD), license number + state, board certifications, school, years. `Physician`/`Dentist` + `Person` schema. This is the authorship/authority anchor. |
| Service page (procedure, e.g. "Dental Implants," "Botox") | Clinical content must be authored or reviewed by a licensed provider, carrying a visible "Medically reviewed by Dr. [Name], [credential]" (or "Clinically reviewed by") byline. Every efficacy/safety/risk statement substantiated (MED-3). Realistic outcome and risk framing, not just benefits. |
| Service-city page | Everything the service page needs plus genuine local substance for G3 doorway. Any local outcome/result claim substantiated and, if a patient case, consented. |
| Before/after or "smile gallery" / results page | Every image is a real patient with a signed HIPAA authorization (MED-4) and, if presented as a typical result, an FTC typical-results disclaimer or honest framing (MED-3). No stock, no fabricated, no mismatched images. |
| Location / service-area page | Provider byline + license state. Do not imply a provider practices where they are not licensed. |

Any page that describes a symptom, condition, procedure, risk, or outcome is treated as clinical content: it needs the reviewed-by byline and full substantiation.

---

## Auto-fail additions (this overlay's new rules)

Each extends a named base gate. All **AF** unless marked.

**MED-1 - Licensed-provider authorship / clinical review (extends C3/C5, G2).**
Any page with clinical content must carry a visible "Medically reviewed by Dr. [Name], [credential]" (medical) or "Clinically reviewed by [Name], [credential]" (dental) byline that traces to `brand.yaml.eeat.providers[]` or `eeat.reviewer`, with a real license number + state. Anonymous clinical content is an auto-fail (spine C5). A reviewer byline naming a person, credential, or license not in `brand.yaml` fails as fabricated E-E-A-T (G10).
*Authority:* QRG YMYL authorship (spine C5); helpful-content "written or reviewed by an expert." The "Medically reviewed by" pattern is the documented health-vertical E-E-A-T convention (`research/expansion-2026-07/02-local-seo-authorities.md`, s3).

**MED-2 - No guarantee of outcome, no cure claim (extends G12, spine C5).**
No language guaranteeing a result, cure, or safety ("guaranteed results," "100% safe," "permanent cure," "painless," "no risk," "the safest procedure"). Every procedure carries real risk; the page must not erase it. Present realistic outcomes with the honest limitation/risk that the provider states.
*Authority:* FTC truthful-claims standard (below); state dental/medical board advertising rules commonly prohibit guarantees and unqualified "painless"/superlative claims.
*Jurisdiction-dependent:* the specific banned words and required qualifiers are set by the client's state board; confirm.

**MED-3 - Health-claim substantiation (extends G10, G12).**
Every claim about a treatment's benefit, efficacy, or safety must trace to `brand.yaml.eeat.health_claims[]` with a real substantiation source, and must be truthful and not misleading. Per FTC Health Products Compliance Guidance, health-benefit claims require "competent and reliable scientific evidence," generally randomized, controlled human clinical evidence for efficacy claims; anecdote, a single testimonial, or a mechanism story does not substantiate an efficacy claim. Where a result is shown that is not typical, an FTC typical-results disclaimer or equivalent honest framing is required. An unsubstantiated or overstated health claim is an auto-fail.
*Authority:* FTC Health Products Compliance Guidance (Dec 2022). https://www.ftc.gov/business-guidance/resources/health-products-compliance-guidance
*Authority:* FTC Endorsement Guides on typical results. https://www.ecfr.gov/current/title-16/chapter-I/subchapter-B/part-255

**MED-4 - HIPAA-safe testimonial and before/after handling (new dimension; extends G10, spine C1/D3).**
Any patient testimonial, review, photo, before/after image, or case story that includes protected health information may be used only if a signed HIPAA authorization for marketing use is on file, referenced in `brand.yaml.eeat.consents[]` and keyed to that specific asset. Per HHS, using patient information in marketing requires the individual's written authorization; a general practice review does not carry consent to republish that patient's PHI in promotional content. No consent on file = the asset does not go on the page, auto-fail. Never fabricate, anonymize-then-still-identify, or reuse a patient image without its keyed authorization.
*Authority:* HHS HIPAA Marketing guidance (45 CFR 164.508 authorization). https://www.hhs.gov/hipaa/for-professionals/privacy/guidance/marketing/index.html
*Note:* the writing system does not collect PHI; it enforces that every PHI-bearing asset it *places* has a consent key in `brand.yaml`. Consent capture is the operator's job; placement without a consent key is this overlay's auto-fail.

**MED-5 - No fabricated outcomes or invented patient stories (extends G10, Law 20).**
No invented patient, no composite "typical patient" presented as real, no fabricated result, no stock image passed off as the practice's own patient. Reinforces G10 and Law 20 with the health-specific severity: a fabricated outcome here is both a trust penalty and a potential FTC/board deception action.
*Authority:* G10; Law 20; FTC deception standard.

**MED-6 - Self-serving review markup still barred (extends spine D3/D4).**
Real patient reviews belong on the visible page (with MED-4 consent), but `review`/`aggregateRating` schema about the practice on its own `Physician`/`Dentist`/`LocalBusiness` page remains ineligible and is an auto-fail per spine D3. Ratings that are marked up must be real and from valid reviewers (D4).
*Authority:* spine D3/D4.

---

## How `compliance-auditor` enforces this overlay

Add to the GATE stage when `vertical == medical-dental`:

1. **Load the overlay;** read `brand.yaml.eeat.providers[]`, `reviewer`, `consents[]`, `health_claims[]`.
2. **MED-1 byline check:** grep for a "reviewed by" byline; confirm the named provider + credential + license exist in `brand.yaml`. Missing on clinical-content page = FAIL, route to `critical-editor` (add byline) or `sme-interviewer` (missing credential).
3. **MED-2 guarantee/superlative scan:** banned-pattern scan for "guarantee(d), cure, 100% safe, painless, no risk, safest, best." Any hit in a clinical/outcome context = FAIL. Add the medical set to `scripts/compliance_lint.py`.
4. **MED-3 substantiation check:** for every efficacy/safety/benefit statement, confirm a matching `health_claims[]` entry with a real source; confirm typical-results framing/disclaimer where a shown result is not typical. Unsubstantiated = FAIL, route to `voice-writer`/`sme-interviewer`.
5. **MED-4 consent check:** enumerate every testimonial, review quote, patient name, and before/after image on the page; each must have a keyed `consents[]` entry. Any PHI-bearing asset without a consent key = FAIL, route to operator (do not "fix" by anonymizing a still-identifiable asset).
6. **MED-5 fabrication check:** confirm every patient story and outcome traces to SME source; a composite or invented patient = FAIL (G10).
7. **MED-6 schema check:** confirm no self-serving review/aggregateRating markup on the practice page (spine D3).
8. **Record each MED rule** in a "Vertical overlay: medical/dental" section of `compliance-report.md`, PASS/FAIL with evidence.
9. **State-board flag:** for MED-2 superlatives/guarantee-adjacent language and before/after conditions, add a note if the client's state board rule was not verified live; do not silently pass.

Any MED **AF** fail blocks publish exactly like a base AF gate.

---

## The sharpest rule for this vertical

**MED-4: no patient asset on the page without a keyed HIPAA authorization.** This is the rule that has no analogue anywhere else in the system and the one an SEO writer is most likely to miss. A glowing patient testimonial or a stunning before/after is the strongest trust asset a health practice has, and republishing it without a signed marketing authorization is a federal privacy violation regardless of how good it is for rankings. The overlay treats a missing consent key as a hard stop, not a warning.

---

## Sources (fetched 2026-07-20 PKT; re-verify quarterly and against the client's state board)

- FTC Health Products Compliance Guidance (Dec 2022): https://www.ftc.gov/business-guidance/resources/health-products-compliance-guidance
- FTC Endorsement Guides, 16 CFR Part 255 (testimonials, typical-results disclosure): https://www.ecfr.gov/current/title-16/chapter-I/subchapter-B/part-255
- HHS - HIPAA Marketing (authorization before marketing use of PHI): https://www.hhs.gov/hipaa/for-professionals/privacy/guidance/marketing/index.html
- Google Search Quality Rater Guidelines (YMYL standard): https://guidelines.raterhub.com/searchqualityevaluatorguidelines.pdf
- Internal: `knowledge/doctrine/google-compliance-spine.md` (C1, C3, C4, C5, D3, D4); `knowledge/quality-gates/gates.md` (G2, G10, G12); `research/expansion-2026-07/02-local-seo-authorities.md` (s3, "Medically reviewed by" convention).

*HIPAA and FTC guidance are federal and uniform; state medical/dental board advertising rules vary and are flagged inline. Confirm the state board rule live before publishing any close-to-the-line claim.*
