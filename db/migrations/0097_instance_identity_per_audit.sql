-- 0097_instance_identity_per_audit.sql - an occurrence belongs to the audit that
-- observed it.
--
-- 0094 made an instance unique on `(finding_id, instance_key)`. That was wrong in
-- a way that only appears once a site is audited TWICE.
--
-- A finding is a persistent CAUSE that many audits observe. An instance is what
-- ONE audit saw. With the audit left out of the identity, the second audit to
-- observe the same occurrence hit `on conflict do nothing` and its evidence was
-- silently discarded - so the newer run under-reported, and the older run's rows
-- were the ones that survived.
--
-- MEASURED: re-ingesting a 12-page run of a site that had already had a 197-page
-- run left the 197-page audit reporting 7,591 of its 8,077 occurrences. 486 rows
-- went missing, with no error, because two audits genuinely saw the same page
-- fail the same check.
--
-- Together with the scoped delete in `audit_ingest`, this makes per-audit
-- evidence durable: an audit's report can be regenerated from its own rows, months
-- later, without a subsequent run having quietly edited it.

alter table public.audit_finding_instances
  drop constraint if exists audit_finding_instances_finding_id_instance_key_key;

-- AND the audit reference becomes a CASCADE.
--
-- It was `on delete set null`, which is wrong twice over now. Semantically, an
-- instance is evidence GATHERED BY one audit - orphaning it from that audit
-- leaves a row that describes an observation nobody made. Mechanically, nulling
-- the column collapses instances from different audits onto the same identity and
-- the unique index below rejects the delete outright, so removing an audit fails.
alter table public.audit_finding_instances
  drop constraint if exists audit_finding_instances_audit_id_fkey;
alter table public.audit_finding_instances
  add constraint audit_finding_instances_audit_id_fkey
  foreign key (audit_id) references public.audits (id) on delete cascade;

drop index if exists audit_fi_identity_idx;
create unique index audit_fi_identity_idx
  on public.audit_finding_instances (audit_id, finding_id, instance_key);

comment on index public.audit_fi_identity_idx is
  'One occurrence per (audit, finding, locus). The audit is part of the identity: '
  'two audits legitimately observe the same page failing the same check.';
