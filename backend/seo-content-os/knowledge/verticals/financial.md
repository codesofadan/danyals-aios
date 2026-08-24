# Vertical Compliance Overlay - Financial (Advisers, Planners, Accounting, Insurance, Lending)

**What this is.** A YMYL compliance overlay the `compliance-auditor` applies ON TOP of the base gate stack (`knowledge/quality-gates/gates.md`) and the compliance spine (`knowledge/doctrine/google-compliance-spine.md`) whenever `brand.yaml.vertical == financial`. It does not replace any base gate. It adds credential-disclosure, no-guaranteed-return, required-disclaimer, and figure-accuracy auto-fails to G2, G10, G12, and spine C3/C4/C5, because a misleading financial claim can cost a reader real money and expose the client to SEC, FINRA, state-securities, or state-insurance enforcement.

**Why the bar is highest here.** Financial stability is core YMYL: the QRG holds finance content to "very high Page Quality standards" (spine C4/C5). And the regulatory overlay is dense and claim-specific. Which regime binds depends on what the client *is*: a registered investment adviser (RIA) is bound by the SEC Marketing Rule 206(4)-1 (or a state equivalent); a broker-dealer by FINRA Rule 2210; a CFP by CFP Board rules; an insurance agent by state insurance advertising rules; a tax/accounting firm by AICPA/state-board rules; a lender by TILA/Reg Z and (for consumer credit) truth-in-lending advertising rules. This overlay enforces the common floor and flags the regime-specific pieces.

**Jurisdiction / regime warning (read before applying any rule).** The applicable rules turn entirely on the client's registration type in `brand.yaml.eeat.registration_type`. The SEC Marketing Rule and FINRA 2210 are the two heaviest regimes and apply only to advisers/broker-dealers; do not apply adviser testimonial rules to a plain bookkeeping firm, and do not skip them for an RIA. Insurance and lending advertising rules are state-level and vary. Where a rule is regime- or state-dependent, this file says so; confirm the client's specific regime live before a close claim.

---

## Trigger and inputs

- **Trigger:** `brand.yaml.vertical == financial`.
- **Required `brand.yaml` fields:** `eeat.registration_type` (one of: `ria`, `broker_dealer`, `dual_registrant`, `cfp`, `cpa_accounting`, `insurance_agent`, `mortgage_lender`, `other`), `eeat.credentials[]` (each `name`, `designation` e.g. CFP/CPA/ChFC, `crd_or_license`, `regulator`), `eeat.registrations[]` (firm CRD/IARD, state registrations), `eeat.required_disclaimers[]` (the disclosures the client's compliance/regime requires), `eeat.figures[]` (any performance/fee/rate figure with its source and as-of date).
- If a page makes a performance, fee, rate, or advice claim and these fields are empty, the overlay fails closed: route to `sme-interviewer`. Financial figures and claims are never drafted from the model's memory.

---

## Extra requirements per page type

| Page type | Financial-specific requirement added on top of the base playbook |
|---|---|
| Homepage | Named credentialed principal(s) with designation and, for advisers/BDs, the firm's registration status. Any required entity-level disclaimer present or one click away. No "guaranteed returns"/"risk-free"/"beat the market" claim. |
| About / team page | Heaviest load. Each professional: name, real designation (CFP/CPA/ChFC/etc.), CRD or license number, regulator/registration. Disciplinary-history honesty (do not conceal a material fact - spine C1). `Person` + `FinancialService`/`AccountingService` schema. |
| Service page (e.g. "Retirement Planning," "Tax Prep," "Mortgages") | Credentialed authorship/review byline. Every rate, return, fee, or benefit figure sourced and as-of dated (FIN-4). Required disclaimers present for the regime. Balanced treatment of risk, not benefits-only. |
| Service-city page | Everything the service page needs plus genuine local substance for G3 doorway. Same disclaimer and figure discipline. |
| Location / service-area page | Confirm the client is registered/licensed to do business in that state before implying they serve clients there (FIN-6, ties spine E3). Securities and insurance are state-registered. |

Any page that states a return, rate, fee, tax outcome, or investment/insurance/lending recommendation is treated as regulated financial content: credentialed byline, sourced figures, and the required disclaimers.

---

## Auto-fail additions (this overlay's new rules)

Each extends a named base gate. All **AF** unless marked.

**FIN-1 - Credential and registration disclosure (extends C3/C5, G2).**
Any page with financial advice or claims must carry a credentialed byline naming a real professional with a designation and CRD/license that trace to `brand.yaml.eeat.credentials[]`, and the firm's registration status where the regime requires it. Anonymous financial-advice content is an auto-fail (spine C5). A designation, CRD, or registration not in `brand.yaml` fails as fabricated E-E-A-T (G10). A designation must be real and current (e.g. do not write "CFP" unless the professional holds it).
*Authority:* QRG YMYL authorship (spine C5); SEC Marketing Rule general prohibitions on untrue/misleading statements; FINRA 2210(d)(1) fair-and-balanced standard.

**FIN-2 - No guaranteed return, no performance promise (extends G12, spine C5).**
No language guaranteeing or predicting investment return, safety of principal beyond what is literally true (e.g. FDIC/NCUA insured amounts stated accurately), "risk-free," "beat the market," "you will retire with $X," or any implication that past performance predicts future results. FINRA Rule 2210(d)(1) prohibits false, exaggerated, promissory, or misleading claims and specifically bars predictions or projections of performance and the implication that past performance will recur. The SEC Marketing Rule's general prohibitions bar untrue and misleading statements and unsubstantiated material claims.
*Authority:* FINRA Rule 2210(d)(1)(B) and (d)(1)(F). https://www.finra.org/rules-guidance/rulebooks/finra-rules/2210
*Authority:* SEC Marketing Rule 206(4)-1 general prohibitions. https://www.sec.gov/newsroom/press-releases/2020-334
*Regime-dependent:* applies most strictly to RIAs/BDs; the no-guarantee principle applies to insurance and lending too under state UDAP and truth-in-advertising rules.

**FIN-3 - Required disclaimers present (extends G12).**
Every disclaimer the client's regime requires, listed in `brand.yaml.eeat.required_disclaimers[]`, must be present and clear/conspicuous on any page where it applies. Examples by regime: RIA/BD performance and testimonial disclosures; "past performance is no guarantee of future results" on any performance reference; "not FDIC insured / may lose value" where investment products sit alongside bank products; insurance policy-limitation disclosures; lending APR/Reg Z disclosures on any rate. A page that states a figure or claim requiring a disclaimer without that disclaimer is an auto-fail.
*Authority:* SEC Marketing Rule (disclosure conditions for testimonials/performance); FINRA 2210(d) (balanced, disclosed); TILA/Reg Z (consumer-credit advertising) where lending.
*Regime-dependent:* the exact required disclaimers are set by the client's regime and compliance function; the overlay enforces presence of whatever `required_disclaimers[]` lists, and flags if that list is empty for a regime that clearly needs one.

**FIN-4 - Accuracy and as-of dating of figures (extends G10, Law 19).**
Every performance number, fee, rate, APR, tax figure, or statistic must trace to `brand.yaml.eeat.figures[]` with a real source and an as-of date, and must be current. A stale rate or a performance figure with no as-of date is misleading. Reinforces G10 (no fabricated facts) and Law 19 (no date without a delta): a "current rate" that is not current, or a figure whose date advanced without the figure changing, fails.
*Authority:* G10; Law 19; FINRA 2210(d)(1)(A) (no omission of material qualification, e.g. the as-of date); SEC Marketing Rule (no misleading presentation).

**FIN-5 - Testimonial / endorsement / third-party-rating compliance (extends spine D3/D4, G10).**
Real reviews belong on the visible page, but for RIAs/BDs, testimonials, endorsements, and third-party ratings are permitted only with the SEC Marketing Rule's required disclosures (whether the promoter is a client, whether compensated, material conflicts) or FINRA 2210's conditions. A testimonial for an adviser/BD without the required disclosure is an auto-fail. For all financial clients: no fabricated review (Law 20), and self-serving `review`/`aggregateRating` schema on the firm's own page remains barred (spine D3).
*Authority:* SEC Marketing Rule 206(4)-1 testimonial/endorsement conditions. https://www.sec.gov/newsroom/press-releases/2020-334
*Authority:* FINRA Rule 2210; spine D3/D4; Law 20.
*Regime-dependent:* the disclosure requirement is specific to advisers/BDs; a CPA or insurance client is bound by its own board/state rules instead.

**FIN-6 - State-registration / licensing honesty (extends spine E3, G12).**
A page may not imply the client can provide securities, insurance, or lending services in a state where the firm/professional is not registered or licensed. A location/service-area page for such a state must not imply a regulated service relationship the registration does not support.
*Authority:* spine E3; state securities/insurance registration requirements.

---

## How `compliance-auditor` enforces this overlay

Add to the GATE stage when `vertical == financial`:

1. **Load the overlay;** read `registration_type`, `credentials[]`, `registrations[]`, `required_disclaimers[]`, `figures[]`. The `registration_type` selects which regime-specific rules bind (FIN-2/3/5 are strictest for `ria`/`broker_dealer`/`dual_registrant`).
2. **FIN-1 byline check:** grep for a credentialed byline; confirm designation + CRD/license in `brand.yaml`. Missing on advice-content page = FAIL.
3. **FIN-2 guarantee scan:** banned-pattern scan for "guarantee(d) return, risk-free, beat the market, you will retire with, can't lose, assured." Any hit = FAIL. Add the financial set to `scripts/compliance_lint.py`.
4. **FIN-3 disclaimer check:** for each figure/claim type present on the page, confirm the corresponding `required_disclaimers[]` entry is on-page and conspicuous. Missing = FAIL. If `required_disclaimers[]` is empty for an `ria`/`broker_dealer`/`insurance_agent`/`mortgage_lender` client, FAIL and route to operator/compliance.
5. **FIN-4 figures check:** for every rate/return/fee/APR/stat, confirm a `figures[]` match with source + as-of date, and that the date is current. Unsourced/undated/stale = FAIL (G10/Law 19).
6. **FIN-5 testimonial check:** if any testimonial/endorsement/third-party rating appears and `registration_type in (ria, broker_dealer, dual_registrant)`, confirm the required disclosure is present; else FAIL. Confirm no self-serving review schema (spine D3).
7. **FIN-6 registration check:** cross-check claimed states against `registrations[]`; implied unregistered service = FAIL, route to `outline-architect`/operator.
8. **Record each FIN rule** in a "Vertical overlay: financial" section of `compliance-report.md`, PASS/FAIL with evidence, and note the governing `registration_type`.
9. **Regime flag:** add a report note naming the regime and stating whether the client's compliance function has approved the disclaimers used; do not silently pass regime-dependent claims.

Any FIN **AF** fail blocks publish exactly like a base AF gate.

---

## The sharpest rule for this vertical

**FIN-2 + FIN-3: no guaranteed or predicted return, and no figure without its required disclaimer.** For an RIA or broker-dealer this is the exact line FINRA and the SEC enforce most often, and it is the one an SEO writer chasing conversion will most want to cross ("guaranteed 8% returns," "beat the market," a headline performance number with no disclosure). The overlay makes a promissory/predictive claim and an undisclaimed figure hard stops, because they are simultaneously a YMYL trust cap and a securities-advertising violation.

---

## Sources (fetched 2026-07-20 PKT; re-verify quarterly and against the client's regime/compliance function)

- SEC - Modernized Marketing Rule for Investment Advisers, Rule 206(4)-1 (testimonials, performance, general prohibitions): https://www.sec.gov/newsroom/press-releases/2020-334
- SEC - Marketing Compliance FAQ: https://www.sec.gov/rules-regulations/staff-guidance/division-investment-management-frequently-asked-questions/marketing-compliance-frequently-asked-questions
- FINRA Rule 2210 - Communications with the Public (d)(1) content standards: https://www.finra.org/rules-guidance/rulebooks/finra-rules/2210
- FTC Endorsement Guides, 16 CFR Part 255 (testimonials, disclosure): https://www.ecfr.gov/current/title-16/chapter-I/subchapter-B/part-255
- Google Search Quality Rater Guidelines (YMYL standard): https://guidelines.raterhub.com/searchqualityevaluatorguidelines.pdf
- Internal: `knowledge/doctrine/google-compliance-spine.md` (C1, C3, C4, C5, D3, E3); `knowledge/quality-gates/gates.md` (G2, G10, G12); `knowledge/doctrine/local-content-laws.md` (Law 19, Law 20).

*Which regime binds depends on `registration_type`; SEC/FINRA rules apply only to advisers/broker-dealers, insurance and lending rules are state-level. Regime- and state-dependent rules are flagged inline. Confirm the specific regime live before publishing any close-to-the-line claim.*
