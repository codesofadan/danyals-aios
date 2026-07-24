"use client";

// ============================================================
// AIOS · tool-workspace data + ACTION hooks
// Two jobs:
//   1. `useToolWorkspace(slug)` — the read side. Backs each `/team/tools/[slug]`
//      page off its real `GET /<slug>/workspace` readout (17 tools; see
//      backend/app/modules/tool_workspaces/router.py + the 8 per-module workspace
//      routes). `ToolExtraResponse` (backend) mirrors `ToolExtra` (frontend)
//      field-for-field, so the JSON drops straight into the type.
//   2. The WRITE side — one mutation hook per real action the 8 Part-8 modules
//      expose (keyword_research · rank_tracker · competitor_intel · on_page ·
//      local_seo · client_onboarding · data_import · billing). These make the
//      granted tool actually DO its job instead of only reading it. Each mutation
//      invalidates its tool's `/workspace` readout on success so the KPIs/table
//      above refresh with the new record.
//
// The module request models are `populate_by_name`, so snake_case body keys match
// the Python field names (same convention as lib/hooks/content.ts). The responses
// are server-authoritative (no frontend type mirror); the lean types below cover
// only the fields these hooks read.
// ============================================================

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { api, ApiError, getToken } from "@/lib/api";
import type { ToolExtra } from "@/lib/tools";

export const toolWorkspaceKey = (slug: string) => ["tool-workspace", slug] as const;

/** A tool's live KPIs/table/primary/bullets (GET /{slug}/workspace). Only
 * fetched once the caller actually has the grant (`enabled`), since an
 * ungranted tool 403s. */
export function useToolWorkspace(slug: string, enabled: boolean) {
  return useQuery({
    queryKey: toolWorkspaceKey(slug),
    enabled,
    queryFn: () => api.get<ToolExtra>(`/${slug}/workspace`),
  });
}

/** Refresh a tool's readout after one of its actions mutates its data. */
function refreshWorkspace(qc: QueryClient, slug: string) {
  void qc.invalidateQueries({ queryKey: toolWorkspaceKey(slug) });
}

// --- keyword research (slug "keyword-research") -------------------------------
// Real action: fire-and-forget research run (POST /keyword-research/research → 202).
// The paid provider pull is cost-gated in the worker; the route needs run_research
// (owner/admin/manager).

export type RunResearchInput = { seed: string; client_id?: string; geo?: string };
export type ResearchQueued = { seed: string; queued: boolean };

export function useRunKeywordResearch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: RunResearchInput) =>
      api.post<ResearchQueued>("/keyword-research/research", input),
    // A research run trickles keywords into the bank asynchronously; refresh the
    // readout so the operator sees the run was accepted (and later, its results).
    onSuccess: () => refreshWorkspace(qc, "keyword-research"),
  });
}

// --- rank tracker (slug "rank-tracker") ---------------------------------------
// Real action: subscribe keyword(s) to nightly rank tracking for a client
// (POST /rank-tracker/keywords → 201, or 402 if the standing bill would breach
// the client's budget). Needs run_research (owner/admin/manager).

export type RankCadence = "daily" | "weekly";
export type RankEngine = "google" | "bing";
export type RankDevice = "desktop" | "mobile" | "tablet";

export type AddRankKeywordsInput = {
  client_id: string;
  keywords: string[];
  cadence: RankCadence;
  engine: RankEngine;
  device: RankDevice;
  target_url?: string;
};
export type RankKeywordsAdded = {
  keywords: { code: string; keyword: string }[];
  projection: { message: string };
};

export function useAddRankKeywords() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: AddRankKeywordsInput) =>
      api.post<RankKeywordsAdded>("/rank-tracker/keywords", input),
    onSuccess: () => refreshWorkspace(qc, "rank-tracker"),
  });
}

// --- competitor intel (slug "competitor-intel") -------------------------------
// Real actions: track a competitor domain (POST /competitor-intel/competitors →
// 201) then fire a gap analysis against it (POST .../{code}/analyze → 202). Both
// need run_research (owner/admin/manager).

export type AddCompetitorInput = { client_id: string; domain: string; label?: string };
export type CompetitorCreated = { code: string; domain: string };
export type AnalysisQueued = { code: string; queued: boolean };

export function useAddCompetitor() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: AddCompetitorInput) =>
      api.post<CompetitorCreated>("/competitor-intel/competitors", input),
    onSuccess: () => refreshWorkspace(qc, "competitor-intel"),
  });
}

export function useAnalyzeCompetitor() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (code: string) =>
      api.post<AnalysisQueued>(`/competitor-intel/competitors/${code}/analyze`),
    onSuccess: () => refreshWorkspace(qc, "competitor-intel"),
  });
}

// --- on-page optimizer (slug "on-page") ---------------------------------------
// Real action: queue a page for analysis (POST /on-page/analyze → 202). This only
// READS the client's page, so it needs run_audits (not a lead role). The URL is
// SSRF-validated server-side.

export type AnalyzePageInput = { client_id: string; page_url: string; target_keyword?: string };
export type OnPageAnalysisQueued = { code: string; queued: boolean };

export function useAnalyzePage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: AnalyzePageInput) =>
      api.post<OnPageAnalysisQueued>("/on-page/analyze", input),
    onSuccess: () => refreshWorkspace(qc, "on-page"),
  });
}

// --- local SEO (slug "local-seo") ---------------------------------------------
// Real action: add a GBP location profile for a client (POST /local-seo/profiles
// → 201). Needs a lead role (owner/admin/manager). Map-pack rank tracking then
// hangs off the profile.

export type AddGbpProfileInput = {
  client_id: string;
  location_label: string;
  primary_category?: string;
  nap_name?: string;
  nap_address?: string;
  nap_phone?: string;
  website_uri?: string;
};
export type GbpProfileCreated = { id: string };

export function useAddGbpProfile() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: AddGbpProfileInput) =>
      api.post<GbpProfileCreated>("/local-seo/profiles", input),
    onSuccess: () => refreshWorkspace(qc, "local-seo"),
  });
}

// --- client onboarding (slug "client-onboarding") -----------------------------
// Real action: start an activation run for a client and seed its 11-step checklist
// (POST /client-onboarding/runs → 201). Needs manage_clients (owner/admin/manager).

export type StartOnboardingInput = { client_id: string; template_key?: string };
export type OnboardingRunCreated = { id: string; status: string };

export function useStartOnboarding() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: StartOnboardingInput) =>
      api.post<OnboardingRunCreated>("/client-onboarding/runs", input),
    onSuccess: () => refreshWorkspace(qc, "client-onboarding"),
  });
}

// --- data import (slug "data-import") -----------------------------------------
// Real action: upload a CSV/TSV/XLSX export (multipart POST /data-import/uploads →
// 201) then commit the mapped run (POST /data-import/runs/{id}/commit → 202). Both
// need manage_clients. The upload is multipart (JSON `api.post` can't drive it), so
// it goes through a dedicated FormData fetch below.

export type ImportSourceType =
  | "search_console"
  | "keywords"
  | "backlinks"
  | "rankings"
  | "citations"
  | "custom";

export const IMPORT_SOURCE_LABELS: Record<ImportSourceType, string> = {
  search_console: "Search Console",
  keywords: "Keywords",
  backlinks: "Backlinks",
  rankings: "Rankings",
  citations: "Citations",
  custom: "Custom",
};

export type ImportUploadResult = {
  run: { id: string; filename: string; status: ImportSourceType | string };
};
export type ImportCommitQueued = { id: string; queued: boolean; reason?: string };

// The one multipart door. Mirrors `apiFetch` (bearer token, error-envelope decode)
// but must NOT set Content-Type — the browser stamps the multipart boundary itself.
const UPLOAD_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

async function uploadImport(form: FormData): Promise<ImportUploadResult> {
  const token = getToken();
  const res = await fetch(`${UPLOAD_BASE}/data-import/uploads`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!res.ok) {
    let message = res.statusText || `Upload failed (${res.status})`;
    let type = "http_error";
    try {
      const data = (await res.json()) as { error?: { type?: string; message?: string } };
      if (data?.error) {
        type = data.error.type ?? type;
        message = data.error.message ?? message;
      }
    } catch {
      /* non-JSON error body — keep the status-derived default */
    }
    throw new ApiError(res.status, type, message, "");
  }
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as ImportUploadResult;
}

export type UploadImportInput = { file: File; source_type: ImportSourceType; client_id?: string };

export function useUploadImport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: UploadImportInput) => {
      const form = new FormData();
      form.append("file", input.file);
      // Form fields are addressed by their alias (Form has no populate_by_name).
      form.append("sourceType", input.source_type);
      if (input.client_id) form.append("clientId", input.client_id);
      return uploadImport(form);
    },
    onSuccess: () => refreshWorkspace(qc, "data-import"),
  });
}

export function useCommitImport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) =>
      api.post<ImportCommitQueued>(`/data-import/runs/${runId}/commit`),
    onSuccess: () => refreshWorkspace(qc, "data-import"),
  });
}

// --- billing (slug "billing") -------------------------------------------------
// Real actions: open a DRAFT invoice with one line (POST /billing/invoices → 201)
// then issue it (POST /billing/invoices/{number}/finalize). Finance-sensitive:
// both need owner/admin (a manager is deliberately NOT enough).

export type InvoiceKind = "retainer" | "one_off";
export type CreateInvoiceInput = {
  client_id: string;
  kind: InvoiceKind;
  currency: string;
  lines: { description: string; quantity: number; unit_amount: number }[];
};
export type InvoiceCreated = { number: string; status: string; total?: number };

export function useCreateInvoice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateInvoiceInput) =>
      api.post<InvoiceCreated>("/billing/invoices", input),
    onSuccess: () => refreshWorkspace(qc, "billing"),
  });
}

export function useFinalizeInvoice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (number: string) =>
      api.post<InvoiceCreated>(`/billing/invoices/${number}/finalize`),
    onSuccess: () => refreshWorkspace(qc, "billing"),
  });
}
