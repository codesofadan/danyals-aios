// Reachability guard. Walks the real import graph from every Next.js entry point and
// asserts it agrees EXACTLY with lib/parked.ts.
//
// Two failure directions, both of which have already happened here:
//   • a component becomes unreachable and nobody notices -> it rots, and a later
//     reader cannot tell it from abandoned code (41 files reached that state).
//   • a parked component is re-mounted but stays listed as parked -> the registry
//     starts lying, which is worse than not having one.
//
// Entry points include error.tsx / global-error.tsx / not-found.tsx, not just
// page/layout. An earlier version of this sweep omitted them and wrongly reported
// SegmentError - which every segment error boundary renders - as an orphan.

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, basename, extname, relative } from "node:path";
import { describe, expect, it } from "vitest";
import { PARKED, PARKED_PATHS } from "./parked.registry";

// vitest runs with the frontend package root as cwd (jsdom gives import.meta.url no
// file: scheme, so it cannot be used here).
const ROOT = process.cwd();
const COMPONENTS = join(ROOT, "components");
const APP = join(ROOT, "app");

// Next.js treats each of these as a render entry point for a route segment.
const ENTRY_FILES = new Set([
  "page.tsx", "layout.tsx", "error.tsx", "global-error.tsx",
  "not-found.tsx", "loading.tsx", "template.tsx", "default.tsx",
]);

function walk(dir: string, keep: (f: string) => boolean): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) out.push(...walk(full, keep));
    else if (keep(name)) out.push(full);
  }
  return out;
}

const isSource = (f: string) =>
  (f.endsWith(".tsx") || f.endsWith(".ts")) && !f.includes(".test.");

const allComponents = walk(COMPONENTS, isSource);
const entryPoints = walk(APP, (f) => ENTRY_FILES.has(f));

// basename -> the component files that could satisfy an import of it.
const byBasename = new Map<string, string[]>();
for (const p of allComponents) {
  const key = basename(p, extname(p));
  byBasename.set(key, [...(byBasename.get(key) ?? []), p]);
}

/** Component files imported by `file`, resolved by basename.
 *
 * Basename resolution rather than true module resolution: it cannot miss an edge
 * (a real import always names the file), and over-linking would only ever make the
 * unreachable set SMALLER - i.e. this sweep errs toward calling things reachable,
 * never toward falsely accusing a live component of being an orphan.
 */
function importsOf(file: string): string[] {
  let src: string;
  try {
    src = readFileSync(file, "utf8");
  } catch {
    return [];
  }
  const out: string[] = [];
  for (const m of src.matchAll(/from\s+"([^"]+)"/g)) {
    const spec = m[1];
    if (!spec.startsWith("@/components") && !spec.startsWith(".")) continue;
    out.push(...(byBasename.get(basename(spec, extname(spec))) ?? []));
  }
  return out;
}

const reachable = new Set<string>();
const stack = [...entryPoints];
while (stack.length) {
  const node = stack.pop()!;
  if (reachable.has(node)) continue;
  reachable.add(node);
  stack.push(...importsOf(node));
}

const unreachable = allComponents
  .filter((p) => !reachable.has(p))
  .map((p) => relative(COMPONENTS, p).split("\\").join("/"))
  .sort();

describe("component reachability", () => {
  it("finds the entry points and the component tree", () => {
    // Guard-for-the-guard: a discovery bug must FAIL, not vacuously pass by
    // declaring everything reachable.
    expect(entryPoints.length).toBeGreaterThan(20);
    expect(allComponents.length).toBeGreaterThan(100);
    expect(reachable.size).toBeGreaterThan(50);
  });

  it("has no unreachable component that is not registered in parked.ts", () => {
    const unregistered = unreachable.filter((p) => !PARKED_PATHS.has(p));
    expect(
      unregistered,
      "These components cannot be reached from any route and are not recorded in " +
        "lib/parked.ts. Either mount them, or add an entry saying what unmounted them " +
        "and what would bring them back. Do not delete on inference alone - see the " +
        "header of lib/parked.ts.",
    ).toEqual([]);
  });

  it("has no registered parked component that is actually reachable", () => {
    const stale = [...PARKED_PATHS].filter((p) => !unreachable.includes(p)).sort();
    expect(
      stale,
      "lib/parked.ts lists these as parked, but they ARE reachable from a route. " +
        "Remove their entries - a registry that misdescribes the tree is worse than none.",
    ).toEqual([]);
  });

  it("records a re-enable condition and a source for every parked entry", () => {
    const vague = PARKED.filter((e) => !e.reEnableWhen.trim() || !e.unmountedBy.trim());
    expect(vague.map((e) => e.path)).toEqual([]);
  });

  it("has no duplicate entries", () => {
    const paths = PARKED.map((e) => e.path);
    expect(paths.length).toBe(new Set(paths).size);
  });
});
