import { describe, expect, it } from "vitest";
import { operatorBlock } from "./content";

// A page waiting on a PERSON sat in the same column, with the same status and
// the same "in progress" glance, as a page the machine was actively writing.
// An operator could watch a page that was waiting on them and conclude the
// system was slow.
describe("telling a page waiting on a person from one being written", () => {
  const job = (status: string, stage: string) =>
    ({ status, stage }) as Parameters<typeof operatorBlock>[0];

  it("flags a page held for its first-party facts", () => {
    const b = operatorBlock(job("drafting", "Waiting on your experience answers (5 to go)"));
    expect(b?.kind).toBe("experience");
    expect(b?.label).toBe("Waiting on you");
  });

  it("flags a run that finished without producing a page", () => {
    const b = operatorBlock(job("drafting", "Held — outline degraded, nothing was written"));
    expect(b?.kind).toBe("held");
    // The point of this one is that it is NOT in the review queue.
    expect(b?.hint).toMatch(/nothing is queued for review/i);
  });

  it("does not flag a page that is genuinely being written", () => {
    expect(operatorBlock(job("drafting", "Draft"))).toBeNull();
    expect(operatorBlock(job("drafting", "Research"))).toBeNull();
  });

  it("only ever flags a drafting job", () => {
    // The same words on a finished job would be stale, not actionable.
    expect(operatorBlock(job("done", "Waiting on your experience answers (5 to go)"))).toBeNull();
    expect(operatorBlock(job("needs_review", "Held — something"))).toBeNull();
  });
});
