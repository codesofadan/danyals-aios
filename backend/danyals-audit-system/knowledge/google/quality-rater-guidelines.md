# Google Search Quality Rater Guidelines - summary for SEO-AUDIT-OS agents

Loaded by: A1 (Content + E-E-A-T), A2 (Keyword + Semantic), M3 (Critic).
Source: Google Search Quality Evaluator Guidelines, updated periodically. This summary distills the parts that map to checklist findings; it is not a substitute for reading the source PDF.

## Page Quality Rating - the framework Google uses

The QRG asks raters to evaluate a page on three dimensions:

1. **Purpose of the page**: every page exists to do something (inform, transact, navigate). Pages whose purpose is unclear or whose purpose is harmful (deceive, plagiarize, mislead) are rated Lowest regardless of polish.
2. **E-E-A-T**: Experience, Expertise, Authoritativeness, Trustworthiness. Trust is the dominant of the four. A page can rank without deep expertise (a personal product review) but it cannot rank without trust signals.
3. **Beneficial purpose + how the page achieves it**: a thin page can be useful (a phone number for an emergency); a long page can be harmful (intentionally bad medical advice).

## E-E-A-T rubric you apply per check

| Signal | What "high E-E-A-T" looks like | What "low" looks like |
|---|---|---|
| Experience | Author cites first-hand use, real photos, dates, places | "I have heard..." or no specifics |
| Expertise | Author credentials shown, named, verifiable on the web | Anonymous, vague "expert team" |
| Authoritativeness | Site is the canonical source for the topic; cited by reputable peers; structured About-Us | New domain, no peer mentions |
| Trustworthiness | HTTPS, accurate contact info, clear ownership, refund/return policies, no deceptive UX | Hidden ownership, deceptive ads, no contact info, no policies |

## "Your Money or Your Life" (YMYL)

YMYL topics affect health, safety, finances, civic decisions. Google raises the E-E-A-T bar dramatically for YMYL pages. A YMYL finding deserves a higher severity for the same on-page issue than the equivalent on a hobby blog. When the audit detects a YMYL topic, A1 upgrades its E-E-A-T-related severities by one level.

## Page quality levels (paraphrased)

- **Lowest**: harmful, deceptive, plagiarized, untrustworthy. Audit response: severity=critical.
- **Low**: unsatisfying main content, low E-E-A-T, untrustworthy info. Audit response: severity=major.
- **Medium**: meets purpose, baseline E-E-A-T. Audit response: pass for most checks unless competitor-relative judgement applies.
- **High**: satisfies, high quality. Audit response: pass + opportunity flags only.
- **Highest**: outstanding, authoritative. Audit response: pass; surface as positive signal.

## Specific anti-patterns the rater catches (and you should flag)

- Hidden text or links (TECH-083, ON-108)
- Sneaky redirects or cloaking (TECH-084)
- Auto-generated low-value content (ON-024, TECH-080)
- Plagiarized content (ON-030)
- Excessive ads or interstitials that block main content
- Missing or vague author byline on commercial / advice content (ON-029)
- Inaccurate claims unsupported by sources

## How M3 uses this

When validating a critical finding, M3 must be able to point to a specific QRG concept. "I rated this critical because the page is a YMYL medical claim with no author credentials and no source citations - QRG section on Low Quality Pages."
