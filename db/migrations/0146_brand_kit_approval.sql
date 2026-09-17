-- 0146_brand_kit_approval.sql - a captured design is not the client's design
-- system until a human says it is.
--
-- WHY THIS EXISTS. `0089` made the design PERSISTENT and versioned, and the content
-- pipeline now builds every page to the client's active kit. That closed the old
-- defect (a measured design that died with the wizard screen) and opened a new one:
-- whatever the analyzer last produced silently became the thing dozens of pages are
-- built to. The analyzer is good but not infallible - a bot-blocked capture, a
-- cookie wall, a site mid-redesign, or the vision fallback reading a screenshot
-- loosely all yield a profile that VALIDATES and is wrong. Publishing forty pages to
-- a wrong design system is expensive to discover and expensive to undo.
--
-- So approval is recorded as a FACT about a kit, with who and when. The generation
-- path reads an APPROVED kit; an unapproved capture is stored, visible and
-- reviewable, but does not shape pages.
--
-- APPROVAL IS SEPARATE FROM ACTIVE, deliberately. `active` answers "which capture is
-- current" (one per client, enforced by the partial unique index in 0089).
-- `approved_at` answers "has a human accepted it". A re-capture can therefore become
-- the active kit while the previously approved one keeps building pages, which is the
-- safe order: a fresh capture never silently changes what is being published.
--
-- NULLABLE, no backfill. A kit captured before this migration was never reviewed by
-- anyone, and stamping it approved would be inventing a human decision that did not
-- happen - the exact class of thing this system must not do. Existing kits therefore
-- read as unapproved, and an operator approves the one they want.
--
-- ON DELETE SET NULL for the approver: a staff member leaving must not delete the
-- record that the approval happened.

alter table public.brand_kits
  add column if not exists approved_at timestamptz,
  add column if not exists approved_by uuid references public.users (id) on delete set null;

comment on column public.brand_kits.approved_at is
  'When a human accepted this capture as the client''s design system. NULL = never '
  'reviewed; the generation path will not build pages to it.';
comment on column public.brand_kits.approved_by is
  'Who approved it. NULL after the approver is deleted - the approval still stands.';

-- The generation read is "this client''s approved kit, newest first", so it is
-- indexed for that and not for the general case.
create index if not exists brand_kits_client_approved_idx
  on public.brand_kits (client_id, approved_at desc)
  where approved_at is not null;
