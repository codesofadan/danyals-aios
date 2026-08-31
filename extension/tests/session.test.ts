import { describe, expect, it } from "vitest";
import { unbankedSeconds, type ActiveClaim } from "../src/lib/session";

/**
 * `worked_seconds` feeds the median that the entire loaded-cost model rests on. A
 * garbage value here does not crash anything — it quietly makes the cost model wrong,
 * which is worse.
 */
const claim = (startedAtMs: number): ActiveClaim => ({
  citationId: "c1",
  directory: "Ourbis",
  bankedSeconds: 0,
  startedAtMs,
});

describe("unbankedSeconds", () => {
  it("counts whole seconds since the timer started", () => {
    const now = 1_000_000;
    expect(unbankedSeconds(claim(now - 125_000), now)).toBe(125);
  });

  it("returns zero when no time has passed", () => {
    expect(unbankedSeconds(claim(1000), 1000)).toBe(0);
  });

  it("never reports negative time when the clock jumps backwards", () => {
    // A laptop waking from sleep, or an NTP correction. A negative delta would be
    // subtracted from the server's accumulated total.
    expect(unbankedSeconds(claim(2_000_000), 1_000_000)).toBe(0);
  });

  it("caps an absurd delta rather than poisoning the median", () => {
    // A claim restored from a browser session left open overnight. Sending 40,000
    // seconds would drag the median far enough to make the cost model meaningless.
    expect(unbankedSeconds(claim(0), 40 * 60 * 60 * 1000)).toBe(4 * 60 * 60);
  });

  it("survives a corrupt stored timestamp", () => {
    expect(unbankedSeconds(claim(Number.NaN), 1000)).toBe(0);
  });
});
