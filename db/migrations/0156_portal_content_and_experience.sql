-- 0156_portal_content_and_experience.sql - the client can see their content pipeline,
-- and can answer the questions that hold it.
--
-- TWO DECISIONS, ONE MIGRATION, because they are the same seam.
--
-- 1. READ-ONLY CONTENT VISIBILITY (operator decision 2026-09-26). The portal shows
--    audits, reports, deliverables, milestones and requests, and nothing at all about
--    content - so every "where is my page?" arrived as a message. `portal_content_jobs`
--    is the client-safe half of `content_jobs`: what stage each page is at, whether it
--    is published and where. The client APPROVES NOTHING; a lead remains the only
--    publisher, which is why this is a view and not a policy.
--
-- 2. THE EXPERIENCE QUESTIONS THE CLIENT IS THE ONLY ONE WHO CAN ANSWER. The content
--    pipeline halts every page until its first-party facts exist, and those facts live
--    in the business owner's head. Staff could answer on their behalf; the owner could
--    not answer at all. `portal_sme_dossiers` / `portal_sme_slots` let them READ their
--    own questions. The WRITE deliberately does NOT get a policy: it runs on the
--    privileged path with the client id pinned server-side from the authenticated
--    session (`app/services/client_experience.py`), exactly as `create_client_audit`
--    does for a portal-initiated audit. Giving the `client` role UPDATE on a table the
--    pipeline reads would be a much wider grant than the one capability we are adding.
--
-- WHAT IS DELIBERATELY EXCLUDED FROM THE CONTENT VIEW: cost (the agency's margin),
-- draft_md and every rich pipeline column (a draft under review is not a client-facing
-- document until a lead approves it), source_pack (it carries the publish target and
-- the design profile), assignee/created_by (staff identities), qa_score (an internal,
-- uncalibrated number the operator has deliberately stopped showing even to staff).
--
-- Every view is `security_barrier` and self-filters on `current_client_id()`, so a
-- client's own id never has to be supplied by - or trusted from - the request.

-- --- What the client may see about their own pages ---------------------------
create or replace view public.portal_content_jobs
  with (security_barrier = true) as
  select
    code,
    client_id,
    page_type,
    topic,
    status,
    stage,
    words,
    images,
    -- The permalink, once a publish actually reached their site. Null before that,
    -- which reads correctly as "not published yet" rather than as a broken link.
    wp_url,
    publish_at,
    created_at,
    updated_at
  from public.content_jobs
  where client_id = public.current_client_id();

comment on view public.portal_content_jobs is
  'Client-safe view of public.content_jobs, self-filtered to current_client_id(). '
  'Read-only by construction (a view): the client sees what stage each page is at and '
  'where it published, never the draft, the cost, the QA score or the publish target. '
  'Approval stays a lead action.';

-- --- The client's own Experience questions -----------------------------------
create or replace view public.portal_sme_dossiers
  with (security_barrier = true) as
  select
    d.id,
    e.client_id,
    d.cluster_key,
    d.status,
    d.created_at,
    d.updated_at
  from public.sme_dossiers d
  join public.content_engagements e on e.id = d.engagement_id
  where e.client_id = public.current_client_id();

comment on view public.portal_sme_dossiers is
  'Client-safe view of public.sme_dossiers via the engagement''s client_id, '
  'self-filtered to current_client_id().';

create or replace view public.portal_sme_slots
  with (security_barrier = true) as
  select
    s.id,
    e.client_id,
    s.dossier_id,
    s.slot_key,
    s.question,
    s.answer,
    s.artifact_url,
    s.answer_evidence,
    s.answered_at,
    -- The KIND of origin is client-safe and useful to them ("you answered this");
    -- `answered_by` is a staff/user id and is deliberately not exposed.
    s.source,
    s.updated_at
  from public.sme_slots s
  join public.sme_dossiers d on d.id = s.dossier_id
  join public.content_engagements e on e.id = d.engagement_id
  where e.client_id = public.current_client_id();

comment on view public.portal_sme_slots is
  'Client-safe view of public.sme_slots via the dossier''s engagement, self-filtered to '
  'current_client_id(). Excludes answered_by (a user id). The client''s ANSWER is written '
  'through the privileged service path with the client id pinned from the session, not '
  'through an UPDATE policy on this table.';

grant select on public.portal_content_jobs  to authenticated, anon;
grant select on public.portal_sme_dossiers  to authenticated, anon;
grant select on public.portal_sme_slots     to authenticated, anon;
