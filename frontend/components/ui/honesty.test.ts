// A component that derives a NUMBER from a query must say when it doesn't know.
//
// The bug this catches, in its exact shape:
//
//     const members = useMembers().data ?? [];      // failed request -> []
//     ...
//     <Value value={members.length} />              // renders a confident 0
//
// On failure the fallback is indistinguishable from a true answer, so a dead
// backend renders as "0 at-risk projects" / "0 toxic links flagged" and an
// operator has no way to tell. Eight components shipped this.
//
// The rule: if a file unwraps `.data ??` from a query hook, it must ALSO
// reference one of the honesty mechanisms — QueryGuard (loading/failure),
// an explicit isError/isLoading branch, or SegmentError. Rendering EmptyState
// alone does not count: "empty" is a claim about data, not about failure.

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const ROOT = process.cwd();
const COMPONENTS = join(ROOT, "components");

/** Files that unwrap query data but legitimately do not branch on failure. */
const ALLOWED = new Set<string>([
  // Container/orchestrator components: they hand their data to children and it
  // is the CHILD that must be honest. Adding a guard here would double-report.
  "components/cost/CostWorkspace.tsx",
  "components/operations/OperationsWorkspace.tsx",
  "components/content/ContentWorkspace.tsx",
  "components/reports/ReportsWorkspace.tsx",
  "components/portal/PortalContext.tsx",
  "components/client/ClientContext.tsx",
]);

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.tsx$/.test(name) && !/\.test\.tsx$/.test(name)) out.push(full);
  }
  return out;
}

/** Does this file pull `.data ?? <fallback>` out of something? */
const UNWRAPS_DATA = /\.data\s*\?\?/;
/** Does it call a query-ish hook at all? */
const USES_QUERY_HOOK = /\buse[A-Z]\w*\(/;
/** Any of the honest ways to say "this might not have loaded". */
const IS_HONEST = /isError|isLoading|isPending|QueryGuard|SegmentError/;

describe("no component renders a confident number it might not have", () => {
  it("every file that unwraps query data also handles not-having-it", () => {
    const offenders: string[] = [];
    for (const file of walk(COMPONENTS)) {
      const rel = relative(ROOT, file).split("\\").join("/");
      if (ALLOWED.has(rel)) continue;
      const src = readFileSync(file, "utf8");
      if (!UNWRAPS_DATA.test(src) || !USES_QUERY_HOOK.test(src)) continue;
      if (!IS_HONEST.test(src)) offenders.push(rel);
    }

    expect(
      offenders,
      "these files turn a failed request into a fallback value and render it as " +
        "fact. Wrap the derived view in components/ui/QueryGuard, or branch on " +
        "isError explicitly. An EmptyState is not enough: 'empty' claims the " +
        "backend answered.",
    ).toEqual([]);
  });

  it("the scan actually looked at files (guard for the guard)", () => {
    expect(walk(COMPONENTS).length).toBeGreaterThan(100);
  });
});
