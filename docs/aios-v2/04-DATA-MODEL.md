# 04 · Data Model

PostgreSQL 16. One database. Every rule here is enforced by a CI gate, not by convention.

---

## 1. Conventions

| Rule | Detail |
|---|---|
| Primary keys | `uuid` with `gen_random_uuid()`. No sequential integer ids on tenant data |
| Timestamps | `timestamptz` always, UTC always. `created_at`, `updated_at` on every table; `updated_at` maintained by trigger |
| Soft delete | Only where restoration is a real requirement (`clients`, `content_pages`). Everything else deletes |
| Money | `integer` cents. Never float |
| Enums | Postgres enums for closed sets that the application branches on. `text` + CHECK for sets that churn |
| JSON | `jsonb`, and only for genuinely open payloads (provider responses, job payloads, artefacts). **Never for data the application queries or validates** — that becomes columns |
| Naming | `snake_case`, plural tables, `<table>_<column>_idx` indexes, `fk_<table>_<ref>` constraints |
| Append-only | Measurement tables (`rank_observations`, `grid_points`, `cost_ledger`, `activity_log`, `side_effects`) have no `UPDATE` grant. Corrections are new rows |

---

## 2. Tenancy and RLS

**The tenant key is `client_id`.** Every table holding client data carries it — denormalised
onto child tables rather than joined through a parent, so the policy is a single predicate.

Every such table:

```sql
alter table <t> enable row level security;
alter table <t> force  row level security;          -- FORCE: applies to the table owner too

create policy <t>_tenant on <t>
  using      (client_id = current_setting('aios.client_id', true)::uuid
              or current_setting('aios.scope', true) = 'staff')
  with check (client_id = current_setting('aios.client_id', true)::uuid
              or current_setting('aios.scope', true) = 'staff');
```

- The application sets `aios.client_id` and `aios.scope` per transaction from the
  authenticated principal, in one place (`platform/db/session.py`). No other code touches
  these settings.
- Staff scope is not "no policy" — staff still read through the policy, which is what
  makes an accidental client-scoped query from a staff surface visible in audit.
- **Gate:** `scripts/verify_rls.py` fails the build if any table with a `client_id` column
  lacks `FORCE` + a policy, and separately runs an adversarial suite that attempts a
  cross-tenant read on every table and requires all of them to return zero rows.

---

## 3. Platform tables

### Identity & access
```
users(id, email unique citext, password_hash, full_name, role, status,
      mfa_secret_encrypted, mfa_enrolled_at, last_login_at, ...)
sessions(id, user_id, device_fingerprint, refresh_token_hash, expires_at, revoked_at)
capabilities(user_id, capability, granted_by, granted_at)      -- capability strings, not roles
invites(id, email, role, token_hash, expires_at, consumed_at, created_by)
operator_tokens(id, user_id, client_id, scope, expires_at, revoked_at)   -- extension
activity_log(id, actor_id, action, target_type, target_id, before jsonb, after jsonb, at)
```

### Clients
```
clients(id, name, slug, website_url, previous_website_url, status, tier_id,
        brand jsonb, onboarded_at, offboarded_at, deleted_at)
client_locations(id, client_id, label, is_primary, address fields, lat, lng, place_id, phone)
nap_records(id, client_id, location_id, name, address_line1..., phone, website,
            canonical bool, verified_at, source)
client_contacts(id, client_id, name, email, phone, role)
client_profiles(id, client_id, categories[], services jsonb, hours jsonb,
                payment_methods[], year_founded, description_short, description_long)
```

### Vault
```
vault_secrets(id, client_id NULLABLE, scope, key, ciphertext bytea, nonce bytea,
              kek_id, created_by, rotated_at, expires_at)
vault_access_log(id, secret_id, actor_id, job_id, purpose, at)
```
`client_id NULL` = agency-level secret. Envelope encryption: a per-secret DEK wrapped by a
KEK held **outside the database** (environment/age file). The ciphertext column is never
selected by any query that does not go through `platform/vault`.

### Jobs & events
```
jobs(...)                       -- see 03-ARCHITECTURE §6
job_children(parent_id, child_id)
side_effects(id, job_id, idempotency_key unique, kind, target, request_digest,
             response jsonb, state, attempted_at, confirmed_at)
schedules(id, kind, cron, timezone, enabled, payload jsonb, last_run_at, next_run_at)
outbox(id, aggregate, event_type, payload jsonb, created_at, delivered_at)
dead_letters(id, job_id, error jsonb, provider_response jsonb, requeued_at)
```

### Cost
```
money_dials(module, state)                        -- off | by_hand | on
client_budgets(client_id, month, cap_cents, spent_cents, alerted_at)
cost_ledger(id, at, module, client_id, job_id, provider, unit, quantity,
            estimate_cents, actual_cents, kind)   -- kind: marginal | loaded
global_halt(enabled, set_by, set_at, reason)      -- single row
```

### Provenance (a composite type reused, not a table)
```
value, source_kind, source_ref, method, confidence, measured_at
method ∈ measured | derived | declared | inferred | defaulted
```

---

## 4. Module tables — the load-bearing ones

Full schemas live in each module spec. These are the ones whose shape is a correctness
requirement rather than a detail.

### Audit
```
audits(id, client_id NULLABLE, kind, tier, target_url, state, engine_version,
       started_at, finished_at, cost_cents, findings_count, degraded_sections[])
audit_findings(id, audit_id, client_id, section, severity, code, title,
               evidence jsonb, measured_value, standard_ref, effort, remediation)
audit_artifacts(id, audit_id, kind, storage_key, bytes, content_type)
free_audit_leads(id, email, domain, verified_at, ip_hash, audit_id, converted_at)
```
`client_id` is nullable **only** on `audits` for public free audits; the RLS policy on
that table admits `client_id is null and current_setting('aios.scope') = 'public'`.

### Content — DesignIR
```
design_profiles(id, client_id, source_url, version, state, approved_by, approved_at,
                captured_at, stale_after, superseded_by)
design_tokens(id, profile_id, client_id, group, name, value,
              method, source_ref, confidence)     -- group: color|type|space|radius|shadow|...
design_components(id, profile_id, client_id, kind, variant, spec jsonb, method)
design_sections(id, profile_id, client_id, ordinal, kind, spec jsonb, method)
design_captures(id, profile_id, client_id, page_url, page_type, screenshot_key,
                computed_styles_key, captured_at)
```
`method` on every token is the provenance rule from P8: `declared` (a CSS custom
property the author wrote) beats `derived` (clustered computed styles) beats `inferred`
beats `defaulted`.

### Content — keyword bank and pages
```
keyword_bank(id, client_id, term, volume, volume_measured_at, difficulty, cpc_cents,
             intent, cluster_id, source, status)          -- status: active|banned|retired
keyword_clusters(id, client_id, parent_id, label, pillar_term, entity_set jsonb)
banned_terms(id, client_id, term, reason)                 -- competitors, compliance, AI tells

page_sets(id, client_id, name, state, proposed_by, approved_by, approved_at)
page_plans(id, page_set_id, client_id, page_type, working_title, cluster_id,
           primary_term, secondary_terms[], intent, priority, state)
content_pages(id, client_id, page_plan_id, slug, title, meta_description,
              state, qa_score, qa_breakdown jsonb, design_profile_id,
              composition jsonb, block_tree jsonb, wp_post_id, wp_url,
              published_at, reverted_at, version)
content_revisions(id, page_id, client_id, version, block_tree jsonb, author, at)
content_claims(id, page_id, client_id, claim, resolved_to, source_ref, state)
internal_links(id, client_id, from_page_id, to_target, anchor, kind, state)
```
`state` on `content_pages` includes `blocked` with a `blocked_reason` — the fix for v1's
`done`-that-did-nothing.

### Citations
```
directories(id, name, url, country, vertical, authority_tier, mechanism,
            requires_account, verification_kind, terms_position, terms_checked_on, state)
citation_targets(id, client_id, location_id, directory_id, priority, state)
citation_accounts(id, client_id, directory_id, username, email_alias,
                  secret_id → vault, state, verified_at, health)
citation_submissions(id, client_id, target_id, account_id, submitted_by, submitted_at,
                     field_values jsonb, proof_screenshot_key, listing_url,
                     state, marginal_cost_cents, operator_minutes)
citation_liveness(id, client_id, submission_id, checked_at, state, nap_match, evidence)
form_field_maps(id, directory_id, structural_fingerprint unique, mapping jsonb,
                confidence, hits, last_used_at, verified_by)
description_variants(id, client_id, length, text, used_count, max_uses)
```
`form_field_maps` is keyed on a **structural fingerprint** of the form (field order,
types, label shapes) — never the URL and never CSS selectors, which carry per-load class
names.

### Web 2.0 / social
```
platforms(id, key unique, name, category, auth_kind, api_capability jsonb,
          content_model jsonb, media_rules jsonb, link_policy, rate_limits jsonb,
          ownership_tier, terms_position, terms_checked_on, state)
web2_accounts(id, client_id NULLABLE, platform_id, ownership, handle,
              secret_id → vault, oauth_expires_at, health, property_count, state)
campaigns(id, client_id, name, state, started_at, ended_at, budget_cents)
campaign_platforms(campaign_id, platform_id, account_id, state)
web2_properties(id, client_id, account_id, platform_id, url, created_at, state)
web2_posts(id, client_id, property_id, campaign_id, content_page_id NULLABLE,
           title, body, media jsonb, seo jsonb, scheduled_for, published_at,
           external_id, url, state, idempotency_key unique)
anchor_bank(id, client_id, anchor, kind, target_url, used_count, cap)
placed_links(id, client_id, post_id, target_url, anchor, kind, first_seen, last_checked,
             state)     -- state: live | removed | nofollowed | unknown
```
`ownership = house` requires `client_id is null` and counts against a per-account property
cap; `ownership = per_client` requires `client_id` and is sealed to that client.

### Tracking
```
tracked_keywords(id, client_id, location_id NULLABLE, term, engine, device, geo)
rank_observations(id, client_id, tracked_keyword_id, observed_at, position,
                  source, url, serp_features jsonb, state)
grid_definitions(id, client_id, location_id, shape, radius_m, rows, cols, center_lat, center_lng)
grid_runs(id, client_id, grid_id, started_at, finished_at, state,
          points_total, points_measured, points_error)
grid_points(id, client_id, run_id, row, col, lat, lng, state, position, evidence jsonb)
```
```sql
-- P2 made structural: the three states cannot be blurred.
alter table grid_points add constraint grid_point_state_coherent check (
      (state = 'ranked'  and position between 1 and 20)
   or (state = 'absent'  and position is null)
   or (state = 'error'   and position is null)
);
```
Every published ratio divides by `points_measured` (= ranked + absent), never by
`points_total`. A rate-limited afternoon must never render as a client's service area
collapsing.

---

## 5. Migration rules

1. **Forward-only.** No `downgrade` is written; rollback is redeploying the previous image.
   This is safe only because of rule 2.
2. **Expand → migrate → contract, across releases.** Add the new column nullable, backfill,
   switch reads, then drop the old one in a *later* release. Never in one migration.
3. **No destructive statement without an owner-approved ADR** — `DROP TABLE`, `DROP COLUMN`,
   a type narrowing, or a `NOT NULL` on a populated column.
4. **Every migration applies from zero.** CI stands up an empty database, applies the whole
   chain, and diffs the result against the SQLAlchemy models. A drift fails the build.
5. **Every new tenant table ships with its RLS policy in the same migration.** A migration
   adding a `client_id` column without a policy fails gate 5.
6. **Long-lived locks are forbidden.** Index creation is `CONCURRENTLY`; backfills are
   batched jobs, not migration statements.
7. **Seed data is separate from schema.** `alembic/` changes structure; `scripts/seed/`
   loads directories, platforms and niche templates, and is idempotent.

---

## 6. Retention

| Class | Retention | Notes |
|---|---|---|
| Measurements (rank, grid, liveness) | Forever | Append-only; the product is the history |
| Cost ledger, activity log | Forever | Financial and audit record |
| Job rows | 90 days, then archived to cold storage | Dead letters kept 1 year |
| Screenshots, captures, artefacts | 1 year | Proof artefacts for live citations kept while the citation is live |
| Provider raw responses | 30 days | Debugging only; digests kept longer |
| Vault secrets | Until rotated or client offboarded | Offboarding destroys the DEK, which destroys the data |
| Client data after offboarding | 90 days, then hard delete on request | `REQ-X-008` |
