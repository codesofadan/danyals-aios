-- 0155_experience_attestation.sql - an experience answer is someone's attestation, and
-- the row now says whose.
--
-- WHY THIS EXISTS. The Experience gate (0087, `sme_slots`) refuses to draft a page until
-- its first-party facts are supplied, because a model asked for experience invents it
-- fluently and no downstream reader can catch the difference. That gate is unchanged.
-- What changes is the INTAKE: the operator's decision (2026-09-26) is that the questions
-- are answered by PICKING from concrete options rather than writing prose, so a business
-- owner can fill a cluster in minutes instead of abandoning a form.
--
-- That decision only stays honest if the options are drawn from the client's OWN
-- evidence and the pick is recorded as an attestation. A suggested answer nobody can
-- account for six months later is exactly the fabrication the gate exists to stop - the
-- difference between "the client confirmed they have traded since 2016" and "something
-- suggested 2016" is entirely in the provenance, and until now there was nowhere to
-- store it.
--
-- WHAT EACH COLUMN IS FOR.
--
--   answer_evidence  WHERE the offered option came from, in words a human can check:
--                    "your website's About page", "your Google profile", "answered for
--                    the emergency-repair cluster on 12 Sep". Empty for a typed answer,
--                    which needs no provenance beyond who typed it.
--   answered_by      WHO attested it. `source` (0087) already records the KIND of
--                    origin (client / operator / transcript / client_site); this records
--                    the identity, which is what makes the attestation falsifiable.
--   answered_at      WHEN. `updated_at` moves on any edit - a question rewritten by the
--                    SME stage bumps it - so it cannot answer "when was this attested".
--
-- Nothing is backfilled. Existing answered slots keep `answered_by = null`, which reads
-- correctly as "attested before we recorded who", not as "attested by nobody".
--
-- Additive and idempotent: three ADD COLUMN IF NOT EXISTS, no value rewritten, no policy
-- change (`sme_slots` already ENABLE + FORCE RLS with staff read/write from 0087).

alter table public.sme_slots
  add column if not exists answer_evidence text not null default '';

alter table public.sme_slots
  add column if not exists answered_by uuid references public.users (id) on delete set null;

alter table public.sme_slots
  add column if not exists answered_at timestamptz;

comment on column public.sme_slots.answer_evidence is
  'Where the offered option came from, in checkable words ("your website''s About page", '
  '"your Google profile", "answered for another cluster on 12 Sep"). Empty for a typed '
  'answer. This is the provenance that separates a client-attested fact from a '
  'plausible suggestion, and it is carried into the draft''s grounding trace.';

comment on column public.sme_slots.answered_by is
  'The user who attested this answer. `source` records the kind of origin; this records '
  'the identity. Null on rows answered before 0155, which means "not recorded", never '
  '"nobody".';

comment on column public.sme_slots.answered_at is
  'When the answer was attested. Distinct from updated_at, which also moves when the '
  'SME stage rewrites the question.';

-- The dossier-library read: "which clusters for this client still hold unanswered
-- slots, and when was the last attestation". Ordered by the attestation time, so the
-- index carries it.
create index if not exists sme_slots_answered_at_idx
  on public.sme_slots (dossier_id, answered_at desc nulls last);
