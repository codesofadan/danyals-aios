/**
 * P0-8 REGRESSION GUARD: every class a content component uses must be DEFINED in a
 * stylesheet that /admin/content actually loads.
 *
 * Prevented defect: ContentWizard used `.op-toolset`, `.op-strong` and `.op-muted`,
 * which are declared ONLY in `app/admin/web2/offpage.css` - a sheet the content
 * route never imports. On a cold load of /admin/content the wizard toolbar lost its
 * flex layout and gaps.
 *
 * It hid for months because Next leaves an already-loaded stylesheet in the document:
 * anyone who reached the page by clicking through from /admin/web2 saw it render
 * correctly. Only a hard navigation exposed it - which is what a real operator does
 * every morning, and what a developer with the app already open never does.
 *
 * A visual test would not have caught this either, for the same reason. A static
 * check does, and costs nothing.
 */
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = join(__dirname, "..", "..");
const COMPONENT_DIR = join(ROOT, "components", "content");

// The only stylesheets loaded for /admin/content: globals.css via the root layout,
// content.css via the page. Anything else is not on this route.
const LOADED_SHEETS = [
  join(ROOT, "app", "globals.css"),
  join(ROOT, "app", "admin", "content", "content.css"),
];

// Prefixes this module owns. Utility/token classes from globals (card, kpi, cs, ...)
// are covered by the same lookup; these prefixes are the ones a rebuild is most
// likely to reference from the wrong sheet.
const GUARDED = /^(co|op|tpl|wiz)-/;

function definedClasses(): Set<string> {
  const out = new Set<string>();
  for (const sheet of LOADED_SHEETS) {
    const css = readFileSync(sheet, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    for (const m of css.matchAll(/\.(-?[_a-zA-Z][\w-]*)/g)) out.add(m[1]);
  }
  return out;
}

function usedClasses(): Map<string, string[]> {
  const used = new Map<string, string[]>();
  for (const file of readdirSync(COMPONENT_DIR).filter((f) => f.endsWith(".tsx"))) {
    const src = readFileSync(join(COMPONENT_DIR, file), "utf8");
    // Only literal className strings; template literals and computed names are out of
    // scope (a static check must not guess at runtime values).
    for (const m of src.matchAll(/className="([^"]+)"/g)) {
      for (const cls of m[1].split(/\s+/).filter(Boolean)) {
        if (!GUARDED.test(cls)) continue;
        used.set(cls, [...(used.get(cls) ?? []), file]);
      }
    }
  }
  return used;
}

describe("content module CSS", () => {
  it("references no class that /admin/content does not load", () => {
    const defined = definedClasses();
    const missing = [...usedClasses().entries()]
      .filter(([cls]) => !defined.has(cls))
      .map(([cls, files]) => `${cls} (used in ${[...new Set(files)].join(", ")})`);

    expect(
      missing,
      "These classes are used by a content component but defined in neither " +
        "globals.css nor content.css, so they resolve to nothing on a cold load of " +
        "/admin/content:\n  " + missing.join("\n  "),
    ).toEqual([]);
  });

  it("keeps the kanban grid column count in step with COLUMNS", () => {
    // An arithmetic mismatch here silently wraps a whole status column out of view.
    // It was `repeat(5, ...)` against six columns, and the one that vanished was
    // `degraded` - the column meaning "nothing reached the client's site".
    const src = readFileSync(join(ROOT, "lib", "content.ts"), "utf8");
    // Scope to the COLUMNS array itself - lib/content.ts declares several other
    // `{ key: ... }` tables and counting all of them proves nothing.
    const block = src.match(/export const COLUMNS[^=]*=\s*\[([\s\S]*?)\];/);
    expect(block, "COLUMNS array not found in lib/content.ts").not.toBeNull();
    const count = [...block![1].matchAll(/\{\s*key:/g)].length;

    const css = readFileSync(LOADED_SHEETS[1], "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    const grid = css.match(/\.co-board\s*\{[^}]*grid-template-columns:\s*repeat\((\d+)/);

    expect(grid, ".co-board must declare an explicit repeat() column count").not.toBeNull();
    expect(Number(grid![1])).toBe(count);
  });
});
