// ============================================================
// AIOS · Feature catalog
// Grounded in the platform documentation — the "Feature Map"
// (aios/context-docs/AIOS-Workflow-and-Features.pdf, pp. 5–6)
// and the Platform Overview module pages. One source of truth for
// the Features popup, the /features page and every feature page.
// ============================================================

export type Tier = "free" | "paid" | "core";

export type Feature = {
  slug: string;
  name: string;   // full name — shown in the hover tooltip + feature page
  label: string;  // short label — shown on the bubble
  icon: string;   // unique Material Symbols name
  tier: Tier;
  blurb: string;  // one-line summary from the docs
  details: string[];
};

export type FeatureModule = {
  id: string;
  num: string;
  name: string;
  tagline: string;
  context: string;
  tag: { label: string; cls: string };
  features: Feature[];
};

export const TIER_LABEL: Record<Tier, string> = {
  free: "Free tier",
  paid: "Paid tier",
  core: "Platform core",
};

export const featureModules: FeatureModule[] = [
  {
    id: "audit",
    num: "01",
    name: "Audit",
    tagline: "URL-only diagnosis",
    context:
      "Step 01 · Measure. The audit runs on a URL alone — no logins — so any prospect can be measured and sold before onboarding. Available on the Free tier.",
    tag: { label: "Free", cls: "free" },
    features: [
      {
        slug: "technical-audit",
        name: "Technical audit",
        label: "Technical",
        icon: "troubleshoot",
        tier: "free",
        blurb: "Crawl, indexing, speed (Core Web Vitals), schema, security headers, SSL.",
        details: [
          "Full-site crawl surfaces indexing and crawlability issues.",
          "Core Web Vitals and page speed measured via PageSpeed Insights.",
          "Schema coverage, security headers and SSL validated.",
          "Domain-level technical issues scored into the report.",
        ],
      },
      {
        slug: "actionable-audit",
        name: "Actionable audit",
        label: "Actionable",
        icon: "checklist",
        tier: "free",
        blurb: "Per-page fixes — titles, meta, headings, NAP, internal links.",
        details: [
          "Pinpoints the specific pages and the exact fix each one needs.",
          "Title tags, meta descriptions and heading structure.",
          "NAP consistency and internal-link opportunities.",
          "Every finding is written as a do-this action.",
        ],
      },
      {
        slug: "local-gbp-signals",
        name: "Local & GBP signals",
        label: "Local & GBP",
        icon: "storefront",
        tier: "free",
        blurb: "Map-pack context, categories, NAP from Places / Business Profile.",
        details: [
          "Map-pack context and category alignment.",
          "NAP pulled from Google Places / Business Profile.",
          "Local relevance signals assessed for the target market.",
        ],
      },
      {
        slug: "ai-geo-signals",
        name: "AI / GEO signals",
        label: "AI / GEO",
        icon: "auto_awesome",
        tier: "free",
        blurb: "AI-overview readiness, entities, structured-data coverage.",
        details: [
          "AI-overview and generative-search readiness.",
          "Entity coverage and structured-data completeness.",
          "Recommendations to earn AI-answer visibility.",
        ],
      },
      {
        slug: "backlink-citation-audit",
        name: "Backlink & citation audit",
        label: "Backlinks",
        icon: "hub",
        tier: "free",
        blurb: "Profile strength, toxic links, listing consistency.",
        details: [
          "Backlink profile strength at a glance.",
          "Toxic and spammy links flagged.",
          "Citation and listing consistency checked — see Off-page for ongoing monitoring.",
        ],
      },
      {
        slug: "audit-pdf-report",
        name: "20–30+ page PDF report",
        label: "PDF Report",
        icon: "picture_as_pdf",
        tier: "free",
        blurb: "House-styled report + live web version, stored to the client Sheet.",
        details: [
          "20–30+ page house-styled PDF.",
          "Live web version inside the portal.",
          "Stored to the client's Google Sheet; the milestone advances on completion.",
        ],
      },
    ],
  },
  {
    id: "content",
    num: "02",
    name: "Content",
    tagline: "Multi-framework + publish",
    context:
      "Step 02 · Create. Runs on the same cost-controlled queue; a human reviews the last 10% before anything publishes. Paid tier.",
    tag: { label: "Paid", cls: "paid" },
    features: [
      {
        slug: "framework-selector",
        name: "Framework selector",
        label: "Frameworks",
        icon: "tune",
        tier: "paid",
        blurb: "AIDA · PAS · BAB · FAB · 4 Ps · PASTOR · 4 U's, chosen by type + intent.",
        details: [
          "Seven copywriting frameworks available.",
          "Auto-selected by content type and search intent.",
          "Keeps every page fit for its purpose.",
        ],
      },
      {
        slug: "page-types",
        name: "Service / blog / local pages",
        label: "Page Types",
        icon: "description",
        tier: "paid",
        blurb: "Long-form copy fit to the page's purpose and search intent.",
        details: [
          "Service pages, blog posts and local pages.",
          "Long-form copy matched to the page's purpose.",
          "Written to the searcher's intent.",
        ],
      },
      {
        slug: "titles-meta",
        name: "Titles & meta",
        label: "Titles & Meta",
        icon: "title",
        tier: "paid",
        blurb: "Built with the 4 U's; bulk generation for whole sections.",
        details: [
          "Titles and meta descriptions built with the 4 U's.",
          "Bulk generation across a whole section at once.",
        ],
      },
      {
        slug: "automated-schema",
        name: "Automated schema (JSON-LD)",
        label: "Schema",
        icon: "data_object",
        tier: "paid",
        blurb: "Generated and validated, wired to the content type.",
        details: [
          "JSON-LD generated per content type.",
          "Validated before it ships.",
          "Wired to the page it describes.",
        ],
      },
      {
        slug: "ai-images",
        name: "AI images + alt text",
        label: "AI Images",
        icon: "add_photo_alternate",
        tier: "paid",
        blurb: "Featured + inline images, geotagged where relevant.",
        details: [
          "AI-generated featured and inline images.",
          "Automatic alt text on every image.",
          "Geotagged where relevant for local pages.",
        ],
      },
      {
        slug: "publish-wordpress-pdf",
        name: "Publish: WordPress / PDF",
        label: "Publish",
        icon: "rocket_launch",
        tier: "paid",
        blurb: "REST push (body, meta, images, schema) or branded export.",
        details: [
          "One-click WordPress REST push — body, meta, images and schema.",
          "Or a branded PDF export for manual publishing.",
          "A human approves before anything goes live.",
        ],
      },
    ],
  },
  {
    id: "offpage",
    num: "03",
    name: "Off-page",
    tagline: "Backlinks · citations · Web 2.0",
    context:
      "Step 03 · Promote. Builds authority through links, citations and Web 2.0 — always human-approved, never link spam. Paid tier.",
    tag: { label: "Paid", cls: "paid" },
    features: [
      {
        slug: "backlink-monitoring",
        name: "Backlink monitoring",
        label: "Link Monitor",
        icon: "monitoring",
        tier: "paid",
        blurb: "Referring domains, new/lost links, anchors, authority, spam score.",
        details: [
          "Tracks referring domains and new / lost links.",
          "Anchor mix, authority and spam score.",
          "A live view of the off-page profile.",
        ],
      },
      {
        slug: "local-citations",
        name: "Local citations / NAP",
        label: "Citations",
        icon: "contact_page",
        tier: "paid",
        blurb: "Directory listings, consistency checks, bulk submit & update.",
        details: [
          "Directory listings with consistency checks.",
          "Bulk submit and update NAP across sources.",
        ],
      },
      {
        slug: "web-2-automation",
        name: "Web 2.0 automation",
        label: "Web 2.0",
        icon: "public",
        tier: "paid",
        blurb: "Branded article → official API publish → live-link verify → track.",
        details: [
          "Branded article published via official platform APIs.",
          "Live-link verification after publish.",
          "Ongoing tracking of every placement.",
        ],
      },
      {
        slug: "quality-gate",
        name: "Quality gate + diversification",
        label: "Quality Gate",
        icon: "verified_user",
        tier: "paid",
        blurb: "Human approval, varied platforms/anchors — never link spam.",
        details: [
          "Human approval on every placement.",
          "Varied platforms and anchors — never link spam.",
        ],
      },
    ],
  },
  {
    id: "portal",
    num: "04",
    name: "Portal",
    tagline: "Role-scoped dashboards",
    context:
      "Step 04 · Report. One app, role-scoped to client, team and admin — the face everyone uses. Anything client-facing passes the review gate first.",
    tag: { label: "Role-scoped", cls: "scoped" },
    features: [
      {
        slug: "dashboard",
        name: "Dashboard",
        label: "Dashboard",
        icon: "dashboard",
        tier: "free",
        blurb: "Each client's site snapshot and latest audit score.",
        details: [
          "Site snapshot and latest audit score.",
          "The client's home inside the portal.",
        ],
      },
      {
        slug: "reports",
        name: "Reports (web + PDF)",
        label: "Reports",
        icon: "summarize",
        tier: "free",
        blurb: "Every audit as a web page and a downloadable PDF.",
        details: [
          "All audits as live web pages.",
          "Downloadable house-styled PDFs.",
        ],
      },
      {
        slug: "milestones",
        name: "Milestones",
        label: "Milestones",
        icon: "timeline",
        tier: "free",
        blurb: "Project progress, auto-updated from job and audit status.",
        details: [
          "Progress tracked as milestones.",
          "Auto-advanced by job and audit status — no manual updates.",
        ],
      },
      {
        slug: "run-audit",
        name: "Run audit",
        label: "Run Audit",
        icon: "play_circle",
        tier: "free",
        blurb: "Trigger a free or paid audit straight from the portal.",
        details: [
          "Clients trigger audits from the portal.",
          "Free or paid, per the tier the agency sets.",
        ],
      },
      {
        slug: "my-queue",
        name: "My queue",
        label: "My Queue",
        icon: "inbox",
        tier: "paid",
        blurb: "The team member's assigned audit and content jobs.",
        details: [
          "Audit and content jobs assigned to each specialist.",
          "The team's work list, in one place.",
        ],
      },
      {
        slug: "review-gate",
        name: "Review gate",
        label: "Review Gate",
        icon: "rule",
        tier: "paid",
        blurb: "The human checkpoint before any content publishes.",
        details: [
          "The 10% human review before publish.",
          "Approve or edit — nothing client-facing skips it.",
        ],
      },
      {
        slug: "key-vault",
        name: "Key vault",
        label: "Key Vault",
        icon: "lock",
        tier: "core",
        blurb: "Agency API keys and WordPress creds, encrypted at rest.",
        details: [
          "Central encrypted vault for every API key.",
          "WordPress credentials stored — never in plain text or logs.",
        ],
      },
      {
        slug: "tiers-roles",
        name: "Tiers + roles",
        label: "Tiers & Roles",
        icon: "admin_panel_settings",
        tier: "core",
        blurb: "Set free/paid access and provision client, team and admin users.",
        details: [
          "Set free vs paid access per client.",
          "Provision client, team and admin logins — no public signup.",
        ],
      },
      {
        slug: "cost-dial",
        name: "Cost dial",
        label: "Cost Dial",
        icon: "savings",
        tier: "core",
        blurb: "Per-client budget caps and an automatic daily spend-stop.",
        details: [
          "Per-client and per-feature budget caps.",
          "An automatic daily spend-stop keeps cost predictable.",
        ],
      },
      {
        slug: "fiverr-upsells",
        name: "Fiverr upsells",
        label: "Fiverr Upsells",
        icon: "sell",
        tier: "free",
        blurb: "Clickable upsell cards that point to the agency's Fiverr gigs.",
        details: [
          "Upsell cards link to Fiverr gigs, not internal services.",
          "Preserves the agency's Fiverr-centered public brand.",
        ],
      },
    ],
  },
  {
    id: "radar",
    num: "05",
    name: "Policy Radar",
    tagline: "Always-on policy watch",
    context:
      "Step 05 · Watch. Runs continuously across every client and feeds new checks and guidance back into Audit and Content. Platform core.",
    tag: { label: "Core", cls: "core" },
    features: [
      {
        slug: "policy-watch",
        name: "Watch → Detect → Research",
        label: "Policy Watch",
        icon: "radar",
        tier: "core",
        blurb: "Diffs official Google sources and researches every change.",
        details: [
          "Watches official Google sources — Search Status, Search Central, the QRG.",
          "Diffs them; a detected change fires a research job immediately.",
          "Summarizes what changed and why it matters.",
        ],
      },
      {
        slug: "policy-flag",
        name: "Flag (severity · category · region)",
        label: "Flagging",
        icon: "label",
        tier: "core",
        blurb: "Versioned, source-cited knowledge-base entries.",
        details: [
          "Each entry tagged by severity, category and region.",
          "Versioned and deduped in the knowledge base.",
          "Every entry cites its source.",
        ],
      },
      {
        slug: "command-center",
        name: "Recommend → Command Center",
        label: "Command Center",
        icon: "tips_and_updates",
        tier: "core",
        blurb: "Human-confirmed recommendations that can change live checks.",
        details: [
          "Recommendations surface in the Command Center.",
          "Human-confirmed before they change any live audit check or advice.",
          "Closed loop: add a check, adjust content guidance, or raise a client advisory.",
        ],
      },
    ],
  },
];

export function allFeatures(): Feature[] {
  return featureModules.flatMap((m) => m.features);
}

export function allFeatureSlugs(): string[] {
  return allFeatures().map((f) => f.slug);
}

export function getFeature(slug: string): { feature: Feature; module: FeatureModule } | null {
  for (const module of featureModules) {
    const feature = module.features.find((f) => f.slug === slug);
    if (feature) return { feature, module };
  }
  return null;
}

export function neighbors(slug: string): { prev: Feature | null; next: Feature | null } {
  const all = allFeatures();
  const i = all.findIndex((f) => f.slug === slug);
  return {
    prev: i > 0 ? all[i - 1] : null,
    next: i >= 0 && i < all.length - 1 ? all[i + 1] : null,
  };
}
