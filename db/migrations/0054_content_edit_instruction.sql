-- 0054_content_edit_instruction.sql - the reviewer's GUIDED-EDIT note.
--
-- The content review gate (POST /content/{code}/review) has three actions:
-- approve / reject / edit. Until now `edit` sent the job back to `drafting` with
-- NO way for the reviewer to say WHAT to change - the worker then blind-regenerated
-- from scratch. This column carries the reviewer's free-text instruction (e.g.
-- "make the intro punchier, add an FAQ, tighten the H2s") so the re-draft is a
-- GUIDED edit: the worker feeds the note into a cost-gated per-section rewrite
-- (content_guard) that targets exactly what the reviewer asked, then re-runs the
-- em-dash guard + the QA gate and returns to needs_review.
--
-- Lifecycle: a LEAD sets it on the needs_review -> drafting transition (the guard's
-- lead path allows any legal column edit alongside the status change); the WORKER
-- reads it, applies it, and CLEARS it back to '' when it writes needs_review (so a
-- later unrelated re-run does not re-apply a stale instruction). Default '' keeps
-- every existing row + the ordinary first-draft path unchanged.
--
-- Not a tenant boundary (server-only, like the other rich pipeline columns), so no
-- RLS policy change and the RLS gate is unaffected. Idempotent (safe to re-run).

alter table public.content_jobs
  add column if not exists edit_instruction text not null default '';

comment on column public.content_jobs.edit_instruction is
  'The reviewer''s free-text guided-edit instruction for the next re-draft; set by a '
  'lead on needs_review->drafting, read + cleared by the worker on drafting->needs_review.';
