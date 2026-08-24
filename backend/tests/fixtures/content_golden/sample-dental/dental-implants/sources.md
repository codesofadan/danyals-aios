# Sources - Dental Implants service page (sample-dental)

Every non-obvious factual claim on the page, with its source. SME-sourced facts are tagged [SME]. Health-efficacy claims (MED-3) require a real, citable clinical source before publish; those are tagged [VERIFY-AT-PUBLISH] because this is a demonstration run and the citations were not fetched live.

## Clinical / efficacy claims (MED-3 substantiation)

| Claim on page | Source status |
|---|---|
| Implants fuse to bone via osseointegration over 3-6 months | Established implant literature. [VERIFY-AT-PUBLISH: cite a specific peer-reviewed source] |
| Implant survival rates are high over ten-plus years (stated without a specific percentage on the page) | Systematic reviews report ~90-95% 10-year survival. Deliberately kept qualitative on the page to avoid an unsubstantiated exact figure. [VERIFY-AT-PUBLISH: cite the specific review before publishing any number] |
| Implants help slow the jawbone loss that follows tooth loss | Established resorption/osseointegration literature. [VERIFY-AT-PUBLISH: cite specific source] |
| Smoking and uncontrolled diabetes lower implant success | Established risk-factor literature. [VERIFY-AT-PUBLISH: cite specific source] |
| Risks: infection, failure to integrate, nerve/sinus involvement, need for graft | Standard informed-consent risk set for implant surgery. [SME, confirmed clinically] |

## Practice facts (Experience artifacts)

| Fact on page | Source |
|---|---|
| In-house periodontist places, in-house prosthodontist restores | [SME - brand.yaml.eeat.differentiators] |
| CBCT 3D scan + guided surgery at all three offices | [SME - brand.yaml.eeat.credentials] |
| 6,000+ implants placed since 2009 | [SME - brand.yaml.eeat.proof] |
| Three offices: Santa Monica (Wilshire), Pasadena (South Lake), Glendale (North Brand) | [SME - brand.yaml.locations; NAP byte-checked] |
| Financing via CareCredit, staged payments | [SME - brand.yaml] |
| Single-case timeline 4-9 months; placement 60-90 min | [SME - sme-answers.md] |

## Compliance notes carried into the page
- No patient testimonial, review quote, or before/after image appears on the page: zero HIPAA marketing consents on file (MED-4). This was a hard constraint, not an oversight.
- No guarantee, "painless," or superlative language used (MED-2). Reviewed-by byline present (MED-1).
- No review/aggregateRating schema on the practice's own node (MED-6 / spine D3).

## Demonstration disclaimer
This is a pipeline test on a fictional client. Business name, providers, license numbers, phone numbers, and counts are SAMPLE values. Before any real publish, every [VERIFY-AT-PUBLISH] citation must be fetched and cited, and every [SAMPLE] value replaced with the client's real, verifiable data.
