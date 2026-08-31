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
  /** The site these pages are researched against and published to. Usually one of
   *  the client's registered sites; may also be a domain derived from the client's
   *  business profile, or empty when the operator continues without one. */
  siteDomain: string;
  /** Whether `siteDomain` is a REGISTERED site row for this client.
   *
   *  It decides whether the domain may travel in the generate payload:
   *  `_chosen_site` 400s on a domain that is not registered to the client, so an
   *  unregistered one is used for research only and omitted at launch (where the
   *  backend then applies its own fallback). */
  siteRegistered: boolean;
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
  clientId: "", clientName: "", siteDomain: "", siteRegistered: false, kind: "service",
  picks: [], proof: "", services: "", testimonials: "", uniqueData: "",
  framework: "Auto", target: "WordPress", design: null, designFrom: "", replicaUrl: "", replicaOwnerConfirmed: false, replicaJobId: null,
  template: "Auto", theme: TEMPLATE_THEME_DEFAULTS.service,
};

export const lines = (s: string): string[] =>
  s.split("\n").map((l) => l.trim()).filter(Boolean);
