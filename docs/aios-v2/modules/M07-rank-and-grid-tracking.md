# M07 · Rank & Grid Tracking

Requirements: `REQ-RNK-001` … `REQ-RNK-008`.

The module that proves the rest of the platform worked. Its output goes straight into client
reports, which is exactly why its integrity rules are the strictest in the system.

---

## 1. Three sources, never mixed

`REQ-RNK-001`.

| Source | Measures | Never used for |
|---|---|---|
| **DataForSEO** | Organic rank position, SERP features, competitor positions | Local pack, grid |
| **serper.dev** | Local pack presence and position, geo-grid points | Organic rank history |
| **Google Search Console** (`REQ-RNK-008`, P1 — see ADR-021) | First-party impressions, clicks, CTR and **average** position for pages we published | A rank position. GSC reports an average over impressions, not a position |

Every stored observation carries its `source`. **The three are never averaged, never
combined into one series, and always labelled in the UI and in reports.** Mixing them makes
historical rank data meaningless, which is a silent, permanent data-integrity loss.

---

## 2. The three-state model

`REQ-RNK-004`. This is the module's load-bearing invariant.

| State | Meaning |
|---|---|
| `ranked` | Measured, and the target was found at position N |
| `absent` | **Measured**, and the target was not in the result set |
| `error` | **Never measured** — rate limit, provider failure, timeout |

`absent` and `error` are different facts. Collapsing them is the defect that makes a
rate-limited afternoon render as a client's service area collapsing — permanently, in an
append-only table, in a report the client keeps.

Enforced structurally:

```sql
alter table grid_points add constraint grid_point_state_coherent check (
      (state = 'ranked' and position between 1 and 20)
   or (state = 'absent' and position is null)
   or (state = 'error'  and position is null)
);
```

**Every ratio divides by `points_measured` (`ranked + absent`), never by `points_total`.**
A run's coverage is displayed alongside every grid, so a partial run reads as partial.

---

## 3. Geo-grid

`REQ-RNK-003`. Configurable shape (square or ring), radius and density per client location.

- Each point is a real coordinate. The provider is queried **by coordinate**
  (`location_coordinate`), not by place name.
  **v1's bug, worth restating:** it passed `location="lat,lng"` into a parameter that expects
  a place name, which returns an unlocalised SERP for every point — producing a perfectly
  smooth, entirely fictional heat map. The fix is not cosmetic; the old data is worthless.
- Ring geometry and summary maths are pure functions with unit tests independent of the
  provider.
- Runs are append-only. A re-run is a new run, never an edit of the last one.

---

## 4. Organic rank

- Tracked keywords are assigned per client and optionally per location, with tier-based
  allowances (`REQ-RNK-002`) enforced at the API.
- Observations are append-only (`REQ-RNK-005`). Correction is a new row with a note, never
  an update.
- SERP features captured per observation (`REQ-RNK-006`): AI Overview presence, local pack,
  FAQ, video, shopping — because "we lost position 3" and "position 3 is now below an AI
  Overview" are different stories for the client.
- Competitor tracking (`REQ-RNK-007`, P1) over a configured competitor set, same rules.

---

## 5. Google Search Console connector

`REQ-RNK-008`, P1. Pending ADR-021 approval — see
[`15-REFERENCE-PRODUCTS.md`](../15-REFERENCE-PRODUCTS.md) §B.

Why it earns its place: it is the only **first-party** measurement in the platform. Every
other number is third-party and sampled. For the content module it answers the question that
matters — did the 50 pages we published actually start receiving impressions, for which
queries, and at what CTR.

- OAuth scope the client already grants alongside GBP.
- Pulls per-page and per-query impressions, clicks, CTR and average position.
- Stored with `source='gsc'` and a clear label. **Average position is never presented as a
  rank**, and never enters a rank series.
- Feeds M11 reports and the content module's own success measurement.

---

## 6. Scheduling

Weekly per client for both organic and grid, staggered so provider quota is spread across
the week rather than spent on Monday. The schedule ships disabled and is enabled once the
job contract passes the chaos suite.

**Quota reality:** serper.dev's free tier is 2,500 searches **per month in total**, not per
client. One 49-point grid for one client is 49 searches. At 100 clients weekly this needs a
paid plan, and it must be costed before launch, not discovered in production.

---

## 7. Acceptance criteria

| # | Criterion |
|---|---|
| A1 | A rate-limited grid run produces `error` points, and every published ratio divides by measured points only |
| A2 | The CHECK constraint rejects a row that blurs the three states |
| A3 | Grid points are queried by coordinate; a fixture proves the SERP differs across points on a real grid |
| A4 | An organic observation and a grid observation never appear in the same series, in the API or the UI |
| A5 | A re-run creates a new run; no prior observation is mutated |
| A6 | Every displayed rank value shows its source and measured-at |
| A7 | GSC average position is labelled as an average and cannot be charted as a rank position |
| A8 | Tier keyword allowances are enforced at the API, not only in the UI |
