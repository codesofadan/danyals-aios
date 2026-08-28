-- 0102_web2_similarity.sql - storage for the CROSS-PROPERTY similarity gate
-- (WEB2-007 / R2-09 of docs/research/R2-web2-safety.md).
--
-- WHAT THIS PROTECTS. A Web 2.0 property is defensible only while it is a genuine brand
-- asset. The moment two properties share a skeleton, the set stops being N independent
-- blog posts and becomes ONE detectable pattern - which is what gets a whole client base
-- actioned at once instead of a single placement removed. `content_qa`'s originality
-- score cannot see this: it compares a document only against ITSELF. Only a
-- cross-document, cross-client comparison can, and nothing in the schema could express
-- one before this migration.
--
-- WHY TWO TABLES. `web2_doc_fingerprints` holds the FULL hash sets, which is what an
-- exact Jaccard needs. `web2_shingle_index` holds only Broder's MOD_16 sample - roughly
-- one hash in sixteen - and exists purely to GENERATE candidates: "which prior documents
-- share at least two sampled hashes with this draft". Scoring then runs on the full
-- arrays, so the sample shrinks the search without ever changing a verdict. Comparing a
-- draft against every prior document in Python would mean loading every prior document.
--
-- WHAT IT DELIBERATELY DOES NOT STORE. No text, ever. The gate runs on the privileged
-- pool because it is the one place that legitimately reads ACROSS tenants, and it must
-- return only a verdict, a scope label, and the colliding web2_id - never another
-- client's prose. Hashes are one-way; a shingle hash cannot be read back into a sentence.
--
-- DEPARTURE FROM R2-09, STATED. R2-09 writes `account_id ... not null`. That cannot hold
-- yet: `web2_properties.account_id` is nullable until the R2-07 reconciliation attributes
-- historic rows (0101), so a NOT NULL here would make every un-migrated property
-- unfingerprintable - the gate would silently cover only the newest rows, which is the
-- worst possible failure for a safety control (it would look installed and be partial).
-- It is nullable here, and the S2 (same-account) scope simply does not apply to a row
-- with no known account - correctly, because a property with no attributed account has
-- no account-mates to collide with.

-- --- Fingerprints: one row per property, written on APPROVAL ---------------------
-- Written at approval rather than at draft (R2-11) so a rejected or redrafted article
-- never pollutes the corpus that later drafts are measured against.
create table if not exists public.web2_doc_fingerprints (
  id                uuid primary key default gen_random_uuid(),
  web2_id           uuid not null references public.web2_properties (id) on delete cascade,
  client_id         uuid not null references public.clients (id) on delete cascade,
  -- Nullable by design - see the header. NOT the R2-09 text, deliberately.
  account_id        uuid references public.web2_accounts (id) on delete set null,
  platform          public.web2_platform not null,
  -- sha256 of the MASKED, normalized body: catches "identical except the brand and the
  -- city", which is what a fan-out of one article across platforms actually looks like.
  body_sha256       text not null,
  -- Signed 64-bit blake2b digests. bigint because Postgres bigint IS signed 64-bit and
  -- the hashes are generated signed to match (see content_lint.duplication).
  shingle_hashes    bigint[] not null default '{}',
  shingle_count     int not null default 0,
  heading_hashes    bigint[] not null default '{}',
  anchor_norm       text not null default '',
  status_at_capture public.web2_status not null default 'published',
  created_at        timestamptz not null default now()
);

-- One fingerprint per property: re-approving replaces rather than accumulates.
create unique index if not exists web2_doc_fp_web2_uq
  on public.web2_doc_fingerprints (web2_id);
-- The three R2-10 scopes, each backed by the index its query needs.
create index if not exists web2_doc_fp_client_idx
  on public.web2_doc_fingerprints (client_id);
create index if not exists web2_doc_fp_account_idx
  on public.web2_doc_fingerprints (account_id) where account_id is not null;
create index if not exists web2_doc_fp_plat_time_idx
  on public.web2_doc_fingerprints (platform, created_at desc);
-- The exact-duplicate probe is a direct equality lookup, not a scan.
create index if not exists web2_doc_fp_sha_idx
  on public.web2_doc_fingerprints (body_sha256);

alter table public.web2_doc_fingerprints enable row level security;
alter table public.web2_doc_fingerprints force row level security;

-- Staff may READ (the board shows which property collided); nothing writes through the
-- RLS path at all. The only writer is the approval worker on service_role, so there is
-- deliberately NO insert/update policy: a fingerprint is a derived fact the platform
-- records, never something an operator authors by hand.
create policy web2_doc_fingerprints_select on public.web2_doc_fingerprints
  for select using (public.is_staff());

comment on table public.web2_doc_fingerprints is
  'Per-property content fingerprints (masked-body sha256 + shingle/heading hash sets) '
  'for the cross-property similarity gate. Hashes only - never text. Written on '
  'approval so rejected drafts never enter the corpus (R2-09/R2-11).';

-- --- The MOD_16 candidate index --------------------------------------------------
create table if not exists public.web2_shingle_index (
  shingle_hash   bigint not null,
  fingerprint_id uuid not null
    references public.web2_doc_fingerprints (id) on delete cascade,
  primary key (shingle_hash, fingerprint_id)
);

-- The PK already serves the hash -> fingerprints lookup; this one serves the reverse
-- (delete/replace a document's sample when its fingerprint is rewritten).
create index if not exists web2_shingle_index_fp_idx
  on public.web2_shingle_index (fingerprint_id);

alter table public.web2_shingle_index enable row level security;
alter table public.web2_shingle_index force row level security;

create policy web2_shingle_index_select on public.web2_shingle_index
  for select using (public.is_staff());

comment on table public.web2_shingle_index is
  'Broder MOD_16 sample of each fingerprint''s shingle hashes - candidate generation '
  'only. Scoring always uses the full arrays on web2_doc_fingerprints, so the sample '
  'narrows the search and can never change a verdict.';
