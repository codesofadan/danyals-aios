# Vertical Compliance Overlay - Home Services (Trades: Plumbing, Electrical, HVAC, Roofing, etc.)

**What this is.** A compliance overlay the `compliance-auditor` applies ON TOP of the base gate stack (`knowledge/quality-gates/gates.md`) and the compliance spine (`knowledge/doctrine/google-compliance-spine.md`) whenever `brand.yaml.vertical == home-services`. It does not replace any base gate. It adds license/bond/insurance-number proof, permit/code-accuracy, safety-honesty, certification-honesty, and real-warranty auto-fails to G2, G10, G12, and spine C3/C5/E1.

**Why this overlay still matters even though home services is less YMYL-strict than legal/medical/financial.** Two reasons. First, several home-services trades *are* YMYL under the spine's own list (electrical, gas, roofing structural, mold/asbestos, pest, water damage, garage doors, security - spine C4): a bad electrician or roofer can hurt someone, so those trades get the heightened C5 bar. Second, and more universally, home-services advertising is directly regulated by *state contractor licensing boards*, many of which legally require the license number in all advertising and prohibit unlicensed-work claims. So while the health-claim machinery is lighter here, the license/bond/insurance and permit/safety machinery is heavier and more concrete. This is the system's core lane; the overlay makes its trust currency (license, bond, insurance, permits, real jobs, real warranties) provable by construction.

**Jurisdiction warning.** Contractor licensing is state-level and varies enormously. Some states (e.g. California via CSLB) require the license number in essentially all advertising and set format rules; some license by trade and dollar threshold; a few have no statewide contractor license at all (local/municipal only). Bond and insurance requirements vary by state and trade. Where a rule is state-dependent, this file says so; confirm the client's state licensing board rule live before a close claim.

---

## Trigger and inputs

- **Trigger:** `brand.yaml.vertical == home-services`.
- **Required `brand.yaml` fields:** `eeat.license` (`number`, `state_or_authority`, `classification` e.g. C-10 Electrical, `expiry`), `eeat.bond` (`amount`, `surety`), `eeat.insurance` (`general_liability_amount`, `workers_comp` bool), `eeat.certifications[]` (each a real cert e.g. NATE, EPA 608, manufacturer-authorized, with issuer), `eeat.permits_note` (the local permit/authority facts the SME provided), `eeat.warranties[]` (each `scope`, `duration`, `terms`), `trade_is_ymyl` (bool flag set when the trade is on the spine C4 list).
- If a page states a license/bond/insurance number, a permit/code fact, a certification, or a warranty and these fields are empty, the overlay fails closed: route to `sme-interviewer`. Never invent a license number, a code citation, a certification, or a warranty term.

---

## Extra requirements per page type

| Page type | Home-services-specific requirement added on top of the base playbook |
|---|---|
| Homepage | License number + issuing authority present (where the state requires it in advertising). "Licensed, bonded, insured" claim backed by real numbers. Named owner/entity. No unlicensed-scope or "#1"/"cheapest"-without-proof claim. |
| About / team page | Full credential stack: license number + class + authority, bond amount + surety, insurance limits, certifications with issuers, real founding date. `LocalBusiness` (correct trade subtype) + `Person` (owner) schema. |
| Service page (e.g. "Panel Upgrades," "Roof Replacement") | Expertise-led per E-E-A-T minimums. Permit/code references accurate to the real local authority (HS-2). Safety claims honest (HS-3). Warranty terms real (HS-5). For YMYL trades, credentialed framing and no risk-erasing claim. |
| Service-city page (money page) | Everything the service page needs plus genuine local substance for G3 doorway: real local jobs, local permit path, local conditions. License number carried where required. |
| Location / service-area page | Real coverage only (spine E3). License valid for that jurisdiction. Do not imply work in a state/municipality the license does not cover (HS-6). |

Any page stating a credential, a permit/code fact, a safety claim, a certification, or a warranty is treated as a proof-bearing page: every such element must trace to `brand.yaml`.

---

## Auto-fail additions (this overlay's new rules)

Each extends a named base gate. All **AF** unless marked.

**HS-1 - License / bond / insurance number proof (extends G2/G10, spine C3/C5).**
Any "licensed," "bonded," or "insured" claim must be backed by a real number/amount in `brand.yaml.eeat.license`/`bond`/`insurance`. A bare "licensed, bonded, and insured" with no license number (where the state requires the number in advertising) fails; a stated number that does not match `brand.yaml`, or a claim with no backing field, fails as fabricated E-E-A-T (G10). For states like California, the license number is legally required in all advertising (Cal. Bus. & Prof. Code 7030.5), so its absence is both a base-gate and a legal fail.
*Authority:* spine C3/C5; G10; California Bus. & Prof. Code 7030.5 (license number required in all advertising). https://codes.findlaw.com/ca/business-and-professions-code/bpc-sect-7030-5/
*Jurisdiction-dependent:* whether the number must appear in advertising, and the format, is set by the client's state board; CSLB is the strict archetype. Confirm the client's state rule.

**HS-2 - Permit and code-compliance accuracy (extends G10, G12).**
Any statement about permits, inspections, or building/electrical/plumbing code must be accurate to the real local authority and trace to `brand.yaml.eeat.permits_note` (SME-sourced) or cited live research on the local building department. No invented code section, no wrong permit authority, no "no permit needed" claim that is false. A fabricated or wrong code/permit fact is an auto-fail; it misleads the buyer and, for a licensed trade, is a real liability.
*Authority:* G10; G12; spine A2 (accuracy). Code/permit facts are inherently local; verify, never guess (E-E-A-T framework source map, `knowledge/foundations/eeat-framework.md`).
*Jurisdiction-dependent:* permit authority and code editions are per-municipality; confirm the local building department live.

**HS-3 - Safety-claim honesty and risk-erasing language (extends G12; heightened for YMYL trades per C5).**
No safety claim that erases real risk or overstates safety ("100% safe," "no risk," "guaranteed safe," "completely hazard-free"). For the YMYL trades on the spine C4 list (electrical, gas, roofing structural, mold/asbestos, pest, water damage, garage doors, security), present the real hazard honestly (e.g. that an aged Federal Pacific/Zinsco panel is a documented fire risk) rather than papering over it. Overstated safety is both a deception surface and, for these trades, a heightened-YMYL fail.
*Authority:* G12; spine C4/C5 (YMYL trades get the very-high bar); FTC truthful-claims standard.

**HS-4 - No fabricated certification (extends G10, spine C3).**
"NATE-certified," "EPA 608," "master electrician," "[manufacturer]-authorized," "certified," "licensed master" may appear only where a real, current certification/credential exists in `brand.yaml.eeat.certifications[]` (or `license.classification` for a master/journeyman class), with the issuer named. A certification claim with no backing entry is an auto-fail. Do not imply a manufacturer authorization or a trade certification the operator does not hold.
*Authority:* G10; spine C3; FTC endorsement/deception standard on unearned credentials. https://www.ecfr.gov/current/title-16/chapter-I/subchapter-B/part-255

**HS-5 - Real warranty / guarantee terms (extends G13/Law 20, G12).**
Any warranty or guarantee must be real and stated with its actual terms from `brand.yaml.eeat.warranties[]` (scope, duration, conditions), not a hollow "lifetime guarantee" or "100% satisfaction guaranteed" with no mechanism. Distinguish honestly between the workmanship warranty (the contractor's) and the manufacturer's parts warranty. A guarantee with no real terms, or one the operator does not actually offer, is an auto-fail (Law 20 fabricated proof; G12).
*Authority:* Law 20; G12; G13 sub-check 5 (real risk-reversal). Consumer-product written-warranty representations are also governed federally by the Magnuson-Moss Warranty Act where a written warranty is offered.

**HS-6 - License scope / jurisdiction honesty (extends spine E1/E3, G12).**
A page may not claim or imply work outside the license's classification or jurisdiction: no advertising a scope the class does not cover, no implying licensed work in a state/municipality the license does not reach. Also enforces spine E1 - the business name must not stuff the trade + city ("Joe's Plumbing Emergency Plumber Dallas 24/7"); the trade and city belong in descriptive copy, not the name.
*Authority:* spine E1 (real business name), E3 (real location/scope); state license classification limits.

---

## How `compliance-auditor` enforces this overlay

Add to the GATE stage when `vertical == home-services`:

1. **Load the overlay;** read `eeat.license`, `bond`, `insurance`, `certifications[]`, `permits_note`, `warranties[]`, `trade_is_ymyl`. If `trade_is_ymyl == true`, also apply the spine C5 heightened checks (this trade is on the YMYL list).
2. **HS-1 credential-number check:** grep "licensed / bonded / insured / license #"; confirm each maps to a real `brand.yaml` field with a number/amount. Where the client's state requires the license number in advertising, confirm it is on the page. Missing/mismatched = FAIL.
3. **HS-2 permit/code check:** for every permit/inspection/code statement, confirm it traces to `permits_note` or cited local-authority research. Invented or wrong = FAIL, route to `sme-interviewer` or live research.
4. **HS-3 safety scan:** banned-pattern scan for "100% safe, no risk, completely safe, guaranteed safe, hazard-free." Any hit = FAIL. For YMYL trades, confirm real hazards are presented honestly. Add the home-services set to `scripts/compliance_lint.py`.
5. **HS-4 certification check:** grep "certified / NATE / EPA 608 / master / authorized / licensed master"; each must map to a `certifications[]` or `license.classification` entry with issuer. Unmatched = FAIL.
6. **HS-5 warranty check:** for every "warranty / guarantee / lifetime / satisfaction guaranteed," confirm real terms in `warranties[]`; hollow or unmatched = FAIL, route to `critical-editor`/`sme-interviewer`.
7. **HS-6 scope/name check:** confirm claimed scope is within `license.classification`, claimed jurisdiction within the license's reach, and the business name is not keyword/geo-stuffed (spine E1).
8. **Record each HS rule** in a "Vertical overlay: home services" section of `compliance-report.md`, PASS/FAIL with evidence, and note whether `trade_is_ymyl` triggered the C5 heightened pass.
9. **State-board flag:** for HS-1 (number-in-advertising requirement) and HS-2 (local permit/code), add a report note if the client's state board / local building department rule was not verified live; do not silently pass.

Any HS **AF** fail blocks publish exactly like a base AF gate.

---

## The sharpest rule for this vertical

**HS-1: no "licensed, bonded, insured" without the real numbers, and in states like California the license number must actually appear in the advertising.** "Licensed, bonded, and insured" is the single most-repeated line in home-services copy and the one most often written as a bare, unbacked slogan. The overlay treats it as a claim that must resolve to real license/bond/insurance numbers in `brand.yaml`, and, where the state requires the license number in advertising (CSLB is the strict model), treats its absence as a legal advertising violation, not just a weak trust signal. This is the trade lane's equivalent of the results disclaimer for lawyers and the HIPAA consent for doctors: the concrete, checkable proof that converts a slogan into a trust asset.

---

## Sources (fetched 2026-07-20 PKT; re-verify quarterly and against the client's state licensing board)

- California Bus. & Prof. Code 7030.5 (contractor license number required in all advertising): https://codes.findlaw.com/ca/business-and-professions-code/bpc-sect-7030-5/
- CSLB - Advertising Guidelines for Contractors: https://www.cslb.ca.gov/resources/guidesandpublications/advertisingguidelines.pdf
- FTC Endorsement Guides, 16 CFR Part 255 (unearned-credential / deceptive endorsement standard): https://www.ecfr.gov/current/title-16/chapter-I/subchapter-B/part-255
- Google Search Quality Rater Guidelines (YMYL standard; home-safety trades): https://guidelines.raterhub.com/searchqualityevaluatorguidelines.pdf
- Internal: `knowledge/doctrine/google-compliance-spine.md` (C3, C4, C5, E1, E3); `knowledge/quality-gates/gates.md` (G2, G10, G12, G13); `knowledge/foundations/eeat-framework.md` (source map, worked electrician examples); `knowledge/doctrine/local-content-laws.md` (Law 20).

*Contractor licensing, bonding, and permit rules are state- and municipality-level and vary widely; the California/CSLB requirement is the strict archetype, not a universal rule. State-dependent items are flagged inline. Confirm the client's state licensing board and local building department live before publishing any close-to-the-line claim.*
