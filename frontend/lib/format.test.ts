// The contracts that let two screens showing the same fact agree.
import { describe, expect, it, vi, afterEach } from "vitest";
import { formatDuration, formatWhen, relativeTime, usd } from "./format";

describe("usd", () => {
  it("renders whole dollars by default", () => expect(usd(1234)).toBe("$1,234"));
  it("renders cents when asked", () => expect(usd(12.5, 2)).toBe("$12.50"));
  it("never invents precision", () => expect(usd(1234.56)).toBe("$1,235"));
});

describe("relativeTime", () => {
  afterEach(() => vi.useRealTimers());
  it("is honest in both directions - future work is not 'ago'", () => {
    vi.useFakeTimers({ now: new Date("2026-08-27T12:00:00Z") });
    expect(relativeTime("2026-08-27T10:00:00Z")).toBe("2h ago");
    expect(relativeTime("2026-08-27T14:00:00Z")).toBe("in 2h");
  });
  it("renders nothing rather than 'Invalid Date'", () => {
    expect(relativeTime(null)).toBe("");
    expect(relativeTime("not-a-date")).toBe("");
  });
});

describe("formatWhen / formatDuration", () => {
  it("empty for the unparseable", () => {
    expect(formatWhen("nope")).toBe("");
    expect(formatDuration(null)).toBe("");
  });
  it("compact durations", () => {
    expect(formatDuration(288)).toBe("4m 48s");
    expect(formatDuration(4320)).toBe("1h 12m");
  });
});
