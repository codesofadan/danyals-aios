-- 0147_client_local_business.sql - whether a client is a LOCAL business, stated
-- rather than guessed.
--
-- THE TWO DEFECTS THIS CLOSES, which are the same mistake in both directions.
--
-- The audit engine gates its whole local pipeline (Google Places lookup, citation
-- discovery, the LOC-* checks) on `--profile local`, and the backend decided that
-- from DEPTH alone: `deep` meant local, anything less meant not.
--
--   1. NO CLIENT EVER GOT LOCAL FINDINGS. A portal client's audit runs at the depth
--      their tier implies, and Paid implies `standard` - so the local pipeline was
--      unreachable from the surface clients actually use. The checks existed and
--      nobody they were for could receive them.
--
--   2. EVERY DEEP AUDIT PAID FOR LOCAL WORK, local business or not. A SaaS or
--      e-commerce client's deep audit ran Places lookups and citation queries about
--      a Google Business Profile they do not have - real money, and findings that
--      describe an absence that was never a problem.
--
-- WHY A COLUMN AND NOT AN INFERENCE. The obvious shortcut is "a client with a stored
-- NAP is local". It is wrong in the direction that hurts: an operator who has not
-- filled in the NAP yet would silently lose the local checks their client is paying
-- for, and nothing on the report would say so. Absence of a record is not evidence
-- about the business. So the fact is stored, by a human, and read.
--
-- DEFAULT FALSE, NO BACKFILL. Every existing client reads as not-local until someone
-- says otherwise. That is the honest default - nobody has been asked this question
-- yet - and it is the SAFE one: the failure mode is a missing local section an
-- operator can turn on, not a surprise bill and a page of findings about a profile
-- that does not exist.

alter table public.clients
  add column if not exists is_local_business boolean not null default false;

comment on column public.clients.is_local_business is
  'Whether this client is a local business (storefront or service area), so audits '
  'run the local pipeline: Google Business Profile lookup, citation discovery and '
  'the LOC-* checks. Stated by an operator, never inferred from whether a NAP '
  'happens to be filled in.';
