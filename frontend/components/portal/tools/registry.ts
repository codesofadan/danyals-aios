// ============================================================
// AIOS · team-portal tool ACTIONS — registry
// Maps a tool slug to its interactive action panel. Only the Part-8 modules
// that expose REAL, callable create/run endpoints appear here; the other tools
// are genuine live readouts (their `/workspace` data renders on the page) and
// have no action panel by design. ToolWorkspace looks a tool up here and, if a
// panel exists, renders it above the readout so the granted tool actually DOES
// its job instead of only describing it.
// ============================================================

import type { ComponentType } from "react";
import ClientOnboardingActions from "./ClientOnboardingActions";
import DataImportActions from "./DataImportActions";
import BillingActions from "./BillingActions";
import KeywordResearchActions from "./KeywordResearchActions";

/** Props every action panel receives — `accent` is the tool group's colour so the
 * panel's icon matches the page's hero. */
export type ToolActionProps = { accent: string };

/** slug (toolSlug(key)) → its action panel. Absent slug = a read-only tool. */
const TOOL_ACTIONS: Record<string, ComponentType<ToolActionProps>> = {
  "client-onboarding": ClientOnboardingActions,
  "data-import": DataImportActions,
  billing: BillingActions,
  "keyword-research": KeywordResearchActions,
};

export function getToolActions(slug: string): ComponentType<ToolActionProps> | null {
  return TOOL_ACTIONS[slug] ?? null;
}
