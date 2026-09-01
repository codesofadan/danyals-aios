-- 0121 · Two columns with no writer leave; two get the writer they were promised.
--
-- Grep-verified 2026-09-02 (app/, workers/, integrations/):
--
--   * `handoff_url` (0064: "where a human finishes the listing") — ZERO writers, and
--     its one reader serialized a permanently-empty string. The concept it carried was
--     superseded by the operator queue, which serves `directories.add_url` per item;
--     the engine-result field of the same name was never persisted either. DROPPED.
--
--   * `skip_reason` (0106: "why this directory was NOT attempted — the client-report
--     line") — ZERO writers AND zero readers; the code writes `blocked_reason` for a
--     row that exists, and "not attempted at all" describes a directory with NO row,
--     which a per-row column can never express. The skip ledger now lives where the
--     fact does: `citation_campaigns.skipped` (0120). DROPPED.
--
--   * `route` (0106: "recorded per unit so a client report can say HOW each listing
--     was built") — never stamped, so every row wore the 'C' default. The app now
--     stamps it at queue time from the directory's own route. KEPT, and finally true.
--
--   * `cost` (0045) — never written; spend went only to cost_log, so the per-listing
--     "what did this cost" answer was permanently 0. The worker now writes the
--     committed estimate onto the row at both commit sites. KEPT, and finally true.
--
-- A zombie column is not harmless: 0064's comment promised an operator surface that
-- read `handoff_url`, and the serializer shipping "" forever made the promise look
-- kept. Dropping is the honest recording that the design moved on.

alter table public.citations
  drop column if exists handoff_url,
  drop column if exists skip_reason;
