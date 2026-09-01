# Sources - Climate Controlled Storage in Round Rock

Every fact on `page.md` and its source. [SAMPLE] client: the operator facts are demonstration data standing in for real SME-supplied values; in production each carries its real provenance and is externally verifiable. Per the output contract, no local specific ships without a source here.

## First-party operator facts (SME / brand.yaml)

| Fact on page | Source | Tag |
|---|---|---|
| Held climate range 55-80F with dehumidification; thermostats checked Monday | sme-answers.md #3; brand.yaml `storage.climate_control` (temp_range_f "55-80", humidity_control true) | SME |
| 10x10 climate ~$129/mo; live PMS pricing ("the price you see is the price you rent") | sme-answers.md #4; brand.yaml `storage.live_inventory: true` | SME |
| First month free; one-time $25 admin fee; protection plan or own policy required | sme-answers.md #7; brand.yaml `storage.move_in_special`, `storage.admin_fee` "$25" | SME |
| Protection plan is the operator's own plan, not insurance | sme-answers.md #7; brand.yaml `storage.tenant_protection_type: protection_plan` | SME |
| 28 HD cameras, recorded 24/7, footage kept 90 days; per-tenant gate code logged; individually alarmed climate units; motion LED; manager on site Tue-Sat | sme-answers.md #2; brand.yaml `storage.security_features` | SME |
| Days-without-a-break-in since 2021-03-14, past 1,240 days | sme-answers.md #2; brand.yaml `storage.break_in_free_since: 2021-03-14` | SME |
| Gate access 6am-10pm daily; office Mon-Fri 9-6, Sat 9-5, closed Sunday | sme-answers.md #5; brand.yaml `storage.access_hours`, `storage.office_hours` | SME |
| Manager Dana Reyes, CSSM (certified 2023-09), 6 years | sme-answers.md #6; brand.yaml `storage.manager`, `eeat.team` | SME |
| 2100 N Mays St, Round Rock, TX 78664; (512) 555-0148 | brand.yaml `nap` / `locations[0]` | brand.yaml (byte-identical, nap_checker PASS) |
| N Mays St / I-35 corridor; apartment turnover drives 10x10 demand | sme-answers.md #8, #10 | SME |
| Founded 2011, family-owned; Texas Self Storage Association member | brand.yaml `client.founded_year`, `eeat.credentials` | brand.yaml |

## Industry-standard patterns (not client facts; used only as framing, not published as specifics)

| Fact | Source | Note |
|---|---|---|
| A 10x10 holds a one-bedroom apartment + ~100 boxes | Industry-standard size mapping (CubeSmart/Public Storage size guides, `research/self-storage-2026-07/01-site-architecture.md`) | The what-fits pattern; the client's real inventory/price is the SME price above |
| "Climate controlled" is not a regulated term | `research/self-storage-2026-07/07-compliance-legal.md` (SS-5, DiSanto v. Safeco); StoragePug | The honesty-lever basis |

## Compliance basis (for the auditor, not published as copy)

- SS-1 (protection plan not insurance): `Heckart v. A-1 Self Storage` (Cal. 2018) - `research/self-storage-2026-07/07-compliance-legal.md`
- SS-5 (climate + moisture only with humidity control): `DiSanto v. Safeco` (OH 2006) - same
- SS-6 ("free" in-line disclosure): 16 CFR 251.1 - same
- SS-11 (lien timeline): TX Property Code ch. 59 - same

No external factual claim on this page requires a live citation URL (all specifics are first-party). Re-verify the $129 rate and the break-in-free day count at publish time (perishable).
