// The state one pass through the flow accumulates. Held by the orchestrator and
// handed down; each screen owns one slice of it and nothing else.

import { TEMPLATE_THEME_DEFAULTS } from "@/lib/content";
import type {
  Framework, PageTemplate, PublishTarget, ResearchItem, SiteDesignProfile, TemplateTheme,
} from "@/lib/content";
import type { PageKindKey } from "@/lib/pageKinds";

export type FlowState = {
  clientId: string;
  clientName: string;
  /** The client's OWN registered site, chosen from the database - never typed. */
  siteDomain: string;
  kind: PageKindKey;
  /** The pages to build, from the keyword bank, a research run, or added by hand. */
  picks: ResearchItem[];
  proof: string;
  services: string;
  testimonials: string;
  uniqueData: string;
  framework: Framework | "Auto";
  target: PublishTarget;
  design: SiteDesignProfile | null;
  designFrom: string;
  // Replicating a design from ANOTHER url (QA 20). `replicaUrl` is what the operator
  // typed; `replicaOwnerConfirmed` is their copyright assertion, which must be the
  // operator's real answer and never a hardcoded true - the server enforces it too.
  replicaUrl: string;
  replicaOwnerConfirmed: boolean;
  replicaJobId: string | null;
  /** The visual template, when the operator picks one instead of measuring the
   *  real site. "Auto" means the page kind's own blueprint decides. */
  template: PageTemplate | "Auto";
  theme: TemplateTheme;
};

export const EMPTY_FLOW: FlowState = {
  clientId: "", clientName: "", siteDomain: "", kind: "service",
  picks: [], proof: "", services: "", testimonials: "", uniqueData: "",
  framework: "Auto", target: "WordPress", design: null, designFrom: "", replicaUrl: "", replicaOwnerConfirmed: false, replicaJobId: null,
  template: "Auto", theme: TEMPLATE_THEME_DEFAULTS.service,
};

export const lines = (s: string): string[] =>
  s.split("\n").map((l) => l.trim()).filter(Boolean);
