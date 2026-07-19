"use client";

// ============================================================
// AIOS · tool-workspace data hook
// Backs each `/team/tools/[slug]` page off its real `GET /<slug>/workspace`
// endpoint (17 tools; see backend/app/modules/tool_workspaces/router.py +
// the 8 per-module workspace routes) instead of the stripped `lib/tools.ts`
// demo constants. `ToolExtraResponse` (backend) mirrors `ToolExtra`
// (frontend) field-for-field, so the JSON drops straight into the type.
// ============================================================

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
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
