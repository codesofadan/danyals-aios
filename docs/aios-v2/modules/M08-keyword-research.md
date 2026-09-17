# M08 · Keyword Research

Requirements: `REQ-KW-001` … `REQ-KW-007`.

**The single upstream of the content word bank.** If a term is not in this module's output,
no page targets it and no tracker follows it. That one rule is what keeps content, tracking
and reporting describing the same reality.

---

## 1. Flow

```
  seeds: client profile (services, categories, areas) + existing site + competitor SERPs
    └── expansion: related terms, questions, modifiers, location permutations
          └── metrics: volume, CPC, difficulty          [DataForSEO, dated]
                └── intent classification               [model, per term]
                      └── semantic clustering            [embeddings → cluster tree]
                            └── entity / must-mention set per cluster
                                  └── TOPICAL MAP: clusters → page types
                                        └── page-set proposal → M03
```

## 2. Data

```
keyword_bank(id, client_id, term, volume, volume_measured_at, difficulty, cpc_cents,
             intent, cluster_id, serp_features jsonb, source, status)
keyword_clusters(id, client_id, parent_id, label, pillar_term, entity_set jsonb,
                 mapped_page_type, priority)
banned_terms(id, client_id, term, reason)
competitor_terms(id, client_id, competitor_domain, term, their_position, we_rank)
```

`volume_measured_at` is mandatory. A volume is a measurement with an age, not a constant —
a report citing a two-year-old volume as current is the kind of small dishonesty that
erodes a client relationship.

## 3. Rules

- **Volume and difficulty come from DataForSEO only**, stored with the date measured. No
  estimated or derived volumes are ever written (`P1`).
- **Intent classification** (`REQ-KW-003`) runs at the `structured` model tier against a
  labelled eval set with a ≥90% accuracy gate. A misclassified intent produces the wrong page
  type, which wastes a whole page's cost.
- **Clustering** (`REQ-KW-004`) uses embeddings stored in `pgvector`, producing a parent/child
  tree rather than a flat grouping — the tree is what maps onto pillar and supporting pages.
- **Entity set per cluster** (feeds `REQ-CNT-013`): the terms and entities a page on this
  topic must mention to read as authoritative. This is the topical-coverage dimension of the
  content QA scorecard, and it is the closest thing the platform has to a real semantic-SEO
  differentiator — give it depth.
- **Gap analysis** (`REQ-KW-006`, P1): terms competitors rank for and the client does not,
  ranked by opportunity.
- **Human editable.** The SEO lead can add, retire, reprioritise and ban terms. Every edit is
  versioned and attributed.

## 4. The topical map

The output that M03 consumes. Per cluster: the mapped page type, the primary term, secondary
terms, intent, priority, and the internal-linking role (pillar / supporting / commercial).

`REQ-KW-005`. The map is a proposal, not a decision — a human approves the resulting page
set before any drafting spends money (`REQ-CNT-014`).

## 5. Acceptance criteria

| # | Criterion |
|---|---|
| A1 | Every term carries a volume with a measured-at date, or no volume at all — never an estimate |
| A2 | Intent classification scores ≥90% against the 200-term labelled eval set |
| A3 | Clustering produces a navigable parent/child tree, not a flat list |
| A4 | Each cluster carries an entity set that the content QA scorecard measures against |
| A5 | A term absent from the bank cannot be targeted by a page or added to tracking — enforced at the API |
| A6 | Banned terms propagate to M03 draft-time and publish-time checks |
| A7 | Research for one client is invisible to another at every layer |
