import { describe, expect, it } from "vitest";
import { PAGE_KINDS, pageKind, storedTypeLabel } from "./pageKinds";
import { PAGE_TEMPLATES, PAGE_TYPES, RESEARCH_CONTENT_TYPES } from "./content";

// The whole point of this table is that one operator choice derives the other
// three values. A derivation that names something the backend does not accept
// would fail at generate time, on a screen the operator already left.
describe("one page vocabulary, three derivations", () => {
  it("every kind derives a research type the recommender accepts", () => {
    const valid = new Set(RESEARCH_CONTENT_TYPES.map((t) => t.key));
    for (const k of PAGE_KINDS) expect(valid.has(k.research), k.key).toBe(true);
  });

  it("every kind derives a template the backend can build", () => {
    const valid = new Set(PAGE_TEMPLATES.map((t) => t.key));
    for (const k of PAGE_KINDS) expect(valid.has(k.template), k.key).toBe(true);
  });

  it("every kind derives a stored page type the enum allows", () => {
    const valid = new Set(PAGE_TYPES);
    for (const k of PAGE_KINDS) expect(valid.has(k.pageType), k.key).toBe(true);
  });

  it("covers every research type the recommender can run", () => {
    // If the backend can research a shape the operator cannot pick, that shape is
    // unreachable — which is how "Service × Location" ended up on one screen only.
    const covered = new Set(PAGE_KINDS.map((k) => k.research));
    for (const t of RESEARCH_CONTENT_TYPES) expect(covered.has(t.key), t.key).toBe(true);
  });

  it("has no duplicate keys and every entry is described", () => {
    expect(new Set(PAGE_KINDS.map((k) => k.key)).size).toBe(PAGE_KINDS.length);
    for (const k of PAGE_KINDS) {
      expect(k.label.length).toBeGreaterThan(0);
      expect(k.bestFor.length, `${k.key} needs a "when to use it"`).toBeGreaterThan(20);
    }
  });

  it("falls back to a real kind rather than undefined", () => {
    expect(pageKind("nonsense").key).toBe(PAGE_KINDS[0].key);
  });

  it("names a stored type without pretending to know which kind made it", () => {
    // Three kinds store as `local`; the board must not claim it was one of them.
    expect(storedTypeLabel("local")).toBe("Local");
    expect(storedTypeLabel("gbp_post")).toBe("GMB post");
  });
});
