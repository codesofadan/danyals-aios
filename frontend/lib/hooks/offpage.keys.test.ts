import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * The two-tabs divergence, pinned. Queue completion used to invalidate
 * `["citations"]` — a key that is a prefix of NOTHING (the board's key is
 * `["offpage","citations"]`) — so finishing an item never refreshed the citations
 * page, and the workspace and the queue disagreed until a hard reload. That single
 * wrong literal was the mechanical cause of "I had two tabs and neither made sense".
 *
 * A source-level guard, deliberately: rendering a full react-query harness to prove
 * an invalidation is heavy, while the defect was a string literal. If the literal
 * comes back, this goes red.
 */

const SRC = readFileSync(resolve(__dirname, "offpage.ts"), "utf8");

describe("citation queue invalidation keys", () => {
  it("never invalidates the phantom [\"citations\"] key", () => {
    expect(SRC).not.toMatch(/queryKey:\s*\[\s*"citations"\s*\]/);
  });

  it("completion invalidates the board, the gap and the KPIs", () => {
    const complete = SRC.slice(
      SRC.indexOf("export function useCompleteQueueItem"),
      SRC.indexOf("export function useBlockQueueItem"),
    );
    expect(complete).toContain("CITATIONS_KEY");
    expect(complete).toContain("CITATION_GAP_KEY");
    expect(complete).toContain("OFFPAGE_KPIS_KEY");
  });

  it("blocking an item also reaches the citations board and the gap", () => {
    const block = SRC.slice(
      SRC.indexOf("export function useBlockQueueItem"),
      SRC.indexOf("export function useReleaseQueueItem"),
    );
    expect(block).toContain("CITATIONS_KEY");
    expect(block).toContain("CITATION_GAP_KEY");
  });
});
