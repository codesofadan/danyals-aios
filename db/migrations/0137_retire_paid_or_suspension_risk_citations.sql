-- 0137_retire_paid_or_suspension_risk_citations.sql
-- Research reviewed 2026-09-08. Keep historical rows for reporting, but never
-- offer these targets to a new campaign: paid-only/identity-gated properties and
-- platforms whose terms or moderation practice make automated SEO placements unsafe.
-- This is intentionally additive and idempotent; existing citations are not deleted.

update public.directories
set active = false,
    tier = 'manual_only',
    route = 'F',
    submit_method = 'closed',
    automation_note = 'Retired 2026-09-08: paid-only, identity-gated, or suspension-risk target; no automated citation work.'
where name in (
  'Data Axle (Local Listings)',
  'TransUnion / Neustar (Localeze)',
  'FindLaw',
  'Nolo / Lawyers.com',
  'Zocdoc',
  'Psychology Today',
  'HomeAdvisor',
  'OpenTable',
  'Grubhub',
  'Cars.com / CarGurus',
  'Checkatrade',
  'RatedPeople',
  'Thebestof',
  'Yelp',
  'Yelp UK',
  'Yelp Australia',
  'Trustpilot',
  'Houzz',
  'OpenStreetMap'
);

-- Web 2.0 research (R2b, 2026-09-02): these properties either charge for hosting,
-- require an administration permit, or actively remove SEO content. They remain in
-- the catalogue as historical evidence, but cannot receive new placements.
update public.web2_platforms
set ownership_tier = 'do_not_use',
    automation_ready = false,
    terms_checked_on = date '2026-09-08',
    terms_position = 'Retired: paid-only, permission-gated, or actively removes SEO content; no new AIOS placements.'
-- Bluesky (free, open AT-Protocol API) and Internet Archive (free, non-commercial)
-- were REMOVED from this list 2026-09-08: neither is paid-only, permission-gated, nor
-- an SEO-content remover, so retiring them was over-broad. They stay usable.
where name in ('Mataroa', 'Micro.blog', 'LiveJournal', 'Dreamwidth', 'Pastebin.com');

-- NOTE: web2_accounts has no `status` column — account state lives in `health`
-- (enum web2_account_health: active|degraded|suspended|deleted|unverified). Never
-- downgrade an account already gone.
update public.web2_accounts
set health = 'degraded'
where platform in ('Mataroa', 'Micro.blog', 'LiveJournal', 'Dreamwidth')
  and health not in ('suspended', 'deleted');
