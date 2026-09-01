-- 0124 — the standing per-client Web 2.0 brief.
--
-- WHY THIS IS STORED AND NOT ASKED EVERY TIME. The generator grounds a draft against
-- first-hand facts (real projects, results, credentials, and the something-only-this-
-- client-knows), and a draft written without them holds at review on [NEEDS:] gaps and
-- cannot publish. Those facts live in the campaign REQUEST today, so the wizard starts
-- empty on every run: the operator either retypes them for each campaign of each client
-- or - far more likely at twenty clients - skips them and ships a campaign that parks
-- unpublishable. Storing them once per client makes the grounded path the easy one.
--
-- WHY JSONB AND NOT FOUR COLUMNS. These are four ordered lists whose shape is the
-- generator's contract (`source_pack`), not this table's. Keeping them as one document
-- means a future generator field needs no migration here, and the campaign path can keep
-- treating source_pack as the single object it already builds.
--
-- SNAPSHOT SEMANTICS ARE UNCHANGED AND DELIBERATE: a campaign still COPIES these facts
-- into each property's source_pack at create time. Editing the brief later must not
-- silently rewrite what an already-drafted article was grounded against.

alter table public.clients
  add column if not exists web2_brief jsonb not null default '{}'::jsonb;

comment on column public.clients.web2_brief is
  'The standing grounding pack for this client''s Web 2.0 articles: proof_points, '
  'testimonials, unique_data, services. Campaigns COPY it into each property''s '
  'source_pack at create time (a later edit never rewrites drafted work). Stored once '
  'per client because a draft written without these facts holds at review, unpublishable.';
