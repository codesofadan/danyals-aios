// Navigation integrity. Two facts that must hold across all three portal shells and
// that nothing else checks.
//
// 1. EVERY nav destination resolves to a real route. A nav item pointing at a deleted
//    route is a 404 the operator finds by clicking it.
// 2. The production lock list has exactly ONE definition. It did not: Sidebar.tsx
//    carried an empty set while TopBar.tsx locked /admin/citations and /admin/web2, so
//    in a production build the sidebar offered two modules the search box denied
//    existed. A third mechanism, lib/lockedInProd.ts, was never called by anything.
//    Two copies of one rule had already drifted, which is the whole reason this exists.

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = process.cwd();
const APP = join(ROOT, "app");

const NAV_SOURCES = [
  "components/Sidebar.tsx",
  "components/portal/TeamSidebar.tsx",
  "components/client/ClientSidebar.tsx",
  "components/TopBar.tsx",
];

/** Every route the app can actually render, e.g. "/admin/audit", "/team/tools/[slug]". */
function routes(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) routes(full, out);
    else if (name === "page.tsx") {
      const rel = relative(APP, dir).split("\\").join("/");
      out.push(rel === "" ? "/" : `/${rel}`);
    }
  }
  return out;
}

const ROUTES = routes(APP);

/** True if `href` is served by a real route, allowing one dynamic segment to match. */
function resolves(href: string): boolean {
  if (ROUTES.includes(href)) return true;
  const parts = href.split("/");
  return ROUTES.some((r) => {
    const rp = r.split("/");
    if (rp.length !== parts.length) return false;
    return rp.every((seg, i) => seg === parts[i] || /^\[.+\]$/.test(seg));
  });
}

function read(rel: string): string {
  return readFileSync(join(ROOT, rel), "utf8");
}

/** Internal hrefs declared in a nav source (skips "#", externals and templates). */
function hrefsIn(src: string): string[] {
  const out = new Set<string>();
  for (const m of src.matchAll(/href[:=]\s*"(\/[^"]*)"/g)) out.add(m[1]);
  return [...out];
}

/** The set literal passed to `new Set<string>([...])` for LOCKED_IN_PROD. */
function lockedSet(src: string): string[] {
  const m = src.match(/LOCKED_IN_PROD\s*=\s*new Set<string>\(\[([\s\S]*?)\]\)/);
  if (!m) return [];
  return [...m[1].matchAll(/"([^"]+)"/g)].map((x) => x[1]).sort();
}

/** The one authoritative lock list. */
const LOCKED = lockedSet(read("lib/lockedInProd.ts"));

describe("navigation integrity", () => {
  it("discovers the route table", () => {
    // Guard-for-the-guard: an empty route table would make every href "unresolvable"
    // and an empty href list would make the suite vacuous.
    expect(ROUTES.length).toBeGreaterThan(20);
    expect(ROUTES).toContain("/admin");
    expect(ROUTES).toContain("/team/tools/[slug]");
  });

  it.each(NAV_SOURCES)("every destination in %s resolves to a real route", (rel) => {
    const broken = hrefsIn(read(rel)).filter((h) => !resolves(h));
    expect(broken, `${rel} points at route(s) that do not exist`).toEqual([]);
  });

  it("defines the production lock list exactly once, in lib/lockedInProd.ts", () => {
    // The authoritative list must be non-empty here, or a later "both are empty"
    // would pass this suite while locking nothing.
    expect(LOCKED.length).toBeGreaterThan(0);

    const redefiners = ["components/Sidebar.tsx", "components/TopBar.tsx"].filter((rel) =>
      /LOCKED_IN_PROD\s*=/.test(read(rel)),
    );
    expect(
      redefiners,
      "these files declare their own LOCKED_IN_PROD instead of importing it from " +
        "lib/lockedInProd.ts. Two copies of this rule have already drifted once: the " +
        "sidebar offered Citations and Web 2.0 in production while the search box hid " +
        "them.",
    ).toEqual([]);

    // Both shells must actually consult the shared rule, not silently ignore it.
    const notConsuming = ["components/Sidebar.tsx", "components/TopBar.tsx"].filter(
      (rel) => !read(rel).includes("isNavLocked"),
    );
    expect(notConsuming, "these nav shells never apply the production lock").toEqual([]);
  });

  it("locks a module in the nav if its page is a disabled placeholder", () => {
    // A module whose page renders a "temporarily disabled" card must not be advertised
    // as available. /admin/citations says the citation builder is off; the sidebar
    // comment claimed the opposite ("now shipped, verified live end-to-end").
    const disabled = ROUTES.filter((r) => {
      const page = join(APP, r.replace(/^\//, ""), "page.tsx");
      try {
        return /temporarily disabled|is disabled while/i.test(readFileSync(page, "utf8"));
      } catch {
        return false;
      }
    });
    const locked = new Set(LOCKED);
    const advertised = disabled.filter((r) => !locked.has(r));
    expect(
      advertised,
      "these routes render a 'temporarily disabled' page but are not in the sidebar's " +
        "LOCKED_IN_PROD, so the nav advertises a module that tells you it is off",
    ).toEqual([]);
  });
});

// ============================================================
// 3. THE SIDEBAR AND THE SEARCH BOX ARE ONE NAV, NOT TWO.
//
// TopBar's *_DESTS lists are a second, hand-maintained copy of the sidebars.
// They had already drifted: /admin/operations — the sidebar's own "health
// surface" — was absent from search, so an operator typing "jobs", "failures"
// or "operations" was told the page did not exist. Nothing caught it, because
// both lists resolve to real routes; the bug is only visible by comparing them.
// ============================================================
describe("search covers every navigable destination", () => {
  const SIDEBARS = [
    "components/Sidebar.tsx",
    "components/portal/TeamSidebar.tsx",
    "components/client/ClientSidebar.tsx",
  ];

  it("every sidebar href is reachable from the search box", () => {
    const searchable = new Set(hrefsIn(read("components/TopBar.tsx")));
    const missing: string[] = [];
    for (const rel of SIDEBARS) {
      for (const href of hrefsIn(read(rel))) {
        if (!searchable.has(href)) missing.push(`${href} (in ${rel})`);
      }
    }
    expect(
      missing,
      "these destinations appear in a sidebar but not in TopBar's *_DESTS, so " +
        "searching for them returns nothing",
    ).toEqual([]);
  });

  it("every searchable href is a real route", () => {
    const bad = hrefsIn(read("components/TopBar.tsx")).filter((h) => !resolves(h));
    expect(bad, "search offers destinations that do not resolve").toEqual([]);
  });
});
