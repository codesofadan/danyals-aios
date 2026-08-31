-- 0116 · A report reaches a client because someone decided it should.
--
-- WHAT WAS MISSING. `emit_deliverable` wrote every document straight to `ready`, and
-- `portal_deliverables` shows any ready row whose `requires` key the client holds. So
-- the moment an audit finished, its PDF was in front of the client - no review, no
-- approval, no way to hold one back short of revoking the whole report grant (which
-- would remove every other document of that kind at the same time).
--
-- The brief asks for three paths that all end the same way: an admin-generated report
-- is published after approval; a scheduled report enters review and is approved; a
-- client-requested report is produced, approved, and released. All three are the same
-- decision - "is this ready for the client to see" - so this adds ONE state for it
-- rather than a parallel approval system.
--
-- WHY NOT A NEW `approved` COLUMN. Visibility already lives in the view. A boolean
-- beside the status would mean two places can hide a document and a reader has to
-- know both; putting it in the status keeps "what state is this in" answerable from
-- one column, and keeps the view the single read surface a client has.
--
-- THE 55P04 RULE. A new enum label cannot be USED in the transaction that adds it, so
-- the view below is recreated against the labels that already exist ('ready',
-- 'generating') and simply stops matching the new one. Nothing here references
-- 'pending_review' by name.

alter type public.deliverable_status add value if not exists 'pending_review';

-- Every deliverable that exists TODAY is already visible to its client. Leaving them
-- to be re-approved would silently retract documents that have been delivered - the
-- opposite failure to the one this migration exists to fix. Only NEW emissions enter
-- review.
--
-- (No statement is needed to do this: existing rows are 'ready' or 'generating' and
-- both remain visible. Recorded here because "nothing happens to existing rows" is a
-- decision, not an omission.)

create or replace view public.portal_deliverables
  with (security_barrier = true) as
  select
    id,
    title,
    kind,
    icon,
    period,
    issued_at,
    size_label,
    status,
    requires
  from public.client_deliverables
  where client_id = public.current_client_id()
    -- The approval gate, enforced IN THE VIEW rather than in a response model: a row
    -- awaiting review is never selected, so no route - present or future - can serve
    -- it by forgetting to filter. `generating` stays visible because it is the
    -- client's own in-progress request, which they asked for and should see running.
    and status in ('ready', 'generating')
    and requires in (
      select report_key
      from public.client_report_grants
      where client_id = public.current_client_id()
    );

comment on view public.portal_deliverables is
  'Client-safe view of public.client_deliverables: safe display columns only, self-filtered to '
  'current_client_id(), to a granted `requires` key, AND to a status a client may see - a '
  'pending_review row is awaiting staff approval and is never selected here. '
  'Hides artifact_key/media_type/source_*.';

grant select on public.portal_deliverables to authenticated, anon;
