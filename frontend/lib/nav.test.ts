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

import { ADMIN_NAV, CLIENT_NAV, TEAM_NAV } from "./nav";

const ROOT = process.cwd();
const APP = join(ROOT, "app");

// After the single-source refactor the nav table lives in lib/nav.ts; the four
// shell components render it and may not declare destinations of their own.
const NAV_SOURCES = ["lib/nav.ts"];
const NAV_RENDERERS = [
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
    // An EMPTY lock list is a legitimate state (2026-08-27: the citations lock
    // moved from a whole route to a tab inside /admin/off-page, leaving no
    // route-level locks). What must hold is that the DEFINITION exists and
    // parsed - lockedSet() returns [] both for "empty set" and "regex missed",
    // so assert the declaration is present rather than the list non-empty.
    expect(read("lib/lockedInProd.ts")).toMatch(/LOCKED_IN_PROD\s*=\s*new Set<string>\(/);

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
        const src = readFileSync(page, "utf8");
        // A TABBED workspace may legitimately carry ONE locked tab (off-page's
        // Citations tab holds the moved lock card) while its other tabs are
        // live - that is not a disabled module and must not force a route lock.
        // Only a page whose PRIMARY content is the disabled card qualifies.
        if (/useUrlTab\(/.test(src)) return false;
        return /temporarily disabled|is disabled while/i.test(src);
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
describe("the one nav table is fit for search", () => {
  // Parity between sidebar and search is now STRUCTURAL (both render lib/nav.ts),
  // so the old cross-file comparison is vacuous. What can still rot is the table
  // itself: an item without keywords is findable only by its exact label, and a
  // duplicated href makes two entries claim one page.
  const all = [...ADMIN_NAV.flatMap((g) => g.items), ...TEAM_NAV, ...CLIENT_NAV];

  it("every destination carries search keywords beyond its label", () => {
    const bare = all.filter((i) => !(i.keywords ?? "").trim()).map((i) => i.href);
    expect(bare).toEqual([]);
  });

  it("no href appears twice within a portal", () => {
    for (const list of [ADMIN_NAV.flatMap((g) => g.items), TEAM_NAV, CLIENT_NAV]) {
      const hrefs = list.map((i) => i.href);
      expect(new Set(hrefs).size).toBe(hrefs.length);
    }
  });

  it("every nav destination resolves to a real route", () => {
    const bad = all.filter((i) => !resolves(i.href)).map((i) => i.href);
    expect(bad).toEqual([]);
  });
});

// ============================================================
// 4. ONE TABLE. A nav component that declares its own `href:` literal is a
// second copy waiting to drift - which is exactly how search lost
// /admin/operations. Links rendered from data (it.href, t.slug) are fine;
// declaring a destination inline is not.
// ============================================================
describe("nav components declare no destinations of their own", () => {
  it("no href literal outside lib/nav.ts", () => {
    const offenders: string[] = [];
    for (const rel of NAV_RENDERERS) {
      const src = read(rel);
      for (const m of src.matchAll(/href[:=]\s*"(\/[^"]*)"/g)) {
        offenders.push(`${rel} declares ${m[1]}`);
      }
    }
    expect(offenders).toEqual([]);
  });
});
