-- 0161_public_page_views_and_expiry.sql - a shared audit link becomes a sales tool:
-- was it opened, and when should it stop working.
--
-- WHAT A SHARED LINK IS FOR. 0126 minted a readable public page per completed report so an
-- operator can paste it into a WhatsApp message or a Fiverr conversation. That is an
-- OUTREACH artifact, and outreach has exactly two questions the platform could not answer:
--
--   1. WAS IT OPENED? Following up blind and following up on a signal are different jobs.
--      Until now nothing recorded a single view, so the person who sent the link learned
--      nothing from sending it.
--   2. SHOULD IT LIVE FOREVER? A published page stays open to anyone holding the URL until
--      somebody remembers to withdraw it - including after the client has gone.
--
-- WHAT IS DELIBERATELY NOT COLLECTED. A count, a timestamp and nothing else. No visitor
-- identifier, no IP, no user agent, no per-view row. The route is unauthenticated and
-- anyone can open it, so anything more would turn a report link into tracking
-- infrastructure aimed at people who never agreed to it - and the operator's actual
-- question ("did they look?") is fully answered by a number and a date.
--
-- EXPIRY IS OPT-IN AND INDISTINGUISHABLE FROM UNPUBLISHED. When a page has passed its
-- expiry the read route answers exactly as it does for a slug that was never published:
-- the same 404, the same body. A distinct "this link has expired" response would confirm
-- to a stranger that a report for that brand exists, which is precisely what the random
-- slug suffix on a paid page exists to prevent.
--
-- NULL `expires_at` means "no expiry", which is what every existing page has and stays.

alter table public.public_audit_pages
  add column if not exists views integer not null default 0;

alter table public.public_audit_pages
  add column if not exists last_viewed_at timestamptz;

alter table public.public_audit_pages
  add column if not exists expires_at timestamptz;

comment on column public.public_audit_pages.views is
  'How many times the published page has been opened. A count, deliberately, and not a '
  'per-view ledger: the operator''s question is "did they look?", and anything that could '
  'answer more than that would be tracking people who never agreed to it.';

comment on column public.public_audit_pages.last_viewed_at is
  'When it was last opened. The other half of the follow-up signal.';

comment on column public.public_audit_pages.expires_at is
  'When this link stops resolving, or NULL for no expiry (the existing behaviour). Past '
  'this instant the read route answers exactly as it does for an unpublished slug - same '
  'status, same body - because a distinct "expired" reply would confirm to a stranger that '
  'a report for that brand exists.';

-- The resolve path now also reads `expires_at`, so the partial index stays useful only if
-- it carries it: a published-but-expired row should not cost a heap fetch to reject.
drop index if exists public_audit_pages_published_idx;
create index if not exists public_audit_pages_published_idx
  on public.public_audit_pages (slug, expires_at) where published;
