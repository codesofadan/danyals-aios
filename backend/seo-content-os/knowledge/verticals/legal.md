# Vertical Compliance Overlay - Legal (Law Firms, Attorneys)

**What this is.** A YMYL compliance overlay the `compliance-auditor` applies ON TOP of the base gate stack (`knowledge/quality-gates/gates.md`) and the compliance spine (`knowledge/doctrine/google-compliance-spine.md`) whenever the client's `brand.yaml` declares `vertical: legal`. It does not replace any base gate. It adds attorney-specific auto-fails to G2, G10, G12, and spine rules C3/C4/C5, and it raises the trust bar because a false or misleading claim here is not just a Google penalty, it is a bar-discipline and malpractice exposure for the client.

**Why the bar is highest here.** Legal is core YMYL: the QRG holds legal topics to "very high Page Quality standards" because a bad hire can cost someone their liberty, custody, or livelihood (spine C4/C5). The Local SEO Guide correlation study found reviews and trust signals weigh *more* heavily for lawyers than for most verticals (`research/expansion-2026-07/02-local-seo-authorities.md`, s1.5). And unlike home services, attorney advertising is governed by enforceable rules of professional conduct in every US state.

**Jurisdiction warning (read before applying any rule below).** Attorney advertising is regulated at the *state* level. The ABA Model Rules are a template that no state adopts verbatim; states vary materially (for example, Florida and New York impose filing, retention, and specific-disclaimer requirements far stricter than the Model Rules; some states mandate the exact wording and placement of a results disclaimer). This overlay enforces the Model-Rule floor. For any client, the writer must confirm the client's licensing state(s) in `brand.yaml.eeat.bar_jurisdictions` and, where a claim is close to a line, read that state's bar advertising rule live before sign-off. When a rule is state-dependent, this file says so.

---

## Trigger and inputs

- **Trigger:** `brand.yaml.vertical == legal`.
- **Required `brand.yaml` fields this overlay reads:** `eeat.attorneys[]` (each with `name`, `bar_number`, `bar_jurisdiction`, `admission_year`, `practice_areas[]`), `eeat.bar_jurisdictions[]`, `eeat.case_results[]` (each result an SME-sourced, real matter with outcome and the facts that produced it), `eeat.fee_structure`, `eeat.certified_specialties[]` (state-board or ABA-accredited certifications only).
- If a page makes a legal claim and these fields are empty, the overlay fails closed: route to `sme-interviewer`, never draft the claim.

---

## Extra requirements per page type

| Page type | Legal-specific requirement added on top of the base playbook |
|---|---|
| Homepage | Named lead attorney with bar number + admitting jurisdiction visible or one click away (About). Firm's real practice areas only. No unqualified superlative ("best DUI lawyer in Dallas"). |
| About / team page | The heaviest load. Every attorney: full name, bar number, jurisdiction(s) of admission, admission year, law school, real credentials. `Person` + `Attorney`/`LegalService` schema. This page is the authorship anchor every other page's byline links to. |
| Service page (practice area, e.g. "Personal Injury") | Must be authored or reviewed by an attorney licensed in the relevant jurisdiction, with a visible attorney byline. Substantive legal information must be accurate and current. Any case result cited carries the results disclaimer. |
| Service-city page (e.g. "Car Accident Lawyer in Mesa") | Everything the service page needs, plus genuine local substance (local court, local venue specifics the SME provided) to clear G3 doorway. Local claims of results must be real and disclaimed. |
| Location / service-area page | Attorney byline + jurisdiction. If the firm is not admitted or does not practice in that jurisdiction, the page cannot imply it can represent clients there (see LEG-6). |

Every page that states or summarizes law, describes outcomes, or invites a representation relationship is treated as attorney-authored content and must carry the byline and jurisdiction.

---

## Auto-fail additions (this overlay's new rules)

These extend the named base gates. Each cites its authority. All are **AF** (block publish) unless marked.

**LEG-1 - Attorney authorship and bar credential (extends C3/C5, G2).**
Any page containing legal information, analysis, or outcome claims must carry a visible byline naming a real attorney, with a bar number and admitting jurisdiction that trace to `brand.yaml.eeat.attorneys[]`. Anonymous legal content is an auto-fail (spine C5: "YMYL page with anonymous authorship ... = fail"). A byline naming a person not in the credential list, or a bar number that does not match, fails as fabricated E-E-A-T (G10).
*Authority:* QRG YMYL authorship standard (spine C5); ABA Model Rule 7.1 (all communications about a lawyer's services must be truthful). https://www.americanbar.org/groups/professional_responsibility/publications/model_rules_of_professional_conduct/rule_7_1_communication_concerning_a_lawyer_s_services/

**LEG-2 - No guarantee or prediction of outcome (extends G12, spine C5).**
No language that guarantees, promises, or predicts a specific result, or that is likely to create an unjustified expectation ("we win 100% of our cases," "guaranteed settlement," "you will get the compensation you deserve"). ABA Rule 7.1 Comment: a truthful statement is still misleading if it creates unjustified expectations; a disclaimer may cure a statement that would otherwise mislead. Many state bars (for example California, New York, Florida) explicitly prohibit guarantees of outcome.
*Authority:* ABA Model Rule 7.1 and its Comment. https://www.americanbar.org/groups/professional_responsibility/publications/model_rules_of_professional_conduct/rule_7_1_communication_concerning_a_lawyer_s_services/comment_on_rule_7_1/
*Jurisdiction-dependent:* the *wording* of the ban and any required disclaimer vary by state; confirm against the client's state bar rule.

**LEG-3 - Real, non-misleading case results with disclaimer (extends G10, G12).**
Every verdict, settlement, or result figure on the page must be a real matter sourced to `brand.yaml.eeat.case_results[]` (SME-verified), stated with enough context that it does not imply a typical or promised outcome, and accompanied by a past-results disclaimer (e.g. "Prior results do not guarantee a similar outcome"). A settlement amount with no context or disclaimer, or a fabricated or unverifiable result, is an auto-fail. Do not aggregate or round results into a headline total ("$50M+ recovered") unless that figure is real, documented, and the firm can substantiate it.
*Authority:* ABA Rule 7.1 (misleading truthful statements; disclaimers); G10 (no fabricated facts).
*Jurisdiction-dependent:* several states mandate a specific disclaimer text and placement for result advertising; some restrict testimonials that describe results. Confirm state rule.

**LEG-4 - Contingency-fee transparency (extends G12, G13/Law 20).**
Any fee claim, especially "no fee unless we win" / "no win, no fee," must not mislead about what the client may owe. Under ABA Rule 1.5(c) a contingent-fee arrangement must be in a signed writing and must state that the client may be liable for costs and expenses regardless of outcome. On-page, a "no fee unless we win" claim that omits the client's potential liability for case costs/expenses is misleading and fails. Pair the claim with an honest qualifier (e.g. "attorney's fees only if we recover; case costs may apply") consistent with the client's real fee agreement.
*Authority:* ABA Model Rule 1.5(c). https://www.americanbar.org/groups/professional_responsibility/publications/model_rules_of_professional_conduct/rule_1_5_fees/

**LEG-5 - No unpermitted specialist / expert claim (extends G12).**
"Specialist," "expert," "certified [X] specialist," or "board-certified" may appear only where the attorney holds a real certification from a state-bar-approved or ABA-accredited certifying organization, listed in `brand.yaml.eeat.certified_specialties[]` with the certifying body named on the page. An uncertified "specialist" claim is a common bar-advertising violation. Generic "experienced" or "focused on [practice area]" is fine; a formal specialist/certified label without the credential is an auto-fail.
*Authority:* ABA Rule 7.1 (this subject was formerly Model Rule 7.4; most states retain an explicit certification requirement for "specialist" claims).
*Jurisdiction-dependent:* the approved certifying bodies and the exact permitted wording differ by state.

**LEG-6 - Jurisdiction / unauthorized-practice honesty (extends spine E3, G12).**
A page may not imply the firm can represent a client in a jurisdiction where no listed attorney is admitted, or in a matter type the firm does not handle. A service-area or location page for a place outside the firm's admitted jurisdiction(s) must not imply representation there (an information-only page must say so). This protects against both a false-location trust fail (spine E3) and an unauthorized-practice-of-law exposure.
*Authority:* spine E3 (real, accurate location / genuine service relationship); ABA Rule 7.1 (no misleading implication).

**LEG-7 - Testimonial and endorsement honesty (extends G10, spine D3/D4).**
Client testimonials must be real, attributable, and, where a jurisdiction requires it, disclaimed (some states require a disclaimer on client testimonials that discuss results). No fabricated review, no invented client quote (Law 20). Self-serving `review`/`aggregateRating` schema on the firm's own `LegalService`/`Attorney` page is still barred by spine D3.
*Authority:* spine D3/D4; ABA Rule 7.1.
*Jurisdiction-dependent:* testimonial disclaimers are required in some states (e.g. certain forms in NY/FL), prohibited-in-part in others; confirm.

---

## How `compliance-auditor` enforces this overlay

Add these steps to the GATE stage when `vertical == legal`:

1. **Load the overlay** after reading the base standards. Read `brand.yaml.eeat.attorneys[]`, `bar_jurisdictions[]`, `case_results[]`, `fee_structure`, `certified_specialties[]`.
2. **LEG-1 byline check:** grep the page for an attorney byline; confirm the named attorney, bar number, and jurisdiction exist in `brand.yaml`. No byline on legal-content page = FAIL, route to `critical-editor` (add byline) or `sme-interviewer` (if the credential is missing from source).
3. **LEG-2 guarantee scan:** run a banned-pattern scan for guarantee/prediction language ("guarantee," "guaranteed," "we win," "you will get," "promise," "assured outcome"). Any hit in an outcome context = FAIL, route to `critical-editor`. Extend `scripts/compliance_lint.py` banned-claim patterns with the legal set.
4. **LEG-3 results check:** for every currency figure or result claim, confirm it traces to `case_results[]` (else G10 fabrication FAIL) and that a past-results disclaimer is present on the page. Missing disclaimer = FAIL.
5. **LEG-4 fee check:** if "no fee unless we win" (or variant) appears, confirm an honest cost/expense qualifier is present and consistent with `fee_structure`. Bare claim = FAIL.
6. **LEG-5 specialist check:** grep "specialist / expert / board-certified / certified"; each must map to a `certified_specialties[]` entry with the certifying body on-page. Unmatched = FAIL.
7. **LEG-6 jurisdiction check:** cross-check every claimed location/jurisdiction against `bar_jurisdictions[]` and the service-area truth; an implied representation outside admitted jurisdictions = FAIL, route to `outline-architect`/operator.
8. **Record each LEG rule as its own row** in `compliance-report.md` under a "Vertical overlay: legal" section, PASS/FAIL with evidence, alongside the base gate table.
9. **State-rule flag:** if any LEG-2/3/5/7 claim sits close to a line, add a report note: "State bar rule for `<jurisdiction>` not verified live this session; operator must confirm before publish." Do not silently pass a jurisdiction-dependent claim.

A legal page fails the overlay if any LEG **AF** rule fails, exactly as a base AF gate blocks publish.

---

## The sharpest rule for this vertical

**LEG-2 + LEG-3 together: never let the page promise or imply an outcome, and never let a real result read like a typical one.** The single fastest way to get a law-firm client sanctioned by their bar (and to trip Google's YMYL trust cap) is outcome language and undisclaimed result advertising. Real, disclaimed, contextualized results are a powerful E-E-A-T asset; the same results without context or disclaimer are a discipline complaint waiting to happen.

---

## Sources (fetched 2026-07-20 PKT; re-verify quarterly and against the client's state bar)

- ABA Model Rule 7.1 - Communications Concerning a Lawyer's Services: https://www.americanbar.org/groups/professional_responsibility/publications/model_rules_of_professional_conduct/rule_7_1_communication_concerning_a_lawyer_s_services/
- ABA Model Rule 7.1 - Comment (unjustified expectations, disclaimers): https://www.americanbar.org/groups/professional_responsibility/publications/model_rules_of_professional_conduct/rule_7_1_communication_concerning_a_lawyer_s_services/comment_on_rule_7_1/
- ABA Model Rule 1.5 - Fees (contingent-fee writing + client cost liability): https://www.americanbar.org/groups/professional_responsibility/publications/model_rules_of_professional_conduct/rule_1_5_fees/
- Example state adoption (California Rules of Professional Conduct, Ch. 7): https://www.calbar.ca.gov/Portals/0/documents/rules/New-Rules-of-Professional-Conduct-7.pdf
- Google Search Quality Rater Guidelines (YMYL standard): https://guidelines.raterhub.com/searchqualityevaluatorguidelines.pdf
- Internal: `knowledge/doctrine/google-compliance-spine.md` (C3, C4, C5, D3, E3); `knowledge/quality-gates/gates.md` (G2, G10, G12, G13).

*Jurisdiction-dependent rules are flagged inline. The ABA Model Rules are the floor; the client's licensing state controls. Confirm the state rule live before publishing any close-to-the-line claim.*
