// ============================================================
// AIOS · Service Tiers mock data — swap for FastAPI/Postgres later.
// The real model is a per-client, per-feature DIAL (API / by-hand /
// off). The three tiers below are just presets over that dial; a
// human approves everything in every tier. Shapes are demo-only.
// ============================================================
import { SERIES } from "@/lib/data";

export type TierKey = "free" | "semi" | "fully";

// How a feature area is delivered under a given tier.
//  off    — not available on this tier
//  byhand — human/manual or free tools (approve, upload, on-request)
//  api    — automated via paid data APIs, human still approves
export type Mode = "off" | "byhand" | "api";

export const MODE_META: Record<Mode, { label: string; cls: string }> = {
  off: { label: "Off", cls: "off" },
  byhand: { label: "By-hand", cls: "byhand" },
  api: { label: "API", cls: "api" },
};

export type Tier = {
  key: TierKey;
  name: string;
  price: number; // USD / client / month
  tagline: string;
  blurb: string;
  c: string; // accent color
  popular?: boolean;
  unlocks: string[]; // what this preset switches on
};

// Ordered Free → Semi → Fully. Middle tier is the "cost-optimized" sweet spot.
export const TIERS: Tier[] = [
  {
    key: "free",
    name: "Free",
    price: 0,
    tagline: "For trials & leads",
    blurb: "No automation, no paid data — free Google + Serper only.",
    c: "#22C08A",
    unlocks: [
      "Google Search Console + Analytics traffic",
      "Client spreadsheet uploads",
      "Serper.dev free rank checks (2,500/mo)",
      "1 free sample / public audit",
      "Basic login portal",
      "On-request basic reports",
    ],
  },
  {
    key: "semi",
    name: "Semi-Automated",
    price: 20,
    tagline: "Cost-optimized",
    blurb: "AI drafts, humans finish — one shared paid seat, on-request data.",
    c: SERIES.c4,
    popular: true,
    unlocks: [
      "AI-drafted content — human edits & posts",
      "Manual backlink uploads (Ahrefs / SEMrush seat)",
      "Cloud crawl audits on request",
      "Weekly rank checks",
      "AI schema markup",
      "Competitor SWOT from uploads",
      "AI-drafted branded reports",
      "Task / workflow board",
      "Full read-only portal",
    ],
  },
  {
    key: "fully",
    name: "Fully-Automated",
    price: 54,
    tagline: "All-API",
    blurb: "DataForSEO nightly pipeline — auto everything, human approves.",
    c: SERIES.c1,
    unlocks: [
      "DataForSEO nightly rankings & keywords",
      "Weekly backlinks & full-site audits",
      "Auto crawl / indexing / redirect checks",
      "Auto content drafted + published on approval",
      "Auto GBP posts + review replies",
      "Scheduled reports",
      "Rank-drop & lost-link alerts",
      "Full portal + live updates",
    ],
  },
];

export const TIER_BY_KEY: Record<TierKey, Tier> = Object.fromEntries(
  TIERS.map((t) => [t.key, t])
) as Record<TierKey, Tier>;

// Shared base infra cost carried regardless of tier (server, DB,
// vault, monitoring, etc.). Not billed per feature — context only.
export const BASE_COST = 54; // USD / mo, midpoint of the ~$44–64 range

// --- Feature-area × tier matrix ---------------------------------------------
// The 7 gated areas. Cells encode the delivery mode per tier — this is
// the "cost dial as presets" view.
export type FeatureArea = {
  id: string; // "A".."G"
  name: string;
  icon: string;
  desc: string;
  modes: Record<TierKey, Mode>;
};

export const featureAreas: FeatureArea[] = [
  {
    id: "A", name: "Data & rankings", icon: "trending_up",
    desc: "Rank tracking, keyword & traffic data",
    modes: { free: "byhand", semi: "byhand", fully: "api" },
  },
  {
    id: "B", name: "Audits & site health", icon: "fact_check",
    desc: "Crawls, technical audits, indexing",
    modes: { free: "byhand", semi: "byhand", fully: "api" },
  },
  {
    id: "C", name: "Backlinks & off-page", icon: "hub",
    desc: "Backlink profile & lost-link monitoring",
    modes: { free: "off", semi: "byhand", fully: "api" },
  },
  {
    id: "D", name: "Content & publishing", icon: "article",
    desc: "Drafting, editing & CMS publishing",
    modes: { free: "off", semi: "byhand", fully: "api" },
  },
  {
    id: "E", name: "Local SEO & GBP", icon: "storefront",
    desc: "Map-pack, schema, GBP posts & reviews",
    modes: { free: "off", semi: "byhand", fully: "api" },
  },
  {
    id: "F", name: "Competitors & strategy", icon: "insights",
    desc: "SWOT, gap analysis & competitor intel",
    modes: { free: "off", semi: "byhand", fully: "api" },
  },
  {
    id: "G", name: "Reports, alerts & workflow", icon: "summarize",
    desc: "Reporting, task board & live alerts",
    modes: { free: "byhand", semi: "byhand", fully: "api" },
  },
];

// --- Per-client tier assignments --------------------------------------------
// Reuses the shared client roster. `tier` is the preset each account
// is currently dialed to; the workspace lets you switch it live.
export type TierClient = {
  id: string;
  cn: string; // client name
  industry: string;
  init: string;
  c: string; // avatar accent
  tier: TierKey;
};

export const tierClients: TierClient[] = [
  { id: "cl-northpeak", cn: "NorthPeak Dental", industry: "Healthcare", init: "ND", c: SERIES.c1, tier: "fully" },
  { id: "cl-meridian", cn: "Meridian Wealth", industry: "Finance", init: "MW", c: SERIES.c1, tier: "fully" },
  { id: "cl-lumen", cn: "Lumen Realty", industry: "Real Estate", init: "LR", c: SERIES.c2, tier: "semi" },
  { id: "cl-atlas", cn: "Atlas Legal", industry: "Legal Services", init: "AL", c: SERIES.c4, tier: "semi" },
  { id: "cl-brighthvac", cn: "BrightHVAC", industry: "Home Services", init: "BH", c: SERIES.c3, tier: "semi" },
  { id: "cl-verde", cn: "Verde Cafe", industry: "Hospitality", init: "VC", c: SERIES.c5, tier: "free" },
  { id: "cl-coastline", cn: "Coastline Fit", industry: "Fitness", init: "CF", c: SERIES.c2, tier: "free" },
  { id: "cl-orchard", cn: "Orchard Pediatrics", industry: "Healthcare", init: "OP", c: SERIES.c5, tier: "free" },
];
