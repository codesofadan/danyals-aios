-- 0059_web2_source_pack.sql
-- Web 2.0 grounding: the first-hand proof the writer grounds against.
--
-- The Web 2.0 write worker calls the SAME ranking-grade content generator as the
-- Content module, which emits a `[NEEDS:]` gap (never a hallucination) for any fact
-- it cannot trace to a source pack. Until now the worker passed NO source pack, so
-- every planned property drafted with those gaps and HELD at the review gate,
-- un-publishable. This column carries the operator-supplied proof / testimonials /
-- unique data / services (mirrors `content_jobs.source_pack`), seeded at plan time
-- and read by the worker, so a property planned WITH proof drafts gap-free.
--
-- Additive + idempotent; existing rows default to an empty pack (they keep degrading
-- to [NEEDS:] exactly as before). No new table -> the FORCE-RLS gate is unaffected;
-- the existing web2_properties policies (0018) already gate every row.

alter table public.web2_properties
  add column if not exists source_pack jsonb not null default '{}'::jsonb;
