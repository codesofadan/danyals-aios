/**
 * Pager arithmetic.
 *
 * Extracted from the component because this is where the bugs live: an
 * off-by-one tells an operator "1 to 100 of 461" while showing rows 101 to 200,
 * and nothing else in the UI would contradict it.
 */
import { describe, expect, it } from "vitest";

import { pageRange } from "@/lib/auditAltitude";

describe("pageRange", () => {
  it("is not needed when everything fits on one page", () => {
    expect(pageRange(0, 100, 100).needed).toBe(false);
    expect(pageRange(0, 100, 42).needed).toBe(false);
  });

  it("is needed the moment one row does not fit", () => {
    expect(pageRange(0, 100, 101).needed).toBe(true);
  });

  it("reads 1-based, because that is what a person reads", () => {
    const r = pageRange(0, 100, 461);
    expect(r.first).toBe(1);
    expect(r.last).toBe(100);
  });

  it("reports the real bounds of a middle page", () => {
    const r = pageRange(2, 100, 461);
    expect(r.first).toBe(201);
    expect(r.last).toBe(300);
  });

  it("does not overrun the total on the final page", () => {
    const r = pageRange(4, 100, 461);
    expect(r.first).toBe(401);
    expect(r.last).toBe(461);
    expect(r.lastPage).toBe(4);
  });

  it("clamps a page beyond the end rather than inventing rows", () => {
    const r = pageRange(99, 100, 461);
    expect(r.first).toBe(401);
    expect(r.last).toBe(461);
  });

  it("clamps a negative page", () => {
    expect(pageRange(-3, 100, 461).first).toBe(1);
  });

  it("says nothing rather than 1 to 0 of 0 when there is no data", () => {
    const r = pageRange(0, 100, 0);
    expect(r.first).toBe(0);
    expect(r.last).toBe(0);
    expect(r.needed).toBe(false);
  });

  it("survives a zero page size instead of dividing by zero", () => {
    const r = pageRange(0, 0, 50);
    expect(Number.isFinite(r.lastPage)).toBe(true);
    expect(r.last).toBeGreaterThan(0);
  });

  it("handles a total that divides exactly", () => {
    const r = pageRange(1, 100, 200);
    expect(r.first).toBe(101);
    expect(r.last).toBe(200);
    expect(r.lastPage).toBe(1);
  });
});
