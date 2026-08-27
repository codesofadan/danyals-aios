// House style: no em dash (U+2014) and no en dash (U+2013) in anything a client
// or an operator reads. The engine's CLAUDE.md has banned them in generated PDFs
// for a long time; the dashboard was never held to the same rule, so the same
// audit read one way in the report and another way on screen.
//
// A grep in a test rather than a lint rule, because the rule is about SHIPPED
// COPY: it has to catch a dash typed into a blurb in `lib/audit.ts` as readily as
// one in JSX. The backend enforces the same ban on the rendered report at the
// document boundary (`audit_report.no_dashes`), where most of the prose is not
// written in this repository at all.

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const ROOTS = [
  "components/audit",
  "components/report",
  "app/admin/audit",
  "lib/audit.ts",
  "lib/auditAltitude.ts",
];
const EXT = /\.(tsx?|css)$/;

function walk(p: string, out: string[] = []): string[] {
  const st = statSync(p, { throwIfNoEntry: false });
  if (!st) return out;
  if (st.isFile()) {
    if (EXT.test(p)) out.push(p);
    return out;
  }
  for (const entry of readdirSync(p)) walk(join(p, entry), out);
  return out;
}

describe("no em or en dashes in the audit surface", () => {
  const files = ROOTS.flatMap((r) => walk(r));

  it("finds the files it is supposed to be checking", () => {
    // A guard that silently scans nothing is worse than no guard: it reports
    // clean for ever.
    expect(files.length).toBeGreaterThan(8);
  });

  // Built from code points, not typed: this file is scanned like every other, so
  // a literal here would make the guard fail on itself for ever.
  const EM = String.fromCharCode(0x2014);
  const EN = String.fromCharCode(0x2013);

  it.each([EM, EN])("has no %s anywhere", (dash) => {
    const offenders = files
      .map((f) => {
        const lines = readFileSync(f, "utf8").split("\n");
        const hits = lines
          .map((l, i) => (l.includes(dash) ? `${f}:${i + 1}  ${l.trim().slice(0, 90)}` : null))
          .filter(Boolean);
        return hits as string[];
      })
      .flat();
    expect(offenders).toEqual([]);
  });
});
